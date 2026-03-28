# Orchestrator Runtime Instructions

The multi-repo pilot has been retired.

This runtime is now local-first. All orchestration happens inside `SPAWN/STOP/`.

Primary goals:

1. Operate the local orchestrator runtime truthfully from repo-backed state.
2. Collect useful training data from local traces, misses, steering events, and memory artifacts.
3. Improve the model pipeline using repo-visible data, not hidden agent memory.
4. Maintain task-scoped security, locks, audit trails, and allowed-path enforcement.
5. Keep `design_graph.json`, `tasks.json`, `task_queue.json`, `TASK.md`, and the repo-truth frontend aligned.

Key rules:

- `SPAWN/START/` is immutable after bootstrap.
- `SPAWN/STOP/` is the writable runtime zone.
- `TASK.md` is owned by canonical sync, not by ad hoc helper code.
- `task_queue.json` contains local orchestrator backlog, strategic work, verification gates, and projection execution tasks.
- Misses, blocked actions, and wrong assumptions should be captured into `MEMORY.md`, `.orchestrator/data/`, `.orchestrator/iterations/`, `.orchestrator/vector_store/`, and `retrieval_log.jsonl`.

Active runtime files:

- `SPAWN/START/prompt.md`
- `SPAWN/STOP/.orchestrator/loop.py`
- `SPAWN/STOP/.orchestrator/dashboard_state.py`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/state/design_graph.json`
- `SPAWN/STOP/state/tasks.json`
- `SPAWN/STOP/web/templates/repo_truth.html`

Retired pilot assumptions:

- no child repos under `SPAWN/STOP/repos/`
- no downstream repo dispatch contract
- no child-repo log collection flow

If future expansion goes beyond the local runtime, it should be introduced as a new explicit architecture rather than reviving the retired multi-repo pilot.
