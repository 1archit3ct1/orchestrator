#!/usr/bin/env python3
"""Test TASK.md processing"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from security_manager import SecurityManager

# Test security initialization
print("Testing Security Manager...")
security = SecurityManager(Path('D:/NextAura/orchestrator/SPAWN'))
print(f"Security initialized: {security is not None}")
print(f"Vault exists: {security.vault_dir.exists()}")

# Test loading credentials
creds = security._load_vault()
print(f"Credentials loaded: {len(creds)} keys")
print(f"Keys: {list(creds.keys())}")

# Check for GitHub credentials
if 'GITHUB_SSH_KEY' in creds:
    print("✓ GITHUB_SSH_KEY found in vault")
else:
    print("✗ GITHUB_SSH_KEY NOT found in vault")

if 'GITHUB_TOKEN' in creds:
    print("✓ GITHUB_TOKEN found in vault")
else:
    print("✗ GITHUB_TOKEN NOT found in vault")

print("\nDone!")
