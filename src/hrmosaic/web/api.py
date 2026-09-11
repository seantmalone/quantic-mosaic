"""The HTTP surface: the access gate, the two personas, and every route of §11.8 P8 owns.

```
GET  /                       chat UI                                  gated
POST /chat                   the contract endpoint (R6.3)             gated · rate limited
POST /chat/confirm           the ONLY place a token is minted         gated
GET  /chat/stream            the SSE span rail (web/sse.py)           gated
GET  /health · /ready        always-200 status · 503 until warm       open
GET  · POST /access          the key page and its form                open
POST /access/logout          clears both cookies                      open
POST /session/actor          the act-as selector                      gated
GET  /api/traces/turns/{id}  the single-turn view-model               gated · admin (P9: web/dashboard.py)
```

**Two levels of identity, and they are not the same thing (§17).** *Authentication* is one shared
secret, `APP_ACCESS_TOKEN`, presented as `?access=` (exchanged once for the HttpOnly `mosaic_access`
cookie and stripped from the URL), as that cookie, or as `Authorization: Bearer`, each compared with
`secrets.compare_digest`. *Authorization* is the persona: cookie `mosaic_actor` or header `X-Actor`,
an `E1xxx` id or the literal `admin`, defaulting to `E1042`. The admin persona is required —
server-side, **403** `{"code": "ADMIN_REQUIRED"}` — for `/dashboard/*`, `/api/*` and the privileged
`POST /chat` options. Inside the MCP tools the acting id stays audit-only (§8.7).

**The gate is ASGI middleware, not `BaseHTTPMiddleware`.** It has to cover the mounted MCP endpoint
and `/chat/stream`, both of which stream; a middleware that wraps the response body would be a new
way for either to stall. This one either short-circuits with a `Response` or hands the untouched
scope on, and it writes the resolved identity into `scope["state"]` for the handlers.

**A client body is never parsed straight into `ChatRequest`.** `ChatRequest` carries `auth_mode`,
`actor_role` and `actor_source` — the fields the gate resolves — so a request model that accepted
them from the wire would let any caller declare itself an admin. `ChatBody` below is exactly
§11.1's client-supplied half, and `web/` fills the rest in.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import re
import secrets
import time
from collections import deque
from html import escape
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hrmosaic.agent import orchestrator as agent
from hrmosaic.agent.client import McpUnavailable
from hrmosaic.agent.guardrails import g5
from hrmosaic.agent.orchestrator import ChatOptions, ChatRequest, ChatResponse, project, render_answer
from hrmosaic.core import corpusread, procstat
from hrmosaic.core import trace as trace_module
from hrmosaic.core.corpusread import IndexModelMismatch
from hrmosaic.core.db import Store, TursoHTTPStore, get_store, now_micros
from hrmosaic.core.ids import new_session_id, new_turn_id, user_agent_hash
from hrmosaic.core.llm import count_calls_today
from hrmosaic.core.models import AnswerBlock, ConfirmationPayload, ErrorPayload
from hrmosaic.core.redact import redact_text
from hrmosaic.mcpserver import confirm as confirm_gate
from hrmosaic.settings import Settings, secret_value
from hrmosaic.web.sse import broker

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

#: The application version `/health.app.version` reports (§11.4). The build's identity is
#: `git_sha`; this is the release line, and it matches the MCP server's advertised version.
APP_VERSION = "2026.1"

#: §11's two cookies. `mosaic_access` is HttpOnly — it is a credential; `mosaic_actor` is not,
#: because the act-as selector reads it to show which persona is active, and it grants nothing
#: on its own (every admin surface re-checks it server-side).
ACCESS_COOKIE = "mosaic_access"
ACTOR_COOKIE = "mosaic_actor"
COOKIE_MAX_AGE_S = 30 * 24 * 60 * 60

#: `^E1[0-9]{3}$` or the literal `admin` (§11). Anything else resolves to the default persona.
ACTOR_PATTERN = re.compile(r"^(?:E1[0-9]{3}|admin)$")
DEFAULT_ACTOR = "E1042"

#: §17's cap on `ChatBody.message`. Every other input on the `POST /chat` path is bounded —
#: `options.k` at `le=10`, the 24/32/128 KB payload caps, the 6-step / 8-tool / 90 s budgets —
#: and this one was not.
MAX_MESSAGE_CHARS = 4000

#: 32-hex, the shape `core/ids.py` mints (§11.1: "may be supplied as UUID4 hex").
ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

#: Never gated (§11). `/access` covers the key page, its form and `/access/logout`.
OPEN_PREFIXES = ("/health", "/ready", "/static", "/access")

#: Gated **and** admin-only (§11.8). The dashboard pages themselves arrive at P9; the prefix is
#: refused from here, so a page can never be added that is readable without the persona.
ADMIN_PREFIXES = ("/dashboard", "/api")

#: The per-IP limit of §17 covers `POST /chat` and the MCP mount, and nothing else: a rate limit on
#: `/chat/stream` would throttle the rail rather than the work behind it.
MCP_MOUNT_PREFIX = "/mcp-server"

#: **The app's own loopback client is exempt from the mount's limit.** The limit is keyed on
#: `request.client.host`, and the agent reaches its own MCP mount over loopback — so every
#: `initialize`, `tools/list` and `tools/call` the app makes on its own behalf, plus the
#: `client.discover()` behind each `GET /health`, lands in the same `127.0.0.1` bucket as the
#: grader's browser. One tool-using turn is ~10 requests, so past three turns a minute the app
#: starts 429-ing its own `tools/call` and the turn silently degrades to `partial`.
#:
#: The exemption is a private header whose value is a **per-process nonce**, minted here at import
#: and handed only to the client `web/main.py` builds. It is unguessable, it never leaves the
#: process, and it is honoured only on the mount and only from a loopback address — so it can
#: neither be replayed from outside nor used to skip the limit on `POST /chat`.
LOOPBACK_HEADER = "X-Mosaic-Loopback"
LOOPBACK_NONCE = secrets.token_urlsafe(32)

#: The five `degradations[]` strings — exactly five, and no sixth (§11.4).
DEGRADATIONS = (
    "llm_api_key_missing",
    "index_model_mismatch",
    "mcp_disconnected",
    "trace_store_unreachable",
    "access_token_missing",
)

#: Every `options` field except `k`; each refused outside `client_label="eval"` + admin (§11.1).
PRIVILEGED_OPTIONS = ("retrieval_strategy", "tools_disabled", "eval_run_id", "variant")

#: How long `/health` waits for the MCP handshake before reporting `mcp_disconnected`. `/health`
#: is a liveness probe: a slow answer is a failed answer to the thing polling it.
HEALTH_MCP_TIMEOUT_S = 5.0

# --------------------------------------------------------------------------------------
# Identity — the access gate and the two personas (§11, §17)
# --------------------------------------------------------------------------------------


class Identity(BaseModel):
    """What the gate resolved for one request; recorded on the session (§10.1)."""

    model_config = ConfigDict(frozen=True)

    auth_mode: Literal["cookie", "bearer", "open"] = "open"
    actor: str = DEFAULT_ACTOR
    actor_role: Literal["employee", "admin"] = "employee"
    actor_source: Literal["explicit", "default"] = "default"

    @property
    def is_admin(self) -> bool:
        return self.actor_role == "admin"


def gate_enabled(settings: Settings) -> bool:
    """On whenever a token is set **or** `APP_ENV != "local"`; unset locally it is off (§11)."""
    return secret_value(settings.app_access_token) is not None or settings.app_env != "local"


def gate_misconfigured(settings: Settings) -> bool:
    """`APP_ENV=render` with no token: every gated route is 403 and `/health` says so (§11.4)."""
    return settings.app_env == "render" and secret_value(settings.app_access_token) is None


def is_open_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in OPEN_PREFIXES)


def needs_admin(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ADMIN_PREFIXES)


def resolve_actor(request: Request) -> tuple[str, str]:
    """`X-Actor` wins over the `mosaic_actor` cookie; absent or malformed, the actor is `E1042`."""
    for candidate in (request.headers.get("X-Actor"), request.cookies.get(ACTOR_COOKIE)):
        if candidate and ACTOR_PATTERN.match(candidate):
            return candidate, "explicit"
    return DEFAULT_ACTOR, "default"


def identity_of(request: Request) -> Identity:
    """The `Identity` the middleware resolved, or the open default for a route it did not gate."""
    resolved = request.scope.get("state", {}).get("identity")
    return resolved if isinstance(resolved, Identity) else Identity()


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _key_page(request: Request, *, status_code: int, message: str) -> Response:
    """The key page, or its JSON equivalent for a client that did not ask for HTML."""
    if _wants_html(request):
        return TEMPLATES.TemplateResponse(
            request=request, name="access.html", context={"message": message}, status_code=status_code
        )
    return JSONResponse({"code": "ACCESS_REQUIRED", "detail": message}, status_code=status_code)


#: What a gated request is told when the gate is on and no token is configured (`APP_ENV=docker`
#: with `APP_ACCESS_TOKEN` unset). It is a 403, not a 401: there is no key that would work.
MISSING_TOKEN_MESSAGE = "APP_ACCESS_TOKEN is not set on this deployment."


def request_is_https(request: Request) -> bool:
    """Whether the *browser* reached this app over https — not whether ASGI did (§14.1).

    Render terminates TLS at its edge and forwards plain http into the container, and uvicorn's
    `ProxyHeadersMiddleware` rewrites the scheme only for a trusted peer (`127.0.0.1` by default),
    which the edge is not. So `request.url.scheme` is `http` on the deployed service and every
    cookie below would ship without `Secure` — contradicting constraint 9 and the published claim
    in `deployed.md`. Reading the header is safe here in a way it would not be for an authorisation
    decision: forging `X-Forwarded-Proto: https` only makes the forger's own cookie `Secure`.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return forwarded == "https" if forwarded else request.url.scheme == "https"


