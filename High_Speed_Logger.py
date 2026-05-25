"""
TPI_F18BlowDown.py
----------
Test Point Instructions for F18 Blowdown Chamber.
Integrates hardware data acquisition with a live Matplotlib dashboard.

Design pattern (mirrors LabVIEW QMH + Producer/Consumer):
  • Producer: Polling hardware and generating data inside test point sequence.
  • Consumer: FuncAnimation draining the queue and safely plotting live data.
"""

import os
import queue
import threading
import time
from collections import defaultdict
from typing import Dict, Tuple

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.widgets import Button

import nidaqmx
from nidaqmx.constants import AcquisitionType

# ---------------------------------------------------------------------------
# Configuration constants (tune these for each test)
# ---------------------------------------------------------------------------
PRESSURE_MAX:       int   = 7000
FLOW_MAX:           int   = 600
PART_NUMBER:        str   = "1D8674-P0100"
TEST_STAND_NUMBER:  str   = "F18_BD_001"
UPDATE_INTERVAL:    int   = 500     # milliseconds
DATALOG_PATH:       str   = "C:\\_Data_Log\\"
PARAMETERS = {
    "CIS/GPM":        3.85,
    "Area Attention": 24.2,
    "Area RAM":       4.8852,
    "Length":         24,
    "Beta":           250000,
}

# Event-queue command tokens
_CMD_START = "START"
_CMD_STOP  = "STOP"
_CMD_EXIT  = "EXIT"

# Series identifiers
_SID_TIME = "Time"
_SID_FLOW = "Flow"

DataPoint = Tuple[str, float, float]

# ---------------------------------------------------------------------------
# DAQ timing constants
# ---------------------------------------------------------------------------
DAQ_DEVICE       = "Dev1"
SAMPLE_RATE      = 1000   # Hz
SAMPLES_PER_READ = 10     # samples per channel per read (~10 ms per chunk at 1 kHz)

# Channel indices within the 4-channel task (Dev1/ai0:3)
_CH_HIGH_PRESSURE    = 0   # ai0 — high-pressure transducer
_CH_LOW_PRESSURE     = 1   # ai1 — low-pressure transducer
_CH_VELOCITY         = 2   # ai2 — velocity sensor
_CH_SOLENOID_VOLTAGE = 3   # ai3 — solenoid voltage


