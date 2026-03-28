---
task_id: task_001
dag_node_id: collect_data
allowed_paths:
  - Stop/.orchestrator/logs/
priority: 1
---

# Task: Collect Data from Child Repos

## Description
Run tasks on all managed repos to gather training trajectories.

## Allowed Paths
You may ONLY write to: `Stop/.orchestrator/logs/`

## Context
This is the first task in the orchestrator's training pipeline. Once child repos are configured in Stop/repos/, this task will coordinate with them to collect logs and outputs for training data.

## Status: PENDING
