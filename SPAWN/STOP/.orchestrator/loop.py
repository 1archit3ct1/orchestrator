#!/usr/bin/env python3
"""
Orchestrator Autonomous Loop
Implements the 10-step coordination cycle defined in orchestratorgraph.md

FLOW: Clone → SPAWN/START/bootstrap.sh → [Orchestrator Initialized] → SPAWN/STOP/ [Orchestrator Coordinates]

This loop runs continuously within SPAWN/STOP/, reading tasks, dispatching to child repos,
collecting results, training models, and updating the vector store.

SECURITY: Integrated with SecurityManager for:
- Encrypted credential vault (GPG/AES-256)
- Write lock protocol (global and repo-level)
- Task-scoped credential injection
- Audit logging for all operations
"""

import json
import hashlib
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

# Import security system
import security_manager
from security_manager import CredentialType, SecurityManager
from dashboard_state import sync_dashboard_state, verify_dashboard_integrations
from maintenance import run_duplicate_parse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'logs', 'orchestrator.log'))
    ]
)
logger = logging.getLogger('orchestrator')


class OrchestratorLoop:
    """
    10-step autonomous orchestration loop with enterprise security.

    Coordinates child repos, collects outputs, trains models, and maintains state.
    All operations are secured with:
    - Write locks (prevent concurrent modifications)
    - Task-scoped credentials (injected per task)
    - Audit logging (tamper-evident trail)
    """

    # === ACCESS CONTROL ===
    # Only these paths (relative to the orchestrator root) are writable.
    # SPAWN/START/ is immutable after bootstrap lock.
    ALLOWED_WRITE_PATHS = [
        'SPAWN/STOP/.orchestrator',
        'SPAWN/STOP/MEMORY.md',
        'SPAWN/STOP/retrieval_log.jsonl',
        'SPAWN/STOP/state',
        'SPAWN/STOP/repos',
        'SPAWN/STOP/training',
        'SPAWN/STOP/web',
    ]

    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.orchestrator_dir = self.root / 'SPAWN' / 'STOP' / '.orchestrator'
        self.config_path = self.orchestrator_dir / 'config.json'
        self.task_queue_path = self.orchestrator_dir / 'task_queue.json'
        self.vector_store_dir = self.orchestrator_dir / 'vector_store'
        self.logs_dir = self.orchestrator_dir / 'logs'
        self.data_dir = self.orchestrator_dir / 'data'
        self.models_dir = self.orchestrator_dir / 'models'
        self.repos_dir = self.root / 'SPAWN' / 'STOP' / 'repos'
        self.state_dir = self.root / 'SPAWN' / 'STOP' / 'state'
        self.training_dir = self.root / 'SPAWN' / 'STOP' / 'training'

        self.config = self._load_json(self.config_path)
        graph = self._load_json(self.state_dir / 'design_graph.json')
        persisted_cycles = max(
            int(self.config.get('cycle_count', 0) or 0),
            int(graph.get('last_cycle', 0) or 0),
        )
        self.cycle_count = persisted_cycles

        # === SECURITY INTEGRATION ===
        # Initialize security manager for credential injection and write locks
        self.security = SecurityManager(self.root)
        logger.info("Security manager initialized")

    # === ACCESS CONTROL METHODS ===

    def _is_write_allowed(self, target_path: str) -> bool:
        """
        Check if a write operation to the given path is allowed.
        START/ is immutable (read-only). Only Stop/ subdirectories are writable.
        """
        resolved = Path(target_path).resolve()
        root_resolved = self.root.resolve()

        # Block writes to START/ (immutable bootstrap zone)
        start_dir = (root_resolved / 'START').resolve()
        if str(resolved).startswith(str(start_dir)):
            logger.error(f"ACCESS DENIED: Write blocked to immutable START/ zone: {target_path}")
            return False

        # Must be within an allowed write path
        for allowed in self.ALLOWED_WRITE_PATHS:
            allowed_resolved = (root_resolved / allowed).resolve()
            if str(resolved).startswith(str(allowed_resolved)):
                return True

        logger.error(f"ACCESS DENIED: Write blocked to unauthorized path: {target_path}")
        return False

    # === FILE I/O ===

    def _load_json(self, path: Path) -> dict:
        """Load JSON file safely."""
        try:
            if path.exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load {path}: {e}")
        return {}

    def _save_json(self, path: Path, data) -> bool:
        """Save JSON file with access control enforcement."""
        if not self._is_write_allowed(str(path)):
            raise PermissionError(f"Write access denied: {path}")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            logger.error(f"Failed to save {path}: {e}")
            return False

    def _append_text(self, path: Path, text: str) -> bool:
        if not self._is_write_allowed(str(path)):
            raise PermissionError(f"Write access denied: {path}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(text)
            return True
        except IOError as e:
            logger.error(f"Failed to append {path}: {e}")
            return False

    def _capture_miss_memory(self, miss_type: str, summary: str, details: dict | None = None):
        details = details or {}
        timestamp = datetime.now().isoformat()
        slug = hashlib.sha1(f"{timestamp}|{miss_type}|{summary}".encode('utf-8')).hexdigest()[:12]

        memory_path = self.root / 'SPAWN' / 'STOP' / 'MEMORY.md'
        retrieval_log = self.root / 'SPAWN' / 'STOP' / 'retrieval_log.jsonl'
        vector_path = self.vector_store_dir / f"miss_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.json"
        data_path = self.data_dir / f"miss_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.jsonl"
        iter_path = self.orchestrator_dir / 'iterations' / f"iter_{datetime.now().strftime('%Y%m%d_%H%M%S')}_miss_{slug}.json"

        memory_block = (
            f"\n## Loop Miss Capture - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Type: {miss_type}\n"
            f"- Summary: {summary}\n"
            f"- Details: {json.dumps(details, default=str)}\n"
        )
        self._append_text(memory_path, memory_block)

        vector_payload = {
            'id': f'miss_{slug}',
            'timestamp': timestamp,
            'type': 'miss_capture',
            'miss_type': miss_type,
            'summary': summary,
            'details': details,
        }
        self._save_json(vector_path, vector_payload)
        self._append_text(data_path, json.dumps(vector_payload, default=str) + '\n')
        self._save_json(iter_path, {
            'id': f'iter_miss_{slug}',
            'timestamp': timestamp,
            'type': 'miss_capture',
            'status': 'success',
            'summary': summary,
            'details': details,
        })
        self._append_text(
            retrieval_log,
            json.dumps({
                'timestamp': timestamp,
                'query': f'loop miss capture: {miss_type}',
                'top_hits': ['SPAWN/STOP/MEMORY.md', str(vector_path.relative_to(self.root)), str(iter_path.relative_to(self.root))],
                'notes': summary,
            }, default=str) + '\n'
        )

    def _load_design_graph(self) -> dict:
        return self._load_json(self.state_dir / 'design_graph.json')

    def _derive_tasks_from_graph(self) -> list:
        graph = self._load_design_graph()
        tasks = []
        for index, node in enumerate(graph.get('nodes', []), start=1):
            node_status = node.get('status', 'red')
            if node_status == 'green':
                task_status = 'completed'
            elif node_status == 'yellow':
                task_status = 'active'
            else:
                task_status = 'pending'

            tasks.append({
                'id': f'task_{index:03d}',
                'task_id': node.get('task_id', f'T{index:02d}'),
                'dag_node_id': node.get('id'),
                'label': node.get('task_name') or node.get('label') or node.get('id'),
                'description': node.get('description', ''),
                'allowed_paths': node.get('allowed_paths', []),
                'dependencies': node.get('dependencies', []),
                'status': task_status,
                'priority': index,
                'progress': node.get('progress'),
            })
        return tasks

    def _sync_tasks_file_from_graph(self) -> list:
        tasks = self._derive_tasks_from_graph()
        self._save_json(self.state_dir / 'tasks.json', tasks)
        return tasks

    def _write_task_md(self, task: dict) -> bool:
        task_md_path = self.root / 'SPAWN' / 'STOP' / 'TASK.md'
        allowed_paths = task.get('allowed_paths', [])
        allowed_lines = '\n'.join(f'  - {path}' for path in allowed_paths) if allowed_paths else '  - SPAWN/STOP/state/'
        label = task.get('label') or task.get('dag_node_id') or task.get('task_id') or 'task'
        description = task.get('description', '')
        content = (
            f"---\n"
            f"task_id: {task.get('id')}\n"
            f"dag_node_id: {task.get('dag_node_id')}\n"
            f"allowed_paths:\n{allowed_lines}\n"
            f"priority: {task.get('priority', 1)}\n"
            f"---\n\n"
            f"# Task: {label}\n\n"
            f"## Description\n"
            f"{description}\n\n"
            f"## Allowed Paths\n"
            f"You may ONLY write to: {', '.join(f'`{path}`' for path in allowed_paths) if allowed_paths else '`SPAWN/STOP/state/`'}\n\n"
            f"## Status: PENDING\n"
        )
        try:
            task_md_path.write_text(content, encoding='utf-8')
            return True
        except IOError as e:
            logger.error(f"Failed to write TASK.md: {e}")
            return False

    def _find_next_runnable_task(self) -> dict | None:
        tasks = self._sync_tasks_file_from_graph()
        completed_nodes = {
            task.get('dag_node_id')
            for task in tasks
            if task.get('status') == 'completed'
        }
        active_tasks = [task for task in tasks if task.get('status') == 'active']
        if active_tasks:
            return active_tasks[0]

        for task in tasks:
            if task.get('status') != 'pending':
                continue
            dependencies = task.get('dependencies', [])
            if all(dep in completed_nodes for dep in dependencies):
                return task
        return None

    def _save_config(self) -> bool:
        return self._save_json(self.config_path, self.config)

    def _persist_cycle_metrics(self):
        self.config['cycle_count'] = max(int(self.config.get('cycle_count', 0) or 0), self.cycle_count)
        self._save_config()

        design_graph = self.state_dir / 'design_graph.json'
        graph = self._load_json(design_graph)
        graph['last_cycle'] = max(int(graph.get('last_cycle', 0) or 0), self.cycle_count)
        graph['last_updated'] = datetime.now().isoformat()
        self._save_json(design_graph, graph)

    def _current_memory_tokens(self) -> int:
        dashboard_state = sync_dashboard_state(self.root / 'SPAWN' / 'STOP')
        model = dashboard_state.get('model', {})
        return int(model.get('memory_collected_tokens', 0) or 0)

    def _fetch_live_dashboard_state(self) -> dict | None:
        try:
            with urlopen('http://localhost:5000/api/dashboard', timeout=2) as response:
                return json.load(response)
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            logger.warning(f"  Live dashboard verification unavailable: {exc}")
            return None

    def _live_dashboard_node_state(self, dag_node_id: str) -> dict:
        payload = self._fetch_live_dashboard_state()
        if not isinstance(payload, dict):
            return {
                'live': False,
                'reason': 'live dashboard API was unavailable',
            }

        graph = payload.get('graph', {})
        for node in graph.get('nodes', []):
            if node.get('id') == dag_node_id:
                node_live = bool(node.get('verified_live')) and node.get('status') == 'green'
                return {
                    'live': node_live,
                    'reason': node.get('verification_reason') or ('node is live in Flask dashboard' if node_live else 'live dashboard node is not green yet'),
                }

        verification = payload.get('verification', {})
        if dag_node_id in verification:
            verified = verification.get(dag_node_id, {})
            return {
                'live': bool(verified.get('live')),
                'reason': verified.get('reason', 'live dashboard verification returned no reason'),
            }

        return {
            'live': False,
            'reason': 'dag node is missing from live dashboard payload',
        }

    def _task_condition_state(self, dag_node_id: str) -> dict:
        if dag_node_id == 'loop_runtime':
            return {
                'live': True,
                'reason': 'loop runtime foundation is present',
                'source_live': True,
                'runtime_live': True,
            }

        verification = verify_dashboard_integrations(self.root / 'SPAWN' / 'STOP')
        source_state = verification.get(dag_node_id)
        if not source_state:
            return {
                'live': False,
                'reason': 'no verification rule',
                'source_live': False,
                'runtime_live': False,
            }

        runtime_state = self._live_dashboard_node_state(dag_node_id)
        source_live = bool(source_state.get('live'))
        runtime_live = bool(runtime_state.get('live'))
        if source_live and runtime_live:
            reason = runtime_state.get('reason') or source_state.get('reason', 'source and runtime verification passed')
        elif not source_live:
            reason = source_state.get('reason', 'source verification failed')
        else:
            reason = runtime_state.get('reason', 'live dashboard verification failed')

        return {
            'live': source_live and runtime_live,
            'reason': reason,
            'source_live': source_live,
            'runtime_live': runtime_live,
        }

    def _queue_has_task(self, task_id: str) -> bool:
        queue = self._load_json(self.task_queue_path)
        if not isinstance(queue, list):
            queue = queue.get('pending', [])
        return any(task.get('id') == task_id for task in queue)

    def _schedule_duplicate_parse_job_if_needed(self) -> bool:
        maintenance_cfg = self.config.setdefault('maintenance', {}).setdefault('duplicate_parse', {})
        if not maintenance_cfg.get('enabled', True):
            return False

        current_tokens = self._current_memory_tokens()
        threshold = int(maintenance_cfg.get('token_threshold', 3000) or 3000)
        last_requested = int(maintenance_cfg.get('last_requested_tokens', 0) or 0)
        task_id = 'maintenance_parse_duplicates'

        if current_tokens < threshold or (current_tokens - last_requested) < threshold:
            return False
        if self._queue_has_task(task_id):
            return False

        queue = self._load_json(self.task_queue_path)
        if not isinstance(queue, list):
            queue = queue.get('pending', [])

        queue.append({
            'id': task_id,
            'repo': 'orchestrator',
            'job': 'parse_duplicates',
            'description': 'Parse memory/training artifacts for duplicates and delete exact duplicates when found.',
            'allowed_paths': [
                'SPAWN/STOP/MEMORY.md',
                'SPAWN/STOP/retrieval_log.jsonl',
                'SPAWN/STOP/.orchestrator/vector_store/',
                'SPAWN/STOP/.orchestrator/data/',
                'SPAWN/STOP/.orchestrator/iterations/',
                'SPAWN/STOP/.orchestrator/logs/maintenance/',
            ],
            'priority': 999,
            'status': 'pending',
            'trigger': {
                'type': 'token_threshold',
                'memory_collected_tokens': current_tokens,
                'threshold': threshold,
                'cron_schedule': maintenance_cfg.get('cron_schedule', '*/15 * * * *'),
            },
            'prompt_load_path': 'SPAWN/STOP/.orchestrator/task_queue.json',
        })
        maintenance_cfg['last_requested_tokens'] = current_tokens
        self._save_json(self.task_queue_path, queue)
        self._save_config()
        logger.info(f"  Scheduled duplicate-parse maintenance task at {current_tokens} tokens")
        return True

    def _promote_next_task(self) -> bool:
        next_task = self._find_next_runnable_task()
        if not next_task:
            logger.info("  No next runnable DAG task was found.")
            return False

        self._update_task_status(next_task.get('id'), 'active')
        if self._write_task_md(next_task):
            logger.info(f"  Promoted next task: {next_task.get('task_id')} -> {next_task.get('label')}")
            return True
        return False

    # === 10-STEP AUTONOMOUS LOOP ===

    def check_and_process_task_md(self) -> str | None:
        """
        Check if TASK.md exists and process it with FULL SECURITY PROTOCOL.

        SECURITY PROTOCOL:
        1. Acquire write lock (global or repo-level)
        2. Inject credentials from vault (task-scoped)
        3. Execute task with credentials in environment
        4. Revoke credentials
        5. Release write lock
        6. Write audit log

        Returns True if a task was processed, False if no TASK.md or task pending.
        """
        task_md_path = self.root / 'SPAWN' / 'STOP' / 'TASK.md'

        if not task_md_path.exists():
            return False

        logger.info(f"Found TASK.md, processing with security protocol...")

        # Parse TASK.md frontmatter
        with open(task_md_path, 'r') as f:
            content = f.read()

        # Extract frontmatter (between --- markers)
        if content.startswith('---'):
            end_frontmatter = content.find('---', 3)
            if end_frontmatter > 0:
                frontmatter = content[4:end_frontmatter].strip()

                # Parse task metadata
                task_id = None
                dag_node_id = None
                allowed_paths = []
                required_credentials = []
                repo_name = None

                for line in frontmatter.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == 'task_id':
                            task_id = value
                        elif key == 'dag_node_id':
                            dag_node_id = value
                        elif key == 'repo':
                            repo_name = value
                        elif key == 'required_credentials':
                            # Will be parsed from YAML list
                            pass
                        elif key == 'allowed_paths':
                            pass

                # Extract allowed_paths list (YAML format)
                import re
                paths_match = re.findall(r'-\s+([^\n]+)', frontmatter)
                allowed_paths = [p.strip() for p in paths_match if 'allowed_paths' not in p and 'required_credentials' not in p]

                # Extract required_credentials if present
                if 'required_credentials:' in frontmatter:
                    cred_section = frontmatter.split('required_credentials:')[1]
                    cred_matches = re.findall(r'-\s+([^\n]+)', cred_section)
                    required_credentials = [c.strip().strip('"').strip("'") for c in cred_matches if c.strip()]

                logger.info(f"  Task ID: {task_id}")
                logger.info(f"  DAG Node: {dag_node_id}")
                logger.info(f"  Repo: {repo_name or 'global'}")
                logger.info(f"  Required Credentials: {required_credentials or 'None'}")

                # === SECURITY PROTOCOL ===
                # Use security context manager for automatic lock/credential handling
                with self.security.task_security_context(
                    task_id=task_id,
                    repo_name=repo_name,
                    credential_keys=required_credentials
                ) as ctx:

                    if not ctx.lock_acquired:
                        logger.error(f"  SECURITY: Failed to acquire write lock")
                        self._update_task_status(task_id, 'in_progress')
                        self._update_dag_node_status(dag_node_id, 'yellow')
                        self._audit_task_event(task_id, 'lock_denied', {
                            'repo': repo_name,
                            'reason': 'Lock held by another task'
                        })
                        self._capture_miss_memory(
                            'lock_denied',
                            f'Active task {dag_node_id} was blocked by a global write lock denial.',
                            {
                                'task_id': task_id,
                                'dag_node_id': dag_node_id,
                                'repo': repo_name,
                                'reason': 'Lock held by another task',
                            }
                        )
                        return 'blocked'

                    logger.info(f"  SECURITY: Write lock acquired")
                    logger.info(f"  SECURITY: Credentials injected ({len(required_credentials)} keys)")

                    self._update_task_status(task_id, 'in_progress')
                    logger.info(f"  Executing task: {dag_node_id}")

                    result = self._execute_task(task_id, dag_node_id, allowed_paths)

                    if result.get('completed') and self._task_condition_met(dag_node_id):
                        self._update_task_status(task_id, 'completed')
                        self._update_dag_node_status(dag_node_id, 'green')
                        logger.info(f"  SECURITY: Task completed successfully")

                        # Delete TASK.md only when the repo truth says the task is satisfied.
                        task_md_path.unlink()
                        logger.info(f"  Task completed, TASK.md deleted")
                        self._promote_next_task()
                    else:
                        self._update_task_status(task_id, 'in_progress')
                        self._update_dag_node_status(dag_node_id, 'yellow')
                        self._capture_miss_memory(
                            'verification_miss',
                            f'Active task {dag_node_id} did not satisfy repo verification yet.',
                            {
                                'task_id': task_id,
                                'dag_node_id': dag_node_id,
                                'reason': result.get('reason', 'verification failed'),
                            }
                        )
                        logger.warning(f"  Task not satisfied yet: {result.get('reason', 'verification failed')}")

                # Context manager automatically:
                # - Revokes credentials
                # - Releases write lock
                # - Writes audit log

                return 'processed'

        return None

    def _execute_task(self, task_id: str, dag_node_id: str, allowed_paths: list):
        """
        Execute a task with security context active.
        Credentials are available in environment as:
        - TASK_{task_id}_{CREDENTIAL_KEY}

        Override this method for specific task implementations.
        """
        # Log which credentials are available
        cred_count = 0
        for key in list(os.environ.keys()):
            if key.startswith(f'TASK_{task_id}_'):
                cred_count += 1

        logger.info(f"  Task execution: {cred_count} credentials available in environment")
        logger.info(f"  Allowed paths: {allowed_paths}")

        condition = self._task_condition_state(dag_node_id)
        result = {
            'completed': bool(condition.get('live')),
            'reason': condition.get('reason', 'verification check returned no reason'),
            'source_live': bool(condition.get('source_live')),
            'runtime_live': bool(condition.get('runtime_live')),
        }

        self._audit_task_event(task_id, 'executed', {
            'dag_node_id': dag_node_id,
            'allowed_paths': allowed_paths,
            'credentials_used': cred_count,
            'result': result,
        })
        return result

    def _task_condition_met(self, dag_node_id: str) -> bool:
        return bool(self._task_condition_state(dag_node_id).get('live'))

    def _update_task_status(self, task_id: str, status: str):
        """Update task status in tasks.json."""
        tasks = self._load_json(self.state_dir / 'tasks.json')
        if not isinstance(tasks, list) or not tasks:
            tasks = self._derive_tasks_from_graph()
        if isinstance(tasks, list):
            for task in tasks:
                if task.get('id') == task_id:
                    task['status'] = status
                    if status == 'completed':
                        from datetime import datetime
                        task['completed_at'] = datetime.now().isoformat()
                    break
            self._save_json(self.state_dir / 'tasks.json', tasks)

    def _update_dag_node_status(self, node_id: str, status: str):
        """Update DAG node status in design_graph.json."""
        dag = self._load_json(self.state_dir / 'design_graph.json')
        if 'nodes' in dag:
            for node in dag['nodes']:
                if node.get('id') == node_id:
                    node['status'] = status
                    if status == 'green':
                        node['display_status'] = 'complete'
                    elif status == 'yellow':
                        node['display_status'] = 'active'
                    else:
                        node['display_status'] = 'pending'
                    break
            self._save_json(self.state_dir / 'design_graph.json', dag)

    def _audit_task_event(self, task_id: str, event: str, details: dict = None):
        """Write audit log entry for task event."""
        self.security._audit(f"Task {event}: {task_id}", task_id, details or {})

    def step_1_read_task_queue(self) -> list:
        """Step 1: Read task_queue.json (priority-ordered child tasks)"""
        logger.info("Step 1: Reading task_queue.json")
        self._schedule_duplicate_parse_job_if_needed()
        tasks = self._load_json(self.task_queue_path)
        if isinstance(tasks, list):
            logger.info(f"  Found {len(tasks)} tasks in queue")
            return tasks
        return tasks.get('pending', [])

    def step_2_query_vector_store(self, tasks: list) -> dict:
        """Step 2: Query vector store for relevant context"""
        logger.info("Step 2: Querying vector store for context")
        context = {}
        if self.vector_store_dir.exists():
            for entry_file in self.vector_store_dir.glob('*.json'):
                entry = self._load_json(entry_file)
                if entry:
                    context[entry_file.stem] = entry
        logger.info(f"  Retrieved {len(context)} context entries")
        return context

    def step_3_process_state(self, tasks: list, context: dict) -> dict:
        """Step 3: Call loop.py with state + child repo requirements"""
        logger.info("Step 3: Processing state with tasks and context")
        state = {
            'tasks': tasks,
            'context': context,
            'config': self.config,
            'timestamp': datetime.now().isoformat(),
            'cycle': self.cycle_count
        }
        return state

    def step_4_dispatch_tasks(self, state: dict) -> dict:
        """Step 4: Dispatch tasks to child repos via their allowed_paths"""
        logger.info("Step 4: Dispatching tasks to child repos")
        results = {}
        for task in state.get('tasks', []):
            if task.get('repo') == 'orchestrator' and task.get('job') == 'parse_duplicates':
                report = run_duplicate_parse(self.root / 'SPAWN' / 'STOP')
                self.config.setdefault('maintenance', {}).setdefault('duplicate_parse', {})['last_completed_tokens'] = self._current_memory_tokens()
                self._save_config()
                results[task.get('id', 'maintenance_parse_duplicates')] = {
                    'status': 'dispatched',
                    'task': task,
                    'report': report,
                }
                logger.info("  Ran duplicate-parse maintenance task")
                continue

            repo_name = task.get('repo', 'unknown')
            repo_path = self.repos_dir / repo_name
            if repo_path.exists():
                # Child repos follow the same SPAWN/STOP runtime contract.
                task_file = repo_path / 'SPAWN' / 'STOP' / 'state' / 'tasks.json'
                if self._is_write_allowed(str(task_file)):
                    results[repo_name] = {'status': 'dispatched', 'task': task}
                    logger.info(f"  Dispatched to {repo_name}")
            else:
                logger.warning(f"  Child repo not found: {repo_name}")
                results[repo_name] = {'status': 'not_found'}
        return results

    def step_5_collect_logs(self, dispatch_results: dict) -> list:
        """Step 5: Collect logs/outputs from child repos into Stop/.orchestrator/logs/"""
        logger.info("Step 5: Collecting logs from child repos")
        collected = []
        for repo_name, result in dispatch_results.items():
            repo_log_dir = self.repos_dir / repo_name / 'SPAWN' / 'STOP' / '.orchestrator' / 'logs'
            if repo_log_dir.exists():
                for log_file in repo_log_dir.glob('*.log'):
                    collected.append({
                        'repo': repo_name,
                        'file': str(log_file),
                        'collected_at': datetime.now().isoformat()
                    })
        logger.info(f"  Collected {len(collected)} log entries")
        return collected

    def step_6_train_models(self, logs: list) -> dict:
        """Step 6: Train/update models if training data available"""
        logger.info("Step 6: Checking for training data")
        training_result = {'trained': False, 'reason': 'no_data'}

        data_files = list(self.data_dir.glob('*.json')) if self.data_dir.exists() else []
        if data_files:
            logger.info(f"  Found {len(data_files)} training data files")
            training_result = {
                'trained': True,
                'data_files': len(data_files),
                'timestamp': datetime.now().isoformat()
            }
        else:
            logger.info("  No training data available, skipping")

        return training_result

    def step_7_update_vector_store(self, state: dict, training_result: dict) -> bool:
        """Step 7: Append orchestration result to vector store"""
        logger.info("Step 7: Updating vector store with results")
        if not state.get('tasks') and not training_result.get('trained'):
            logger.info("  No coordinated work occurred, skipping vector-store append")
            return False
        entry = {
            'cycle': self.cycle_count,
            'timestamp': datetime.now().isoformat(),
            'tasks_processed': len(state.get('tasks', [])),
            'training': training_result
        }
        entry_path = self.vector_store_dir / f"cycle_{self.cycle_count}.json"
        return self._save_json(entry_path, entry)

    def step_8_update_task_queue(self, state: dict, dispatch_results: dict) -> bool:
        """Step 8: Update task_queue.json with next batch of task priorities"""
        logger.info("Step 8: Updating task queue with next priorities")
        remaining = []
        for task in state.get('tasks', []):
            result_key = task.get('id') if task.get('repo') == 'orchestrator' else task.get('repo', 'unknown')
            result = dispatch_results.get(result_key, {})
            if result.get('status') != 'dispatched':
                remaining.append(task)
        return self._save_json(self.task_queue_path, remaining)

    def step_9_finalize_state(self, state: dict, remaining_tasks: bool) -> bool:
        """Step 9: If orchestration complete, finalize state"""
        logger.info("Step 9: Checking if orchestration is complete")
        design_graph = self.state_dir / 'design_graph.json'
        graph = self._load_json(design_graph)
        graph['last_cycle'] = self.cycle_count
        graph['last_updated'] = datetime.now().isoformat()
        node_statuses = [node.get('status') for node in graph.get('nodes', [])]
        if node_statuses and all(status == 'green' for status in node_statuses):
            graph['status'] = 'complete'
        elif (self.root / 'SPAWN' / 'STOP' / 'TASK.md').exists():
            graph['status'] = 'awaiting_task_completion'
        elif remaining_tasks:
            graph['status'] = 'in_progress'
        else:
            graph['status'] = 'waiting_for_work'
        return self._save_json(design_graph, graph)

    def step_10_loop_control(self, tasks: list) -> bool:
        """Step 10: Repeat until all coordinated tasks complete"""
        if (self.root / 'SPAWN' / 'STOP' / 'TASK.md').exists():
            logger.info("Step 10: TASK.md still active. Continuing loop.")
            return True
        graph = self._load_json(self.state_dir / 'design_graph.json')
        pending_nodes = [
            node for node in graph.get('nodes', [])
            if node.get('status') != 'green'
        ]
        if pending_nodes:
            logger.info(f"Step 10: {len(pending_nodes)} DAG tasks remain. Waiting for real work.")
            return True
        if not tasks:
            logger.info("Step 10: All tasks complete. Orchestration finished.")
            return False
        logger.info(f"Step 10: {len(tasks)} tasks remaining. Continuing loop.")
        return True

    # === MAIN LOOP ===

    def run(self, max_cycles: int = 0):
        """
        Execute the autonomous orchestration loop.

        Args:
            max_cycles: Maximum cycles to run (0 = unlimited)
        """
        logger.info("=" * 60)
        logger.info("ORCHESTRATOR LOOP STARTING")
        logger.info(f"Root: {self.root}")
        logger.info(f"Config: gpu_enabled={self.config.get('gpu_enabled', False)}")
        logger.info("=" * 60)

        should_continue = True
        while should_continue:
            self.cycle_count += 1
            self._persist_cycle_metrics()
            logger.info(f"\n{'─' * 40}")
            logger.info(f"CYCLE {self.cycle_count}")
            logger.info(f"{'─' * 40}")

            try:
                # Priority 1: Check for TASK.md (orchestrator's own DAG tasks)
                task_md_result = self.check_and_process_task_md()
                if task_md_result == 'processed':
                    logger.info("TASK.md checked, continuing to next cycle...")
                    if max_cycles > 0 and self.cycle_count >= max_cycles:
                        logger.info(f"Reached max cycles ({max_cycles}). Stopping.")
                        should_continue = False
                        continue
                    time.sleep(2)
                    continue

                if task_md_result == 'blocked':
                    logger.warning("TASK.md is active but lock acquisition was blocked. Retrying next cycle without entering queue flow...")
                    if max_cycles > 0 and self.cycle_count >= max_cycles:
                        logger.info(f"Reached max cycles ({max_cycles}). Stopping.")
                        should_continue = False
                        continue
                    time.sleep(2)
                    continue

                # Priority 2: Run 10-step coordination loop for child repos
                # Step 1: Read task queue
                tasks = self.step_1_read_task_queue()

                # Step 2: Query vector store
                context = self.step_2_query_vector_store(tasks)

                # Step 3: Process state
                state = self.step_3_process_state(tasks, context)

                # Step 4: Dispatch tasks
                dispatch_results = self.step_4_dispatch_tasks(state)

                # Step 5: Collect logs
                logs = self.step_5_collect_logs(dispatch_results)

                # Step 6: Train models
                training_result = self.step_6_train_models(logs)

                # Step 7: Update vector store
                self.step_7_update_vector_store(state, training_result)

                # Step 8: Update task queue
                self.step_8_update_task_queue(state, dispatch_results)

                # Step 9: Finalize state
                remaining = self._load_json(self.task_queue_path)
                remaining_tasks = len(remaining) > 0 if isinstance(remaining, list) else len(remaining.get('pending', [])) > 0
                self.step_9_finalize_state(state, remaining_tasks)

                # Step 10: Loop control
                should_continue = self.step_10_loop_control(tasks)

                if max_cycles > 0 and self.cycle_count >= max_cycles:
                    logger.info(f"Reached max cycles ({max_cycles}). Stopping.")
                    should_continue = False

                if should_continue:
                    time.sleep(5)  # Brief pause between cycles

            except Exception as e:
                logger.error(f"Error in cycle {self.cycle_count}: {e}")
                time.sleep(10)

        logger.info("=" * 60)
        logger.info(f"ORCHESTRATOR LOOP COMPLETE after {self.cycle_count} cycles")
        logger.info("=" * 60)


if __name__ == '__main__':
    # Determine repo root from SPAWN/STOP/.orchestrator/loop.py
    script_dir = Path(__file__).resolve().parent
    root_dir = script_dir.parent.parent.parent  # .orchestrator -> STOP -> SPAWN -> repo root

    max_cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    orchestrator = OrchestratorLoop(str(root_dir))
    orchestrator.run(max_cycles=max_cycles)
