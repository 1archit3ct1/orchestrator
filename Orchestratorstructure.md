Orchestrator Structure

The active runtime is local-first and lives inside `SPAWN/STOP/`.

Use these files as the current structure contract:

- `README.md`
- `SPAWN/START/prompt.md`
- `SPAWN/STOP/.orchestrator/loop.py`
- `SPAWN/STOP/.orchestrator/dashboard_state.py`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/state/design_graph.json`
- `SPAWN/STOP/state/tasks.json`
