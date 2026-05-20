"""
State Manager — Atomic Persistent JSON I/O
==========================================
All state files go through here. Two guarantees:

1. ATOMIC WRITES — writes to .tmp then os.replace() so a crash mid-write
   never produces a corrupted JSON file that breaks the dashboard.

2. PERSISTENT VOLUME AWARE — DATA_DIR env var points to Railway's mounted
   volume (/data) in the cloud, or falls back to the bot directory locally.
   Set DATA_DIR=/data in Railway environment variables.

Usage:
    from state_manager import load_json, save_json, state_path

    data = load_json("portfolio_state.json", default={})
    save_json("portfolio_state.json", data)
    path = state_path("portfolio_state.json")   # full path string
"""

import os, json
from pathlib import Path

# ── Directory resolution ──────────────────────────────────────────────────────
# Railway: set DATA_DIR=/data (persistent volume mount point)
# Local:   defaults to the bot directory (same behaviour as before)

_BOT_DIR  = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.getenv("DATA_DIR", _BOT_DIR)

# Ensure the data directory exists (important on first Railway boot)
Path(_DATA_DIR).mkdir(parents=True, exist_ok=True)

def state_path(filename: str) -> str:
    """Return the full absolute path for a state file."""
    return os.path.join(_DATA_DIR, filename)

# ── Atomic load ───────────────────────────────────────────────────────────────

def load_json(filename: str, default=None):
    """
    Load a JSON state file. Returns `default` if file doesn't exist or is
    corrupted (e.g. from a previous crash mid-write).
    """
    path = state_path(filename)
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # File exists but is corrupt — return default and let caller overwrite
        print(f"  [state] WARNING: {filename} corrupt or unreadable — using default")
        return default if default is not None else {}

# ── Atomic save ───────────────────────────────────────────────────────────────

def save_json(filename: str, data, indent: int = 2):
    """
    Atomically write data to a JSON state file.
    Writes to a .tmp file in the same directory, then os.replace() which is
    atomic on all OS (POSIX rename syscall, Windows MoveFileEx).
    A crash at any point leaves either the old file or the new file intact —
    never a half-written corrupt file.
    """
    path     = state_path(filename)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError as e:
        print(f"  [state] ERROR saving {filename}: {e}")
        # Clean up orphaned tmp file if it exists
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

# ── Convenience: read-modify-write ────────────────────────────────────────────

def update_json(filename: str, updater_fn, default=None):
    """
    Load a state file, apply updater_fn(data) → new_data, save atomically.
    Example:
        update_json("portfolio_state.json", lambda s: {**s, "virtual_capital": 99000})
    """
    data     = load_json(filename, default=default)
    new_data = updater_fn(data)
    save_json(filename, new_data)
    return new_data

# ── List all state files ──────────────────────────────────────────────────────

def list_state_files() -> list:
    """Return all .json files in the data directory."""
    try:
        return [f for f in os.listdir(_DATA_DIR) if f.endswith(".json")]
    except OSError:
        return []

# ── Diagnostic ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"  Bot dir:  {_BOT_DIR}")
    print(f"  Data dir: {_DATA_DIR}  ({'CUSTOM' if _DATA_DIR != _BOT_DIR else 'local default'})")
    print(f"  State files: {list_state_files()}")
    # Test atomic write
    save_json("_state_test.json", {"test": True, "dir": _DATA_DIR})
    result = load_json("_state_test.json")
    assert result["test"] is True
    os.remove(state_path("_state_test.json"))
    print("  [OK] Atomic write/read test passed")