def is_loopback(host: str) -> bool:
    """`127.0.0.1`, `::1` and the rest of `127.0.0.0/8` — never a hostname, never a proxy header."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_own_loopback_client(request: Request, host: str) -> bool:
    """This process's own in-process MCP client: the nonce, on loopback (see `LOOPBACK_NONCE`)."""
    supplied = request.headers.get(LOOPBACK_HEADER)
    return bool(supplied) and is_loopback(host) and hmac.compare_digest(supplied, LOOPBACK_NONCE)


#: The sliding window §17's `ACCESS_RATE_LIMIT_PER_MIN` is measured over.
RATE_WINDOW_S = 60.0

#: How often `RateLimiter` sweeps the whole table for windows that expired without the client ever
#: coming back. Without the sweep the table is bounded only by the number of distinct addresses the
#: process has *ever* seen: a drive-by scanner leaves one `deque` behind per source address, for
#: the life of the instance, inside §14.3's 512 MB. With it, the table is bounded by the number of
#: distinct addresses seen in the last minute or two, which is what the limit is about.
RATE_SWEEP_INTERVAL_S = 60.0


class RateLimiter:
    """A per-IP sliding window over one minute (§17's `ACCESS_RATE_LIMIT_PER_MIN`).

    Two evictions, and they cover different clients. A key whose window empties is dropped the next
    time that client is seen; every key nobody comes back to is dropped by the periodic sweep.

    The table is a plain `dict`, **not** a `defaultdict`: under a `defaultdict` the `del` below is
    undone by the very next subscript, so the eviction reads as if it works and does nothing.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._swept_at = float("-inf")

    def allow(self, key: str, *, now: float | None = None) -> bool:
        moment = now if now is not None else time.monotonic()
        self._sweep(moment)
        window = self._hits.get(key)
        if window is not None:
            while window and moment - window[0] > RATE_WINDOW_S:
                window.popleft()
            if not window:  # the window emptied: drop the key with it
                del self._hits[key]
                window = None
        if len(window if window is not None else ()) >= self.per_minute:
            return False
        if window is None:
            window = self._hits[key] = deque()
        window.append(moment)
        return True

    def _sweep(self, moment: float) -> None:
        """Drop every window that expired without the client returning. Amortised O(1)."""
        if moment - self._swept_at < RATE_SWEEP_INTERVAL_S:
            return
        self._swept_at = moment
        for key in [key for key, window in self._hits.items() if not window or moment - window[-1] > RATE_WINDOW_S]:
            del self._hits[key]


class AccessGateMiddleware:
    """Pure-ASGI so the MCP mount and `/chat/stream` are gated without being wrapped (§11)."""

    def __init__(self, app: Any, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.limiter = RateLimiter(settings.access_rate_limit_per_min)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})
        request = Request(scope, receive)
        refusal = self._check(request)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)

    # -- the gate ----------------------------------------------------------------------
    def _check(self, request: Request) -> Response | None:
        path = request.url.path
        actor, actor_source = resolve_actor(request)
        role = "admin" if actor == "admin" else "employee"
        if is_open_path(path):
            request.scope["state"]["identity"] = Identity(
                auth_mode="open", actor=actor, actor_role=role, actor_source=actor_source
            )
            return None

        if gate_misconfigured(self.settings):
            return JSONResponse(
                {
                    "code": "ACCESS_TOKEN_MISSING",
                    "detail": "APP_ACCESS_TOKEN is not set on this deployment; every gated route is refused.",
                },
                status_code=403,
            )

        auth_mode: Literal["cookie", "bearer", "open"] = "open"
        if gate_enabled(self.settings):
            outcome = self._authenticate(request)
            if isinstance(outcome, Response):
                return outcome
            auth_mode = outcome

        request.scope["state"]["identity"] = Identity(
            auth_mode=auth_mode, actor=actor, actor_role=role, actor_source=actor_source
        )

        if needs_admin(path) and role != "admin":
            return JSONResponse({"code": "ADMIN_REQUIRED"}, status_code=403)

        if self._rate_limited(request, path):
            return JSONResponse(
                {"code": "RATE_LIMITED", "detail": f"more than {self.limiter.per_minute} requests in a minute"},
                status_code=429,
            )
        return None

    def _authenticate(self, request: Request) -> Response | Literal["cookie", "bearer"]:
        """The three presentations of §11, in order, each `compare_digest`-compared."""
        token = secret_value(self.settings.app_access_token) or ""
        if not token:
            # The gate is on because `APP_ENV != "local"` (docker or render) but no token is
            # configured. `compare_digest` against `""` succeeds for an empty credential, so
            # `Authorization: Bearer`, `Cookie: mosaic_access=` and `?access=` would each open a
            # gate that has just refused the anonymous request. `gate_misconfigured()` fails closed
            # for `render` only, by design (§11.4 scopes the `access_token_missing` degradation to
            # it), so the refusal belongs here: never compare against an empty secret.
            return _key_page(request, status_code=403, message=MISSING_TOKEN_MESSAGE)
        supplied = request.query_params.get("access")
        if supplied is not None and request.method == "GET":
            if not hmac.compare_digest(supplied, token):
                return _key_page(request, status_code=401, message="That access key was not recognised.")
            return self._exchange(request, token)

        cookie = request.cookies.get(ACCESS_COOKIE)
        if cookie is not None and hmac.compare_digest(cookie, token):
            return "cookie"

        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and hmac.compare_digest(value.strip(), token):
            return "bearer"

        return _key_page(request, status_code=401, message="This deployment needs an access key.")

    def _exchange(self, request: Request, token: str) -> Response:
        """`?access=` → the cookie, and a 302 to the same URL with the parameter stripped (§11)."""
        remaining = [(key, value) for key, value in request.query_params.multi_items() if key != "access"]
        query = urlencode(remaining)
        target = request.url.path + (f"?{query}" if query else "")
        response = RedirectResponse(target, status_code=302)
        response.set_cookie(
            ACCESS_COOKIE,
            token,
            max_age=COOKIE_MAX_AGE_S,
            httponly=True,
            samesite="lax",
            secure=request_is_https(request),
            path="/",
        )
        return response

    def _rate_limited(self, request: Request, path: str) -> bool:
        chat_post = path == "/chat" and request.method == "POST"
        mcp = path == MCP_MOUNT_PREFIX or path.startswith(MCP_MOUNT_PREFIX + "/")
        if not (chat_post or mcp):
            return False
        client = request.client.host if request.client else "unknown"
        if mcp and is_own_loopback_client(request, client):
            return False  # the app talking to itself never spends a visitor's budget
        return not self.limiter.allow(client)


# --------------------------------------------------------------------------------------
# Request bodies — §11.1's client-supplied half, and nothing more
# --------------------------------------------------------------------------------------


class ChatBody(BaseModel):
    """`POST /chat`'s body (§11.1). Deliberately **not** `ChatRequest`: see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    #: Bounded like every other input on this path (§17): the message is embedded on the request
    #: path (~0.6 s of CPU on the 0.1-vCPU instance), stored verbatim in `turns.user_message`
    #: and sent to the paid model, so an unbounded one is a denial-of-service lever. 4,000
    #: characters is an order of magnitude above the longest dataset item and demo prompt.
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = None
    turn_id: str | None = None
    employee_id: str | None = None
    client_label: Literal["web", "api", "eval", "demo"] = "web"
    options: ChatOptions = Field(default_factory=ChatOptions)


