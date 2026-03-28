#!/usr/bin/env python3
"""
Run git commands sequentially against the top-level repo.

Why this exists:
- the orchestrator lives under SPAWN/, but the git repo root is one level up
- concurrent git writes against the same top-level index can leave transient
  `.git/index.lock` conflicts
- callers should route mutating git operations through this wrapper instead of
  launching `git commit` and `git push` in parallel
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


LOCK_NAME = "nextaura_git_serial.lock"
WAIT_SECONDS = 30.0
POLL_SECONDS = 0.2


def repo_root_from(start: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def acquire(self, timeout: float = WAIT_SECONDS) -> None:
        deadline = time.time() + timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self.fd, str(os.getpid()).encode("ascii", errors="ignore"))
                return
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {self.path}")
                time.sleep(POLL_SECONDS)

    def release(self) -> None:
        try:
            if self.fd is not None:
                os.close(self.fd)
        finally:
            self.fd = None
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def wait_for_index_lock(git_dir: Path, timeout: float = WAIT_SECONDS) -> None:
    index_lock = git_dir / "index.lock"
    deadline = time.time() + timeout
    while index_lock.exists():
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {index_lock}")
        time.sleep(POLL_SECONDS)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python scripts/git_serial.py <git args...>", file=sys.stderr)
        return 2

    cwd = Path.cwd()
    root = repo_root_from(cwd)
    git_dir = root / ".git"
    lock = FileLock(git_dir / LOCK_NAME)

    try:
        lock.acquire()
        wait_for_index_lock(git_dir)
        proc = subprocess.run(["git", *argv], cwd=root)
        return proc.returncode
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
