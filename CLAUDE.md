# Claude Code instructions for this folder

## Delegation

- Delegate work to subagents whenever possible instead of doing it inline in the main session.
- Use Opus for all delegated execution: pass `model: "opus"` on every Agent tool call and on every Workflow `agent()` call (or set `model: "opus"` on each phase in a workflow's `meta.phases`).
- Reason: Opus subagents are more token-efficient and faster for delegated execution.
- Keep the main session for coordination, decisions, and synthesizing subagent results.
