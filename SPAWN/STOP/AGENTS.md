# Orchestrator Runtime Instructions

This runtime operates locally inside `SPAWN/STOP/`.

Primary goals:

1. Operate the local orchestrator runtime truthfully from repo-backed state.
2. Collect useful training data from traces, misses, steering events, and memory artifacts.
3. Improve the model pipeline using repo-visible artifacts, not hidden agent memory.
4. Maintain task-scoped security, locks, audit trails, and allowed-path enforcement.
5. Keep `task_queue.json`, memory artifacts, and the repo-truth frontend aligned.

Key rules:

- `SPAWN/START/` is immutable after bootstrap.
- `SPAWN/STOP/` is the writable runtime zone.
- `task_queue.json` contains the actionable local backlog, verification gates, projection execution tasks, and training work.
- Queue progress is stage-based: use `scaffolded`, `implemented`, `validated`, and `completed` truthfully, and never collapse file creation alone into `completed`.
- Misses, blocked actions, and wrong assumptions should be captured into `MEMORY.md`, `.orchestrator/data/`, `.orchestrator/iterations/`, `.orchestrator/vector_store/`, and `retrieval_log.jsonl`.

Active runtime files:

- `SPAWN/START/prompt.md`
- `SPAWN/STOP/.orchestrator/loop.py`
- `SPAWN/STOP/.orchestrator/dashboard_state.py`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/web/templates/repo_truth.html`