class ConfirmBody(BaseModel):
    """`POST /chat/confirm`'s body (§11.2)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_id: str
    decision: Literal["confirmed", "declined"]


class ActorBody(BaseModel):
    """`POST /session/actor`'s body (§11.8) — the act-as selector."""

    model_config = ConfigDict(extra="forbid")

    actor: str = Field(pattern=r"^(?:E1[0-9]{3}|admin)$")


# --------------------------------------------------------------------------------------
# Helpers shared by the handlers
# --------------------------------------------------------------------------------------


async def _parse_body[BodyT: BaseModel](request: Request, model: type[BodyT]) -> BodyT:
    """Accept the same body as JSON or as an HTML form.

    `POST /chat`, `POST /chat/confirm` and `POST /session/actor` are driven both by JSON clients
    (the demo scripts, the eval runner, the contract tests) and by the chat page's own htmx forms.
    One endpoint each — §11.8's list is exact — so the body is parsed here rather than split across
    a JSON route and a form route. Empty form fields are dropped, so an untouched hidden input
    reads as "absent" rather than as an empty id.
    """
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_JSON", "detail": str(exc)}) from exc
    else:
        data = {key: value for key, value in (await request.form()).items() if value != ""}
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_REQUEST", "errors": json.loads(exc.json())},
        ) from exc


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> Store:
    return get_store(_settings(request))


