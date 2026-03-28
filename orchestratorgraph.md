# Orchestrator Graph

The historical multi-repo pilot has been retired.

This repo now operates as a local-first orchestrator runtime rooted in `SPAWN/STOP/`.

Current sources of truth:

- `SPAWN/START/prompt.md`
- `SPAWN/STOP/.orchestrator/loop.py`
- `SPAWN/STOP/.orchestrator/dashboard_state.py`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `README.md`

Retired assumptions:

- no child repos under `SPAWN/STOP/repos/`
- no downstream repo dispatch model
- no cross-repo log collection contract

If local runtime work is later extended outward, it should be designed as a new explicit architecture rather than reviving the retired pilot model described in older versions of this file.
