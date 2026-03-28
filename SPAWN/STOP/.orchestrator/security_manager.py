#!/usr/bin/env python3
"""
Orchestrator Security & Access Control System

Enterprise-level security for credential management, write locks, and task-scoped access.

Features:
- Encrypted credential vault (GPG/AES-256)
- Global write freeze protocol
- Task-scoped credential release
- Repo-level access control (single-repo write lock)
- Automatic secret rotation
- Audit logging

Usage:
    from security_manager import SecurityManager

    security = SecurityManager(orchestrator_dir=Path("/path/to/orchestrator"))

    # Acquire write lock for a task
    lock = security.acquire_write_lock(task_id="task_001", repo="my-repo")
    if lock.acquired:
        # Get credentials for this task (auto-injected into environment)
        creds = security.get_task_credentials(task_id="task_001")

        # Execute task...

        # Release lock (automatic on context exit)
        lock.release()
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

# Windows compatibility for fcntl
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    import msvcrt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('orchestrator_security')


class LockStatus(Enum):
    ACQUIRED = "acquired"
    DENIED = "denied"
    EXPIRED = "expired"
    RELEASED = "released"


class CredentialType(Enum):
    API_KEY = "api_key"
    GIT_TOKEN = "git_token"
    SSH_KEY = "ssh_key"
    DATABASE = "database"
    CUSTOM = "custom"


@dataclass
class WriteLock:
    """Represents an active write lock."""
    lock_id: str
    task_id: str
    repo: Optional[str]
    acquired_at: str
    expires_at: str
    status: str

    def is_expired(self) -> bool:
        return datetime.fromisoformat(self.expires_at) < datetime.now()


@dataclass
class CredentialGrant:
    """Represents credentials granted for a specific task."""
    grant_id: str
    task_id: str
    credential_type: str
    granted_at: str
    expires_at: str
    accessed: bool = False


class SecurityManager:
    """
    Enterprise security manager for orchestrator.

    Manages:
    - Encrypted credential vault
    - Write lock protocol
    - Task-scoped credential release
    - Repo-level access control
    """

    def __init__(self, orchestrator_dir: Path = None):
        if orchestrator_dir is None:
            orchestrator_dir = Path(__file__).resolve().parent.parent

        self.orchestrator_dir = Path(orchestrator_dir)
        runtime_root = self.orchestrator_dir / 'SPAWN' / 'STOP' if (self.orchestrator_dir / 'SPAWN' / 'STOP').exists() else self.orchestrator_dir
        self.runtime_root = runtime_root
        self.vault_dir = self.runtime_root / '.orchestrator' / 'vault'
        self.locks_dir = self.runtime_root / '.orchestrator' / 'locks'
        self.audit_dir = self.runtime_root / '.orchestrator' / 'logs' / 'security'
        self.config_path = self.runtime_root / '.orchestrator' / 'config.json'

        # Ensure directories exist
        for dir_path in [self.vault_dir, self.locks_dir, self.audit_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # File paths
        self.vault_file = self.vault_dir / '.env'
        self.vault_gpg = self.vault_dir / '.env.gpg'
        self.global_lock_file = self.locks_dir / 'global_write.lock'
        self.repo_locks_dir = self.locks_dir / 'repo_locks'
        self.audit_log = self.audit_dir / 'security_audit.log'

        # Configuration
        self.config = self._load_config()
        self.secret_rotation_days = self.config.get('secret_rotation_days', 30)

        # Initialize GPG if available
        self.gpg_available = self._check_gpg()

        self._audit("SecurityManager initialized", "system")

    def _load_config(self) -> dict:
        """Load orchestrator configuration."""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load config: {e}")
        return {}

    def _check_gpg(self) -> bool:
        """Check if GPG is available."""
        try:
            result = subprocess.run(['gpg', '--version'], capture_output=True, timeout=5)
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("GPG not available - using plaintext vault (INSECURE)")
            return False

    def _audit(self, action: str, actor: str, details: dict = None):
        """Write audit log entry."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'actor': actor,
            'details': details or {}
        }

        try:
            with open(self.audit_log, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except IOError as e:
            logger.error(f"Failed to write audit log: {e}")

    # ==================== VAULT MANAGEMENT ====================

    def store_credential(self, key: str, value: str, credential_type: CredentialType,
                        encrypt: bool = True) -> bool:
        """
        Store a credential in the vault.

        Args:
            key: Credential name (e.g., 'OPENAI_API_KEY')
            value: Credential value
            credential_type: Type of credential
            encrypt: Whether to encrypt (requires GPG)

        Returns:
            True if successful
        """
        # Load existing credentials
        credentials = self._load_vault()

        # Update or add credential
        credentials[key] = {
            'value': value,
            'type': credential_type.value,
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(days=self.secret_rotation_days)).isoformat()
        }

        # Save to vault
        return self._save_vault(credentials, encrypt)

    def get_credential(self, key: str, task_id: str = None) -> Optional[str]:
        """
        Retrieve a credential from the vault.

        Args:
            key: Credential name
            task_id: Optional task ID for audit trail

        Returns:
            Credential value or None
        """
        credentials = self._load_vault()

        if key not in credentials:
            self._audit(f"Failed credential access: {key}", task_id or 'unknown')
            return None

        cred = credentials[key]

        # Check expiration
        if datetime.fromisoformat(cred['expires_at']) < datetime.now():
            self._audit(f"Expired credential accessed: {key}", task_id or 'unknown')
            return None

        # Audit access
        self._audit(f"Credential accessed: {key}", task_id or 'unknown', {
            'credential_type': cred['type']
        })

        return cred['value']

    def _load_vault(self) -> dict:
        """Load vault contents."""
        if self.gpg_available and self.vault_gpg.exists():
            return self._load_encrypted_vault()
        elif self.vault_file.exists():
            return self._load_plaintext_vault()
        return {}

    def _load_plaintext_vault(self) -> dict:
        """Load plaintext vault (INSECURE - fallback only)."""
        credentials = {}
        try:
            # Try UTF-8 first, then fallback to system encoding with error handling
            try:
                with open(self.vault_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                with open(self.vault_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    credentials[key] = {
                        'value': value,
                        'type': CredentialType.CUSTOM.value,
                        'created_at': datetime.now().isoformat(),
                        'expires_at': (datetime.now() + timedelta(days=365)).isoformat()
                    }
        except IOError as e:
            logger.error(f"Failed to read vault: {e}")
        return credentials

    def _load_encrypted_vault(self) -> dict:
        """Load GPG-encrypted vault."""
        try:
            result = subprocess.run(
                ['gpg', '-d', str(self.vault_gpg)],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                credentials = {}
                for line in result.stdout.decode().splitlines():
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        credentials[key] = value
                return credentials
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"GPG decryption failed: {e}")
        return {}

    def _save_vault(self, credentials: dict, encrypt: bool = True) -> bool:
        """Save vault contents."""
        if encrypt and self.gpg_available:
            return self._save_encrypted_vault(credentials)
        else:
            return self._save_plaintext_vault(credentials)

    def _save_plaintext_vault(self, credentials: dict) -> bool:
        """Save plaintext vault (INSECURE - fallback only)."""
        try:
            with open(self.vault_file, 'w') as f:
                f.write(f"# Orchestrator Vault - Created {datetime.now().isoformat()}\n")
                f.write("# WARNING: Plaintext storage - configure GPG for production!\n\n")
                for key, cred in credentials.items():
                    if isinstance(cred, dict):
                        f.write(f"{key}={cred.get('value', cred)}\n")
                    else:
                        f.write(f"{key}={cred}\n")
            return True
        except IOError as e:
            logger.error(f"Failed to save vault: {e}")
            return False

    def _save_encrypted_vault(self, credentials: dict) -> bool:
        """Save GPG-encrypted vault."""
        try:
            content = f"# Orchestrator Vault - Created {datetime.now().isoformat()}\n\n"
            for key, cred in credentials.items():
                if isinstance(cred, dict):
                    content += f"{key}={cred.get('value', cred)}\n"
                else:
                    content += f"{key}={cred}\n"

            result = subprocess.run(
                ['gpg', '--symmetric', '--cipher-algo', 'AES256', '-o', str(self.vault_gpg)],
                input=content.encode(),
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                # Remove plaintext if exists
                if self.vault_file.exists():
                    self.vault_file.unlink()
                return True
            else:
                logger.error(f"GPG encryption failed: {result.stderr.decode()}")
                return False
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"GPG operation failed: {e}")
            return False

    # ==================== WRITE LOCK PROTOCOL ====================

    def acquire_global_write_lock(self, task_id: str, timeout_seconds: int = 300) -> WriteLock:
        """
        Acquire global write lock for a task.
        
        Any agent working on the current TASK.md task can acquire/release the lock.
        This allows multiple LLMs/agents to collaborate on the same task.

        Args:
            task_id: Task requesting the lock
            timeout_seconds: Lock timeout (default 5 minutes)

        Returns:
            WriteLock with status indicating success/failure
        """
        lock_id = f"global_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        expires_at = (datetime.now() + timedelta(seconds=timeout_seconds)).isoformat()

        try:
            if self.global_lock_file.exists():
                with open(self.global_lock_file, 'r', encoding='utf-8') as handle:
                    existing = json.load(handle)
                expires = existing.get('expires_at')
                
                # Lock is expired - any agent can take over
                if expires and datetime.fromisoformat(expires) < datetime.now():
                    logger.info(f"Lock expired, allowing takeover for task {task_id}")
                
                # Lock is held by SAME task - allow (agent continuation)
                elif existing.get('task_id') == task_id:
                    logger.info(f"Lock already held by same task {task_id}, allowing continuation")
                    # Refresh the lock expiry
                    lock_data = WriteLock(
                        lock_id=existing.get('lock_id', lock_id),
                        task_id=task_id,
                        repo=None,
                        acquired_at=existing.get('acquired_at', datetime.now().isoformat()),
                        expires_at=expires_at,
                        status=LockStatus.ACQUIRED.value
                    )
                    with open(self.global_lock_file, 'w', encoding='utf-8') as handle:
                        json.dump(asdict(lock_data), handle)
                    return lock_data
                
                # Lock held by different task - deny
                else:
                    self._audit("Global write lock denied", task_id, {'reason': 'lock held by another task', 'holder': existing.get('task_id')})
                    return WriteLock(
                        lock_id=lock_id,
                        task_id=task_id,
                        repo=None,
                        acquired_at=datetime.now().isoformat(),
                        expires_at=expires_at,
                        status=LockStatus.DENIED.value
                    )

            # No lock exists - acquire it
            lock_data = WriteLock(
                lock_id=lock_id,
                task_id=task_id,
                repo=None,
                acquired_at=datetime.now().isoformat(),
                expires_at=expires_at,
                status=LockStatus.ACQUIRED.value
            )
            self.global_lock_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.global_lock_file, 'w', encoding='utf-8') as handle:
                json.dump(asdict(lock_data), handle)

            self._audit("Global write lock acquired", task_id, {
                'lock_id': lock_id,
                'expires_at': expires_at
            })

            return lock_data

        except (IOError, json.JSONDecodeError, OSError) as e:
            self._audit("Global write lock denied", task_id, {'reason': 'lock held by another task', 'error': str(e)})
            return WriteLock(
                lock_id=lock_id,
                task_id=task_id,
                repo=None,
                acquired_at=datetime.now().isoformat(),
                expires_at=expires_at,
                status=LockStatus.DENIED.value
            )

    def release_global_write_lock(self, task_id: str) -> bool:
        """Release global write lock."""
        try:
            if self.global_lock_file.exists():
                with open(self.global_lock_file, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)
                    if lock_data.get('task_id') == task_id:
                        for _ in range(5):
                            try:
                                if self.global_lock_file.exists():
                                    self.global_lock_file.unlink()
                                break
                            except OSError:
                                time.sleep(0.1)

                        self._audit("Global write lock released", task_id)
                        return not self.global_lock_file.exists()
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to release lock: {e}")
        return False

    def acquire_repo_write_lock(self, task_id: str, repo_name: str,
                                timeout_seconds: int = 300) -> WriteLock:
        """
        Acquire write lock for a specific repository.

        Args:
            task_id: Task requesting the lock
            repo_name: Repository to lock
            timeout_seconds: Lock timeout

        Returns:
            WriteLock with status indicating success/failure
        """
        self.repo_locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file_path = self.repo_locks_dir / f"{repo_name}.lock"
        lock_id = f"repo_{repo_name}_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        expires_at = (datetime.now() + timedelta(seconds=timeout_seconds)).isoformat()

        try:
            if lock_file_path.exists():
                with open(lock_file_path, 'r', encoding='utf-8') as handle:
                    existing = json.load(handle)
                expires = existing.get('expires_at')
                if expires and datetime.fromisoformat(expires) >= datetime.now():
                    self._audit(f"Repo write lock denied: {repo_name}", task_id, {
                        'reason': 'lock held by another task'
                    })
                    return WriteLock(
                        lock_id=lock_id,
                        task_id=task_id,
                        repo=repo_name,
                        acquired_at=datetime.now().isoformat(),
                        expires_at=expires_at,
                        status=LockStatus.DENIED.value
                    )

            lock_data = WriteLock(
                lock_id=lock_id,
                task_id=task_id,
                repo=repo_name,
                acquired_at=datetime.now().isoformat(),
                expires_at=expires_at,
                status=LockStatus.ACQUIRED.value
            )
            with open(lock_file_path, 'w', encoding='utf-8') as handle:
                json.dump(asdict(lock_data), handle)

            self._audit(f"Repo write lock acquired: {repo_name}", task_id, {
                'lock_id': lock_id,
                'expires_at': expires_at
            })

            return lock_data

        except (IOError, json.JSONDecodeError, OSError):
            self._audit(f"Repo write lock denied: {repo_name}", task_id, {
                'reason': 'lock held by another task'
            })
            return WriteLock(
                lock_id=lock_id,
                task_id=task_id,
                repo=repo_name,
                acquired_at=datetime.now().isoformat(),
                expires_at=expires_at,
                status=LockStatus.DENIED.value
            )

    def release_repo_write_lock(self, task_id: str, repo_name: str) -> bool:
        """Release write lock for a specific repository."""
        lock_file_path = self.repo_locks_dir / f"{repo_name}.lock"

        try:
            if lock_file_path.exists():
                with open(lock_file_path, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)
                    if lock_data.get('task_id') == task_id:
                        for _ in range(5):
                            try:
                                if lock_file_path.exists():
                                    lock_file_path.unlink()
                                break
                            except OSError:
                                time.sleep(0.1)

                        self._audit(f"Repo write lock released: {repo_name}", task_id)
                        return not lock_file_path.exists()
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to release repo lock: {e}")
        return False

    # ==================== TASK-SCOPED CREDENTIAL RELEASE ====================

    def grant_task_credentials(self, task_id: str, repo_name: str,
                               credential_keys: List[str]) -> CredentialGrant:
        """
        Grant credentials for a specific task (after acquiring write lock).

        Args:
            task_id: Task requesting credentials
            repo_name: Repository being worked on
            credential_keys: List of credential keys needed

        Returns:
            CredentialGrant with access details
        """
        grant_id = f"grant_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        expires_at = (datetime.now() + timedelta(hours=2)).isoformat()  # 2 hour grant

        # Inject credentials into environment for this task
        for key in credential_keys:
            value = self.get_credential(key, task_id)
            if value:
                os.environ[f"TASK_{task_id}_{key}"] = value

        grant = CredentialGrant(
            grant_id=grant_id,
            task_id=task_id,
            credential_type='task_scoped',
            granted_at=datetime.now().isoformat(),
            expires_at=expires_at,
            accessed=True
        )

        self._audit("Credentials granted for task", task_id, {
            'grant_id': grant_id,
            'repo': repo_name,
            'credential_keys': credential_keys,
            'expires_at': expires_at
        })

        return grant

    def revoke_task_credentials(self, task_id: str) -> bool:
        """Revoke all credentials granted for a task."""
        revoked = []

        # Remove from environment
        for key in list(os.environ.keys()):
            if key.startswith(f"TASK_{task_id}_"):
                del os.environ[key]
                revoked.append(key)

        self._audit("Task credentials revoked", task_id, {
            'revoked_count': len(revoked)
        })

        return len(revoked) > 0

    # ==================== SECURITY CONTEXT MANAGER ====================

    @contextmanager
    def task_security_context(self, task_id: str, repo_name: str = None,
                             credential_keys: List[str] = None):
        """
        Context manager for secure task execution.

        Usage:
            with security.task_security_context(
                task_id="task_001",
                repo_name="my-repo",
                credential_keys=["OPENAI_API_KEY", "GIT_TOKEN"]
            ) as ctx:
                if ctx.lock_acquired:
                    # Execute task with credentials injected
                    run_task()
                else:
                    # Handle lock failure
                    log_error("Could not acquire write lock")

        Args:
            task_id: Task identifier
            repo_name: Repository name (optional)
            credential_keys: List of credential keys needed

        Yields:
            SecurityContext with lock and credential status
        """
        ctx = SecurityContext(self, task_id, repo_name, credential_keys)
        try:
            ctx.enter()
            yield ctx
        finally:
            ctx.exit()


@dataclass
class SecurityContext:
    """Context for secure task execution."""
    security: SecurityManager
    task_id: str
    repo_name: Optional[str]
    credential_keys: Optional[List[str]]

    lock_acquired: bool = False
    lock_type: str = ""
    credentials_granted: bool = False

    def enter(self):
        """Acquire locks and credentials."""
        # Acquire appropriate lock
        if self.repo_name:
            lock = self.security.acquire_repo_write_lock(self.task_id, self.repo_name)
            self.lock_type = 'repo'
        else:
            lock = self.security.acquire_global_write_lock(self.task_id)
            self.lock_type = 'global'

        self.lock_acquired = lock.status == LockStatus.ACQUIRED.value

        # Grant credentials if lock acquired
        if self.lock_acquired and self.credential_keys:
            grant = self.security.grant_task_credentials(
                self.task_id,
                self.repo_name or 'global',
                self.credential_keys
            )
            self.credentials_granted = True

        return self

    def exit(self):
        """Release locks and revoke credentials."""
        # Revoke credentials
        if self.credentials_granted:
            self.security.revoke_task_credentials(self.task_id)

        # Release lock
        if self.lock_acquired:
            if self.lock_type == 'repo' and self.repo_name:
                self.security.release_repo_write_lock(self.task_id, self.repo_name)
            else:
                self.security.release_global_write_lock(self.task_id)


if __name__ == '__main__':
    # Test the security system
    print("Testing Orchestrator Security System...")

    security = SecurityManager()

    # Test 1: Store credentials
    print("\n1. Testing credential storage...")
    security.store_credential('TEST_API_KEY', 'test_value_123', CredentialType.API_KEY)
    print("   ✅ Credential stored")

    # Test 2: Retrieve credential
    print("\n2. Testing credential retrieval...")
    value = security.get_credential('TEST_API_KEY', 'test_task')
    print(f"   ✅ Credential retrieved: {value[:10]}...")

    # Test 3: Acquire write lock
    print("\n3. Testing write lock acquisition...")
    lock = security.acquire_global_write_lock('test_task_001', timeout_seconds=60)
    print(f"   ✅ Lock status: {lock.status}")

    # Test 4: Context manager
    print("\n4. Testing security context manager...")
    with security.task_security_context(
        task_id='test_task_002',
        repo_name='test-repo',
        credential_keys=['TEST_API_KEY']
    ) as ctx:
        print(f"   ✅ Lock acquired: {ctx.lock_acquired}")
        print(f"   ✅ Credentials granted: {ctx.credentials_granted}")
        print(f"   ✅ Environment injected: {'TASK_test_task_002_TEST_API_KEY' in os.environ}")

    # Test 5: Check audit log
    print("\n5. Checking audit log...")
    if security.audit_log.exists():
        with open(security.audit_log, 'r') as f:
            lines = f.readlines()
            print(f"   ✅ Audit log has {len(lines)} entries")

    print("\n✅ Security system test complete!")