def _validated_id(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not ID_PATTERN.match(value):
        raise HTTPException(status_code=422, detail={"code": "INVALID_ID", "field": field})
    return value


def privileged_options_used(options: ChatOptions) -> list[str]:
    """Which privileged fields this request actually set — `k` is never one of them (§11.1)."""
    used = []
    for name in PRIVILEGED_OPTIONS:
        value = getattr(options, name)
        if value not in (None, [], ""):
            used.append(name)
    return used


def authorise_options(body: ChatBody, identity: Identity) -> None:
    """§11.1's four-row matrix. The refusal splits by cause, and both codes are contract-visible."""
    used = privileged_options_used(body.options)
    if not used:
        return
    if not identity.is_admin:
        raise HTTPException(status_code=403, detail={"code": "ADMIN_REQUIRED"})
    if body.client_label != "eval":
        raise HTTPException(status_code=403, detail={"code": "PRIVILEGED_OPTION_REFUSED", "field": used[0]})


def _turn_rollups(store: Store, turn_id: str) -> tuple[agent.Usage, agent.Timings]:
    """The closed turn's own rollups, so a `/chat/confirm` response and the dashboard agree."""
    row = (
        store.execute(
            "SELECT total_tokens_in, total_tokens_out, llm_calls, tool_calls, retrievals, duration_ms, "
            "llm_ms, retrieval_ms, tool_ms, store_ms FROM turns WHERE id = ?",
            (turn_id,),
        ).one()
        or {}
    )
    return (
        agent.Usage(
            prompt_tokens=row.get("total_tokens_in") or 0,
            completion_tokens=row.get("total_tokens_out") or 0,
            llm_calls=row.get("llm_calls") or 0,
            tool_calls=row.get("tool_calls") or 0,
            retrievals=row.get("retrievals") or 0,
        ),
        agent.Timings(
            total_ms=row.get("duration_ms") or 0,
            llm_ms=row.get("llm_ms") or 0,
            retrieval_ms=row.get("retrieval_ms") or 0,
            tool_ms=row.get("tool_ms") or 0,
            store_ms=row.get("store_ms") or 0,
        ),
    )


def _spans_of(store: Store, turn_id: str) -> list[dict[str, Any]]:
    rows = store.execute(
        "SELECT id, parent_span_id, seq, kind, name, started_at, ended_at, duration_ms, status, "
        "error_message, payload_json FROM spans WHERE turn_id = ? ORDER BY seq",
        (turn_id,),
    ).dicts()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return rows


def snapshot_as_of(spans: list[dict[str, Any]]) -> str | None:
    """The `as_of` any tool result carried — the UI's *"Employee data as of …"* note (§11.5)."""
    for span in spans:
        if span["kind"] != "tool_call":
            continue
        body = span["payload"].get("structured_content") or {}
        if not isinstance(body, dict):
            continue
        as_of = body.get("as_of")
        if isinstance(as_of, str) and as_of:
            return as_of
    return None


def _publish_turn_started(store: Store, session_id: str, turn_id: str, *, seq: int | None = None) -> None:
    """§11.3's first frame. A resumed turn keeps its own `seq`; a new one is the session's next."""
    if seq is None:
        existing = store.execute("SELECT COUNT(*) AS n FROM turns WHERE session_id = ?", (session_id,)).scalar() or 0
        seq = int(existing) + 1
    broker.publish(
        turn_id,
        "turn_started",
        {"turn_id": turn_id, "session_id": session_id, "seq": seq, "started_at": now_micros()},
    )


def _publish_turn_completed(response: ChatResponse) -> None:
    broker.publish(
        response.turn_id,
        "turn_completed",
        {
            "outcome": response.outcome,
            "duration_ms": response.timings.total_ms,
            "dashboard_url": response.dashboard_url,
        },
    )


#: The label each typed answer block wears (§11.5). The recommendation string is verbatim: the
#: rubric asks that a recommendation never read as company policy, and `test_chat_page_renders`
#: asserts on this exact text.
BADGE_TEXT = {
    "policy_fact": "Policy fact",
    "recommendation": "Recommendation — not company policy",
    "escalation": "Escalation",
}

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def human_date(value: str) -> str:
    """`2026-09-01` → `1 September 2026`, the form the snapshot note reads in (§11.5)."""
    try:
        year, month, day = (int(part) for part in value.split("-"))
        return f"{day} {_MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return value


def _render_turn(request: Request, response: ChatResponse, *, question: str | None = None) -> Response:
    """JSON is the contract (§11.1); the chat page asks for the same turn as an htmx fragment.

    One endpoint, two representations — never a second route, because §11.8's endpoint list is
    exact. The fragment is the *same* `ChatResponse`, rendered server-side, so the badges and the
    citation chips `tests/contract/test_chat_page_renders.py` asserts on are the shipped ones.
    """
    if request.headers.get("HX-Request") != "true":
        return JSONResponse(response.model_dump(mode="json"))
    as_of = snapshot_as_of(_spans_of(_store(request), response.turn_id))
    preview = response.confirmation.arguments_preview if response.confirmation else {}
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_turn.html",
        context={
            "turn": response,
            "question": question,
            "as_of": as_of,
            "as_of_human": human_date(as_of) if as_of else None,
            "badge_text": BADGE_TEXT,
            "citations_by_id": {citation.chunk_id: citation for citation in response.citations},
            "arguments_preview": json.dumps(preview, indent=2, ensure_ascii=False),
        },
    )


