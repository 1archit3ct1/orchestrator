 Prompt

You are initializing the orchestrator from `SPAWN/START/`.

Do not auto-run installers, launch services, mutate unrelated files, or "bootstrap the machine."
Only prepare the orchestrator repo itself from canonical repo state.

 Goal

Initialize `SPAWN/STOP/` so the autonomous orchestration loop can run truthfully from repo-backed state.

## Required Runtime State

- `SPAWN/STOP/.orchestrator/config.json`
- `SPAWN/STOP/.orchestrator/task_queue.json`
- `SPAWN/STOP/state/design_graph.json`
- `SPAWN/STOP/state/tasks.json`
- `SPAWN/STOP/state/projection_pipeline.json`
- `SPAWN/STOP/TASK.md`
- `SPAWN/STOP/MEMORY.md`
- `SPAWN/STOP/web/templates/repo_truth.html`

## Truth Rules

- Only mark a DAG task green when the corresponding repo condition is actually satisfied.
- When a GUI section becomes repo-live, update its corresponding dashboard task/state to green on the next cycle.
- If a task is not satisfied, keep `TASK.md` on that task.
- Canonical sync owns `TASK.md` retirement and next-task promotion; agents should not invent side channels for task advancement.
- Only write inside the current task's `allowed_paths`.
- Never fabricate model integration, training data, or vector entries.
- Unknown state should remain null, pending, empty, or absent.
- Every task MUST deliver repo-visible data artifacts, not just status changes or plans.
- A task is incomplete until its expected files, folders, or records exist on disk and can be verified from repo state.
- Misses are useful training data: whenever the loop, verifier, audit log, or chat reveals a miss, blocked action, wrong assumption, or failed attempt, capture it as memory instead of discarding it.
- The repo-truth frontend served at `/` is the live GUI contract; do not rely on deleted legacy dashboard templates or stale DOM assumptions.
- `task_queue.json`, `design_graph.json`, and `tasks.json` must stay aligned with canonical sync so queue state, GUI state, and loop state do not drift apart.

## Mandatory Data Delivery Contract

For every task, produce concrete GUI-visible deliverables that the repo can read later:

- navigation work must leave explicit `data-*` hooks and panel state handling in the dashboard
- drilldown work must leave clickable repo-backed detail views, not hover-only shells
- export work must leave real Flask endpoints plus matching front-end bindings
- control work must leave real Flask control endpoints plus matching front-end bindings
- readiness work must render from canonical repo state rather than static placeholder text
- miss analysis work must leave repo-visible memory artifacts in `MEMORY.md`, `.orchestrator/vector_store/`, `.orchestrator/data/`, `.orchestrator/iterations/`, and `retrieval_log.jsonl`
- maintenance work must enqueue itself in `SPAWN/STOP/.orchestrator/task_queue.json`, run from repo-backed thresholds or schedules, and leave a log/report artifact on disk

If a task does not leave behind verifiable repo data, do not advance the DAG.

## Active Orchestration Loop

```text
1. Bring up the Linux/WSL runtime first whenever GPU-backed work, training, or heavy token processing is involved so CUDA access and memory behavior stay optimized
2. Read task_queue.json (priority-ordered child tasks)
3. Query vector store for relevant context (past child task results, embeddings)
4. Call loop.py with local runtime state + task requirements
5. Execute or defer local orchestrator tasks within their allowed_paths and runtime guards
6. Collect local logs/outputs into SPAWN/STOP/.orchestrator/logs/
7. Train/update models if training data available
8. Check for misses: verifier failures, lock denials, stray writes, wrong assumptions, and user-corrected mistakes
9. Dump useful misses into MEMORY.md, vector store, data pipeline, iteration artifacts, and retrieval log
10. Queue threshold-triggered maintenance jobs, including duplicate parsing for memory artifacts when token accumulation crosses its threshold
11. Run canonical sync so design_graph.json, tasks.json, TASK.md, and repo-truth frontend state stay aligned
12. Update task_queue.json with next batch of task priorities
13. If orchestration complete, finalize state
14. Repeat until all coordinated tasks complete
```

