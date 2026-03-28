#!/usr/bin/env python3
"""
LLM Iteration Logger
Automatically logs all LLM interactions for training data collection.

This module captures prompts, responses, errors, corrections, and design decisions
from all LLM interactions within the orchestrator system.
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path


class IterationLogger:
    """
    Logs LLM iterations to structured JSON files for training data collection.

    Usage:
        logger = IterationLogger(orchestrator_dir=Path("/path/to/orchestrator"))

        # Log a complete iteration
        logger.log_iteration(
            task_id="task_001",
            dag_node_id="setup_flask_app",
            prompt={"system": "...", "user": "..."},
            response={"content": "..."},
            outcome={"status": "success", "files_created": ["app.py"]},
            metadata={"model": "deepseek-coder-6.7b", "duration_ms": 1234}
        )

        # Log an error and correction
        logger.log_error(
            parent_iteration="iter_20260327_143052_001",
            error={"type": "SyntaxError", "message": "..."},
            correction_prompt={"system": "...", "user": "..."},
            correction_response={"content": "..."},
            resolution={"status": "resolved"}
        )

        # Log a design decision
        logger.log_decision(
            task_id="task_004",
            dag_node_id="build_dashboard_frontend",
            decision={"question": "...", "options": [...], "chosen": "B"},
            outcome={"result": "success", "lesson": "..."}
        )
    """

    def __init__(self, orchestrator_dir: Path = None):
        """
        Initialize the iteration logger.

        Args:
            orchestrator_dir: Path to the orchestrator root directory.
                             Defaults to detecting from environment or current location.
        """
        if orchestrator_dir is None:
            # Try to detect from environment
            env_dir = os.environ.get('ORCHESTRATOR_HOME')
            if env_dir:
                orchestrator_dir = Path(env_dir)
            else:
                # Default: SPAWN/STOP is the runtime directory
                # iteration_logger.py is at: SPAWN/STOP/.orchestrator/iteration_logger.py
                orchestrator_dir = Path(__file__).resolve().parent.parent.parent

        self.orchestrator_dir = Path(orchestrator_dir)
        self.iterations_dir = self.orchestrator_dir / 'STOP' / '.orchestrator' / 'iterations'
        self.errors_dir = self.iterations_dir / 'errors'
        self.decisions_dir = self.iterations_dir / 'decisions'

        # Ensure directories exist
        for dir_path in [self.iterations_dir, self.errors_dir, self.decisions_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        self._log_file = self.orchestrator_dir / '.orchestrator' / 'logs' / 'iteration_logger.log'

    def _log(self, message: str, level: str = 'INFO'):
        """Write to logger log file."""
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] [{level}] {message}\n"

        try:
            with open(self._log_file, 'a') as f:
                f.write(log_entry)
        except IOError:
            pass  # Silently fail if can't write log

    def log_iteration(self,
                      task_id: str,
                      dag_node_id: str,
                      prompt: dict,
                      response: dict,
                      outcome: dict,
                      metadata: dict = None) -> str:
        """
        Log a complete LLM iteration.

        Args:
            task_id: Unique task identifier
            dag_node_id: DAG node being executed
            prompt: Dict with 'system', 'user', 'context' keys
            response: Dict with 'content', 'tokens_used', etc.
            outcome: Dict with 'status', 'files_created', 'errors'
            metadata: Optional dict with model info, timing, etc.

        Returns:
            iteration_id: Unique identifier for this iteration
        """
        iteration_id = f"iter_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

        iteration = {
            'iteration_id': iteration_id,
            'timestamp': datetime.now().isoformat(),
            'task_id': task_id,
            'dag_node_id': dag_node_id,
            'agent': 'orchestrator',
            'llm_model': metadata.get('model', 'unknown') if metadata else 'unknown',
            'prompt': prompt,
            'response': response,
            'outcome': outcome,
            'metadata': metadata or {}
        }

        file_path = self.iterations_dir / f"{iteration_id}.json"

        try:
            with open(file_path, 'w') as f:
                json.dump(iteration, f, indent=2, default=str)

            self._log(f"Logged iteration {iteration_id} for task {task_id}")
            return iteration_id

        except IOError as e:
            self._log(f"Failed to log iteration: {e}", 'ERROR')
            return None

    def log_error(self,
                  parent_iteration: str,
                  error: dict,
                  correction_prompt: dict,
                  correction_response: dict,
                  resolution: dict) -> str:
        """
        Log an error and correction cycle.

        Args:
            parent_iteration: ID of the original iteration that produced the error
            error: Dict with 'type', 'message', 'traceback'
            correction_prompt: Dict with prompt used for correction
            correction_response: Dict with corrected response
            resolution: Dict with 'status', 'corrections_applied'

        Returns:
            error_id: Unique identifier for this error log
        """
        error_id = f"err_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

        error_log = {
            'error_id': error_id,
            'timestamp': datetime.now().isoformat(),
            'parent_iteration': parent_iteration,
            'error': error,
            'correction_prompt': correction_prompt,
            'correction_response': correction_response,
            'resolution': resolution
        }

        file_path = self.errors_dir / f"{error_id}.json"

        try:
            with open(file_path, 'w') as f:
                json.dump(error_log, f, indent=2, default=str)

            self._log(f"Logged error {error_id} for parent {parent_iteration}")
            return error_id

        except IOError as e:
            self._log(f"Failed to log error: {e}", 'ERROR')
            return None

    def log_decision(self,
                     task_id: str,
                     dag_node_id: str,
                     decision: dict,
                     outcome: dict) -> str:
        """
        Log a design decision.

        Args:
            task_id: Task associated with this decision
            dag_node_id: DAG node where decision was made
            decision: Dict with 'question', 'options', 'chosen', 'rationale'
            outcome: Dict with 'result', 'lesson'

        Returns:
            decision_id: Unique identifier for this decision log
        """
        decision_id = f"dec_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

        decision_log = {
            'decision_id': decision_id,
            'timestamp': datetime.now().isoformat(),
            'task_id': task_id,
            'dag_node_id': dag_node_id,
            'decision': decision,
            'outcome': outcome
        }

        file_path = self.decisions_dir / f"{decision_id}.json"

        try:
            with open(file_path, 'w') as f:
                json.dump(decision_log, f, indent=2, default=str)

            self._log(f"Logged decision {decision_id} for task {task_id}")
            return decision_id

        except IOError as e:
            self._log(f"Failed to log decision: {e}", 'ERROR')
            return None

    def get_iteration_count(self) -> int:
        """Count total logged iterations."""
        try:
            return len(list(self.iterations_dir.glob('*.json')))
        except:
            return 0

    def get_error_count(self) -> int:
        """Count total logged errors."""
        try:
            return len(list(self.errors_dir.glob('*.json')))
        except:
            return 0

    def get_decision_count(self) -> int:
        """Count total logged decisions."""
        try:
            return len(list(self.decisions_dir.glob('*.json')))
        except:
            return 0

    def get_summary(self) -> dict:
        """Get summary of all logged data."""
        return {
            'iterations': self.get_iteration_count(),
            'errors': self.get_error_count(),
            'decisions': self.get_decision_count(),
            'timestamp': datetime.now().isoformat()
        }


# Convenience function for quick logging
def log_llm_interaction(task_id: str,
                        prompt: str,
                        response: str,
                        status: str = 'success',
                        model: str = 'unknown',
                        orchestrator_dir: Path = None) -> str:
    """
    Quick log an LLM interaction with minimal parameters.

    Args:
        task_id: Task identifier
        prompt: User prompt text
        response: LLM response text
        status: 'success' or 'failed'
        model: Model name used
        orchestrator_dir: Path to orchestrator directory

    Returns:
        iteration_id if successful, None otherwise
    """
    logger = IterationLogger(orchestrator_dir)

    return logger.log_iteration(
        task_id=task_id,
        dag_node_id='quick_log',
        prompt={'system': 'You are a helpful assistant.', 'user': prompt},
        response={'content': response, 'tokens_used': len(response.split())},
        outcome={'status': status, 'files_created': [], 'errors': []},
        metadata={'model': model, 'quick_log': True}
    )


if __name__ == '__main__':
    # Test the logger
    print("Testing IterationLogger...")

    logger = IterationLogger()

    # Test iteration logging
    iteration_id = logger.log_iteration(
        task_id='test_001',
        dag_node_id='test_node',
        prompt={'system': 'Test system', 'user': 'Test prompt'},
        response={'content': 'Test response', 'tokens_used': 10},
        outcome={'status': 'success', 'files_created': ['test.txt'], 'errors': []},
        metadata={'model': 'test-model', 'duration_ms': 100}
    )

    print(f"Logged iteration: {iteration_id}")

    # Test decision logging
    decision_id = logger.log_decision(
        task_id='test_001',
        dag_node_id='test_node',
        decision={
            'question': 'Test decision?',
            'options': [{'id': 'A', 'description': 'Option A'}],
            'chosen': 'A',
            'rationale': 'Test rationale'
        },
        outcome={'result': 'success', 'lesson': 'Test lesson'}
    )

    print(f"Logged decision: {decision_id}")

    # Print summary
    summary = logger.get_summary()
    print(f"\nSummary: {json.dumps(summary, indent=2)}")

    print("\n✅ IterationLogger test complete!")
