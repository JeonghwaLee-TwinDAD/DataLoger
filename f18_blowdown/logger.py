"""
logger.py
---------
DataLogger — serialises recorded Time/Flow Series data to timestamped CSV files.

Implements DL-REQ-001: stateless beyond `datalog_path`, depends only on pandas
and the standard library, and knows nothing about acquisition, processing, or
the GUI (see Requirements.md, section 8 "Dependencies").
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pandas as pd

from .config import DATALOG_PATH
from .models import Series


class DataLogger:
    """Serialises recorded Time/Flow series to CSV. Stateless beyond datalog_path."""

    def __init__(self, datalog_path: str = DATALOG_PATH) -> None:
        self.datalog_path = datalog_path

    def save(
        self,
        time_series: Series | None,
        flow_series: Series | None,
        part_number: str,
        serial_number: str,
    ) -> str | None:
        """
        Write a timestamped CSV containing the given Time/Flow series.

        Returns the absolute path of the written file, or None if no data is
        available (in which case no file is written).
        """
        columns: dict[str, pd.Series] = {}

        if time_series is not None and time_series.xs:
            columns["time"] = pd.Series(time_series.xs)
        if flow_series is not None and flow_series.xs:
            columns["delp"] = pd.Series(flow_series.xs)
            columns["flow"] = pd.Series(flow_series.ys)

        if not columns:
            print("[DataLogger] No data to export.")
            return None

        os.makedirs(self.datalog_path, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.abspath(
            os.path.join(self.datalog_path, f"{part_number}_{serial_number}_{timestamp}.csv")
        )
        pd.DataFrame(columns).to_csv(filepath, index=False)
        print(f"[DataLogger] Saved -> {filepath}")
        return filepath

    def save_async(
        self,
        time_series: Series | None,
        flow_series: Series | None,
        part_number: str,
        serial_number: str,
    ) -> None:
        """Snapshot the given series and write the CSV on a daemon background thread."""
        time_snapshot = time_series.snapshot() if time_series is not None else None
        flow_snapshot = flow_series.snapshot() if flow_series is not None else None

        def _run() -> None:
            try:
                self.save(time_snapshot, flow_snapshot, part_number, serial_number)
            except Exception as exc:
                print(f"[DataLogger] Background save failed: {exc}", file=sys.stderr)

        threading.Thread(target=_run, daemon=True).start()