# --------------------------------------------------------------------------------------
# The unmodelled failure — constraint 11 and §12.3: still 200, still a closed turn
# --------------------------------------------------------------------------------------

#: What the caller is told when something the design does not model went wrong. Never the
#: exception, never a stack trace (§12.3) — the detail lives on the `error` span instead.
INTERNAL_ERROR_TEXT = (
    "Something went wrong inside the copilot and this request could not be completed. Nothing was created or changed."
)
INTERNAL_ESCALATION_TEXT = f"Please ask People Operations directly at {g5.PEOPLE_OPS} and try again shortly."


def _open_buffer(turn_id: Any) -> trace_module.TurnBuffer | None:
    """The still-open buffer for this request's turn, if the failure left one behind."""
    if not isinstance(turn_id, str):
        return None
    return next((buffer for buffer in trace_module.open_turns() if buffer.turn_id == turn_id), None)


def _internal_error_json(answer: str) -> Response:
    """The typed 200 body that needs neither the store nor a template to build."""
    return JSONResponse({"code": "INTERNAL_ERROR", "detail": INTERNAL_ERROR_TEXT, "answer": answer})


def _last_resort_error_response(scope: Any) -> Response:
    """The handler of last resort: hard-coded, store-free, template-free — and still **200**.

    Reached only when `unhandled_error_response` itself raised. That is not hypothetical: closing
    the buffered turn writes through `core/trace.py` to the store, so an unreachable trace store —
    one of the five modelled `degradations[]` — makes the error path fail inside its own `except`
    clause, and uvicorn then answers a bare `500 Internal Server Error`. Constraint 11 has no
    exception for *"the error path also failed"*, so this body comes from literals alone: no store,
    no Jinja, no `render_answer`. The turn stays `ended_at IS NULL` in that case — unavoidable when
    the store cannot be written — and `sweep_stale_turns()` at boot is the existing backstop.
    """
    htmx = any(
        name.lower() == b"hx-request" and value.strip().lower() == b"true" for name, value in scope.get("headers") or ()
    )
    if htmx:
        return HTMLResponse(
            '<article class="turn" data-outcome="error">'
            f"<p>{escape(INTERNAL_ERROR_TEXT)}</p><p>{escape(INTERNAL_ESCALATION_TEXT)}</p>"
            "</article>"
        )
    return _internal_error_json(f"{INTERNAL_ERROR_TEXT}\n\n{INTERNAL_ESCALATION_TEXT}")


def unhandled_error_response(request: Request, exc: BaseException) -> Response:
    """Close the turn an unmodelled exception left open, then answer **200** with a typed block.

    Constraint 11 — *"every failure path answers HTTP 200 with a useful body"* — and §12.3's
    *"never a 5xx, never a stack trace"*. The shape is the one `_configuration_required` already
    uses on the modelled paths: a `recommendation` block saying what happened and an `escalation`
    block pointing at People Operations, with the exception recorded on an `error` span
    (`error_kind="internal"`) written through `core/trace.py`, exactly like every other span.
    """
    message = f"{type(exc).__name__}: {exc}"
    logger.error("unhandled error on %s %s: %s", request.method, request.url.path, message, exc_info=exc)
    buffer = _open_buffer(request.scope.get("state", {}).get("turn_id"))
    blocks = [
        AnswerBlock(type="recommendation", text=INTERNAL_ERROR_TEXT, citations=[]),
        AnswerBlock(type="escalation", text=INTERNAL_ESCALATION_TEXT, citations=[]),
    ]
    answer = render_answer(blocks, [])
    if buffer is None:
        # Nothing was in flight (or the writer is already gone): there is no turn to close, so the
        # answer is the typed body without a trace.
        return _internal_error_json(answer)

    # Everything below this line touches the trace store or the template engine, and each of them
    # can fail for the same reason the request did (an unreachable store makes `close()` raise on
    # its flush). The catch-all is only a catch-all if it cannot itself throw out of the `except`
    # clause that called it, so the whole tail falls back to the buffer-less body.
    try:
        buffer.add_span(
            "error",
            "web",
            ErrorPayload(error_kind="internal", message=message, retryable=True, component="web"),
            status="error",
            error_message=message,
        )
        buffer.close(
            outcome="error",
            stop_reason="error",
            error_kind="internal",
            final_answer=answer,
            answer_blocks=blocks,
            citations=[],
        )
        store = _store(request)
        usage, timings = _turn_rollups(store, buffer.turn_id)
        response = ChatResponse(
            session_id=buffer.session_id,
            turn_id=buffer.turn_id,
            trace_id=buffer.session_id,
            outcome="error",
            answer=answer,
            answer_blocks=blocks,
            citations=[],
            trace=project(buffer.turn_id, session_id=buffer.session_id, store=store),
            confirmation=None,
            usage=usage,
            timings=timings,
            stream_url=f"/chat/stream?turn_id={buffer.turn_id}",
            dashboard_url=f"/dashboard/sessions/{buffer.session_id}#turn-{buffer.seq}",
        )
        _publish_turn_completed(response)
        return _render_turn(request, response)
    except Exception:
        logger.exception("recording the unmodelled failure failed too; answering without a trace")
        return _internal_error_json(answer)


