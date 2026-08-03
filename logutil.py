"""Shared file-logging helper for GUI processes with no visible stdout.

A double-clicked macOS .app has no terminal, so plain print() output vanishes
silently. Mirroring it to ~/Library/Logs/<app_name>/desktop.log makes it
visible after the fact. Namespaced by app name so independently-running
builds (e.g. production and a beta build) never share one log file.
"""
import os
import time


def make_file_logger(app_name: str):
    """Return a log(msg) function that prints and appends to the app's log file."""
    log_dir = os.path.expanduser(f"~/Library/Logs/{app_name}")
    log_path = os.path.join(log_dir, "desktop.log")

    def log(msg: str) -> None:
        print(msg, flush=True)
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    return log
