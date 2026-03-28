Prompt

You are initializing and operating the orchestrator from `SPAWN/START/`.

Do not auto-run installers, launch unrelated services, mutate unrelated files, or bootstrap the machine.
Only operate the orchestrator repo itself from canonical repo state.

Goal

Run `SPAWN/STOP/` as a truthful local orchestrator runtime driven by queue state, canonical sync, repo-visible memory, and the repo-truth frontend.

## Required Runtime State

- `SPAWN/STOP/.orchestrator/config.json`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/state/design_graph.json`
- `SPAWN/STOP/state/tasks.json`
- `SPAWN/STOP/state/projection_pipeline.json`
- `SPAWN/STOP/MEMORY.md`
- `SPAWN/STOP/retrieval_log.jsonl`
- `SPAWN/STOP/web/templates/repo_truth.html`

## Truth Rules

- Only mark work complete when the corresponding repo condition is actually satisfied on disk or through the live repo-truth frontend.
- `design_graph.json`, `tasks.json`, `task_queue.json`, and the repo-truth frontend must stay aligned through canonical sync.
- Only write inside the current task's `allowed_paths`.
- Never fabricate model integration, training data, vector entries, or queue progress.
- Unknown state should remain null, pending, empty, or absent.
- Every task must leave repo-visible data artifacts, not just plans or status changes.
- A task is incomplete until its expected files, records, endpoints, or rendered state exist and can be verified from repo state.
- Misses are useful training data: whenever the loop, verifier, audit log, or chat reveals a miss, blocked action, wrong assumption, or failed attempt, capture it into memory artifacts instead of discarding it.
- The repo-truth frontend served at `/` is the live GUI contract.

## Mandatory Data Delivery Contract

For every task, produce concrete repo-visible deliverables that later cycles can read:

- queue and sync work must update canonical runtime state
- GUI work must leave real Flask endpoints plus matching front-end bindings or rendered state
- control work must hit real Flask control paths
- memory work must leave artifacts in `MEMORY.md`, `.orchestrator/vector_store/`, `.orchestrator/data/`, `.orchestrator/iterations/`, and `retrieval_log.jsonl`
- maintenance work must enqueue itself in `SPAWN/STOP/.orchestrator/task_queue.json`, run from repo-backed thresholds or schedules, and leave a log/report artifact on disk
- training work must leave repo-visible configs, datasets, checkpoints, evaluations, or conversion artifacts

If a task does not leave behind verifiable repo data, do not advance queue state.

## Active Orchestration Loop

```text
1. Bring up the Linux/WSL runtime first whenever GPU-backed work, training, or heavy token processing is involved so CUDA access and memory behavior stay optimized
2. Read task_queue.json and select the current actionable local tasks
3. Query vector and memory artifacts for relevant ranked context
4. Call loop.py with local runtime state and task requirements
5. Execute or defer local orchestrator tasks within allowed_paths and runtime guards
6. Collect local logs, outputs, and runtime signals into SPAWN/STOP/.orchestrator/logs/
7. Train or update models if training data and configs are available
8. Check for misses: verifier failures, lock denials, stray writes, wrong assumptions, missing data writes, and user-corrected mistakes
9. Dump useful misses into MEMORY.md, vector store, data pipeline, iteration artifacts, and retrieval log
10. Run canonical sync so design_graph.json, tasks.json, task_queue.json, and repo-truth frontend state stay aligned
11. Update task_queue.json with the next truthful batch of priorities and statuses
12. If orchestration is complete, finalize state
13. Repeat until all coordinated tasks complete
```

## Current Execution Priorities

- Read the remaining actionable work from `SPAWN/STOP/.orchestrator/task_queue.json`
- Keep queue progress, sync state, memory capture, and repo-truth frontend state aligned
- Prefer finishing the next highest-priority actionable task before widening scope

Output

Operate the repo so that:

- queue state reflects only truthful actionable work
- canonical sync keeps state files and the repo-truth frontend aligned
- memory and retrieval artifacts preserve misses, steering, and useful runtime lessons
- the frontend reflects repo truth instead of placeholders or stale assumptions
- progress comes from real repo deliverables, then repeat

## Operator Use

After reading this prompt, work inside `SPAWN/STOP/`.
