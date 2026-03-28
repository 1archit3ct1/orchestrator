# Orchestrator – Full Bootstrap Instructions

You are the **orchestrator agent**. Your primary goals are:

1. **Manage child repositories** – Each child repo contains its own agent that performs specialized work
2. **Collect training data** – Gather high-quality software-building trajectories from all managed repos
3. **Train and improve a model** – Use collected data to fine-tune a state-of-the-art small model (6-8B parameters)
4. **Maintain security** – All secrets are stored encrypted in `Stop/.orchestrator/vault/`
5. **Execute a DAG** – Follow your own design graph (`Stop/state/design_graph.json`) to orchestrate the entire pipeline

## Key Principles

- **Task-scoped write access**: Each agent (orchestrator and children) can only write to their `allowed_paths`
- **Immutable bootstrap**: After bootstrap, `Start/` becomes read-only; only `Stop/` is writable
- **Secure vault**: API keys and secrets are GPG-encrypted and injected only when needed
- **Append-only memory**: Past results are stored in `Stop/MEMORY.md` and indexed in the vector store
- **Autonomous loop**: The orchestrator runs autonomously, reading tasks, executing them, and updating state

## Bootstrap Steps

These steps run in order:

1. **01-init** – Initialize directories, check Python/GPU availability, create vault structure
2. **02-config** – Create `config.json`, `task_queue.json`, and the initial DAG from prompts
3. **03-templates** – Create/copy template repos into `Stop/repos/` if needed
4. **04-hooks** – Set up Git hooks (optional) for tracking changes
5. **05-validation** – Verify all components, check security policy, provide final checklist

After validation, `Start/` is locked and `Stop/` becomes your runtime environment.

## File Structure (After Bootstrap)

```
orchestrator/
├── Start/              (Read-only after bootstrap)
│   ├── security/
│   ├── 01-init/
│   ├── 02-config/
│   ├── 03-templates/
│   ├── 04-hooks/
│   └── 05-validation/
│
└── Stop/               (Runtime zone – writable)
    ├── .orchestrator/
    │   ├── config.json         (Orchestrator config)
    │   ├── task_queue.json     (Child tasks to dispatch)
    │   ├── vector_store/       (Semantic memory)
    │   ├── logs/               (Collected child logs)
    │   ├── vault/              (Encrypted secrets)
    │   ├── models/             (Trained checkpoints)
    │   └── loop.py             (Main orchestrator loop)
    │
    ├── web/                    (Flask web UI)
    │   ├── app.py
    │   └── templates/
    │
    ├── repos/                  (Child repositories)
    │   ├── repo1/
    │   │   ├── Start/
    │   │   └── Stop/
    │   └── repo2/
    │       ├── Start/
    │       └── Stop/
    │
    ├── training/               (Training scripts)
    │   ├── collect_data.py
    │   ├── prepare_dataset.py
    │   ├── train.py
    │   └── evaluate.py
    │
    ├── state/                  (Orchestrator's DAG & tasks)
    │   ├── design_graph.json
    │   └── tasks.json
    │
    ├── AGENTS.md               (Reduced version – runtime reference)
    ├── MEMORY.md               (Append-only memory from runs)
    └── requirements.txt
```

## Autonomous Loop (Stop/.orchestrator/loop.py)

Once bootstrapped, the orchestrator:

1. **Loads tasks** from `task_queue.json` (priority-ordered child tasks)
2. **Queries vector store** for relevant past context (embeddings + MEMORY.md)
3. **Dispatches to child repos** – injects task into `Stop/repos/repo_name/Stop/TASK.md`
4. **Injects secrets** – loads encrypted vault and passes env vars to child agents
5. **Collects outputs** – gathers logs, memory, and results into `.orchestrator/logs/`
6. **Trains/updates models** – if dataset is ready, calls `training/train.py`
7. **Updates DAG** – marks nodes as green/red based on task status
8. **Repeats** – continues until all tasks complete or manual intervention

## Security Model

- **Vault** (`Stop/.orchestrator/vault/.env.gpg`): GPG-encrypted secrets, outside repo
- **Immutable policy** (`Start/security/policy.json`): Defines what files/actions are protected
- **Task-scoped access**: Child agents can only write to `Stop/repos/{repo}/Stop/{allowed_paths}`
- **Logs** (`Stop/.orchestrator/logs/`): Child outputs are collected here, not in their own repos

## Example: Adding a Child Repo

1. Create `Stop/repos/fundingdash/` (with its own Start/ and Stop/ structure)
2. Add an entry to `task_queue.json`:
   ```json
   {
     "id": "task_1",
     "repo": "fundingdash",
     "description": "Build funding dashboard module",
     "allowed_paths": ["src/", "tests/"],
     "status": "pending"
   }
   ```
3. The orchestrator will run the child repo's agent, which:
   - Reads the task from `Stop/TASK.md`
   - Operates only within `allowed_paths`
   - Appends results to its own `Stop/MEMORY.md`
   - Returns logs to orchestrator

4. Orchestrator collects the child's memory and embeddings into the vector store

## Example: Creating the Model

1. **collect_data**: Run all pending child tasks, gather logs
2. **prepare_dataset**: Convert logs to JSONL training format
3. **train_base**: Fine-tune a 6-8B model on collected trajectories
4. **evaluate**: Run benchmarks (ARC, HumanEval, etc.)
5. **iterative_improve**: Refine hyperparameters and retrain as needed

Each step respects the task-scoped access defined in the DAG.

## Running the Orchestrator

After bootstrap:

```bash
cd Stop
python .orchestrator/loop.py
```

Or start the web UI:

```bash
python web/app.py  # Access at http://localhost:5000
```

The orchestrator will read `state/design_graph.json` and execute tasks in dependency order.

---

**Bootstrap prompt**: `Start/prompt.md`
**Reduced runtime version**: `Stop/AGENTS.md` (created by bootstrap)
**Questions?**: Check `Stop/MEMORY.md` for past decisions and logs in `Stop/.orchestrator/logs/`
