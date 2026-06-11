"""
mcp_datalogger_server.py
------------------------
MCP server exposing the F18 Blowdown Chamber DataLogger to LLM assistants:

  • Tools to list/read recorded CSV runs from C:\\_Data_Log\\
  • Tools to query live status and remotely toggle Start/Stop Record on a
    running High_Speed_Logger.py instance (via its localhost control API)
  • Resources exposing the project's README and Requirements documents

Run with stdio transport (the default for local Claude Code/Desktop use):
    python mcp_datalogger_server.py
"""

import glob
import json
import os
import urllib.error
import urllib.request
from datetime import datetime

import pandas as pd
from mcp.server.fastmcp import FastMCP

PROJECT_DIR  = os.path.dirname(os.path.abspath(__file__))
DATALOG_PATH = "C:\\_Data_Log\\"
CONTROL_BASE = "http://127.0.0.1:8787"

mcp = FastMCP("F18 DataLogger")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _control_request(path: str, method: str = "GET") -> dict:
    """Call the running logger's localhost control API; raise a friendly error if unreachable."""
    req = urllib.request.Request(f"{CONTROL_BASE}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise RuntimeError(
            "Could not reach the DataLogger app's control API at "
            f"{CONTROL_BASE}. Is High_Speed_Logger.py running? ({exc})"
        ) from exc


def _safe_recording_path(filename: str) -> str:
    """Resolve filename within DATALOG_PATH, rejecting any path traversal."""
    candidate = os.path.abspath(os.path.join(DATALOG_PATH, filename))
    base = os.path.abspath(DATALOG_PATH)
    if os.path.commonpath([candidate, base]) != base:
        raise ValueError(f"'{filename}' is not a valid recording filename.")
    return candidate


# ---------------------------------------------------------------------------
# Tools — recorded CSV data
# ---------------------------------------------------------------------------

@mcp.tool()
def list_recordings() -> list[dict]:
    """List recorded CSV runs in the DataLogger output directory (newest first)."""
    if not os.path.isdir(DATALOG_PATH):
        return []

    entries = []
    for path in glob.glob(os.path.join(DATALOG_PATH, "*.csv")):
        stat = os.stat(path)
        entries.append({
            "filename":      os.path.basename(path),
            "size_bytes":    stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    entries.sort(key=lambda e: e["modified_time"], reverse=True)
    return entries


@mcp.tool()
def read_recording(filename: str, max_rows: int = 50) -> dict:
    """
    Read a recorded CSV (columns: time, delp, flow) and summarize it.

    Returns row count, column names, a preview of up to max_rows rows, and
    min/max/mean for each numeric column.
    """
    path = _safe_recording_path(filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No recording named '{filename}' in {DATALOG_PATH}")

    df = pd.read_csv(path)
    stats = {
        col: {
            "min":  float(df[col].min()),
            "max":  float(df[col].max()),
            "mean": float(df[col].mean()),
        }
        for col in df.select_dtypes(include="number").columns
    }
    return {
        "filename":   os.path.basename(path),
        "row_count":  len(df),
        "columns":    list(df.columns),
        "preview":    df.head(max_rows).to_dict(orient="records"),
        "stats":      stats,
    }


# ---------------------------------------------------------------------------
# Tools — live logger control
# ---------------------------------------------------------------------------

@mcp.tool()
def get_logger_status() -> dict:
    """Get live status from the running DataLogger app (recording state, DAQ connection, sample count, last save path)."""
    return _control_request("/status")


@mcp.tool()
def toggle_record() -> dict:
    """
    Toggle Start/Stop Record on the running DataLogger app — the same action
    as clicking the 'Start Record' / 'Stop Record' button or pressing F8.

    Returns the resulting status (including the saved CSV path once a
    recording is stopped and written to disk).
    """
    _control_request("/toggle_record", method="POST")
    return _control_request("/status")


# ---------------------------------------------------------------------------
# Resources — project documentation
# ---------------------------------------------------------------------------

@mcp.resource("datalogger://readme")
def readme() -> str:
    """The DataLogger project README."""
    with open(os.path.join(PROJECT_DIR, "README.md"), encoding="utf-8") as f:
        return f.read()


@mcp.resource("datalogger://requirements")
def requirements() -> str:
    """The DataLogger requirements specification."""
    with open(os.path.join(PROJECT_DIR, "Requirements.md"), encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    mcp.run()
