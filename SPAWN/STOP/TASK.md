---
task_id: task_001
dag_node_id: gui_nav_panels
allowed_paths:
  - SPAWN/STOP/state/design.html
  - SPAWN/STOP/web/app.py
priority: 1
---

# Task: gui-nav-panels

## Description
Wire the sidebar navigation so each GUI section changes live panel state from repo-backed Flask data instead of acting like a visual-only shell.

## Allowed Paths
You may ONLY write to: `SPAWN/STOP/state/design.html`, `SPAWN/STOP/web/app.py`

## Data Delivery Requirement
This task is not complete until the repo contains all of the following:

- sidebar nav items with explicit `data-nav` and `data-panel` hooks in `SPAWN/STOP/state/design.html`
- live navigation handling in `SPAWN/STOP/web/app.py`
- repo-backed panel switching rather than click-only visual feedback

## Status: PENDING
