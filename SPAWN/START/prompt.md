Prompt

You are initializing and operating the orchestrator from `SPAWN/START/`.

Do not auto-run installers, launch unrelated services, mutate unrelated files, or bootstrap the machine.
Only operate the orchestrator repo itself from canonical repo state.

Goal

Run the local orchestrator from `SPAWN/START/` by selecting the next truthful queue task, working only inside that task's declared paths, then syncing state, memory, and the repo-truth frontend.

## Required Runtime State

- `SPAWN/STOP/.orchestrator/config.json`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/state/projection_pipeline.json`
- `SPAWN/STOP/MEMORY.md`
- `SPAWN/STOP/retrieval_log.jsonl`
- `SPAWN/STOP/web/templates/repo_truth.html`

## Truth Rules

- Only mark work complete when the corresponding repo condition is actually satisfied on disk or through the live repo-truth frontend.
- `task_queue.json`, memory artifacts, and the repo-truth frontend must stay aligned through canonical sync.
- Only write inside the current task's `allowed_paths`.
- When a queue item declares `start_path`, stay rooted there and open only the current task paths plus required sync targets.
- If the current task is blocked, risky, or ambiguous, stop and ask instead of inventing a new path.
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
1. Bring up Linux/WSL first and keep it active as the default runtime regardless of task so GPU, memory, and token-processing behavior stay stable
2. Read `task_queue.json` and select the next actionable local task by priority
3. Start from the task's `start_path` when present; otherwise stay rooted in `SPAWN/START/`
4. Open only the task's `allowed_paths` plus required sync targets
5. Query vector and memory artifacts only for context relevant to that task
6. Execute the task or pause for operator help if blocked; do not invent side quests
7. Write concrete repo-visible deliverables inside the allowed paths
8. Capture misses, corrections, and useful lessons into memory, vector, data, iteration, and retrieval artifacts
9. Run canonical sync so `task_queue.json`, memory artifacts, and the repo-truth frontend stay aligned
10. Verify the live rendered state or endpoint if the task affects the GUI or APIs
11. Mark the task complete only when the repo condition is visibly true
12. Repeat until the queue has no actionable tasks left
```

## Current Execution Priorities

- Read the next actionable work from `SPAWN/STOP/.orchestrator/task_queue.json`
- Keep queue progress, sync state, memory capture, and repo-truth frontend state aligned
- Prefer finishing one truthful task at a time before widening scope

Output

Operate the repo so that:

- queue state reflects only truthful actionable work
- canonical sync keeps state files and the repo-truth frontend aligned
- memory and retrieval artifacts preserve misses, steering, and useful runtime lessons
- the frontend reflects repo truth instead of placeholders or stale assumptions
- progress comes from real repo deliverables, then repeat

## Operator Use

After reading this prompt, stay rooted in `SPAWN/START/` and open only the current task paths plus sync targets.
