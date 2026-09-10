# Deployment notes — Mosaic HR Copilot

> **Status: partial.** This file is completed at **P11** (provisioning, the live URL, cold-start and
> RSS measurements) and finalised at **P12**. It is created here at **P10 step 0** to carry the two
> live facts of §3.1 that P10 is responsible for reading and dating: the Gemini free-tier judge
> quotas and the Anthropic `claude-haiku-4-5` prices. Every remaining heading below is a stub with
> the shape P12's `test_docs_completeness.py` asserts.

## Deployed URLs

_P11._ The single Render Hobby service, its `/health` and `/ready` endpoints, and the tokenized
`?access=` link go here.

## Access

_P11._ The tokenized link, the `mosaic_access` cookie, the `Authorization: Bearer` header for API
clients and MCP Inspector, the two personas (`E1xxx` and `admin`) and the post-grading rotation step
go here.

## Cold start

_P11._ Measured by `scripts/measure_cold_start.py` (idle ≥ 16 min, then curl `/health` and `/chat`),
published distinctly from the cold **turn** p50 of §13.5.

## Environment variables

_P11._ Every variable of §12.3 with its deployed value or "unset".

## MCP transport

_P11._ Why the MCP server is **not** deployed as a second service, and how R7.2 / R7.3 are satisfied.

## Cost

_P11/P12._ $0 Render Hobby, $0 Turso, no paid database, local embeddings, a free-tier judge and
failover, plus the agent's **estimated** Anthropic spend. The P10 evaluation sweep's measured spend
is recorded in `CHANGELOG.md` and in `evaluation/REPORT.md`.

### Live provider facts — read at P10 step 0

Every row of §3.1 that P10 owns, read live on the date shown. Nothing here is inferred.

| Fact | Observed | Read on | Source |
|---|---|---|---|
| Anthropic `claude-haiku-4-5` input | **$1.00 / MTok** | 2026-09-09 | https://claude.com/pricing (`https://www.anthropic.com/pricing` 301s here) |
| Anthropic `claude-haiku-4-5` output | **$5.00 / MTok** | 2026-09-09 | as above |
| Anthropic `claude-haiku-4-5` prompt-cache **write** (5-minute TTL) | **$1.25 / MTok** | 2026-09-09 | as above |
| Anthropic `claude-haiku-4-5` prompt-cache **read** | **$0.10 / MTok** | 2026-09-09 | as above |
| Anthropic minimum cacheable prefix for `claude-haiku-4-5` | **4,096 tokens** — the highest of any current model; below it a request silently writes no cache entry and returns `cache_creation_input_tokens: 0` with no error | 2026-09-09 | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| Gemini free-tier limits for the judge model | **not published in the API documentation.** `https://ai.google.dev/gemini-api/docs/rate-limits` no longer carries a free-tier RPM/TPM/RPD table; it states that *"rate limits depend on a variety of factors (such as your usage tier) and can be viewed in Google AI Studio"* and links to `https://aistudio.google.com/rate-limit`, which requires an authenticated session and could not be read from this environment. Third-party trackers report **15 RPM · 250,000 TPM · 1,000 RPD** for the Flash-Lite tier; that figure is **unverified** and is not relied on. | 2026-09-09 | https://ai.google.dev/gemini-api/docs/rate-limits |

**`core/models.py::MODEL_PRICES` matches the observed Anthropic prices exactly** — `{input: 1.00,
output: 5.00, cache_write: 1.25, cache_read: 0.10}` — so no change was needed, and every
`cost_usd_estimate` on an `llm_call` span is computed from the prices above.

**What the unverified Gemini figure does and does not affect.** §13.9 is explicit that the Gemini
RPD/TPM arithmetic bounds **only the judge and the failover path**; what bounds the agent is
`LLM_DAILY_CALL_CAP` (1,500 Anthropic calls per UTC day) and the prompt cache. The P10 sweep issued
its judge calls behind the same token-bucket limiter as everything else (`LLM_RPM = 10`, so ≤ 600
calls/hour against a reported 15 RPM ceiling) and the observed behaviour — how many judge calls the
run made and whether any `429` / `Retry-After` was seen — is recorded in `CHANGELOG.md` and in the
run's `eval_runs.notes`. That observation is the honest substitute for a number this environment
could not read. P11 step 0 re-reads the row from an authenticated AI Studio session.
