"""The four judge prompts and the one call path behind them (spec §13.7).

Judge = Google `gemini-3.5-flash-lite` on `JUDGE_API_KEY`, `temperature = 0`,
**JSON-schema-constrained output**, **one repair retry** with the parse error appended. On a second
failure the verdict is `None`, the item leaves that metric's denominator and `n_scored` is reported
beside the metric — **never a silent zero** (§13.7).

**Judge independence is structural.** The agent is Anthropic `claude-haiku-4-5`; the judge is a
different vendor and a different model family, so the self-preference objection does not arise by
construction and no re-judge machinery exists. The reference labeller of
`evaluation/reference_labels.yaml` is a third, independent model.

Every judge call writes **two** spans through `core/trace.py` into the run's synthetic
`eval_judge` session: the adapter's own `llm_call` span (so the call is costed and auditable like
any other) and one `judge` span carrying the prompt, the raw reply, the parsed verdict and the
repair count (§10.2). Nothing here writes to the store directly.

The four prompts are module constants so `design-and-evaluation.md` can reproduce them verbatim at
P12 rather than paraphrasing them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from hrmosaic.core.llm import ChatModel, Message, ProviderError, build_judge_model
from hrmosaic.core.models import JudgePayload
from hrmosaic.core.trace import TurnBuffer
from hrmosaic.settings import Settings

logger = logging.getLogger(__name__)

#: §13.3's verdict scale: `supported | partially_supported | unsupported | contradicted`.
VERDICT_SCORES: dict[str, float] = {
    "supported": 1.0,
    "partially_supported": 0.5,
    "unsupported": 0.0,
    "contradicted": -0.5,
}


# --------------------------------------------------------------------------------------
# The four constrained-output schemas. Strict mode: `extra="forbid"`, no defaults anywhere.
# --------------------------------------------------------------------------------------


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    kind: Literal["policy_claim", "recommendation"]


class Decomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim]


class GroundednessVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["supported", "partially_supported", "unsupported", "contradicted"]
    rationale: str
    supporting_chunk_ids: list[str]


class SupportVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    rationale: str


class EntailmentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entailed: bool
    rationale: str


# --------------------------------------------------------------------------------------
# The four prompts (§13.7), each ~15 lines and each reproduced in design-and-evaluation.md
# --------------------------------------------------------------------------------------

DECOMPOSE_SYSTEM = """\
You split an assistant's answer into atomic, independently verifiable factual claims.

RULES
1. One claim per sentence-sized assertion; never merge two facts into one claim.
2. Exclude pleasantries, questions, headings and pure restatements of the user's question.
3. Tag a claim `policy_claim` when it asserts what company policy says, a rule, a number, a
   deadline, a threshold, an eligibility condition or a fact about the employee's record.
4. Tag a claim `recommendation` when it advises an action rather than stating written policy
   ("request approval early", "check with your manager"). Recommendations are excluded from the
   groundedness denominator, so tagging matters.
5. Give each claim a short stable id: c1, c2, c3, …
6. Return the claims in the order they appear in the answer.

Return JSON matching the schema. No prose outside the JSON."""

DECOMPOSE_USER = """\
ANSWER
{answer}"""

GROUNDEDNESS_SYSTEM = """\
You judge whether ONE claim is supported by the EVIDENCE the assistant actually saw.

