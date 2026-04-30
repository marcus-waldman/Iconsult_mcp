# Phase 2 Briefing — Triage Layer

> **For a fresh session.** Read this end-to-end before doing anything. The full plan lives at [`../multi-book-architecture-plan.md`](../multi-book-architecture-plan.md). The active-initiative memory file is `~/.claude/projects/C--Users-marcu-git-repositories-Iconsult-mcp/memory/multi_book_refactor.md`.

## TL;DR

Phase 1 is in. The system now supports per-book KGs, a local DuckDB, and a `books` corpus catalogue. Phase 2 adds the **triage layer**: generate one summary embedding per book, then expose a `triage_books(project_description)` MCP tool that returns a deterministic ranked book list. Single-book by itself this is a no-op, but it's the gate before any second book can be onboarded.

## Where we are

```
feat/multi-book-kg  1dd78d6  Phase 1d: end-to-end pipeline + tests pass; CLAUDE.md updated
                    d63c5c6  Phase 1c: parameterize pipeline + scope all queries by book_id
                    b141d98  Phase 1b: per-book registry + seed arsanjani_2026 books row
                    adf8e45  Phase 1a: schema foundation for multi-book KG (local DuckDB)
main                a69968e  Drop DuckPGQ from plan: not available on windows_amd64
```

Both branches are pushed to `origin`. The local DuckDB at `data/iconsult.duckdb` already contains a fully-populated arsanjani_2026 graph (138 concepts / 786 sections / 583 relationships / 138 + 786 embeddings).

Test suite: 135/135 passing.

## Locked design decisions — do not re-litigate

| Topic | Decision |
|---|---|
| Database | Local DuckDB only (`data/iconsult.duckdb`, override via `ICONSULT_DB`). MotherDuck deferred indefinitely. |
| Triage signal | **Book-summary embeddings.** One vector per book, deterministic cosine match against project description. |
| Unified KG cadence | Cached per-project (Phase 3). Not corpus-wide, not per-consultation. |
| Concept role | Both `supporting_evidence` and `informational_only`, tagged distinctly (Phase 3-5). |
| First books to onboard | Mid-level patterns (Hohpe EIP, Fowler, Nygard *Release It!*) — Phase 6. |
| PDF→markdown | Mathpix for everything. |
| Branch strategy | Single `feat/multi-book-kg`, phase-per-commit. Merge to `main` only after all 6 phases land + a real second book is verified. |
| Concept ID convention | `{book_id}__{slug}` prefix on every concept and section ID. `normalize_pattern_id()` strips the prefix before alias lookup. |
| Oracle | Ch. 12 of Arsanjani is the immutable scoring oracle. Multi-book scoring works via `_PATTERN_ID_ALIASES` populated at alignment time (Phase 5). |
| DuckPGQ | Evaluated and dropped — community extension not available for `windows_amd64`. Python priority-queue BFS in `get_subgraph` stays. |

## Phase 2 scope

Per the plan: "**Triage layer.** `books.summary_embedding` populated for all books. `triage_books` tool returns sane rankings on test prompts."

### What's needed concretely

1. **Generate `books.summary` for arsanjani_2026.** A ~500–1000-word natural-language description of the book — what it covers, what altitude (mid-level patterns), key themes. The summary is the basis for the triage embedding, so it should *describe what a project would need this book for*, not just summarize the table of contents.

2. **Generate `books.summary_embedding`.** Use the existing `embed_query()` helper (from `iconsult_mcp.embed`) on the summary text. 1536-dim float vector, stored in the column we already created in Phase 1a.

3. **Build `triage_books` MCP tool.** New module `src/iconsult_mcp/tools/triage.py` exposing `triage_books(project_description, top_k=5, threshold=0.4) -> {ranked_books: [{id, title, score}, ...]}`. Cosine similarity between the project-description embedding and every row in `books`. Pure read tool. Deterministic.

4. **Wire it into `server.py`.** 4-place edit per CLAUDE.md: import, `TOOL_METADATA`, `TOOL_DISPATCH`, `list_tools()`.

5. **New script `scripts/generate_book_summary.py`.** Generates `summary` + `summary_embedding` for a given `--book <id>`. For arsanjani_2026 it can either prompt Claude to summarize the book content OR accept a hand-written summary. Idempotent — re-running updates the row.

6. **Tests.** New `tests/test_triage.py` covering: (a) determinism (same description → same ranking), (b) sane ranking on a representative prompt, (c) `top_k` and `threshold` filters work, (d) returns empty when no books are above threshold.

