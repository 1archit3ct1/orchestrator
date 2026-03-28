#!/usr/bin/env python3
"""
Spawn Loop Background Runner

Monitors config.json spawn_loop state and runs the orchestrator loop when state=running.
This allows the GUI spawn controls to start/pause the actual autonomous loop process.

Usage:
    python spawn_runner.py
    
The runner checks spawn_loop.state in config.json every 5 seconds:
- state=running: Starts loop.py if not already running
- state=paused: Stops loop.py if running
- state=stopped: Stops loop.py if running
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'logs', 'spawn_runner.log'))
    ]
)
logger = logging.getLogger('spawn_runner')

SCRIPT_DIR = Path(__file__).resolve().parent
LOOP_SCRIPT = SCRIPT_DIR / 'loop.py'
CONFIG_PATH = SCRIPT_DIR / 'config.json'

loop_process = None
last_state = None
last_state_change = None


def load_config():
    """Load config.json safely."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load config: {e}")
    return {}


def get_spawn_state():
    """Get current spawn loop state from config."""
    config = load_config()
    spawn_loop = config.get('spawn_loop', {})
    return spawn_loop.get('state', 'stopped')


def start_loop():
    """Start the orchestrator loop process."""
    global loop_process
    
    if loop_process is not None and loop_process.poll() is None:
        logger.info("Loop already running")
        return True
    
    try:
        logger.info(f"Starting loop: python {LOOP_SCRIPT}")
        loop_process = subprocess.Popen(
            [sys.executable, str(LOOP_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Loop process started with PID {loop_process.pid}")
        return True
    except Exception as e:
        logger.error(f"Failed to start loop: {e}")
        loop_process = None
        return False


def stop_loop():
    """Stop the orchestrator loop process gracefully."""
    global loop_process
    
    if loop_process is None:
        logger.info("No loop process to stop")
        return True
    
    try:
        logger.info(f"Stopping loop process {loop_process.pid}...")
        loop_process.terminate()
        try:
            loop_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Loop did not terminate gracefully, killing...")
            loop_process.kill()
            loop_process.wait()
        logger.info("Loop process stopped")
        loop_process = None
        return True
    except Exception as e:
        logger.error(f"Failed to stop loop: {e}")
        loop_process = None
        return False


def check_loop_status():
    """Check if loop process is still running."""
    global loop_process
    
    if loop_process is None:
        return False
    
    if loop_process.poll() is not None:
        logger.warning(f"Loop process exited with code {loop_process.returncode}")
        loop_process = None
        return False
    
    return True


def main():
    """Main runner loop."""
    global last_state, last_state_change, loop_process
    
    logger.info("=" * 60)
    logger.info("SPAWN LOOP RUNNER STARTING")
    logger.info(f"Config: {CONFIG_PATH}")
    logger.info(f"Loop script: {LOOP_SCRIPT}")
    logger.info("=" * 60)
    
    if not LOOP_SCRIPT.exists():
        logger.error(f"Loop script not found: {LOOP_SCRIPT}")
        sys.exit(1)
    
    while True:
        try:
            current_state = get_spawn_state()
            
            # State changed?
            if current_state != last_state:
                logger.info(f"Spawn state changed: {last_state} -> {current_state}")
                last_state_change = datetime.now().isoformat()
                last_state = current_state
            
            # Act based on state
            if current_state == 'running':
                if not check_loop_status():
                    logger.info("State is 'running' but loop not running - starting...")
                    start_loop()
            elif current_state in ('paused', 'stopped'):
                if check_loop_status():
                    logger.info(f"State is '{current_state}' - stopping loop...")
                    stop_loop()
            
            # Log status every 30 seconds
            if last_state_change:
                elapsed = (datetime.now() - datetime.fromisoformat(last_state_change)).total_seconds()
                if elapsed > 30:
                    loop_status = "running" if check_loop_status() else "stopped"
                    logger.info(f"Status: state={current_state}, loop={loop_status}, elapsed={elapsed:.0f}s")
                    last_state_change = datetime.now().isoformat()
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            logger.info("Interrupted, stopping...")
            stop_loop()
            break
        except Exception as e:
            logger.error(f"Error in runner: {e}")
            time.sleep(10)
    
    logger.info("SPAWN LOOP RUNNER STOPPED")


if __name__ == '__main__':
    main()
