"""W2-C — a search hit carries the whole chunk, and never a quarantined one's text.

10 of 53 deployed act steps, on 7 turns, existed only to call `get_policy_section` after a search:
`SNIPPET_CHARS` is 320 while 116 of 116 retrieved chunks are longer (median 974), so the model could
see a citation's heading and a third of its sentence and had to spend a whole round trip — 21,618 ms
across the run — to read the rest. The hit now carries `chunk.text` alongside the snippet, from the
same `retrieve()` call, so the server does no extra work.

**The gate this file exists for is the quarantine.** The corpus's only quarantinable chunk is 630
characters and its `IGNORE ALL PREVIOUS INSTRUCTIONS…` imperative begins at character 355 — beyond
`SNIPPET_CHARS`. Before this change `g4.scan(snippet)` never saw it and the imperative never reached
the act conversation; a hit carrying the whole chunk puts it one `json.dumps` away from the model's
own context. So the decision is taken **twice**, and neither copy is redundant:

* in `_search`, before the body is serialised, which is the plan's stated locus and the only place
  that keeps the text off the wire for an MCP Inspector session attached to the deliberately public
  `/mcp-server/mcp` (§15, R-12);
* in `client.call_tool`, on the way in, because a client that trusts a server to police its own
  output has no shield against any other MCP server it is pointed at.

Either way a quarantined chunk is handed on as its snippet alone with `quarantined: true`, and the
only prompt that ever shows its text is the synthesis prompt, inside a `quarantined="true"`
`<document>` banner under rule 4.

Nothing here is a mock. `StubAdapter` replays the committed `injection_probe` recording while the
retrieval, the corpus and the tool are the shipped MCP server in a separate OS process.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pytest

from hrmosaic.agent.guardrails import g4
from hrmosaic.agent.orchestrator import ChatRequest
from hrmosaic.core import corpusread
from hrmosaic.mcpserver.tools.search_policy_documents import CHUNK_MAX_CHARS
from tests.integration.conftest import BASE_META

pytestmark = pytest.mark.anyio

QUESTION = "What should I do about a suspicious phishing email?"


@lru_cache(maxsize=1)
def canary_id() -> str:
    """The one committed chunk `g4.scan` fires on — found, never typed (`test_g4_no_false_positives`)."""
    dirty = [
        row.chunk_id
        for document in corpusread.list_documents()
        for row in corpusread.list_chunks(document.doc_id)
        if g4.scan(row.text) is not None
    ]
    assert len(dirty) == 1, dirty
    return dirty[0]


def search_hits(records) -> list[dict]:
    """Every hit of every `search_policy_documents` result, as the act loop received it.

    Read from `structured_content` rather than from `result_json`: the two are the same body, but
    §10.5's per-string cap is 8 KB and a k=5 search carrying whole chunks serialises to more than
    that, so the string copy is stored with a truncation marker while the structured one — whose
    individual strings are each well under the cap — survives intact.
    """
    return [
        hit
        for kind, _, payload in records
        if kind == "tool_call" and payload["tool_name"] == "search_policy_documents"
        for hit in payload["structured_content"]["hits"]
    ]


async def test_a_clean_hit_carries_the_whole_chunk_beside_its_snippet(run_agent, spans):
    """The lever itself: the act step no longer has to spend a round trip to read the passage."""
    answered = await run_agent("injection_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    clean = [hit for hit in search_hits(spans(answered.turn_id)) if hit["chunk_id"] != canary_id()]
    assert clean, "the probe must return something citable"
    for hit in clean:
        stored = corpusread.get_chunk(hit["chunk_id"])
        assert hit["text"] == stored.text[:CHUNK_MAX_CHARS]
        assert hit["quarantined"] is False
        assert hit["snippet"] == stored.snippet, "the snippet stays what it is: what a citation shows"
        assert len(hit["text"]) > len(hit["snippet"]), "pick a corpus the snippet actually truncates"


async def test_search_hit_omits_text_for_quarantined_chunk(run_agent, spans):
    """The highest-severity gate of the wave: the imperative never reaches the act conversation."""
    answered = await run_agent("injection_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    dirty = [hit for hit in search_hits(spans(answered.turn_id)) if hit["chunk_id"] == canary_id()]
    assert dirty, "the probe must surface the corpus canary, or this test proves nothing"
    for hit in dirty:
        assert hit["quarantined"] is True, "the wire body says so; it is not left to the client's copy"
        assert hit["text"] is None
        assert hit["snippet"], "the snippet is what a quarantined hit is allowed to carry"
        assert g4.scan(hit["snippet"]) is None


async def test_no_act_message_contains_unbannered_g4_pattern(run_agent, store):
    """Asserted over `llm_messages` — the verbatim bytes, not a reconstruction of them."""
    answered = await run_agent("injection_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    rows = store.execute(
        "SELECT m.span_id, m.seq, m.role, m.content, s.payload_json FROM llm_messages m "
        "JOIN spans s ON s.id = m.span_id WHERE s.turn_id = ? AND s.kind = 'llm_call' "
        "ORDER BY m.span_id, m.seq",
        (answered.turn_id,),
    ).dicts()
    assert rows, "the turn wrote its prompts"
    by_purpose: dict[str, list[dict]] = {}
    for row in rows:
        by_purpose.setdefault(json.loads(row["payload_json"])["purpose"], []).append(row)

    assert by_purpose.get("act"), "the act loop ran"
    for row in by_purpose["act"]:
        found = g4.scan(row["content"])
        assert found is None, f"{row['role']} message trips {found[0] if found else ''}: {row['content'][:200]}"

    bannered = [row for row in by_purpose["synthesize"] if g4.scan(row["content"]) is not None]
    assert bannered, "the synthesis prompt is where the quarantined chunk is shown at all"
    for row in bannered:
        assert 'quarantined="true"' in row["content"], "shown only inside the §7.4 banner"


async def test_the_injected_chunk_text_is_capped(run_agent, spans):
    """`CHUNK_MAX_CHARS` bounds what a hit can add, since those bytes are re-billed every act step."""
    answered = await run_agent("injection_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    for hit in search_hits(spans(answered.turn_id)):
        assert len(hit["text"] or "") <= CHUNK_MAX_CHARS

    longest = max(
        len(row.text) for document in corpusread.list_documents() for row in corpusread.list_chunks(document.doc_id)
    )
    assert longest <= CHUNK_MAX_CHARS, (
        "the clamp is a bound on a future corpus, not a live truncation: it must sit above the "
        f"longest committed chunk ({longest} characters)"
    )


async def test_the_synthesis_prompt_carries_one_copy_of_a_passage(run_agent, store, spans):
    """The `<document>` block is the single copy of a passage in the synthesis prompt.

    Every non-quarantined chunk the turn retrieved is already rendered into EVIDENCE from
    `turn.chunks()`, under a `trust="data"` banner and with the `rrf=` weight §7.2 requires. Leaving
    the text inside a `<tool_result>` envelope as well would double the evidence bytes of the prompt
    and show the model the same passage twice under two different labels — so W2-D drops the search
    envelope from EMPLOYEE CONTEXT outright (`core.models.UNRENDERED_ENVELOPES`), which subsumes
    W2-C's narrower strip of the `text` key.
    """
    answered = await run_agent("injection_probe.json", ChatRequest(message=QUESTION, employee_id="E1042"))

    rows = store.execute(
        "SELECT m.content, s.payload_json FROM llm_messages m JOIN spans s ON s.id = m.span_id "
        "WHERE s.turn_id = ? AND s.kind = 'llm_call' ORDER BY m.span_id, m.seq",
        (answered.turn_id,),
    ).dicts()
    prompts = [row["content"] for row in rows if json.loads(row["payload_json"])["purpose"] == "synthesize"]
    evidence = next(prompt for prompt in prompts if "EMPLOYEE CONTEXT" in prompt)

    envelopes = evidence[evidence.index("EMPLOYEE CONTEXT") :]
    assert '<tool_result tool="search_policy_documents"' not in envelopes, "the search envelope is dropped"
    assert '"text":' not in envelopes, "so nothing repeats the chunk"

    retrieved = {hit["chunk_id"] for hit in search_hits(spans(answered.turn_id))} - {canary_id()}
    assert retrieved, "the turn retrieved something citable"
    for chunk_id in retrieved:
        text = corpusread.get_chunk(chunk_id).text
        assert evidence.count(text) == 1, f"{chunk_id} is rendered {evidence.count(text)} times"


async def test_the_server_never_puts_a_quarantined_chunk_on_the_wire(open_session):
    """W2-C's BLOCKING bullet, at its stated locus: measured on the raw `tools/call` result.

    `/mcp-server/mcp` is deliberately publicly reachable (§15, R-12) so a grader can attach MCP
    Inspector, so "the wire" is not only the loopback hop between our own client and our own server.
    This asserts on the bytes the server serialised, with no agent-side shield anywhere between them
    and the assertion — on both transports, since the fixture parametrises them.
    """
    async with open_session() as session:
        result = await session.call_tool("search_policy_documents", {"query": QUESTION, "k": 5}, meta=BASE_META)
    serialised = result.content[0].text
    body = json.loads(serialised)

    dirty = [hit for hit in body["hits"] if hit["chunk_id"] == canary_id()]
    assert dirty, "the probe must surface the corpus canary, or this test proves nothing"
    for hit in dirty:
        assert hit["quarantined"] is True, "the decision is the server's own, at the plan's locus"
        assert hit["text"] is None
        assert hit["snippet"], "the snippet is what a quarantined hit is allowed to carry"
    assert g4.scan(serialised) is None, "nothing in the whole serialised body trips G4"
