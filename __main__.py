#!/usr/bin/env python3
import sys
import signal
from .config import HOME, INBOX
from .utils_fs import safe_move, wait_port
from .cleanup import remove_empty_dirs
from .agent import run

def _prestage_inbox():
    # Move Downloads/Desktop into INBOX safely (no overwrite)
    for src in [HOME/"Downloads", HOME/"Desktop"]:
        if src.exists():
            for it in src.iterdir():
                if it.name.startswith("."):
                    continue
                try:
                    safe_move(it, INBOX, it.name)
                except Exception as e:
                    print(f"skip {it}: {e}")

def _final_cleanup():
    # Only remove EMPTY dirs under INBOX. Never flatten Documents/...
    try:
        print("Cleaning up empty directories in INBOX...")
        remove_empty_dirs(INBOX)
    except Exception as e:
        print(f"Cleanup error: {e}")

def _signal_handler(signum, frame):
    print(f"Received signal {signum}. Performing cleanup...")
    _final_cleanup()
    # POSIX: exit code 128+signal
    code = 128 + (signum if isinstance(signum, int) else 0)
    try:
        sys.exit(code)
    except SystemExit:
        raise

if __name__ == "__main__":
    # Pre-stage content
    _prestage_inbox()

    # Optional: wait for LLM server
    wait_port()

    # Ensure cleanup on Ctrl-C / SIGTERM
    signal.signal(signal.SIGINT,  _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        run()
    except KeyboardInterrupt:
        print("KeyboardInterrupt received. Performing cleanup...")
    finally:
        _final_cleanup()