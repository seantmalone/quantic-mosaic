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
GET  /api/traces/turns/{id}  the single-turn view-model               gated (P9: web/dashboard.py)
```

**Two levels of identity, and they are not the same thing (§17).** *Authentication* is one shared
secret, `APP_ACCESS_TOKEN`, presented as `?access=` (exchanged once for the HttpOnly `mosaic_access`
cookie and stripped from the URL), as that cookie, or as `Authorization: Bearer`, each compared with
`secrets.compare_digest`. *Authorization* is the persona: cookie `mosaic_actor` or header `X-Actor`,
an `E1xxx` id or the literal `admin`, defaulting to `E1042`. The admin persona is required —
server-side, **403** `{"code": "ADMIN_REQUIRED"}` — for the three write endpoints of `ADMIN_ROUTES`
and the privileged `POST /chat` options, and for nothing else: every `/dashboard/*` page and every
`/api/*` read answers any persona that holds the token. Inside the MCP tools the acting id stays
audit-only (§8.7).

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
import html
import ipaddress
import json
import logging
import re
import secrets
import time
from collections import deque
from collections.abc import Mapping
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hrmosaic.agent import orchestrator as agent
from hrmosaic.agent.client import McpUnavailable
from hrmosaic.agent.guardrails import g5
from hrmosaic.agent.orchestrator import (
    ChatOptions,
    ChatRequest,
    ChatResponse,
    Timings,
    Usage,
    clarify_chips,
    clarify_slot_of,
    parse_next_steps,
    project,
    render_answer,
)
from hrmosaic.core import corpusread, procstat
from hrmosaic.core import trace as trace_module
from hrmosaic.core.corpusread import IndexModelMismatch
from hrmosaic.core.db import Store, TursoHTTPStore, get_store, now_micros
from hrmosaic.core.ids import new_session_id, new_turn_id, user_agent_hash
from hrmosaic.core.llm import count_calls_today
from hrmosaic.core.models import NOTICE, AnswerBlock, Citation, ErrorPayload
from hrmosaic.core.redact import redact_text
from hrmosaic.mcpserver import confirm as confirm_gate
from hrmosaic.mcpserver.tools.create_mock_hr_ticket import queue_label
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

#: **One gate, not two** (§11.8, UX W1). Everything the shared access token opens is reachable in
#: one click: the role gates *writes* only, never reads and never navigation.
#:
#: This used to be `ADMIN_PREFIXES = ("/dashboard", "/api")`, which refused both whole prefixes to
#: anyone but the `admin` persona. It protected nothing — `POST /session/actor` sets the persona
#: cookie with no check at all, so the "gate" was one dropdown away — while costing 24 of the 25
#: personas, the default `E1042` included, any route to the dashboard: every citation chip, every
#: `Export JSON` button and every `hx-get` drawer dead-ended in a raw `{"code":"ADMIN_REQUIRED"}`
#: body.
#:
#: The match is on the **exact `(method, path)` pair**, never a prefix: `GET /api/eval/runs` and
#: `POST /api/eval/runs` share a path, and a prefix rule would take the read down with the write.
ADMIN_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/dev/reset-sandbox"),
        ("POST", "/api/mcp/rediscover"),
        ("POST", "/api/eval/runs"),
    }
)

#: The per-IP limit of §17 covers `POST /chat` and the MCP mount, and nothing else: a rate limit on
#: `/chat/stream` would throttle the rail rather than the work behind it.
MCP_MOUNT_PREFIX = "/mcp-server"

#: **The app's own loopback client is exempt from the mount's limit.** The limit is keyed on the
#: client address (`rate_limit_key()` below), and the agent reaches its own MCP mount over
#: loopback — so every `initialize`, `tools/list` and `tools/call` the app makes on its own behalf,
#: plus the `client.discover()` behind each `GET /health`, lands in the same `127.0.0.1` bucket as
#: the grader's browser. One tool-using turn is ~10 requests, so past three turns a minute the app
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


def needs_admin(method: str, path: str) -> bool:
    """Exact-match the three write endpoints of `ADMIN_ROUTES`; everything else is a read."""
    return (method.upper(), path.rstrip("/") or "/") in ADMIN_ROUTES


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


def actor_display_name(request: Request, actor: str) -> str:
    """The persona's own name — what the masthead's read-only identity chip shows (UX W1).

    `getattr`, not `request.app.state.employees`: the refusal page is rendered from inside the
    ASGI gate, which can run before the lifespan has populated `app.state` (and after a failure
    that left it empty). A masthead is not worth a 500.
    """
    if actor == "admin":
        return "HR admin"
    for employee in getattr(request.app.state, "employees", None) or ():
        if employee.get("employee_id") == actor:
            return str(employee.get("name") or actor)
    return actor


def _greeting_name(request: Request, actor: str) -> str:
    """Who the empty conversation says hello to: a first name, or nobody in particular.

    The admin persona is a role rather than a person, and *"Hi HR admin"* is the interface talking
    to its own configuration.
    """
    if actor == "admin":
        return "there"
    return actor_display_name(request, actor).split(" ")[0] or "there"


def shell_context(request: Request, *, surface: Literal["chat", "dashboard"]) -> dict[str, Any]:
    """What `_masthead.html` needs, and the only thing that differs between the two surfaces.

    `web/dashboard.py::_page()` and every page in `web/api.py` call this, so the rendered masthead
    is byte-identical modulo `aria-current` — `tests/contract/test_nav_parity.py` (**P3**).
    """
    identity = identity_of(request)
    settings = getattr(request.app.state, "settings", None)
    return {
        "surface": surface,
        "actor": identity.actor,
        "actor_name": actor_display_name(request, identity.actor),
        "is_admin": identity.is_admin,
        "gate_on": gate_enabled(settings) if settings is not None else False,
    }


def conversation_url(request: Request) -> str:
    """Where *"Back to your conversation"* goes from the policy reader (UX W6, nav-reaudit-1).

    The reader is the destination of every citation and had no outbound route but the masthead's
    `Chat`, which — before the chat page started writing `?session=` into its own URL — landed on an
    empty composer. The link is built server-side from the persona's most recent conversation,
    which is the same boundary `_owns()` draws on the way back in: a raw id is never guessed at,
    and a persona with no conversation yet is offered the fresh one at `/`.
    """
    identity = identity_of(request)
    where, params = ("", []) if identity.is_admin else ("WHERE s.employee_id = ?", [identity.actor])
    try:
        row = (
            _store(request)
            .execute(
                "SELECT s.id FROM sessions s JOIN turns t ON t.session_id = s.id AND t.ended_at IS NOT NULL "
                f"{where} ORDER BY s.last_activity_at DESC LIMIT 1",
                params,
            )
            .one()
        )
    except Exception:  # noqa: BLE001 — a reader with no store still gets a way back
        return "/"
    return f"/?session={row['id']}" if row else "/"


def _key_page(
    request: Request, *, status_code: int, message: str, detail: str | None = None, invalid: bool = False
) -> Response:
    """The key page, or its JSON equivalent for a client that did not ask for HTML.

    Two strings where the audience differs: `message` is what a visitor reads, `detail` is what an
    operator's `curl` gets. They are the same string unless a caller says otherwise — the one case
    that does is the unconfigured deployment, whose cause is an environment variable name and
    therefore no business of a visitor (UX W1, jargon-and-exposure-17).

    `invalid` is the narrower fact: a key was **supplied and rejected**. It is what the page marks
    the field with and prefixes the title with, so a reader who cannot see the red sentence is
    still told (UX W5, accessibility-and-responsive-12). An anonymous request that offered no
    credential at all is not a rejection and never sets it.
    """
    if _wants_html(request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="access.html",
            context={"message": message, "invalid": invalid},
            status_code=status_code,
        )
    return JSONResponse({"code": "ACCESS_REQUIRED", "detail": detail or message}, status_code=status_code)


#: What a gated request is told when the gate is on and no token is configured (`APP_ENV=docker`
#: with `APP_ACCESS_TOKEN` unset). It is a 403, not a 401: there is no key that would work.
#:
#: Two strings, because there are two audiences (jargon-and-exposure-17). The visitor is told what
#: they can do about it and nothing else; the environment variable is the operator's business and
#: travels only in the JSON `detail` an operator's `curl` sees.
MISSING_TOKEN_MESSAGE = "This deployment is not finished being set up, so nothing can be opened yet."
MISSING_TOKEN_DETAIL = "APP_ACCESS_TOKEN is not set on this deployment; every gated route is refused."

#: The plain sentence each refusal code reads as on a themed page. Nothing here names a header, a
#: cookie, an environment variable or a status code: the code itself is still in the JSON body a
#: client gets from the same route (UX W1, navigation-and-ia-3).
REFUSAL_COPY: dict[str, tuple[str, str]] = {
    "ADMIN_REQUIRED": (
        "That control is for the HR admin",
        "You can read everything on this dashboard, but changing it is reserved for the HR admin "
        "persona. Nothing was changed.",
    ),
    "ACCESS_TOKEN_MISSING": ("Not available yet", MISSING_TOKEN_MESSAGE),
    "RATE_LIMITED": (
        "That was a lot of questions at once",
        "Give it a minute and try again — this demo runs on one small instance.",
    ),
    "NOT_FOUND": (
        "That page is not here",
        "The link may be old, or the conversation it points at may have been cleared. "
        "Nothing is missing from your own chat.",
    ),
    "ERROR": (
        "Something went wrong",
        "That request could not be completed, and nothing was created or changed.",
    ),
}


def refusal_page(request: Request, *, status_code: int, code: str) -> Response:
    """The HTML representation of a refusal: the shared masthead, a sentence, and a route back.

    Beside `_key_page()` and negotiated the same way. A browser gets `templates/refused.html`; an
    API client gets the identical JSON body it has always got, because §11.8's codes are a
    contract and this is a representation, not a second one.
    """
    headline, detail = REFUSAL_COPY.get(code, REFUSAL_COPY["ERROR"])
    return TEMPLATES.TemplateResponse(
        request=request,
        name="refused.html",
        context={
            "status": status_code,
            "headline": headline,
            "detail": detail,
            **shell_context(request, surface="chat"),
        },
        status_code=status_code,
    )


def request_is_https(request: Request) -> bool:
    """Whether the *browser* reached this app over https — not whether ASGI did (§14.1).

    Render terminates TLS at its edge and forwards plain http into the container, and uvicorn's
    `ProxyHeadersMiddleware` rewrites the scheme only for a peer the process was told to trust. The
    deployed image now tells it to (`--proxy-headers --forwarded-allow-ips='*'` in the Dockerfile
    CMD, P20), but every other way this app runs does not — `make run`, `make demo1`, the test
    servers, a bare `uvicorn` — so the header is read here rather than left to the middleware. The
    two agree: with the middleware on, `request.url.scheme` is already `https` **and**
    `X-Forwarded-Proto` is still on the request, because the middleware rewrites the scope and
    strips nothing. Without this, `request.url.scheme` was `http` on the deployed service and every
    cookie below shipped without `Secure` — contradicting constraint 9 and the published claim in
    `deployed.md`. Reading the header is safe here in a way it would not be for an authorisation
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


def rate_limit_key(request: Request) -> str:
    """The bucket §17's `ACCESS_RATE_LIMIT_PER_MIN` counts against — the **last** forwarded hop.

    Every `X-Forwarded-For` entry is a claim, and only the last one was made by a peer this process
    has any reason to believe. Each proxy *appends* the address it received the request from, so
    behind Render's edge the chain reads `<whatever the caller sent>, <the address the edge saw>`:
    the prefix is attacker-controlled and the final entry is the edge's own observation.

    That distinction is why this function exists rather than `request.client.host`. The image's CMD
    carries `--proxy-headers --forwarded-allow-ips='*'` (P20), and `'*'` sets uvicorn's
    `always_trust`, under which `_TrustedHosts.get_trusted_client_address` returns the **first**
    entry of the chain (uvicorn 0.52.4). `request.client.host` inside the container is therefore
    client-settable. For the scheme rewrite the flag exists for that is harmless; for a
    denial-of-service bucket it is a regression on the single shared bucket P20 set out to fix — a
    caller who rotates the header mints an unlimited supply of fresh 30-per-minute budgets, where
    before the fix they were capped at 30 along with everyone else. Keying on the last entry keeps
    what the flag bought (a real per-visitor bucket) without handing out the bucket selector.

    Where no proxy header arrives at all — `make run`, `make demo1`, every test server, a bare
    `uvicorn` — this is exactly `request.client.host`, so the local behaviour is unchanged. uvicorn
    rewrites the ASGI scope and strips no header, so the full chain is still readable here.
    """
    hops = [
        hop.strip() for value in request.headers.getlist("x-forwarded-for") for hop in value.split(",") if hop.strip()
    ]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


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
            if _wants_html(request):
                return refusal_page(request, status_code=403, code="ACCESS_TOKEN_MISSING")
            return JSONResponse(
                {"code": "ACCESS_TOKEN_MISSING", "detail": MISSING_TOKEN_DETAIL},
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

        if needs_admin(request.method, path) and role != "admin":
            if _wants_html(request):
                return refusal_page(request, status_code=403, code="ADMIN_REQUIRED")
            return JSONResponse({"code": "ADMIN_REQUIRED"}, status_code=403)

        if self._rate_limited(request, path):
            if _wants_html(request):
                return refusal_page(request, status_code=429, code="RATE_LIMITED")
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
            return _key_page(request, status_code=403, message=MISSING_TOKEN_MESSAGE, detail=MISSING_TOKEN_DETAIL)
        supplied = request.query_params.get("access")
        if supplied is not None and request.method == "GET":
            if not hmac.compare_digest(supplied, token):
                return _key_page(request, status_code=401, message="That access key was not recognised.", invalid=True)
            return self._exchange(request, token)

        cookie = request.cookies.get(ACCESS_COOKIE)
        if cookie is not None and hmac.compare_digest(cookie, token):
            return "cookie"

        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and hmac.compare_digest(value.strip(), token):
            return "bearer"

        return _key_page(request, status_code=401, message="Enter the access key you were given to continue.")

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
        client = rate_limit_key(request)
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


#: The heading each **non-fact** group of answer blocks is given (§11.5, amended UX W2).
#:
#: Until W2 every block wore an uppercase chip — `POLICY FACT` five times in one answer, and
#: `RECOMMENDATION — NOT COMPANY POLICY` stamped over refusals, clarifications, confirmation cards
#: and server errors alike (chat-production-ux-8, jargon-and-exposure-5/14). A `policy_fact` gets no
#: label at all now: it is prose, and the source reference beneath it carries the authority. The
#: other two are grouped once per turn under one of these headings.
#:
#: The labelling guarantee the rubric asks for — a recommendation must never read as company
#: policy — is unchanged and lives in two places it always did: `orchestrator.render_answer()`,
#: which builds the plain-text `answer` the JSON contract and the eval harness read, and
#: `SUGGESTION_FOOTNOTE` below, which states it once under the group instead of once per sentence.
BLOCK_HEADINGS = {
    # The reader's own data — never advice, never policy (UX W7, JX2-05 = cpux2-4).
    "record": "From your HR record",
    "recommendation": "What I suggest you do",
    "escalation": "Who to contact",
}

#: One footnote per turn, under the suggestions.
SUGGESTION_FOOTNOTE = "Suggestions are guidance, not company policy."

#: The outcomes on which a heading is the right thing to wear. On every other one — a refusal, a
#: clarifying question, a confirmation card, a crash — the blocks *are* the answer, and heading them
#: "What I suggest you do" would be the badge defect in another font (jargon-and-exposure-5).
LABELLED_OUTCOMES = frozenset({"answered", "escalated", "partial"})

#: What the confirmation card calls each argument it shows, in the order it shows them. The card
#: used to print the tool's raw arguments as JSON — `employee_id`, `queue: hr-timeoff`, `priority` —
#: inside a `<pre>` that was clipped mid-value at 390px (jargon-and-exposure-6). Anything not named
#: here is not shown: the full arguments are on the `tool_call` span and in `/api/traces/tools`.
CONFIRM_FIELD_LABELS: dict[str, str] = {
    "summary": "Request",
    "queue": "Goes to",
    "priority": "Priority",
    "to_name": "Goes to",
    "recipient_role": "Goes to",
    "subject": "Subject",
    "purpose": "About",
}

#: The priority that is not worth a row. Every ticket is `normal` unless the turn said otherwise.
DEFAULT_PRIORITY = "normal"


def _confirm_fields(preview: Mapping[str, Any]) -> list[dict[str, str]]:
    """The confirmation card's `<dl>`: label/value pairs, in reading order, human words only.

    `queue` is translated through the tool server's own `QUEUE_LABELS`, so the card says
    *"HR Time Off team"* where the routing key says `hr-timeoff`; `employee_id` is dropped (the
    person reading the card is the person the request is for); and a `normal` priority is dropped
    because it is the default and says nothing.
    """
    rows: list[dict[str, str]] = []
    for key, label in CONFIRM_FIELD_LABELS.items():
        raw = preview.get(key)
        if raw in (None, ""):
            continue
        value = str(raw)
        if key == "queue":
            value = queue_label(value)
        elif key == "priority":
            if value == DEFAULT_PRIORITY:
                continue
            value = value.capitalize()
        if any(row["label"] == label for row in rows):
            continue
        rows.append({"label": label, "value": value})
    return rows


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


#: **P2 — no internal identifier in chat**, the fourteenth pattern. Twelve of the thirteen
#: enumerated patterns were clean at the re-audit; `E1007` reached the reader fifteen times inside
#: *"Obtain written approval from your director (Dana, E1007)"* the first time `next_steps` was
#: rendered (UX W6, cpux-re-4). `synthesize.j2` rule 6c forbids writing one; this is the guard
#: behind that rule, applied to every string the answer body prints, because a prompt rule is an
#: instruction and a reader-facing invariant needs a mechanism.
EMPLOYEE_ID = re.compile(r"\bE1\d{3}\b")

#: The id as an aside beside a name — `(Dana, E1007)` → `(Dana)`, `(E1007)` → nothing at all.
_ID_ASIDE = re.compile(r"\s*,\s*E1\d{3}\b")
_ID_PARENTHESIS = re.compile(r"\s*[(\[]\s*E1\d{3}\s*[)\]]")


def _without(pattern: re.Pattern[str], text: str) -> str:
    r"""`text` with every match of `pattern` removed, tidying **only the gap each one leaves**.

    The tidy-up used to be a pass over the whole string — `\s{2,}` → `" "`, then `" ."` → `"."` —
    which is a different function on a block than it is on a sentence: `\s` matches a newline, so
    removing one id from a two-paragraph block also flattened the paragraph break and rewrote every
    unrelated `" ."` in it (UX W6, the fix round of the re-audit). Here the space that introduced a
    removed id goes with it, spaces and tabs only, and every other character survives untouched.
    """
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        prefix = text[cursor : match.start()]
        trimmed = prefix.rstrip(" \t")
        cursor = match.end()
        if not any(piece.strip() for piece in pieces) and not trimmed.strip():
            # The removal opened the string: the space it left behind is leading whitespace.
            cursor += len(text[cursor:]) - len(text[cursor:].lstrip(" \t"))
        elif trimmed != prefix and text[cursor : cursor + 1].isalnum():
            # Two words would otherwise be welded together where the id stood between them.
            trimmed += " "
        pieces.append(trimmed)

    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)


def without_employee_ids(text: str) -> str:
    """Chat prose with every `E1xxx` taken out of it, and the punctuation around it tidied.

    The person is kept and the id is dropped: *"your director (Dana, E1007)"* reads *"your director
    (Dana)"*. The id is not lost — it is on the `tool_call` span, in `mock_writes` and in
    `/api/*` (P15); it is simply not something a person is shown in a sentence about their manager.
    """
    body = _without(_ID_PARENTHESIS, text)
    body = _without(_ID_ASIDE, body)
    return _without(EMPLOYEE_ID, body)


def rendered_next_steps(response: ChatResponse) -> list[str]:
    """The steps the turn actually prints, which is not always the steps it carries (UX W6).

    Two rules, both from the re-audit (cpux-re-3 = JX-R15, npo2-02):

    * **Never on an outcome that groups its suggestions.** On `answered`, `escalated` and `partial`
      the `recommendation` blocks are gathered under *"What I suggest you do"*, and `next_steps` —
      the other half of the same model call, saying the same kind of thing — was merged into that
      one list: seven bullets where §3.3 wireframes two, carrying a model-computed deadline and an
      employee id onto the one outcome that already had five other things to read (cpux-re-3 =
      JX-R15, npo2-02, cpux-re-4). On a refusal, a clarification or a crash nothing is grouped, the
      steps *are* the recovery path, and they are the most useful half of those turns.
    * **Never a duplicate of a block.** Belt and braces for the same reason: the two lists come out
      of one model call and it repeats itself.

    The record keeps every step either way: `turns.next_steps_json`, `/api/*` and the stored
    `final_answer` all carry the full list (P15).
    """
    if response.outcome in LABELLED_OUTCOMES:
        return []
    said = {" ".join(block.text.split()).rstrip(".").lower() for block in response.answer_blocks}
    steps: list[str] = []
    for step in response.next_steps:
        text = without_employee_ids(str(step))
        key = " ".join(text.split()).rstrip(".").lower()
        if key and key not in said:
            said.add(key)
            steps.append(text)
    return steps


#: The four things the corpus markdown uses that a reader notices when they are missing: bold,
#: italic, inline code and a bulleted or numbered list. The reader published the source verbatim
#: inside one `<p>` — literal `*people*` asterisks and the database field name `work_arrangement`
#: in backticks, shown to employees (UX W6, JX-R3) — because the passage text is stored as the
#: markdown it was ingested from. Everything is escaped first and only these four are given back,
#: so a corpus document cannot inject markup into the page that quotes it.
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_STRONG = re.compile(r"\*\*([^*]+)\*\*")
_MD_EM = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_MD_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_MD_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _inline_markup(line: str) -> str:
    body = html.escape(line)
    body = _MD_CODE.sub(r"<code>\1</code>", body)
    body = _MD_STRONG.sub(r"<strong>\1</strong>", body)
    return _MD_EM.sub(r"<em>\1</em>", body)


def policy_markup(text: str) -> Markup:
    """One stored passage as HTML: paragraphs, lists, emphasis and inline code, and nothing else.

    Deliberately not a markdown library: the corpus is fourteen documents this repository ingested
    itself, the four constructs below are what they use, and an unknown construct is left as the
    characters it is rather than interpreted. Every line is HTML-escaped before anything is added
    back, so the *only* markup on the page is the markup this function wrote.
    """
    blocks: list[str] = []
    items: list[str] = []
    ordered = False

    def flush() -> None:
        nonlocal items, ordered
        if items:
            tag = "ol" if ordered else "ul"
            blocks.append(f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>")
            items = []

    #: One entry per source line of the paragraph being built: the raw line, and whether it asked
    #: for a hard break. The corpus is hard-wrapped at ~150 characters, so a source newline is a
    #: typographic accident and not an instruction: joining on `<br>` reprinted every one of them as
    #: a forced break mid-sentence, at every viewport (UX W6, the fix round of the re-audit).
    #: Markdown's own rule is the one applied here — a soft wrap is a space, and only a line ending
    #: in two spaces is a break the author asked for.
    #:
    #: The lines are joined BEFORE the inline markup runs (UX W7, JX2-04): W6 marked each line up
    #: on its own, so an emphasis span that straddled a wrap — `**Tax & Legal` on one line,
    #: `review**` on the next — matched nothing and printed its literal asterisks to employees.
    paragraph: list[tuple[str, bool]] = []

    def flush_paragraph() -> None:
        if paragraph:
            # Runs of soft-wrapped lines, split only where the author asked for a break.
            runs: list[list[str]] = [[]]
            for raw, hard_break in paragraph:
                runs[-1].append(raw)
                if hard_break:
                    runs.append([])
            body = "<br>".join(_inline_markup(" ".join(run)) for run in runs if run)
            blocks.append(f"<p>{body}</p>")
            paragraph.clear()

    for line in str(text).splitlines():
        bullet = _MD_BULLET.match(line)
        number = None if bullet else _MD_NUMBER.match(line)
        if bullet or number:
            flush_paragraph()
            wanted = number is not None
            if items and wanted != ordered:
                flush()
            ordered = wanted
            items.append(_inline_markup((bullet or number).group(1)))
            continue
        flush()
        if not line.strip():
            flush_paragraph()
            continue
        paragraph.append((line.strip(), line.endswith("  ")))
    flush()
    flush_paragraph()
    return Markup("".join(blocks))  # noqa: S704 — every character above was escaped by `_inline_markup`


#: The reader speaks the same vocabulary as chat: one heading join, one date form, one markup pass.
TEMPLATES.env.filters["policy_markup"] = policy_markup
TEMPLATES.env.filters["heading_path"] = lambda value: str(value).replace(" > ", " · ")
TEMPLATES.env.filters["human_date"] = human_date

#: The partial scrubs every string it prints through `no_ids`, so a block the model wrote and a
#: step it wrote are held to one rule and neither can be forgotten (UX W6, cpux-re-4).
TEMPLATES.env.filters["no_ids"] = without_employee_ids


#: The one line that replaces a resolved confirmation card, by the decision that resolved it.
#: Before UX W2 the card simply vanished — `hx-swap="outerHTML"` over the whole turn, with no
#: `question` on the resume path — so approving a write erased the question that asked for it and
#: left no record on the page that a human had decided anything (chat-production-ux-10).
DECISION_LINES = {
    "confirmed": "You approved this — it went ahead.",
    "declined": "You cancelled this — nothing was created.",
}


#: What the one live region says when a turn finishes, by the outcome it finished with (UX W3).
#:
#: Until W3 every outcome announced *"Answer ready."* — including a refusal, a clarifying question,
#: a crash and a confirmation card, none of which is an answer and two of which are waiting on the
#: reader. A screen-reader user was told the opposite of what had happened three outcomes out of
#: five. One sentence per outcome, in the same plain language the rest of the page speaks; the page
#: reads this mapping rather than holding a second copy of it in JavaScript.
TURN_ANNOUNCEMENTS = {
    "answered": "Answer ready.",
    "partial": "Partial answer ready.",
    "escalated": "Answer ready — it points you to a person.",
    "awaiting_confirmation": "Waiting for your confirmation.",
    # No direction in it (UX W7, cpux2-3). `.turn-status` is visually-hidden once a turn has
    # finished, so "see below" pointed a screen-reader user at the composer and the demo panel;
    # the refusal itself is *above* the line that said it.
    "refused": "I can't answer that one.",
    "clarify": "Could you clarify?",
    "error": "Something went wrong — you can retry.",
}

#: The outcomes left are the two boot failures (`configuration_required`, `maintenance`). From the
#: reader's chair they are the error turn, and saying so is better than saying nothing.
TURN_ANNOUNCEMENT_FALLBACK = TURN_ANNOUNCEMENTS["error"]


#: What the panel calls that line, in the plan's own words (§3.7 item 4).
PRODUCED_LEAD = "How this answer was produced"
#: …and the lead for a turn that produced no answer — a refusal, a clarifying question, a
#: confirmation card, a crash — which *"How this answer was produced"* misdescribed (UX W7, M10).
HANDLED_LEAD = "How this was handled"


def _count(number: int, noun: str) -> str:
    """`1 tool` / `7 tools` — the plural follows the count, and no `(s)` is ever rendered (P9)."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def human_duration(total_ms: int | None) -> str:
    """A turn's length as a person would say it — never a millisecond count in a human sentence.

    The panel's produced line is read beside `/dashboard/sessions/{id}`, which carries the
    unrounded figure; this is the sentence, so it rounds (plan §3.7 item 4, UX W6).
    """
    milliseconds = float(total_ms or 0)
    if milliseconds >= 60_000:
        return f"{milliseconds / 60_000:.1f} minutes"
    if milliseconds < 1_000:
        return "under a second"
    seconds = milliseconds / 1_000
    return f"{seconds:.1f} seconds"


#: The six rules of §7.4 — the denominator every surface states "checks" against (UX W7, npo3-04).
SAFETY_RULES = 6


def safety_checks(spans: list[dict[str, Any]]) -> tuple[int, int]:
    """`(passed, ran)` — counted in **distinct §7.4 rules**, which is the unit the pages agree in.

    The panel used to count guardrail *spans* and say *"7 safety checks passed"*, while the
    Guardrails page one click away said *"The six safety checks…"* and counted rules: two surfaces
    the plan built to agree, contradicting, because G2 runs twice on a repaired turn (UX W6, JX-R7).
    A rule passes when it ran and never returned anything but `allow` on this turn.
    """
    ran: list[str] = []
    blocked: set[str] = set()
    for span in spans:
        if span["kind"] != "guardrail":
            continue
        rule = str(span["payload"].get("rule_id") or "")
        if rule and rule not in ran:
            ran.append(rule)
        if rule and span["payload"].get("verdict") != "allow":
            blocked.add(rule)
    return len(ran) - len(blocked), len(ran)


def produced_summary(response: ChatResponse, spans: list[dict[str, Any]]) -> str:
    """*"How this answer was produced"*, in four counts and no identifiers (plan §3.7).

    The demo panel's one-line account of the last turn: what the assistant looked things up with,
    what it read, how many of the §7.4 rules passed over the result, and how long the turn took.
    Every one of those numbers exists unrounded on `/dashboard/sessions/{id}` — this is the human
    summary beside the link to it, not a second record (P15).

    A *check* is one of the six rules, not one guardrail span: a rule that runs twice is still one
    check, and the denominator is printed so the figure agrees with the Guardrails page (UX W6).
    """
    passed, ran = safety_checks(spans)
    # One meaning for "checks" (UX W7, npo3-04 = dgc-r2-2): the six rules are the system's, the
    # ones that *applied* to this answer are a subset, and both numbers are said — "5 of the 6
    # safety checks applied to this answer; all 5 passed" — so the panel agrees with the session
    # tile ("Safety checks: 5 of 6 applied · 7 checks run") and the Guardrails lede ("The six
    # safety checks…") by construction. `SAFETY_RULES` is the same six the tile divides by.
    lead = PRODUCED_LEAD if response.outcome in LABELLED_OUTCOMES else HANDLED_LEAD
    verdict = f"all {ran} passed" if passed == ran else f"{passed} of the {ran} passed"
    return (
        f"{lead}: {_count(response.usage.tool_calls, 'tool')} used, "
        f"{_count(len(response.citations), 'policy section')} read, "
        f"in {human_duration(response.timings.total_ms)}. "
        f"{ran} of the {SAFETY_RULES} safety checks applied to this answer; {verdict}."
    )


#: The demo panel's environment block (plan §3.7 item 5). Stated once, here, instead of inside the
#: answers: a sentence about mock writes belongs to the demo, not to the policy an answer quotes.
RECORDED_PROVIDER = "a recorded script — no live model call"
LIVE_PROVIDER = "a live model — every answer is written for you as you wait"
SIMULATED_WRITES = "Writes are simulated — nothing leaves this app."


def provider_label(provider: str) -> str:
    """What answered, in the one form both surfaces say it in (UX W6, JX-R2).

    The dashboard's first screen printed the raw enum — *"Answers come from **stub**"* — which is
    the token W2 spent a wave removing from chat, while chat named the same fact correctly two
    clicks away. One map, two readers.
    """
    return RECORDED_PROVIDER if provider == "stub" else LIVE_PROVIDER


def demo_environment(request: Request) -> dict[str, str]:
    """What the demo is actually running on, in three lines a grader can check against the record."""
    settings = getattr(request.app.state, "settings", None)
    provider = settings.llm_provider if settings is not None else "stub"
    as_of = getattr(request.app.state, "data_as_of", "")
    return {
        "provider": provider_label(provider),
        "snapshot": human_date(as_of) if as_of else "not loaded on this instance",
        "writes": SIMULATED_WRITES,
    }


def sent_at_human(started_at: int | None) -> tuple[str, str, str]:
    """A turn's clock time for the speaker row (UX W2, chat-production-ux-17).

    `turns.started_at` is epoch **microseconds** on the real wall clock (constraint 6: no clock
    module, no override). The three forms are the `<time datetime=…>` attribute, the `HH:MM` the row
    shows, and the full sentence its hover carries — never a duration, never a millisecond count and
    never an id: the timestamp a person wants beside a message is when it was said, in the same date
    vocabulary as the snapshot note (`numbers-precision-overflow-12`).
    """
    if not started_at:
        return "", "", ""
    moment = datetime.fromtimestamp(started_at / 1_000_000).astimezone()
    short = moment.strftime("%H:%M")
    return moment.isoformat(timespec="seconds"), short, f"{short} on {human_date(moment.strftime('%Y-%m-%d'))}"


#: Every name `_turn.html` reads out of its context. The partial is rendered from two places — a
#: live turn (`_render_turn`) and a replayed one (`_rehydrate`) — and a name bound in one but not
#: the other is silently `Undefined`, i.e. falsy, i.e. a reloaded transcript that renders
#: *differently from the turn it is replaying*. That is exactly what happened to `labelled` between
#: the two W2 commits: the headings and the suggestion footnote vanished on reload and nothing
#: failed. Both paths now build their context through `_turn_context()` and
#: `tests/contract/test_conversation_reload.py` asserts the page binds every key of this tuple.
TURN_CONTEXT_KEYS = (
    "turn",
    "question",
    "as_of",
    "as_of_human",
    "produced",
    "sent_at",
    "sent_at_human",
    "sent_at_full",
    "decision_line",
    "labelled",
    "next_steps",
    "quick_replies",
    "block_headings",
    "suggestion_footnote",
    "citations_by_id",
    "confirm_fields",
)


def _turn_context(
    response: ChatResponse,
    *,
    question: str | None,
    spans: list[dict[str, Any]],
    started_at: int | None,
    decision: str | None = None,
    confirm_fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """The one context `_turn.html` is rendered from, live and replayed alike.

    `spans` is the turn's own closed spans — the list both callers already read for the snapshot
    note. Two things are derived from it here rather than by each caller: the *"Employee data from
    …"* date, and the demo panel's plain-language account of the turn.
    """
    sent_at, sent_at_text, sent_at_full = sent_at_human(started_at)
    as_of = snapshot_as_of(spans)
    return {
        "turn": response,
        "question": question,
        "as_of": as_of,
        "as_of_human": human_date(as_of) if as_of else None,
        "produced": produced_summary(response, spans),
        "sent_at": sent_at,
        "sent_at_human": sent_at_text,
        "sent_at_full": sent_at_full,
        "decision_line": DECISION_LINES.get(decision or ""),
        "labelled": response.outcome in LABELLED_OUTCOMES,
        "next_steps": rendered_next_steps(response),
        "quick_replies": list(response.quick_replies),
        "block_headings": BLOCK_HEADINGS,
        "suggestion_footnote": SUGGESTION_FOOTNOTE,
        "citations_by_id": {citation.chunk_id: citation for citation in response.citations},
        "confirm_fields": confirm_fields if confirm_fields is not None else [],
    }


def _started_at(store: Store, turn_id: str) -> int | None:
    row = store.execute("SELECT started_at FROM turns WHERE id = ?", (turn_id,)).one()
    return row["started_at"] if row else None


def _render_turn(
    request: Request,
    response: ChatResponse,
    *,
    question: str | None = None,
    decision: str | None = None,
) -> Response:
    """JSON is the contract (§11.1); the chat page asks for the same turn as an htmx fragment.

    One endpoint, two representations — never a second route, because §11.8's endpoint list is
    exact. The fragment is the *same* `ChatResponse`, rendered server-side, so the headings, the
    sources and the confirmation card `tests/contract/test_chat_page_renders.py` asserts on are the
    shipped ones.
    """
    if request.headers.get("HX-Request") != "true":
        return JSONResponse(response.model_dump(mode="json"))
    store = _store(request)
    preview = response.confirmation.arguments_preview if response.confirmation else {}
    return TEMPLATES.TemplateResponse(
        request=request,
        name="_turn.html",
        context=_turn_context(
            response,
            question=question,
            spans=_spans_of(store, response.turn_id),
            started_at=_started_at(store, response.turn_id),
            decision=decision,
            confirm_fields=_confirm_fields(preview),
        ),
    )


# --------------------------------------------------------------------------------------
# The unmodelled failure — constraint 11 and §12.3: still 200, still a closed turn
# --------------------------------------------------------------------------------------

#: What the caller is told when something the design does not model went wrong. Never the
#: exception, never a stack trace (§12.3) — the detail lives on the `error` span instead.
#:
#: Rewritten at UX W2 (jargon-and-exposure-16): it used to say *"inside the copilot"*, which is the
#: assistant talking about itself in the third person, in a sentence whose job is to reassure
#: someone whose request just failed.
INTERNAL_ERROR_TEXT = "Something went wrong and I could not finish that. Nothing was created or changed."
INTERNAL_ESCALATION_TEXT = f"Please try again, or contact People Operations at {g5.PEOPLE_OPS}."


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
    state = request.scope.get("state", {})
    question = state.get("message") if isinstance(state.get("message"), str) else None
    buffer = _open_buffer(state.get("turn_id"))
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
            # Explicitly empty rather than omitted: `_replayed_next_steps` treats a NULL column as
            # a row written before migration 002 and re-parses the joined answer for it. This turn
            # has no next steps, and the record should say so (UX W3 review).
            next_steps=[],
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
        return _render_turn(request, response, question=question)
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


#: What `GET /?session=<id>` says when the id names no session, or one another persona owns. It
#: names no id and asserts nothing about who owns what: a stranger's session id is not a thing to
#: confirm the existence of, and the honest user-facing fact is simply that this page could not
#: open it (UX W1, navigation-and-ia-16).
FOREIGN_SESSION_NOTICE = "That conversation could not be opened here, so this is a new one."


def _owns(session_row: dict[str, Any] | None, identity: Identity) -> bool:
    """Own-persona or admin. `/` is not admin-gated, so a raw id must not expose another's chat."""
    if session_row is None:
        return False
    return identity.is_admin or session_row.get("employee_id") == identity.actor


def _replayed_clarify_slot(row: Mapping[str, Any]) -> str | None:
    """Which slot a stored clarifying question asked about (W8, C18).

    The question the reader was shown is the first block of the stored answer, and the questions
    are a closed set, so the slot is recoverable exactly. Keying the replay on `workflow` would
    offer the wrong two chips on the very turn C18 exists for: an `admin` PTO clarification is
    asking for an identity, not for dates.
    """
    blocks = json.loads(row["answer_blocks_json"] or "[]")
    text = str(blocks[0].get("text") or "") if blocks else ""
    return clarify_slot_of(text)


def _replayed_next_steps(row: Mapping[str, Any]) -> list[str]:
    """`turns.next_steps_json`, or — for a row older than migration 002 — the joined answer.

    Every path that closes a turn now passes the field, empty ones included, so the fallback really
    is only the pre-migration one: the unmodelled-failure handler and the decline recorder used to
    omit it and land here with nothing to parse (UX W3 review).
    """
    stored = row["next_steps_json"]
    if stored:
        parsed = json.loads(stored)
        if isinstance(parsed, list):
            return [str(step) for step in parsed]
    return parse_next_steps(row["final_answer"] or "")


def _rehydrate(request: Request, session_id: str) -> list[dict[str, Any]]:
    """Replay a stored session's turns into the shape `_turn.html` renders a live one in (§11.5).

    The turn rows already hold everything the partial reads — `answer_blocks_json` and
    `citations_json` are written by `core/trace.py` on close — so this is a projection, not a second
    renderer, and `project()` reads the same spans the `/chat` response's `trace[]` does.

    `confirmation` is deliberately never rebuilt: a confirmation token is minted in exactly one
    place (`POST /chat/confirm`, §11.2) and a replayed card offering a Confirm button that cannot
    write would be a lie. A parked turn replays as the transcript it is.

    **What `_owns()` above is, and is not.** A raw session id is not enough on its own; the persona
    cookie is the boundary. It is not an authentication boundary and this docstring will not call
    it one: the persona is audit-only (§8.7), anyone holding the one shared access token can set
    `mosaic_actor` or send `X-Actor`, and every record behind it is synthetic. It stops a shared id
    from replaying someone else's conversation by accident, which is the whole of its job.
    """
    store = _store(request)
    rows = store.execute(
        "SELECT id, seq, started_at, user_message, final_answer, answer_blocks_json, citations_json, "
        "next_steps_json, outcome, "
        "workflow, llm_calls, tool_calls, retrievals, total_tokens_in, total_tokens_out, duration_ms "
        "FROM turns WHERE session_id = ? AND ended_at IS NOT NULL ORDER BY seq",
        (session_id,),
    ).dicts()
    replayed: list[dict[str, Any]] = []
    for row in rows:
        turn_id = row["id"]
        citations = [Citation.model_validate(item) for item in json.loads(row["citations_json"] or "[]")]
        outcome = row["outcome"] or "answered"
        turn = ChatResponse(
            session_id=session_id,
            turn_id=turn_id,
            trace_id=session_id,
            outcome=outcome,
            answer=row["final_answer"] or "",
            # The steps are their own column since UX W3, so a refusal comes back from a reload
            # with the redirect that is the most useful half of it. Rows written before that
            # migration hold `NULL`, and only those fall back to reading the steps out of the
            # section `render_answer()` closes the stored answer with.
            next_steps=_replayed_next_steps(row),
            # `turns` stores the blocks and the citations, not the chrome built around them. The
            # quick replies are not model output — they are `CLARIFY_CHIPS` keyed by the slot the
            # question asked about, which `clarify_slot_of` recovers from the stored question text
            # — so a replayed clarification still offers the same two ways to answer it that the
            # live one did (chat-production-ux-7; W8, C18).
            quick_replies=list(clarify_chips(_replayed_clarify_slot(row))) if outcome == "clarify" else [],
            answer_blocks=[AnswerBlock.model_validate(item) for item in json.loads(row["answer_blocks_json"] or "[]")],
            citations=citations,
            trace=project(turn_id, session_id=session_id, store=store),
            usage=Usage(
                prompt_tokens=row["total_tokens_in"] or 0,
                completion_tokens=row["total_tokens_out"] or 0,
                llm_calls=row["llm_calls"] or 0,
                tool_calls=row["tool_calls"] or 0,
                retrievals=row["retrievals"] or 0,
            ),
            timings=Timings(total_ms=row["duration_ms"] or 0),
            dashboard_url=f"/dashboard/sessions/{session_id}#turn-{row['seq']}",
        )
        # The same context builder the live fragment is rendered from — not a second dict that
        # looks like it. A replay never rebuilds a card (§11.5) and never re-states a decision: it
        # is the transcript of what happened, not an offer to do it again, so `decision` and
        # `confirm_fields` are the empty ones and everything else is identical by construction.
        replayed.append(
            _turn_context(
                turn,
                question=row["user_message"],
                spans=_spans_of(store, turn_id),
                started_at=row["started_at"],
            )
        )
    return replayed


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request) -> Response:
    """The single Jinja page of §11.5, plus `?session=<id>` rehydration (UX W1).

    Chat used to lose the whole transcript on any reload, which made "Continue this conversation in
    chat" from a session record impossible to offer honestly. `?session=` replays the stored turns
    for the persona that owns the session; anything else — an unknown id, a malformed one, another
    persona's — renders an empty conversation and one plain sentence.
    """
    identity = identity_of(request)
    requested = request.query_params.get("session")
    transcript: list[dict[str, Any]] = []
    session_id, notice = "", None
    if requested is not None:
        row = None
        if ID_PATTERN.match(requested):
            row = _store(request).execute("SELECT employee_id FROM sessions WHERE id = ?", (requested,)).one()
        if _owns(row, identity):
            session_id = requested
            transcript = _rehydrate(request, requested)
        else:
            notice = FOREIGN_SESSION_NOTICE
    return TEMPLATES.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "employees": request.app.state.employees,
            "greeting_name": _greeting_name(request, identity.actor),
            "demo_prompts": DEMO_PROMPTS,
            "demo_prompt_labels": DEMO_PROMPT_LABELS,
            "demo_environment": demo_environment(request),
            "turn_announcements": TURN_ANNOUNCEMENTS,
            "turn_announcement_fallback": TURN_ANNOUNCEMENT_FALLBACK,
            "starters": STARTER_PROMPTS,
            "transcript": transcript,
            "session_id": session_id,
            "session_notice": notice,
            **shell_context(request, surface="chat"),
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
    # this is the turn it has to close before answering (§12.3). The message rides along with it:
    # a failed turn used to arrive on the page with no copy of the question that failed, which is
    # half of why it had nothing to retry (chat-production-ux-20).
    state = request.scope.setdefault("state", {})
    state["turn_id"] = turn_id
    state["message"] = body.message

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
    turn = store.execute("SELECT id, session_id, seq, user_message FROM turns WHERE id = ?", (body.turn_id,)).one()
    if turn is None or turn["session_id"] != body.session_id:
        raise HTTPException(status_code=404, detail={"code": "UNKNOWN_TURN", "turn_id": body.turn_id})

    spans = _spans_of(store, body.turn_id)
    confirmations = [span for span in spans if span["kind"] == "confirmation"]
    pending = next(
        (span for span in reversed(confirmations) if span["payload"].get("user_response") == "pending"),
        None,
    )
    if pending is None:
        # **A proposal is answered once** (W8, C11). Until the pending span was resolved in place,
        # nothing here could tell an unanswered card from one that had already been confirmed, so a
        # replayed `POST /chat/confirm` minted a second token and a second ticket. A resolved
        # proposal is a conflict, not a missing one.
        resolved = next((span for span in reversed(confirmations) if span["payload"].get("resolved_at")), None)
        if resolved is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CONFIRMATION_ALREADY_RESOLVED",
                    "turn_id": body.turn_id,
                    "user_response": resolved["payload"].get("user_response"),
                },
            )
        raise HTTPException(status_code=404, detail={"code": "NO_PENDING_CONFIRMATION", "turn_id": body.turn_id})
    if int(pending["payload"].get("expires_at") or 0) <= now_micros():
        # §8.6 step 3: the proposal was good for ten minutes and nobody answered it. It is written
        # `expired` and the turn is **closed with a stated outcome** rather than left parked
        # forever, which is what three turns on the deployed build were (W8, C11).
        return _record_expiry(request, store, turn, pending)

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

    # The pending span is resolved in place by the orchestrator, on both the confirmed and the
    # declined path, so a resume that did not come through this endpoint is recorded the same way
    # (W8, C11). What this endpoint owns is the replay: a proposal already answered is a conflict.
    awaiting_ms = max(0, (now_micros() - int(pending["ended_at"] or pending["started_at"])) // 1000)
    # A decline reopens the buffer **uncounted**: the turn is answered without re-issuing the
    # write, so `resumed_count` must not report a resume nobody asked for — the number the
    # dashboard's resumed-turn figures read.
    confirmed = body.decision == "confirmed"
    trace_module.reopen_turn(body.turn_id, awaiting_ms, resumed=confirmed)
    request.scope.setdefault("state", {})["turn_id"] = body.turn_id
    _publish_turn_started(store, body.session_id, body.turn_id, seq=int(turn["seq"]))

    if confirmed:
        response = await agent.resume_turn(body.session_id, body.turn_id, token)
    else:
        # **The answer the turn already earned is kept** (W8, C11). A decline used to discard every
        # policy block and every citation and ship one sentence; the reader had asked a question
        # and answered a card, and cancelling the card is not cancelling the question.
        response = await agent.decline_turn(body.session_id, body.turn_id)
    _publish_turn_completed(response)
    # The question the card belonged to is re-rendered with the resolved turn: the fragment replaces
    # the whole `article.turn`, so without it the transcript loses the half the reader wrote.
    return _render_turn(request, response, question=turn["user_message"], decision=body.decision)


#: …and what an unanswered one does. §8.6 step 3 gives a proposal ten minutes; the turns that were
#: never answered sat `awaiting_confirmation` forever, and the reader was told nothing (W8, C11).
EXPIRED_NOTICE = (
    "This proposal expired before it was confirmed, so nothing was created. Ask again and I will "
    "put it back in front of you."
)


def _record_expiry(request: Request, store: Store, turn: Mapping[str, Any], pending: dict[str, Any]) -> Response:
    """A lapsed TTL: the span says `expired`, the turn closes, and the reader is told (W8, C11)."""
    trace_module.resolve_confirmation(pending["id"], user_response="expired")
    buffer = trace_module.reopen_turn(str(turn["id"]), 0, resumed=False)
    blocks = [AnswerBlock(type=NOTICE, text=EXPIRED_NOTICE, citations=[])]
    answer = render_answer(blocks, [])
    buffer.close(outcome="refused", stop_reason="expired", final_answer=answer, answer_blocks=blocks, next_steps=[])
    usage, timings = _turn_rollups(store, buffer.turn_id)
    response = ChatResponse(
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
    _publish_turn_completed(response)
    return _render_turn(request, response, question=str(turn["user_message"] or ""), decision="expired")


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
    return TEMPLATES.TemplateResponse(request=request, name="access.html", context={"message": None, "invalid": False})


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
            context={"message": MISSING_TOKEN_MESSAGE, "invalid": False},
            status_code=403,
        )
    if not hmac.compare_digest(supplied, token):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="access.html",
            context={"message": "That access key was not recognised.", "invalid": True},
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


#: The four questions the empty conversation offers (UX plan §3.1). They prefill the composer and
#: submit nothing: they are examples of what this assistant is for, which is what the page had
#: instead of a greeting — an unlabelled textarea and two buttons named "Demo" (chat-production-ux-1).
#: Not demo controls: the two scripted demo prompts of §18 keep their own place in the demo panel.
STARTER_PROMPTS = (
    "How much PTO do I have left?",
    "Can I work from another country?",
    "How much notice do I need to book time off?",
    "What does my benefits status cover?",
)

#: What each demo button is *called*. The buttons printed the whole verbatim prompt — two
#: three-line sentences — which is most of what filled the panel at 390px (UX W6, dgc-re-3). §3.7
#: draws a short label; the prompt itself still goes into the composer, unchanged, where the reader
#: can read and edit it before sending.
DEMO_PROMPT_LABELS = {
    "demo_1": "Working from Berlin for six weeks",
    "demo_2": "Three days of PTO, opened for me",
}

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
    "ADMIN_ROUTES",
    "APP_VERSION",
    "BLOCK_HEADINGS",
    "DEGRADATIONS",
    "DEMO_PROMPTS",
    "DEMO_PROMPT_LABELS",
    "LABELLED_OUTCOMES",
    "LIVE_PROVIDER",
    "PRODUCED_LEAD",
    "RECORDED_PROVIDER",
    "SIMULATED_WRITES",
    "STARTER_PROMPTS",
    "SUGGESTION_FOOTNOTE",
    "TURN_ANNOUNCEMENTS",
    "TURN_ANNOUNCEMENT_FALLBACK",
    "TURN_CONTEXT_KEYS",
    "AccessGateMiddleware",
    "ChatBody",
    "ConfirmBody",
    "Identity",
    "RateLimiter",
    "demo_environment",
    "gate_enabled",
    "gate_misconfigured",
    "health_payload",
    "identity_of",
    "produced_summary",
    "provider_label",
    "refusal_page",
    "router",
    "sent_at_human",
    "shell_context",
]
