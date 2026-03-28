1. DELIVER A 24B MODEL THAT OUTPERFORMS FRONTIER GPT ON CODING
2. BUILD AND MANAGE A LOCAL ORCHESTRATOR RUNTIME WITH COMPREHENSIVE SECURITY

## Projection-First Integration Plan

The repo carries a non-destructive projection scaffold so planning can happen before stack execution.

High-level flow:

1. extractor emits draft repo structure into `SPAWN/STOP/state/extraction.json`
2. operator review corrects draft structure in `SPAWN/STOP/state/operator_overrides.json`
3. task generator expands approved structure into `SPAWN/STOP/state/projected_tasks.json` and `SPAWN/STOP/state/projection_graph.json`
4. promotion gate copies approved projected work into canonical execution state only after validation
5. prompt handoff points the build agent at `SPAWN/START/prompt.md`
6. memory/vector feedback captures corrections, misses, and successful structure recognition for later retrieval

Non-breaking rule:

- projection artifacts must remain separate from canonical execution state until approval and promotion complete

Repo memory rule:

- planning and correction knowledge must live on disk in `SPAWN/STOP/MEMORY.md`, `SPAWN/STOP/retrieval_log.jsonl`, `.orchestrator/vector_store/`, `.orchestrator/iterations/`, and `.orchestrator/data/`
- the loop should retrieve ranked relevant context from those stores instead of assuming hidden agent memory

## Repo-Truth Frontend

The default frontend route is the repo-truth shell that reads explicit backend state domains.

High-level flow:

1. keep canonical repo state generation in `SPAWN/STOP/.orchestrator/dashboard_state.py`
2. expose explicit frontend state contracts for execution, queue, projection, runtime, memory, training, and misses
3. stream backend runtime activity into the GUI through repo-backed APIs and SSE
4. correlate runtime activity with trace, retrieval, and dataset writes so missed data capture can be detected visibly
5. keep `/` as the single live frontend

Non-breaking rule:

- the new frontend must consume canonical state domains without mutating queue or execution state during rendering
- canonical sync remains responsible for keeping queue state, canonical state files, and the frontend aligned from repo truth

## Git Serialization

The repo root is intentionally one level above `SPAWN/`, so every git write still targets the single top-level index under `.git/`.

That layout is not the bug.
The real failure mode is concurrent git writes against the same root, especially when `commit`, `push`, or other mutating commands are launched in parallel.

Rules:

- run mutating git commands from the top-level repo, not from separate ad hoc child contexts
- never launch `git add`, `git commit`, and `git push` in parallel against the same repo
- use `python scripts/git_serial.py ...` for automation-facing git writes

Examples:

```powershell
python scripts/git_serial.py status
python scripts/git_serial.py add SPAWN/STOP/web/app.py
python scripts/git_serial.py commit -m "Update repo-truth frontend"
python scripts/git_serial.py push origin main
```