class UnhandledErrorMiddleware:
    """The catch-all, as pure ASGI so `/chat/stream` and the MCP mount stream through untouched.

    It sits **inside** the access gate and **outside** Starlette's `ExceptionMiddleware`, so by the
    time anything reaches here `HTTPException` and `RequestValidationError` have already been
    mapped: what is left is precisely the unmodelled failure — the one that used to escape
    `run_turn` as a bare HTTP 500 and leave the turn row open until the next boot sweep.

    `app.add_exception_handler(Exception, …)` is deliberately **not** used for this. Starlette
    routes that key to `ServerErrorMiddleware`, which sends the response and then re-raises, so the
    connection is still torn down and the failure is still reported as a crash. Catching it here
    ends the request cleanly. Once the response has started there is nothing left to say, so the
    exception is re-raised and the server closes the stream.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def sender(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, sender)
        except Exception as exc:
            if started:  # the headers are already on the wire; nothing can be substituted now
                raise
            try:
                response = unhandled_error_response(Request(scope, receive), exc)
            except Exception:
                # Even building the typed answer failed. Anything that escaped here would leave
                # uvicorn to send a bare 500, which constraint 11 forbids unconditionally.
                logger.exception("the unmodelled-failure handler itself failed")
                response = _last_resort_error_response(scope)
            await response(scope, receive, send)


# --------------------------------------------------------------------------------------
# The routes
# --------------------------------------------------------------------------------------

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request) -> Response:
    """The single Jinja page of §11.5."""
    identity = identity_of(request)
    settings = _settings(request)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "employees": request.app.state.employees,
            "actor": identity.actor,
            "is_admin": identity.is_admin,
            "demo_prompts": DEMO_PROMPTS,
            "data_as_of": request.app.state.data_as_of,
            "gate_on": gate_enabled(settings),
        },
    )


@router.post("/chat")
async def chat(request: Request) -> Response:
    """The contract endpoint (R6.3). Thin: validate, authorise, call `run_turn`, return (§9.1)."""
    body = await _parse_body(request, ChatBody)
    identity = identity_of(request)
    authorise_options(body, identity)
    store = _store(request)

    session_id = _validated_id(body.session_id, "session_id") or new_session_id()
    turn_id = _validated_id(body.turn_id, "turn_id")
    if turn_id is not None and store.execute("SELECT id FROM turns WHERE id = ?", (turn_id,)).one():
        raise HTTPException(status_code=409, detail={"code": "TURN_ID_IN_USE", "turn_id": turn_id})
    turn_id = turn_id or new_turn_id()
    # The seam `UnhandledErrorMiddleware` reads: if an unmodelled exception escapes `run_turn`,
    # this is the turn it has to close before answering (§12.3).
    request.scope.setdefault("state", {})["turn_id"] = turn_id

    chat_request = ChatRequest(
        message=body.message,
        session_id=session_id,
        turn_id=turn_id,
        employee_id=body.employee_id or identity.actor,
        client_label=body.client_label,
        options=body.options,
        auth_mode=identity.auth_mode,
        actor_role=identity.actor_role,
        actor_source="explicit" if body.employee_id or identity.actor_source == "explicit" else "default",
        user_agent_hash=user_agent_hash(request.headers.get("user-agent")),
    )
    _publish_turn_started(store, session_id, turn_id)
    response = await agent.run_turn(chat_request)
    request.app.state.served_a_turn = True
    _publish_turn_completed(response)
    return _render_turn(request, response, question=body.message)


@router.post("/chat/confirm")
async def chat_confirm(request: Request) -> Response:
    """Resolve a pending mock write — **the only place a confirmation token is minted** (§8.6).

    The token is bound to the exact arguments read from the gated attempt's `tool_call` span
    payload, never to `arguments_preview`, which is a display subset. A Cancel mints the same row
    with `user_response="declined"`: `confirm.validate()` already rejects it, it is never returned
    to any client, and the decision is recorded as a **second** `confirmation` span — emitted here,
    because `resume_turn` is not called on a decline (§11.2).
    """
    body = await _parse_body(request, ConfirmBody)
    store = _store(request)
    turn = store.execute("SELECT id, session_id, seq FROM turns WHERE id = ?", (body.turn_id,)).one()
    if turn is None or turn["session_id"] != body.session_id:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_TURN", "turn_id": body.turn_id})

    spans = _spans_of(store, body.turn_id)
    pending = next(
        (
            span
            for span in reversed(spans)
            if span["kind"] == "confirmation" and span["payload"].get("user_response") == "pending"
        ),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=404, detail={"code": "NO_PENDING_CONFIRMATION", "turn_id": body.turn_id})
    if int(pending["payload"].get("expires_at") or 0) <= now_micros():
        raise HTTPException(status_code=409, detail={"code": "CONFIRMATION_EXPIRED", "turn_id": body.turn_id})

    gated = next(
        (span for span in spans if span["id"] == pending["parent_span_id"] and span["kind"] == "tool_call"),
        None,
    )
    if gated is None:
        raise HTTPException(status_code=409, detail={"code": "NO_GATED_CALL", "turn_id": body.turn_id})

    token = confirm_gate.mint(
        store,
        session_id=body.session_id,
        turn_id=body.turn_id,
        span_id=gated["id"],
        tool_name=str(gated["payload"]["tool_name"]),
        arguments=dict(gated["payload"].get("arguments") or {}),
        human_summary=str(pending["payload"].get("human_summary") or ""),
        user_response=body.decision,
    )

    awaiting_ms = max(0, (now_micros() - int(pending["ended_at"] or pending["started_at"])) // 1000)
    # A decline reopens the buffer **uncounted**: the reopen exists only so `_record_decline` can
    # write the second `confirmation` span through `core/trace.py`, and §11.2 closes that turn
    # without ever resuming it. Counting it would report `resumed_count = 1` on a turn nobody
    # resumed — the number the dashboard's resumed-turn figures read.
    confirmed = body.decision == "confirmed"
    buffer = trace_module.reopen_turn(body.turn_id, awaiting_ms, resumed=confirmed)
    request.scope.setdefault("state", {})["turn_id"] = body.turn_id
    _publish_turn_started(store, body.session_id, body.turn_id, seq=int(turn["seq"]))

    if confirmed:
        response = await agent.resume_turn(body.session_id, body.turn_id, token)
    else:
        response = _record_decline(store, buffer, pending)
    _publish_turn_completed(response)
    return _render_turn(request, response)


def _record_decline(store: Store, buffer: trace_module.TurnBuffer, pending: dict[str, Any]) -> ChatResponse:
    """The **second** `confirmation` span, `declined`, and the turn closes without resuming (§11.2)."""
    payload = pending["payload"]
    action = str(payload.get("action") or "")
    buffer.add_span(
        "confirmation",
        action,
        ConfirmationPayload(
            action=action,
            arguments_preview=dict(payload.get("arguments_preview") or {}),
            human_summary=str(payload.get("human_summary") or ""),
            prompt_shown=str(payload.get("prompt_shown") or payload.get("human_summary") or ""),
            expires_at=int(payload.get("expires_at") or 0),
            user_response="declined",
            resolved_at=now_micros(),
        ),
    )
    blocks = [
        AnswerBlock(
            type="recommendation",
            text="Cancelled — nothing was created. Ask again whenever you would like me to open it.",
            citations=[],
        )
    ]
    answer = render_answer(blocks, [])
    buffer.close(
        outcome="refused",
        stop_reason="declined",
        final_answer=answer,
        answer_blocks=blocks,
        citations=[],
    )
    usage, timings = _turn_rollups(store, buffer.turn_id)
    return ChatResponse(
        session_id=buffer.session_id,
        turn_id=buffer.turn_id,
        trace_id=buffer.session_id,
        outcome="refused",
        answer=answer,
        answer_blocks=blocks,
        citations=[],
        trace=project(buffer.turn_id, session_id=buffer.session_id, store=store),
        confirmation=None,
        usage=usage,
        timings=timings,
        stream_url=f"/chat/stream?turn_id={buffer.turn_id}",
        dashboard_url=f"/dashboard/sessions/{buffer.session_id}#turn-{buffer.seq}",
    )


@router.get("/chat/stream")
async def chat_stream(turn_id: str) -> StreamingResponse:
    """One SSE subscription per `turn_id`; subscribe **before** POSTing (§11.1, §11.3).

    The id is validated against the same `ID_PATTERN` `POST /chat` applies (§17). Each subscription
    allocates a queue and a `_subscribers` entry that lives for up to `STREAM_MAX_S`, and
    `_rate_limited` deliberately exempts this route — a limit here would throttle the rail rather
    than the work behind it — so an unvalidated id let a gated-but-authenticated client hold an
    unbounded number of 300-second subscriptions on arbitrary strings. It also makes a typo'd id a
    named error instead of a stream that silently emits nothing but heartbeats.
    """
    if not ID_PATTERN.match(turn_id):
        raise HTTPException(status_code=422, detail={"code": "INVALID_ID", "field": "turn_id"})
    return StreamingResponse(
        broker.stream(turn_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/session/actor")
async def set_actor(request: Request) -> Response:
    """The act-as selector (§11.5). The cookie is not HttpOnly: it is a preference, not a key."""
    body = await _parse_body(request, ActorBody)
    response = JSONResponse({"actor": body.actor, "actor_role": "admin" if body.actor == "admin" else "employee"})
    response.set_cookie(
        ACTOR_COOKIE,
        body.actor,
        max_age=COOKIE_MAX_AGE_S,
        httponly=False,
        samesite="lax",
        secure=request_is_https(request),
        path="/",
    )
    return response


# -- the key page (never gated) ---------------------------------------------------------


@router.get("/access", response_class=HTMLResponse)
async def access_page(request: Request) -> Response:
    return TEMPLATES.TemplateResponse(request=request, name="access.html", context={"message": None})


@router.post("/access")
async def access_submit(request: Request) -> Response:
    """The key form: validate, set `mosaic_access`, redirect to `/` (§11.8)."""
    form = await request.form()
    supplied = str(form.get("access") or "")
    token = secret_value(_settings(request).app_access_token) or ""
    if not gate_enabled(_settings(request)):
        return RedirectResponse("/", status_code=303)
    if not token:
        # The gate is on with no token configured: `compare_digest(supplied, "")` would mint the
        # cookie for an empty form field. There is no key that works, so say so and set nothing.
        return TEMPLATES.TemplateResponse(
            request=request,
            name="access.html",
            context={"message": MISSING_TOKEN_MESSAGE},
            status_code=403,
        )
    if not hmac.compare_digest(supplied, token):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="access.html",
            context={"message": "That access key was not recognised."},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        ACCESS_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=request_is_https(request),
        path="/",
    )
    return response


@router.post("/access/logout")
async def access_logout() -> Response:
    """Clears both cookies (§11.8)."""
    response = RedirectResponse("/access", status_code=303)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(ACTOR_COOKIE, path="/")
    return response


# -- status (never gated) ---------------------------------------------------------------


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Always 200 while the process is up — degradation is a status string, never a 5xx (§11.4)."""
    return JSONResponse(await health_payload(request.app))


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """503 until the ONNX model and the index are resident (§11.4)."""
    state = request.app.state
    if state.ready:
        return JSONResponse({"ready": True, "reason": None})
    return JSONResponse({"ready": False, "reason": state.ready_reason}, status_code=503)


