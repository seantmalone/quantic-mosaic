"""The only structural test file in the repository (spec §16.3).

Five greps over `src/`, each protecting an invariant that a later phase could
otherwise break silently:

1. only `core/trace.py` writes to the trace tables;
2. `rag/embed.py` is the only fastembed call site;
3. `parallel=` appears nowhere (it hung indefinitely in the probe);
4. `agent/**` never imports `hrmosaic.mcpserver` — it reaches the server over the MCP wire;
5. `evaluation/**` never imports `hrmosaic.mcpserver`, `hrmosaic.agent` or `hrmosaic.web` — §4.2
   puts the harness on `evaluation/ -> core/` and the HTTP API, so anything it needs from inside
   the application (the canonical argument serialisation of §8.6, say) belongs in `core/`;
6. the top-level `mcp/` directory is not an importable package (§4.1).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

TRACE_WRITER = SRC / "hrmosaic" / "core" / "trace.py"
MIGRATIONS = SRC / "hrmosaic" / "core" / "migrations"
EMBED_MODULE = SRC / "hrmosaic" / "rag" / "embed.py"
AGENT_PACKAGE = SRC / "hrmosaic" / "agent"
EVALUATION_PACKAGE = REPO_ROOT / "evaluation"

SPAN_WRITE = re.compile(r"INSERT\s+INTO\s+(?:spans|turns|sessions)\b", re.IGNORECASE)
EMBED_CALL = re.compile(r"\.(?:embed|query_embed)\(")
PARALLEL_KWARG = "parallel="
MCPSERVER_IMPORT = re.compile(r"^\s*(?:from|import)\s+hrmosaic\.mcpserver\b", re.MULTILINE)
INSIDE_THE_APP_IMPORT = re.compile(r"^\s*(?:from|import)\s+hrmosaic\.(?:mcpserver|agent|web)\b", re.MULTILINE)


def _source_files(suffixes: tuple[str, ...] = (".py",)) -> list[Path]:
    return sorted(path for path in SRC.rglob("*") if path.suffix in suffixes and path.is_file())


def _offenders(pattern: re.Pattern[str], allowed: set[Path], suffixes: tuple[str, ...] = (".py",)) -> list[str]:
    hits = []
    for path in _source_files(suffixes):
        is_migration = path.suffix == ".sql" and MIGRATIONS in path.parents
        if path in allowed or is_migration:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


def test_only_trace_module_writes_spans():
    # The grep has a real target from P1 on: `core/trace.py` is the writer, so a vacuous pass
    # (nobody writes spans at all) can never be mistaken for the invariant holding.
    assert SPAN_WRITE.search(TRACE_WRITER.read_text(encoding="utf-8"))
    assert _offenders(SPAN_WRITE, {TRACE_WRITER}, (".py", ".sql")) == []


def test_fastembed_is_called_in_one_place():
    # As with the trace writer, the grep has a real target from P4 on: `rag/embed.py` calls the
    # model, so a vacuous pass (nothing embeds at all) can never be mistaken for the invariant.
    assert EMBED_CALL.search(EMBED_MODULE.read_text(encoding="utf-8"))
    assert _offenders(EMBED_CALL, {EMBED_MODULE}) == []


def test_no_parallel_kwarg():
    hits = [
        str(path.relative_to(REPO_ROOT))
        for path in _source_files()
        if PARALLEL_KWARG in path.read_text(encoding="utf-8")
    ]
    assert hits == []


def test_agent_does_not_import_mcpserver():
    hits = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(AGENT_PACKAGE.rglob("*.py"))
        if MCPSERVER_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == []


def test_evaluation_does_not_import_inside_the_application():
    # §4.2: the harness drives the app over HTTP and reads what happened through `core/db.py`.
    # The grep has a real target — `evaluation/deterministic.py` imports `hrmosaic.core.canonical`,
    # the shared serialisation that used to live in `mcpserver/confirm.py` — so a vacuous pass
    # (the package importing no `hrmosaic` module at all) can never be mistaken for the invariant.
    sources = sorted(EVALUATION_PACKAGE.rglob("*.py"))
    assert sources
    assert any(
        re.search(r"^\s*from\s+hrmosaic\.core\b", path.read_text(encoding="utf-8"), re.MULTILINE) for path in sources
    )
    hits = [
        str(path.relative_to(REPO_ROOT))
        for path in sources
        if INSIDE_THE_APP_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == []


def test_mcp_dir_is_not_a_package():
    assert not (REPO_ROOT / "mcp" / "__init__.py").exists()