### Suggested sub-staging

| Stage | Scope |
|---|---|
| **2a** | New `scripts/generate_book_summary.py` + run it once for arsanjani_2026. Confirm `books.summary` and `books.summary_embedding` populated. |
| **2b** | New `src/iconsult_mcp/tools/triage.py` with `triage_books`. Register in `server.py`. New `tests/test_triage.py`. |
| **2c** | Verification: full test suite passes; `triage_books` over MCP returns arsanjani_2026 with a high score for an obviously-relevant prompt. Phase 2 commit. |

## Files that will change

- **NEW** `scripts/generate_book_summary.py`
- **NEW** `src/iconsult_mcp/tools/triage.py`
- **NEW** `tests/test_triage.py`
- `src/iconsult_mcp/server.py` (register `triage_books` — 4-place edit pattern)
- `CLAUDE.md` (mention the new tool + script under Pipeline / MCP Tools)
- The `books` table gains real values for `summary` + `summary_embedding` (data-only change, no schema change — column already exists from Phase 1a)

## Reuse — don't reinvent

- `embed_query()` in `iconsult_mcp.embed` — same OpenAI wrapper used by `match_concepts`. Stays the same; just feed it the summary text.
- `get_book(book_id)` / `list_books()` / `upsert_book(...)` in `db.py` — already exist from Phase 1b. `upsert_book` updates the summary; add a small helper if needed for `summary_embedding` specifically (or extend `upsert_book`).
- DuckDB `array_cosine_similarity` — already used in `search_concepts_by_embedding`. Same SQL pattern over the `books` table.
- Tool-registration pattern (4-place edit) — see how `validate_subagent` was added; copy that structure.

## Verification

```bash
# After 2a:
py scripts/generate_book_summary.py --book arsanjani_2026
py -c "from iconsult_mcp.db import get_book; r = get_book('arsanjani_2026'); print(bool(r.get('summary')), len(r.get('summary') or ''))"
# Expect: True, ~500-1000 chars (or however long the summary is)

# After 2b:
py -m pytest tests/test_triage.py -v

# After 2c:
py -m pytest tests/ -v       # all tests still pass (135 + new triage tests)
iconsult-mcp                  # then via MCP client:
#   triage_books("multi-agent system with retry, fault tolerance, supervisor coordination")
# Expect: arsanjani_2026 ranked first with score > 0.5
```

## Cost / time

- **Summary generation**: one Claude call (use ~`anthropic_messages`-equivalent in `iconsult_mcp.embed`) with a chunk of the book intro / table-of-contents / Ch. 1 abstract as context. Cents.
- **Embedding generation**: one OpenAI `text-embedding-3-small` call. Fraction of a cent.
- **Test runtime**: triage tests are pure-DB queries, sub-second.
- **Wall time**: 2a should take ~1 minute end-to-end. Total Phase 2 implementation: probably 30-60 minutes of focused work (scripts + tool + tests + commit).

Negligible vs. Phase 1d.

## First commands to run in the new session

```bash
git status                                # confirm clean tree
git branch --show-current                 # should be feat/multi-book-kg
git log --oneline -5                      # confirm 1dd78d6 at top
py -c "from iconsult_mcp.db import get_book; r = get_book('arsanjani_2026'); print({k: r.get(k) for k in ['id','title','authors','altitude','is_oracle']})"
# Expect: full metadata, summary=None, summary_embedding=None
```

If `data/iconsult.duckdb` is missing (e.g., fresh clone), rebuild it before starting Phase 2:

```bash
py scripts/seed_books_table.py
py scripts/run_pipeline.py --book arsanjani_2026 --reset
# This is the Phase 1d run again — 30-60 min, real API cost.
# Skip if data/iconsult.duckdb already exists from this session.
```

## Open question (worth thinking about before 2a)

**How is the summary generated?** Two reasonable options:

1. **Hand-written by the user.** Most accurate, easiest to control voice/altitude. ~15 minutes. Drop into `scripts/generate_book_summary.py` as a literal string keyed by `book_id`, or read from `literature/{book_id}/summary.md`.
2. **Claude-generated from the book.** Feed Ch. 1 intro + table of contents + maybe Ch. 12 abstract; ask Claude to produce the 500-1000 word triage-oriented summary. More automatic, slightly less controlled, costs a Claude call.

Either works. Option 2 scales better when onboarding more books in Phase 6, but Option 1 gives a stronger anchor for the oracle book. Worth deciding at the start of 2a — could even do Option 2 with the user reviewing/editing before storing.