class DataLogger(object):
    def __init__(self) -> None:
        self.daq_task: nidaqmx.Task | None = None
        
        self.datalog_path      = DATALOG_PATH
        self.parameters        = PARAMETERS
        self.pressure_max      = PRESSURE_MAX
        self.flow_max          = FLOW_MAX
        self.part_number       = PART_NUMBER
        self.serial_number     = "SN_UNKNOWN"
        self.test_stand_number = TEST_STAND_NUMBER
        self.update_interval   = UPDATE_INTERVAL

    # ------------------------------------------------------------------
    # DAQ lifecycle  (mirrors HardwareInterface in XY Plotter hardware.py)
    # ------------------------------------------------------------------

    def _connect_daq(self) -> None:
        """Open a 4-channel continuous acquisition task on Dev1/ai0:3."""
        try:
            self.daq_task = nidaqmx.Task("DataLoggerDAQ")
            self.daq_task.ai_channels.add_ai_voltage_chan(
                f"{DAQ_DEVICE}/ai0:3", min_val=-10.0, max_val=10.0
            )
            self.daq_task.timing.cfg_samp_clk_timing(
                rate=SAMPLE_RATE,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=SAMPLES_PER_READ * 10,   # buffer = 10× read chunk
            )
            self.daq_task.start()
            print(f"[TPI] DAQ task started — {DAQ_DEVICE}/ai0:3 "
                  "(high-pressure, low-pressure, velocity, solenoid-voltage).")
        except nidaqmx.DaqError as e:
            print(f"[TPI] DAQmx task failed to start: {e}")
            self.daq_task = None

    def _disconnect_daq(self) -> None:
        """Safely stop and close the DAQ task."""
        if self.daq_task is not None:
            try:
                self.daq_task.stop()
            except nidaqmx.DaqError:
                pass
            self.daq_task.close()
            self.daq_task = None
            print("[TPI] DAQ task closed.")

    def _read_voltages(self) -> "np.ndarray":
        """
        Read one chunk from all four channels and return per-channel mean voltages.

        Returns:
            np.ndarray shape (4,): [high_pressure_V, low_pressure_V,
                                    velocity_V, solenoid_voltage_V]
            Returns zeros if the DAQ task is unavailable.
        """
        if self.daq_task is None:
            return np.zeros(4)
        data = self.daq_task.read(number_of_samples_per_channel=SAMPLES_PER_READ)
        arr = np.array(data)                      # shape: (4, SAMPLES_PER_READ)
        if arr.ndim == 1:                         # single-sample edge case
            arr = arr.reshape(4, SAMPLES_PER_READ)
        return arr.mean(axis=1)                   # (4,) one mean voltage per channel

    def process_data(
        self,
        hp: float,
        lp: float,
        vel: float,
        last_hp: float,
        last_len: float,
        delta_t: float,
    ) -> Dict[str, float]:
        """
        Hydraulic blowdown calculations (ported from LabVIEW G-code).

        Uses compressibility compensation (K_comp) to correct measured flow for
        pressure-transient effects in the hydraulic line between the actuator and
        the flow meter — a constraint imposed by the F18 test rig geometry.
        """
        params = self.parameters

        if delta_t <= 0.0:
            delta_t = 0.00125  # prevent division-by-zero; smallest expected sample period

        # Integrate velocity to track piston position
        current_len = last_len - (vel * delta_t)

        # Compressibility correction coefficient
        k_comp = params["Area Attention"] / (delta_t * params["Beta"] * params["CIS/GPM"])
        q_comp = (hp - last_hp) * current_len * k_comp

        flow = (vel * params["Area Attention"]) / params["CIS/GPM"] - q_comp

        return {
            "last_hp_out":    hp,
            "last_len_out":   current_len,
            "delta_pressure": hp - lp,
            "flow":           flow,
        }

    def save(
        self,
        series_data: Dict,
        part_number: str,
        serial_number: str,
    ) -> str | None:
        """
        Collate the logged series and write a timestamped CSV.

        Intended to be called on a background thread so the Matplotlib event
        loop is not blocked during file I/O.

        Returns:
            Absolute path of the written file, or None if no data is available.
        """
        columns: Dict[str, pd.Series] = {}

        if _SID_TIME in series_data and series_data[_SID_TIME]["X"]:
            columns["time"] = pd.Series(series_data[_SID_TIME]["X"])
        if _SID_FLOW in series_data and series_data[_SID_FLOW]["X"]:
            columns["delp"] = pd.Series(series_data[_SID_FLOW]["X"])
            columns["flow"] = pd.Series(series_data[_SID_FLOW]["Y"])

        if not columns:
            print("[TPI] No data to export.")
            return None

        os.makedirs(self.datalog_path, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath  = os.path.join(self.datalog_path, f"{part_number}_{serial_number}_{timestamp}.csv")
        pd.DataFrame(columns).to_csv(filepath, index=False)
        print(f"[TPI] Saved → {filepath}")
        return filepath

    # ------------------------------------------------------------------
    # Figure / layout construction
    # ------------------------------------------------------------------

    def _build_figure(self) -> None:
        self.fig: Figure
        self.ax: Axes
        self.fig, self.ax = plt.subplots(figsize=(10, 5), dpi=100)
        plt.subplots_adjust(top=0.93, bottom=0.12, left=0.1, right=0.96)
        self.ax.grid(False)

        # Store connection IDs so listeners can be disconnected if needed
        self._cid_close = self.fig.canvas.mpl_connect("close_event",     self._on_close)
        self._cid_key   = self.fig.canvas.mpl_connect("key_press_event", self._on_key)

    def _build_layout(self) -> None:
        """Axes labels, ticks, ROI boundary, overlay text, and buttons."""
        self.fig.canvas.manager.set_window_title(
            f"F18 Blowdown Chamber, P/N : {self.part_number} @ Test Stand : {self.test_stand_number}"
        )

        self.ax.set_xlabel("DELTA-P, PSI")
        self.ax.set_xlim(0, self.pressure_max)
        self.ax.set_xticks(np.arange(0, self.pressure_max, self.pressure_max / 7))
        self.ax.set_ylabel("FLOW, GPM")
        self.ax.set_ylim(0, self.flow_max)
        self.ax.set_yticks(np.arange(0, self.flow_max, self.flow_max / 6))

        Flow_ROI = np.array([
            [0, 90], [3800, 210], [5100, 600],
            [7000, 600], [4000, 10], [0, 0], [0, 90],
        ])
        self.ax.plot(Flow_ROI[:, 0], Flow_ROI[:, 1], color="gray", linestyle="--", linewidth=1)

        self.timing_text = self.ax.text(
            0.01, 0.99, "",
            transform=self.ax.transAxes, fontsize=8, family="monospace",
            verticalalignment="top", color="gray",
        )
        self.loop_timing_text = self.ax.text(
            0.01, 0.965, "",
            transform=self.ax.transAxes, fontsize=8, family="monospace",
            verticalalignment="top", color="gray",
        )
        self.live_val_text = self.ax.text(
            0.01, 0.94, "dP: 0.0 PSI | Flow: 0.0 GPM",
            transform=self.ax.transAxes, fontsize=8, family="monospace",
            verticalalignment="top", color="tab:red",
        )

        self.ax_record  = self.fig.add_axes([0.86, 0.94, 0.1, 0.05])
        self.btn_record = Button(self.ax_record, "Start Record")
        self.btn_record.on_clicked(self._on_record_clicked)

    def _init_state(self) -> None:
        """Initialise all mutable state containers."""
        self.series_data:   Dict[str, Dict[str, list]] = {}
        self.recorded_data: defaultdict                = defaultdict(lambda: {"X": [], "Y": []})

        self.lines: Dict[str, plt.Line2D] = {}

        self.is_running:       bool  = False
        self.is_recording:     bool  = False
        self.reset_time_flag:  bool  = False
        self.current_loop_time: float = 0.0
        self._start_time:      float = time.time()
        self._timing_text_val: str   = ""  # tracks last-written value to skip no-op set_text calls

        self.data_queue:  queue.Queue[DataPoint] = queue.Queue()
        self.event_queue: queue.Queue[dict]      = queue.Queue()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _start_background_thread(self) -> None:
        self._event_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._event_thread.start()

    def _event_loop(self) -> None:
        """
        QMH-style event loop: blocking get handles commands immediately;
        queue.Empty is the timeout / idle case.
        """
        while not self._stop_event.is_set():
            try:
                cmd_dict = self.event_queue.get(timeout=self.update_interval / 1000.0)
                self._handle_command(cmd_dict)
            except queue.Empty:
                pass

    def _handle_command(self, cmd_dict: dict) -> None:
        cmd = cmd_dict.get("cmd", "")
        if cmd == _CMD_START:
            self._clear_data_queue()
        elif cmd == _CMD_EXIT:
            self._stop_event.set()
        # _CMD_STOP: intentionally no-op; pause is handled via the is_running flag

    def _clear_data_queue(self) -> None:
        """Discard all pending data points (accesses queue internals — not part of the public API)."""
        with self.data_queue.mutex:
            self.data_queue.queue.clear()

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _start_animation(self) -> None:
        self.anim = FuncAnimation(
            self.fig,
            self._update_plot,
            interval=self.update_interval,
            blit=False,
            cache_frame_data=False,
        )

    def _update_plot(self, _frame) -> list:
        """Drain data_queue, update line data, refresh overlay text."""
        now = time.time()

        if self.is_running:
            new_val = (
                f"Recording Time: {now - self._start_time:.1f} s"
                if self.is_recording else ""
            )
            if new_val != self._timing_text_val:
                self.timing_text.set_text(new_val)
                self._timing_text_val = new_val
                
        if self.is_recording and self.current_loop_time > 0:
            self.loop_timing_text.set_text(f"Sample Rate: {1.0 / self.current_loop_time:.0f} Hz")
        else:
            self.loop_timing_text.set_text("")

        has_new = False
        while True:
            try:
                series_id, x, y = self.data_queue.get_nowait()
            except queue.Empty:
                break

            self._ensure_series(series_id)

            if self.is_recording:
                self.recorded_data[series_id]["X"].append(x)
                self.recorded_data[series_id]["Y"].append(y)
                if len(self.recorded_data[series_id]["X"]) % 10 == 0:
                    self.series_data[series_id]["X"].append(x)
                    self.series_data[series_id]["Y"].append(y)
            else:
                self.series_data[series_id]["X"].append(x)
                self.series_data[series_id]["Y"].append(y)

            has_new = True

        if has_new:
            for sid, line in self.lines.items():
                d = self.series_data[sid]
                line.set_data(d["X"], d["Y"])
                if sid == _SID_FLOW and d["Y"]:
                    self.live_val_text.set_text(
                        f"dP: {d['X'][-1]:.0f} PSI | Flow: {d['Y'][-1]:.1f} GPM"
                    )

        return list(self.lines.values()) + [self.timing_text, self.live_val_text, self.loop_timing_text]

    def _ensure_series(self, series_id: str) -> None:
        """Create series_data entry and a blank Line2D on first encounter."""
        if series_id in self.series_data:
            return
        self.series_data[series_id] = {"X": [], "Y": []}
        if series_id == _SID_FLOW:
            line, = self.ax.plot(
                [], [], marker="s", markersize=5, color="tab:red",
                linewidth=0, markerfacecolor="white", markeredgecolor="tab:red",
            )
            self.lines[series_id] = line

    # ------------------------------------------------------------------
    # Public acquisition control
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start (or resume) data acquisition."""
        self.is_running  = True
        self._start_time = time.time()
        self.event_queue.put({"cmd": _CMD_START})

    def stop(self) -> None:
        """Pause data acquisition without resetting state."""
        self.is_running = False
        self.event_queue.put({"cmd": _CMD_STOP})

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------

    def _on_record_clicked(self, _event) -> None:
        """Toggle recording; save to CSV on a background thread when stopped."""
        if self.is_recording:
            self.is_recording = False
            self.btn_record.label.set_text("Start Record")
            # Snapshot recorded_data before handing to background thread
            snapshot = {k: {"X": list(v["X"]), "Y": list(v["Y"])} for k, v in self.recorded_data.items()}
            threading.Thread(
                target=self.save,
                args=(snapshot, self.part_number, self.serial_number),
                daemon=True,
            ).start()
        else:
            self.is_recording    = True
            self.btn_record.label.set_text("Stop Record")
            self.recorded_data   = defaultdict(lambda: {"X": [], "Y": []})
            self.reset_time_flag = True
            self._start_time     = time.time()
            for sid in self.series_data:
                self.series_data[sid]["X"].clear()
                self.series_data[sid]["Y"].clear()
                if sid in self.lines:
                    self.lines[sid].set_data([], [])
            self.live_val_text.set_text("dP: 0.0 PSI | Flow: 0.0 GPM")

        self.fig.canvas.draw_idle()

    def _on_close(self, _event) -> None:
        self._stop_event.set()
        self.event_queue.put({"cmd": _CMD_EXIT})
        self.is_running = False
        if getattr(self.anim, "event_source", None) is not None:
            self.anim.event_source.stop()
        self._disconnect_daq()

    def _on_key(self, event) -> None:
        key = str(getattr(event, "key", "") or "").lower()
        if key == "f8":
            self._on_record_clicked(event)
        elif key == "f4":
            try:
                plt.close(self.fig)
            except Exception:
                pass


def main(logger: DataLogger) -> None:

    logger._connect_daq()
    logger._build_figure()
    logger._build_layout()
    logger._init_state()
    logger._start_background_thread()
    logger._start_animation()

    def producer() -> None:
        logger.start()
        start_time = time.time()
        last_time  = start_time
        last_hp    = 0.0
        last_len   = logger.parameters.get("Length", 0.0)

        while not logger._stop_event.is_set():
            if logger.reset_time_flag:
                start_time             = time.time()
                last_time              = start_time
                logger.reset_time_flag = False
                logger._clear_data_queue()

            now = time.time()
            dt  = now - last_time

            # Target ~800 Hz; sleep briefly to avoid burning a full CPU core
            if dt < 0.00125:
                time.sleep(0.0005)
                continue

            last_time = now
            logger.current_loop_time = dt
            t = now - start_time

            voltages = logger._read_voltages()
            hp_val  = float(voltages[_CH_HIGH_PRESSURE]) * 1500.0
            lp_val  = float(voltages[_CH_LOW_PRESSURE]) * 150.0
            vel_val = float(voltages[_CH_VELOCITY]) * 17.5

            processed = logger.process_data(
                hp=hp_val, lp=lp_val, vel=vel_val,
                last_hp=last_hp, last_len=last_len, delta_t=dt,
            )
            last_hp  = processed["last_hp_out"]
            last_len = processed["last_len_out"]

            logger.data_queue.put((_SID_TIME, t, t))
            logger.data_queue.put((_SID_FLOW, processed["delta_pressure"], processed["flow"]))

    logger._producer_thread = threading.Thread(target=producer, daemon=True)
    logger._producer_thread.start()
    plt.show()


if __name__ == "__main__":
    main(DataLogger())