# --------------------------------------------------------------------------------------
# `/health`'s payload (§11.4)
# --------------------------------------------------------------------------------------


async def health_payload(app: Any) -> dict[str, Any]:
    """The §11.4 body. Every block is independently degradable and none of them can raise."""
    settings: Settings = app.state.settings
    degradations: list[str] = []

    mcp = await _mcp_block(app)
    if not mcp["connected"]:
        degradations.append("mcp_disconnected")

    index = _index_block()
    if index.get("mismatch"):
        degradations.append("index_model_mismatch")
    index.pop("mismatch", None)

    store_block, store = _store_block(settings)
    if not store_block["reachable"]:
        degradations.append("trace_store_unreachable")

    llm = _llm_block(settings, store)
    if not llm["agent"]["configured"]:
        degradations.append("llm_api_key_missing")

    if gate_misconfigured(settings):
        degradations.append("access_token_missing")

    return {
        "status": "degraded" if degradations else "ok",
        "app": {
            "version": APP_VERSION,
            "git_sha": settings.git_sha,
            "uptime_ms": procstat.uptime_ms(),
            "cold_start": not app.state.served_a_turn,
            "rss_mb": procstat.rss_mb(),
            "rss_peak_mb": procstat.rss_peak_mb(),
            "deploy_mode": settings.app_env,
            "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "mcp": mcp,
        "index": index,
        "data": {"as_of": app.state.data_as_of, "employees": len(app.state.employees)},
        "llm": llm,
        "trace_store": store_block,
        "degradations": degradations,
    }


async def _mcp_block(app: Any) -> dict[str, Any]:
    client = app.state.orchestrator.client
    try:
        catalog = await asyncio.wait_for(client.discover(), timeout=HEALTH_MCP_TIMEOUT_S)
    except (McpUnavailable, TimeoutError, OSError) as exc:
        return {
            "connected": False,
            "transport": app.state.settings.mcp_transport_effective,
            "url": app.state.settings.mcp_server_url,
            "protocol_version": None,
            "server_info": None,
            "tool_count": 0,
            "tool_names": [],
            "handshake_ms": None,
            "last_error": redact_text(str(exc)),
        }
    return {
        "connected": True,
        "transport": catalog.transport,
        "url": catalog.url,
        "protocol_version": catalog.protocol_version,
        "server_info": catalog.server_info.model_dump() if catalog.server_info else None,
        "tool_count": len(catalog.tools),
        "tool_names": list(catalog.names),
        "handshake_ms": catalog.handshake_ms,
        "last_error": None,
    }


def _index_block() -> dict[str, Any]:
    """`index_model_mismatch` names both values, and a missing index is simply not loaded (§11.4)."""
    from hrmosaic.rag.index import open_index

    try:
        open_index().close()
        meta = corpusread.read_index_meta()
    except IndexModelMismatch as exc:
        return {"loaded": False, "mismatch": True, "error": redact_text(str(exc))}
    except Exception as exc:  # a missing or unreadable file: not loaded, not a mismatch
        return {"loaded": False, "error": redact_text(str(exc))}
    return {
        "loaded": True,
        "doc_count": meta.doc_count,
        "chunk_count": meta.chunk_count,
        "embed_model": meta.embed_model,
        "dim": meta.dim,
        "corpus_sha256": meta.corpus_sha256,
        "manifest_sha256": meta.manifest_sha256,
        "built_at": meta.built_at,
    }


def _store_block(settings: Settings) -> tuple[dict[str, Any], Store | None]:
    try:
        store = get_store(settings)
        sessions = int(store.execute("SELECT COUNT(*) AS n FROM sessions").scalar() or 0)
        spans = int(store.execute("SELECT COUNT(*) AS n FROM spans").scalar() or 0)
        runs = int(store.execute("SELECT COUNT(*) AS n FROM eval_runs").scalar() or 0)
    except Exception as exc:
        return (
            {"backend": settings.persist_backend, "reachable": False, "last_error": redact_text(str(exc))},
            None,
        )
    return (
        {
            "backend": "turso" if isinstance(store, TursoHTTPStore) else "sqlite",
            "reachable": True,
            "session_count": sessions,
            "span_count": spans,
            "eval_runs_imported": runs,
        },
        store,
    )


def _llm_block(settings: Settings, store: Store | None) -> dict[str, Any]:
    agent_configured = settings.llm_provider == "stub" or bool(
        secret_value(settings.anthropic_api_key)
        if settings.llm_provider == "anthropic"
        else secret_value(settings.llm_api_key)
    )
    judge_key = secret_value(settings.judge_api_key)
    last_status, last_latency = _last_llm_call(store, settings.llm_provider)
    return {
        "agent": {
            "provider": settings.llm_provider,
            "model": settings.llm_model if settings.llm_provider != "stub" else "stub",
            "configured": agent_configured,
            "last_status": last_status,
            "last_latency_ms": last_latency,
            "calls_today": count_calls_today(store, settings.llm_provider) if store is not None else 0,
            "daily_call_cap": settings.llm_daily_call_cap,
        },
        "judge": {
            "provider": settings.judge_provider,
            "model": settings.judge_model,
            "configured": settings.judge_provider == "stub" or bool(judge_key or secret_value(settings.llm_api_key)),
            "separate_key": judge_key is not None,
        },
    }


def _last_llm_call(store: Store | None, provider: str) -> tuple[str | None, int | None]:
    if store is None:
        return None, None
    try:
        row = store.execute(
            "SELECT status, duration_ms FROM spans WHERE kind = 'llm_call' AND name LIKE ? "
            "ORDER BY started_at DESC LIMIT 1",
            (f"{provider}:%",),
        ).one()
    except Exception:
        return None, None
    if row is None:
        return None, None
    return row["status"], row["duration_ms"]


#: The two one-click demo prompts of §18, shared by the UI buttons and `scripts/demo_task_*.sh`.
DEMO_PROMPTS = {
    "demo_1": "I want to work from Berlin from 3 November to 14 December 2026 — can I?",
    "demo_2": (
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?"
    ),
}

__all__ = [
    "ACCESS_COOKIE",
    "ACTOR_COOKIE",
    "APP_VERSION",
    "DEGRADATIONS",
    "BADGE_TEXT",
    "DEMO_PROMPTS",
    "AccessGateMiddleware",
    "ChatBody",
    "ConfirmBody",
    "Identity",
    "RateLimiter",
    "gate_enabled",
    "gate_misconfigured",
    "health_payload",
    "identity_of",
    "router",
]
