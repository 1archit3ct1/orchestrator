Repository Architecture (with Vector Memory & Agent‑Agnostic)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ REPOSITORY ROOT │
│ │
│ ┌──────────────────────┐ ┌──────────────────────────────┐ │
│ │ 📁 Start/ │ │ 📁 Stop/ │ │
│ │ (Bootstrap Zone) │ │ (Agent Work Zone) │ │
│ │ │ │ │ │
│ │ ┌────────────────┐ │ BOOTSTRAP ┌──────────────────────────┐ │ │
│ │ │ 01-init/ │ │ COMPLETE │ 📁 .agent/ │ │ │
│ │ │ 02-config/ │ │ ─────────────► │ │ ├── loop.py │ │ │
│ │ │ 03-templates/ │ │ │ │ ├── planner.sh │ │ │
│ │ │ 04-hooks/ │ │ │ │ └── vector_store/ │ │ │
│ │ │ 05-validation/ │ │ │ │ (Chroma/FAISS) │ │ │
│ │ └────────────────┘ │ │ ├──────────────────────────┤ │ │
│ │ │ │ │ 📁 src/ │ │ │
│ │ 📄 bootstrap.sh │ │ │ 📁 docs/ │ │ │
│ │ 📄 AGENTS.md │ │ │ 📁 tests/ │ │ │
│ │ (FULL VERSION) │ │ │ 📄 TASK.md │ │ │
│ │ │ │ │ 📄 MEMORY.md │ │ │
│ │ 🔒 AFTER BOOTSTRAP: │ │ │ 📄 AGENTS.md │ │ │
│ │ REDUCED TO │ │ │ (REDUCED VERSION) │ │ │
│ │ PERENNIAL PROMPT │ │ └──────────────────────────┘ │ │
│ │ + TASK-SCOPED │ │ │ │
│ │ WRITE ACCESS │ │ 🟢 AGENT OPERATES HERE │ │
│ │ │ │ (Post-Bootstrap) │ │
│ └──────────────────────┘ └──────────────────────────────┘ │
│ │
│ ═══════════════════════════════════════════════════════════════════════════ │
│ FLOW: Clone → Start/bootstrap.sh → [Agent Initialized] → Stop/ [Agent Works] │
│ │
│ 🔁 AUTONOMOUS LOOP (within Stop/): │
│ 1. Read TASK.md (includes allowed_paths in frontmatter) │
│ 2. Query vector store for relevant past context (MEMORY.md + embeddings) │
│ 3. Call planner (./.agent/planner.sh) with state + prompt │
│ 4. Execute actions, respecting allowed_paths (task-scoped write) │
│ 5. Append result to MEMORY.md, embed new knowledge into vector store │
│ 6. If task done, update TASK.md to next task (user can edit manually) │
│ 7. Repeat until all tasks complete │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Loop reinforcement rule:
When integrations go live in Flask, their corresponding DAG tasks turn green, and the autonomous loop should keep reinforcing that green state from canonical repo truth on later cycles.

---

Key Additions & Explanations

1. AGENTS.md (instead of CLAUDE.md)

· Full version in Start/ contains the complete bootstrap instructions (the six steps) and the initial security policy.
· Reduced version is symlinked (or copied) into Stop/ after bootstrap, containing only the perennial prompt that defines the agent’s ongoing role, permissions, and the task‑scoped loop.
· This makes the system model‑agnostic – any LLM can read it and understand the protocol.

2. Vector Memory

· Stored in Stop/.agent/vector_store/ (e.g., Chroma, FAISS).
· During bootstrap (Step 4), the agent indexes the entire repository (code, docs, previous sessions) and builds the vector store.
· At runtime, before each task, the agent queries the vector store with the current task description and recent context, injecting the top‑k results into the planner prompt.
· After each task, the outcome (success, code changes, lessons) is embedded and added to the vector store, so future tasks benefit from past experience.

3. Autonomous Loop Details

· loop.py (in .agent/) implements the loop shown in the diagram.
· It reads TASK.md (which can have YAML frontmatter for allowed_paths, dependencies, etc.).
· It respects the task‑scoped write policy: only files matching allowed_paths can be created/modified.
· It calls the planner (planner.sh), which can be as simple as the original user‑prompt or later replaced by a local LLM.
· After execution, it updates MEMORY.md (append‑only) and also adds an embedding to the vector store.
· The loop continues until the task list is exhausted or a user interrupt.

4. Task‑Scoped Write Enforcement

· The allowed paths are defined per task in TASK.md (e.g., allowed_paths: ["src/api/", "tests/api/"]).
· The agent’s executor checks every write action against these patterns before executing.
· This is implemented in the loop’s action handling, mirroring the enforce_policy() from the earlier Python code but driven by the frontmatter of TASK.md.

5. Bootstrap Script (bootstrap.sh)

· Executes the numbered steps (01‑init through 05‑validation).
· Step 4 now includes setting up the vector store and indexing the repository.
· Step 5 validates that AGENTS.md is reduced, TASK.md exists (with initial task), and permissions are correct.
· After validation, it creates the Stop/ folder with the necessary structure and hands control to the agent (or instructs the user to start the loop).

---