## Git Safety

- The git repo root is the parent folder above `SPAWN/`
- Do not run mutating git operations in parallel against that shared root
- For automation-facing git writes, prefer `python scripts/git_serial.py <git args>`

## Current Expected DAG

- `T01 gui-surface-routing`
- `T02 gui-legacy-dag-retired`
- `T03 gui-spawn-loop-controls`
- `T04 gui-training-run-details`
- `T05 gui-dataset-details`
- `T06 gui-eta-tracker-live`
- `T07 gui-scale-analysis-page`
- `T08 gui-audit-log-details`
- `T09 gui-repo-freeze-toggle`
- `T10 gui-stray-monitor-details`
- `T11 gui-trace-capture-details`
- `T12 gui-steering-log-details`
- `T13 gui-bootstrap-step-details`
- `T14 gui-repo-structure-details`
- `T15 gui-vector-phase-details`
- `T16 gui-memory-file-open`
- `T17 gui-export-jsonl`
- `T18 gui-export-alpaca`
- `T19 gui-export-sharegpt`
- `T20 gui-export-steering`
- `T21 gui-readiness-tracker-live`
- `T22 gui-mutex-lock-details`
- `T23 gui-model-status-panel`


Output

Initialize the repo so that:

- each GUI task maps to a real inactive function from the dashboard surface
- only truly repo-backed GUI functions ever turn green
- the GUI visibly turns green for any section whose repo-backed function is live
- the next runnable GUI task is written into `SPAWN/STOP/TASK.md`
- the dashboard reads canonical repo truth without placeholder function claims
- the repo-truth frontend at `/` remains the single live shell for the system

## Task Completion Requirements

Do not complete a task unless it delivers the following:

- `T01 gui-surface-routing`: dashboard surfaces stay truthfully routed through repo-backed panel hooks, with full-page fallback when no sidebar is present
- `T02 gui-legacy-dag-retired`: legacy GUI DAG list and drilldown surface remain removed from the repo-truth frontend and no stale backend DAG routes are required for normal use
- `T03 gui-spawn-loop-controls`: spawn loop controls hit a live Flask control plane
- `T04 gui-training-run-details`: training run section opens detailed repo-backed training state
- `T05 gui-dataset-details`: dataset section opens detailed repo-backed dataset state
- `T06 gui-eta-tracker-live`: ETA tracker renders canonical ETA details instead of static text
- `T07 gui-scale-analysis-page`: scale analysis page renders repo-backed scale recommendations, thresholds, and viability guidance
- `T08 gui-audit-log-details`: audit log panel opens detailed audit events
- `T09 gui-repo-freeze-toggle`: repo freeze toggle mutates live freeze state through Flask
- `T10 gui-stray-monitor-details`: stray monitor panel opens detailed stray events
- `T11 gui-trace-capture-details`: trace capture section opens detailed repo-backed trace history
- `T12 gui-steering-log-details`: steering log surface opens detailed repo-backed steering events
- `T13 gui-bootstrap-step-details`: bootstrap rows open real step details
- `T14 gui-repo-structure-details`: repo structure rows open real details
- `T15 gui-vector-phase-details`: vector phases open real phase details
- `T16 gui-memory-file-open`: memory file rows open real repo file details
- `T17-T20`: each export button has a matching live Flask export endpoint and binding
- `T21 gui-readiness-tracker-live`: readiness tracker rows render from canonical repo state
- `T22 gui-mutex-lock-details`: mutex status box opens detailed live lock ownership and gating state
- `T23 gui-model-status-panel`: model status surface is a first-class repo-backed function with readiness, graph rendering, and training-scale state


## Operator Use

After reading this prompt, work inside `SPAWN/STOP/`.
