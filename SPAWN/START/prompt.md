# Orchestrator Bootstrap Prompt

You are initializing the orchestrator from `SPAWN/START/`.

Do not auto-run installers, launch services, mutate unrelated files, or "bootstrap the machine."
Only prepare the orchestrator repo itself from canonical repo state.

## Bootstrap Goal

Initialize `SPAWN/STOP/` so the autonomous orchestration loop can run truthfully from repo-backed state.

## Required Runtime State

- `SPAWN/STOP/.orchestrator/config.json`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/state/design_graph.json`
- `SPAWN/STOP/state/tasks.json`
- `SPAWN/STOP/TASK.md`
- `SPAWN/STOP/MEMORY.md`

## Truth Rules

- Only mark a DAG task green when the corresponding repo condition is actually satisfied.
- When a GUI section becomes repo-live, update its corresponding dashboard task/state to green on the next cycle.
- If a task is not satisfied, keep `TASK.md` on that task.
- Only write inside the current task's `allowed_paths`.
- Never fabricate model integration, training data, child repos, or vector entries.
- Unknown state should remain null, pending, empty, or absent.
- Every task MUST deliver repo-visible data artifacts, not just status changes or plans.
- A task is incomplete until its expected files, folders, or records exist on disk and can be verified from repo state.
- Misses are useful training data: whenever the loop, verifier, audit log, or chat reveals a miss, blocked action, wrong assumption, or failed attempt, capture it as memory instead of discarding it.

## Mandatory Data Delivery Contract

For every task, produce concrete GUI-visible deliverables that the repo can read later:

- navigation work must leave explicit `data-*` hooks and panel state handling in the dashboard
- drilldown work must leave clickable repo-backed detail views, not hover-only shells
- export work must leave real Flask endpoints plus matching front-end bindings
- control work must leave real Flask control endpoints plus matching front-end bindings
- readiness work must render from canonical repo state rather than static placeholder text
- miss analysis work must leave repo-visible memory artifacts in `MEMORY.md`, `.orchestrator/vector_store/`, `.orchestrator/data/`, `.orchestrator/iterations/`, and `retrieval_log.jsonl`

If a task does not leave behind verifiable repo data, do not advance the DAG.

## Active Orchestration Loop

```text
1. Read task_queue.json (priority-ordered child tasks)
2. Query vector store for relevant context (past child task results, embeddings)
3. Call loop.py with state + child repo requirements
4. Dispatch tasks to child repos via their allowed_paths (task-scoped coordination)
5. Collect logs/outputs from child repos into SPAWN/STOP/.orchestrator/logs/
6. Train/update models if training data available
7. Check for misses: verifier failures, lock denials, stray writes, wrong assumptions, and user-corrected mistakes
8. Dump useful misses into MEMORY.md, vector store, data pipeline, iteration artifacts, and retrieval log
9. Update task_queue.json with next batch of task priorities
10. If orchestration complete, finalize state
11. Repeat until all coordinated tasks complete
```

## Current Expected DAG

- `T01 gui-nav-panels`
- `T02 gui-dag-task-details`
- `T03 gui-bootstrap-step-details`
- `T04 gui-repo-structure-details`
- `T05 gui-vector-phase-details`
- `T06 gui-memory-file-open`
- `T07 gui-export-jsonl`
- `T08 gui-export-alpaca`
- `T09 gui-export-sharegpt`
- `T10 gui-export-steering`
- `T11 gui-repo-freeze-toggle`
- `T12 gui-spawn-loop-controls`
- `T13 gui-audit-log-details`
- `T14 gui-stray-monitor-details`
- `T15 gui-readiness-tracker-live`

## Bootstrap Output

Initialize the repo so that:

- each GUI task maps to a real inactive function from the dashboard surface
- only truly repo-backed GUI functions ever turn green
- the GUI visibly turns green for any section whose repo-backed function is live
- the next runnable GUI task is written into `SPAWN/STOP/TASK.md`
- the dashboard reads canonical repo truth without placeholder function claims

## Task Completion Requirements

Do not complete a task unless it delivers the following:

- `T01 gui-nav-panels`: sidebar nav changes live panel state through repo-backed hooks
- `T02 gui-dag-task-details`: DAG rows open real task detail state
- `T03 gui-bootstrap-step-details`: bootstrap rows open real step details
- `T04 gui-repo-structure-details`: repo structure rows open real details
- `T05 gui-vector-phase-details`: vector phases open real phase details
- `T06 gui-memory-file-open`: memory file rows open real repo file details
- `T07-T10`: each export button has a matching live Flask export endpoint and binding
- `T11`: repo freeze toggle mutates live freeze state through Flask
- `T12`: spawn loop controls hit a live Flask control plane
- `T13`: audit log panel opens detailed audit events
- `T14`: stray monitor panel opens detailed stray events
- `T15`: readiness tracker rows render from canonical repo state

## Operator Use

After reading this prompt, work inside `SPAWN/STOP/`.
