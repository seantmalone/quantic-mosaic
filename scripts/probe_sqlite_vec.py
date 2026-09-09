"""Prove sqlite-vec loads and answers a cosine KNN on this platform (spec §15.1, §6.5).

    python scripts/probe_sqlite_vec.py

CI's `docker` job runs it inside a bare `python:3.12-slim` with nothing installed but `sqlite-vec`:

    docker run --rm -v "$PWD":/w -w /w python:3.12-slim \
      sh -c "pip install -q sqlite-vec && python scripts/probe_sqlite_vec.py"

so it must import **nothing** from `hrmosaic` and nothing beyond the standard library plus
`sqlite_vec`. What it checks is exactly what would break silently on a different base image:

* the extension loads at all — `enable_load_extension` is compiled out of some Python builds, and a
  `vec0` table is unreadable without it;
* `distance_metric=cosine` is honoured. sqlite-vec defaults to **L2**, and a silent switch would move
  every `dense_score`, and therefore `MIN_EVIDENCE_SCORE`, `MIN_SUPPORT_SCORE` and every calibrated
  threshold in the project. The probe asserts an identical vector scores distance 0 and an orthogonal
  one scores 1, which is true of cosine and of nothing else.

It prints the versions it observed so the CI log records them.
"""

from __future__ import annotations

import sqlite3
import struct
import sys

import sqlite_vec

DIM = 4
TOLERANCE = 1e-5


def serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def probe() -> list[str]:
    """Return a list of human-readable problems; an empty list means the platform is sound."""
    problems: list[str] = []
    connection = sqlite3.connect(":memory:")
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
    except AttributeError:
        return ["this Python build has no enable_load_extension: sqlite-vec cannot be loaded"]
    except sqlite3.Error as exc:
        return [f"sqlite-vec failed to load: {exc}"]

    vec_version = connection.execute("SELECT vec_version()").fetchone()[0]
    print(f"  sqlite3 {sqlite3.sqlite_version}  ·  sqlite-vec {vec_version}  ·  python {sys.version.split()[0]}")

    connection.execute(
        f"CREATE VIRTUAL TABLE probe USING vec0("
        f"chunk_rowid INTEGER PRIMARY KEY, embedding float[{DIM}] distance_metric=cosine)"
    )
    connection.execute("INSERT INTO probe (chunk_rowid, embedding) VALUES (?, ?)", (1, serialize([1.0, 0.0, 0.0, 0.0])))
    connection.execute("INSERT INTO probe (chunk_rowid, embedding) VALUES (?, ?)", (2, serialize([0.0, 1.0, 0.0, 0.0])))

    rows = connection.execute(
        "SELECT chunk_rowid, distance FROM probe WHERE embedding MATCH ? AND k = 2 ORDER BY distance",
        (serialize([1.0, 0.0, 0.0, 0.0]),),
    ).fetchall()
    connection.close()

    if [rowid for rowid, _ in rows] != [1, 2]:
        problems.append(f"KNN returned {rows} — the identical vector must rank first")
        return problems
    identical, orthogonal = rows[0][1], rows[1][1]
    if abs(identical) > TOLERANCE:
        problems.append(f"cosine distance to an identical vector is {identical}, expected 0.0")
    if abs(orthogonal - 1.0) > TOLERANCE:
        problems.append(
            f"cosine distance to an orthogonal vector is {orthogonal}, expected 1.0 — "
            "distance_metric=cosine was not honoured (L2 would give ~1.414)"
        )
    return problems


def main() -> int:
    problems = probe()
    if problems:
        print(f"\nFAIL — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK — sqlite-vec loads and vec0 answers a cosine KNN on this platform.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