RULES
1. The evidence below is the complete set of evidence the assistant was given, and it comes in four
   classes: `retrieval` (a policy passage it searched up), `section` (a passage it fetched in full),
   `compliance` (the deterministic rule engine's own requirement evidence) and `structured_data`
   (a record it read about this employee — a balance, an eligibility date, a profile). **A claim is
   supported if ANY item of ANY class supports it**: a correct fact taken from the employee's own
   record is grounded, not invented. Judge against this set alone — outside knowledge, plausibility
   and your own opinion are irrelevant.
2. `supported` — the evidence states the claim, or states it in equivalent words.
3. `partially_supported` — the evidence supports part of the claim, or supports it with a
   qualification the claim omits.
4. `unsupported` — the evidence neither states nor contradicts the claim.
5. `contradicted` — the evidence states something incompatible with the claim.
6. `supporting_chunk_ids` lists the ids of the evidence items you relied on, of whatever class;
   empty for unsupported.
7. `rationale` is ONE sentence.

Return JSON matching the schema. No prose outside the JSON."""

GROUNDEDNESS_USER = """\
EVIDENCE
{evidence}

CLAIM
{claim}"""

CITATION_SUPPORT_SYSTEM = """\
You judge whether the CITED passages ALONE support one claim.

RULES
1. Only the evidence the assistant CITED for this claim is listed below. Everything else it saw is
   deliberately not shown: the question is whether the citation the reader can follow does its job.
2. `supported: true` — a reader who opened only these passages would find the claim stated there.
3. `supported: false` — the claim needs a passage that is not among them, or they contradict it.
4. Equivalent wording counts as stated; an inference two steps away does not.
5. `rationale` is ONE sentence.

Return JSON matching the schema. No prose outside the JSON."""

CITATION_SUPPORT_USER = """\
CITED PASSAGES
{evidence}

CLAIM
{claim}"""

ENTAILMENT_SYSTEM = """\
You judge whether a single gold FACT is entailed by an ANSWER.

RULES
1. `entailed: true` — a careful reader of the answer would come away holding the fact, whether it
   is stated in the same words or in equivalent ones.
2. Numbers, dates, thresholds and units must match. "about a month" does not entail "30 days".
3. An answer that omits the fact entirely is not entailment, however good the rest of it is.
4. An answer that states the fact and then contradicts it is not entailment.
5. `rationale` is ONE sentence.

Return JSON matching the schema. No prose outside the JSON."""

ENTAILMENT_USER = """\
FACT
{fact}

ANSWER
{answer}"""

CLARIFICATION_SYSTEM = """\
You judge whether a clarifying question names the information that was missing.

RULES
1. `entailed: true` — the clarifying question asks for the missing information named below, in any
   wording; asking for it among other things still counts.
2. `entailed: false` — the question is generic ("could you say more?"), asks for something else, or
   answers the request instead of clarifying it.
3. `rationale` is ONE sentence.

Return JSON matching the schema. No prose outside the JSON."""

CLARIFICATION_USER = """\
MISSING INFORMATION
{missing}

CLARIFYING QUESTION
{question}"""

#: The one repair round trip of §13.7: the parse error, appended, and one more attempt.
REPAIR_INSTRUCTION = (
    "That reply could not be used ({error}). Reply again with the JSON object alone — "
    "no prose, no code fence — matching the schema exactly."
)


#: The four classes of evidence `synthesize.j2` can put in front of the model (§13.3, ratified
#: 2026-09-10). Retrieval chunks were the whole set until then, which scored a correct fact the
#: agent read out of the employee's own benefits record as *unsupported* — penalising exactly the
#: behaviour the §9.6 workflows require. The class travels with the item so the judge can say what
#: it relied on and so a reader of a `judge` span can tell a policy passage from a record lookup.
EvidenceKind = Literal["retrieval", "section", "compliance", "structured_data"]


class EvidenceItem(NamedTuple):
    """One item of the evidence the synthesis prompt actually carried."""

    id: str
    kind: EvidenceKind
    text: str


def render_evidence(items: Sequence[EvidenceItem]) -> str:
    """The evidence block, in the envelope shape the assistant saw, each item naming its class."""
    return "\n".join(f'<evidence id="{item.id}" kind="{item.kind}">\n{item.text}\n</evidence>' for item in items)


class Judge:
    """One judge for one run. Stateless apart from the call counter the run file reports."""

    def __init__(
        self,
        *,
        run_id: str,
        model: ChatModel | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.run_id = run_id
        self._model = model or build_judge_model(settings)
        self.calls = 0
        self.failures = 0

    @property
    def model_name(self) -> str:
        return getattr(self._model, "model", "unknown")

    @property
    def provider(self) -> str:
        return getattr(self._model, "provider", "unknown")

    async def _ask(
        self,
        *,
        metric: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        item_id: str,
        scored_turn_id: str,
        turn: TurnBuffer,
    ) -> dict[str, Any] | None:
        """One judged question: constrained JSON, one repair retry, then `None` (§13.7)."""
        messages = [Message(role="system", content=system), Message(role="user", content=user)]
        raw = ""
        repairs = 0
        for attempt in range(2):
            try:
                self.calls += 1
                completion = await self._model.complete(
                    messages,
                    response_schema=schema,
                    purpose="judge" if metric != "decompose" else "decompose",
                    turn=turn,
                )
                raw = completion.text
                parsed = schema.model_validate(completion.parsed_json()).model_dump(mode="json")
            except (ProviderError, ValueError, json.JSONDecodeError) as exc:
                if attempt == 0:
                    repairs = 1
                    messages = [*messages, Message(role="user", content=REPAIR_INSTRUCTION.format(error=exc))]
                    continue
                self.failures += 1
                logger.warning("judge %s for %s failed twice; recording a null verdict", metric, item_id)
                self._record(
                    metric=metric,
                    prompt=user,
                    raw=raw,
                    parsed={},
                    repairs=repairs,
                    item_id=item_id,
                    scored_turn_id=scored_turn_id,
                    turn=turn,
                    error=str(exc),
                )
                return None
            self._record(
                metric=metric,
                prompt=user,
                raw=raw,
                parsed=parsed,
                repairs=repairs,
                item_id=item_id,
                scored_turn_id=scored_turn_id,
                turn=turn,
            )
            return parsed
        return None

    def _record(
        self,
        *,
        metric: str,
        prompt: str,
        raw: str,
        parsed: dict[str, Any],
        repairs: int,
        item_id: str,
        scored_turn_id: str,
        turn: TurnBuffer,
        error: str | None = None,
    ) -> None:
        """The one `judge` span, through `core/trace.py` like every other span in the system."""
        turn.add_span(
            "judge",
            f"{self.provider}:{self.model_name}",
            JudgePayload(
                metric=metric,
                judge_provider=self.provider,
                judge_model=self.model_name,
                prompt=prompt,
                raw=raw,
                parsed=parsed,
                repair_attempts=repairs,
                item_id=item_id,
                run_id=self.run_id,
                scored_turn_id=scored_turn_id,
            ),
            status="error" if error else "ok",
            error_message=error,
        )

    # -- the four questions ---------------------------------------------------------------

    async def decompose(self, answer: str, *, item_id: str, scored_turn_id: str, turn: TurnBuffer) -> list[Claim]:
        """Prompt 1. A failure yields **no claims**, so the item leaves the groundedness mean."""
        parsed = await self._ask(
            metric="decompose",
            system=DECOMPOSE_SYSTEM,
            user=DECOMPOSE_USER.format(answer=answer),
            schema=Decomposition,
            item_id=item_id,
            scored_turn_id=scored_turn_id,
            turn=turn,
        )
        if parsed is None:
            return []
        return [Claim.model_validate(claim) for claim in parsed.get("claims") or []]

    async def groundedness(
        self,
        *,
        evidence: Sequence[EvidenceItem],
        claim: str,
        item_id: str,
        scored_turn_id: str,
        turn: TurnBuffer,
    ) -> str | None:
        """Prompt 2 — one of the four §13.3 verdicts, or `None` after the repair retry failed."""
        parsed = await self._ask(
            metric="groundedness",
            system=GROUNDEDNESS_SYSTEM,
            user=GROUNDEDNESS_USER.format(evidence=render_evidence(evidence), claim=claim),
            schema=GroundednessVerdict,
            item_id=item_id,
            scored_turn_id=scored_turn_id,
            turn=turn,
        )
        return None if parsed is None else str(parsed["verdict"])

    async def citation_support(
        self,
        *,
        cited: Sequence[EvidenceItem],
        claim: str,
        item_id: str,
        scored_turn_id: str,
        turn: TurnBuffer,
    ) -> bool | None:
        """Prompt 3 — do the **cited** chunks alone support this claim?"""
        parsed = await self._ask(
            metric="citation_support",
            system=CITATION_SUPPORT_SYSTEM,
            user=CITATION_SUPPORT_USER.format(evidence=render_evidence(cited), claim=claim),
            schema=SupportVerdict,
            item_id=item_id,
            scored_turn_id=scored_turn_id,
            turn=turn,
        )
        return None if parsed is None else bool(parsed["supported"])

    async def entailed(
        self,
        *,
        fact: str,
        answer: str,
        item_id: str,
        scored_turn_id: str,
        turn: TurnBuffer,
    ) -> bool | None:
        """Prompt 4a — is this gold fact entailed by the answer? (`PartialMatch`'s numerator)."""
        parsed = await self._ask(
            metric="gold_fact_entailment",
            system=ENTAILMENT_SYSTEM,
            user=ENTAILMENT_USER.format(fact=fact, answer=answer),
            schema=EntailmentVerdict,
            item_id=item_id,
            scored_turn_id=scored_turn_id,
            turn=turn,
        )
        return None if parsed is None else bool(parsed["entailed"])

    async def clarification_names_missing(
        self,
        *,
        missing: str,
        question: str,
        item_id: str,
        scored_turn_id: str,
        turn: TurnBuffer,
    ) -> bool | None:
        """Prompt 4b — does the clarifying question name the missing information? (§13.4)."""
        parsed = await self._ask(
            metric="clarification",
            system=CLARIFICATION_SYSTEM,
            user=CLARIFICATION_USER.format(missing=missing, question=question),
            schema=EntailmentVerdict,
            item_id=item_id,
            scored_turn_id=scored_turn_id,
            turn=turn,
        )
        return None if parsed is None else bool(parsed["entailed"])


__all__ = [
    "CITATION_SUPPORT_SYSTEM",
    "CITATION_SUPPORT_USER",
    "CLARIFICATION_SYSTEM",
    "CLARIFICATION_USER",
    "DECOMPOSE_SYSTEM",
    "DECOMPOSE_USER",
    "ENTAILMENT_SYSTEM",
    "ENTAILMENT_USER",
    "GROUNDEDNESS_SYSTEM",
    "GROUNDEDNESS_USER",
    "REPAIR_INSTRUCTION",
    "VERDICT_SCORES",
    "Claim",
    "Decomposition",
    "EntailmentVerdict",
    "GroundednessVerdict",
    "Judge",
    "SupportVerdict",
    "EvidenceItem",
    "EvidenceKind",
    "render_evidence",
]
