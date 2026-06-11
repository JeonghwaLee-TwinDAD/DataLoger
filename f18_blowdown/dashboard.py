"""
dashboard.py
------------
BlowdownDashboard — live Matplotlib UI, recording controls, and the
localhost remote-control API.

Consumer side of the producer/consumer pattern: FuncAnimation drains
data_queue every UPDATE_INTERVAL ms, updating the live Flow-vs-dP chart and
the 4-channel trend chart, and (when recording) accumulating Time/Flow Series
for export via DataLogger.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.widgets import Button

from . import config
from .logger import DataLogger
from .models import (
    CMD_EXIT,
    CMD_START,
    CMD_STOP,
    REMOTE_CMD_TOGGLE_RECORD,
    SID_FLOW,
    SID_TIME,
    DataPoint,
    Series,
)


class _RemoteControlHandler(BaseHTTPRequestHandler):
    """
    Minimal localhost HTTP control surface for the running dashboard.

    GET  /status          → JSON snapshot of run/record/DAQ state.
    POST /toggle_record   → enqueues a TOGGLE_RECORD token; the actual toggle
                            runs on the Matplotlib UI thread (see _update_plot)
                            so it reuses _on_record_clicked exactly as a real
                            button click or F8 press would.
    """
    dashboard: "BlowdownDashboard"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/status":
            dashboard = self.dashboard
            self._send_json(200, {
                "is_running":      dashboard.is_running,
                "is_recording":    dashboard.is_recording,
                "daq_connected":   dashboard.daq_connected,
                "elapsed_s":       round(time.time() - dashboard._start_time, 1),
                "sample_count":    len(dashboard.recorded_time.xs),
                "last_saved_path": dashboard.last_saved_path,
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/toggle_record":
            self.dashboard._remote_cmd_queue.put(REMOTE_CMD_TOGGLE_RECORD)
            self._send_json(202, {"queued": REMOTE_CMD_TOGGLE_RECORD})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        pass  # silence BaseHTTPRequestHandler's default stderr request logging


class BlowdownDashboard:
    """Live Matplotlib dashboard: Flow-vs-dP chart, 4-channel trend chart, and recording controls."""

    def __init__(
        self,
        part_number: str = config.PART_NUMBER,
        test_stand_number: str = config.TEST_STAND_NUMBER,
        pressure_max: int = config.PRESSURE_MAX,
        flow_max: int = config.FLOW_MAX,
        update_interval: int = config.UPDATE_INTERVAL,
        datalog_path: str = config.DATALOG_PATH,
    ) -> None:
        self.part_number       = part_number
        self.serial_number     = "SN_UNKNOWN"
        self.test_stand_number = test_stand_number
        self.pressure_max      = pressure_max
        self.flow_max          = flow_max
        self.update_interval   = update_interval

        self.data_logger    = DataLogger(datalog_path)
        self.daq_connected  = False
        self._on_close_callbacks: List[Callable[[], None]] = []

    def add_close_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to run when the dashboard window is closed (e.g. DAQ disconnect)."""
        self._on_close_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Figure / layout construction
    # ------------------------------------------------------------------

    def _style_axes(self, ax: Axes) -> None:
        """Apply the shared Material card styling (outline, grid, ticks) to an axes."""
        ax.set_facecolor(config.COLOR_PLOT_BG)
        ax.set_axisbelow(True)
        ax.grid(True, color=config.COLOR_GRID, alpha=1.0, linestyle="-", linewidth=0.8)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(True)
            ax.spines[side].set_color(config.COLOR_GRID)
            ax.spines[side].set_linewidth(1.0)
        ax.tick_params(colors=config.COLOR_MUTED)

    def _build_figure(self) -> None:
        self.fig: Figure
        self.ax: Axes
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = config.FONT_FAMILY
        self.fig, self.ax = plt.subplots(figsize=(10, 5), dpi=100)
        self.fig.patch.set_facecolor(config.COLOR_BG)
        plt.subplots_adjust(top=0.80, bottom=0.12, left=0.08, right=0.97)
        self._style_axes(self.ax)

        # Second axes (4-channel trend chart), overlaid on the same rect and
        # shown/hidden by the tab buttons — see _switch_tab.
        self.ax_channels: Axes = self.fig.add_axes(self.ax.get_position())
        self._style_axes(self.ax_channels)
        self.ax_channels.set_visible(False)

        # Store connection IDs so listeners can be disconnected if needed
        self._cid_close = self.fig.canvas.mpl_connect("close_event",     self._on_close)
        self._cid_key   = self.fig.canvas.mpl_connect("key_press_event", self._on_key)

    def _build_layout(self) -> None:
        """Axes labels, ticks, ROI boundary, overlay text, and buttons."""
        self.fig.canvas.manager.set_window_title(
            f"F18 Blowdown Chamber, P/N : {self.part_number} @ Test Stand : {self.test_stand_number}"
        )

        title_text = f"F18 Blowdown Chamber  —  P/N {self.part_number}  @  {self.test_stand_number}"
        title_kwargs = dict(loc="left", fontsize=12, fontweight="bold", color=config.COLOR_TEXT, pad=12)
        self.ax.set_title(title_text, **title_kwargs)
        self.ax_channels.set_title(title_text, **title_kwargs)

        self.ax.set_xlabel("DELTA-P, PSI", fontsize=10, fontweight="bold", color=config.COLOR_TEXT)
        self.ax.set_xlim(0, self.pressure_max)
        self.ax.set_xticks(np.arange(0, self.pressure_max, self.pressure_max / 7))
        self.ax.set_ylabel("FLOW, GPM", fontsize=10, fontweight="bold", color=config.COLOR_TEXT)
        self.ax.set_ylim(0, self.flow_max)
        self.ax.set_yticks(np.arange(0, self.flow_max, self.flow_max / 6))

        Flow_ROI = np.array([
            [0, 90], [3800, 210], [5100, 600],
            [7000, 600], [4000, 10], [0, 0], [0, 90],
        ])
        self.ax.fill(Flow_ROI[:, 0], Flow_ROI[:, 1], color=config.COLOR_ENVELOPE, alpha=0.12, zorder=0)
        self.ax.plot(
            Flow_ROI[:, 0], Flow_ROI[:, 1],
            color=config.COLOR_ENVELOPE, linestyle="--", linewidth=1.2, alpha=0.8,
            zorder=0, label="Operating Envelope",
        )
        self.ax.legend(loc="lower right", fontsize=8, framealpha=1.0, facecolor=config.COLOR_BG, edgecolor=config.COLOR_GRID, labelcolor=config.COLOR_TEXT)

        label_box = dict(boxstyle="round,pad=0.35", facecolor=config.COLOR_BG, edgecolor=config.COLOR_GRID, alpha=1.0, linewidth=0.8)

        self.timing_text = self.ax.text(
            0.012, 0.97, "",
            transform=self.ax.transAxes, fontsize=8, family="monospace",
            verticalalignment="top", color=config.COLOR_MUTED, bbox=label_box,
        )
        self.loop_timing_text = self.ax.text(
            0.012, 0.885, "",
            transform=self.ax.transAxes, fontsize=8, family="monospace",
            verticalalignment="top", color=config.COLOR_MUTED, bbox=label_box,
        )
        self.live_val_text = self.ax.text(
            0.012, 0.80, "dP: 0.0 PSI | Flow: 0.0 GPM",
            transform=self.ax.transAxes, fontsize=9, family="monospace", fontweight="bold",
            verticalalignment="top", color=config.COLOR_ACCENT, bbox=label_box,
        )
        self.rec_indicator = self.ax.text(
            0.988, 0.97, "● REC",
            transform=self.ax.transAxes, fontsize=10, fontweight="bold",
            verticalalignment="top", horizontalalignment="right", color=config.COLOR_MUTED,
        )

        self.ax_record  = self.fig.add_axes([0.80, 0.90, 0.165, 0.06])
        self.btn_record = Button(self.ax_record, "●  Start Record", color=config.COLOR_IDLE, hovercolor=config.COLOR_IDLE_HOVER)
        self.btn_record.label.set_color(config.COLOR_ON_PRIMARY)
        self.btn_record.label.set_fontweight("bold")
        self.btn_record.on_clicked(self._on_record_clicked)

        # ------------------------------------------------------------
        # 4-channel trend chart (second "tab")
        # ------------------------------------------------------------
        self.ax_channels.set_xlabel("TIME, s", fontsize=10, fontweight="bold", color=config.COLOR_TEXT)
        self.ax_channels.set_ylabel("SIGNAL, V", fontsize=10, fontweight="bold", color=config.COLOR_TEXT)
        self.ax_channels.set_xlim(0, config.CHANNEL_WINDOW_S)
        self.ax_channels.set_ylim(-11, 11)

        self.channel_lines: Dict[str, plt.Line2D] = {}
        for sid in config.CHANNEL_SERIES:
            line, = self.ax_channels.plot(
                [], [], color=config.CHANNEL_COLORS[sid], linewidth=1.2, label=config.CHANNEL_LABELS[sid],
            )
            self.channel_lines[sid] = line
        self.ax_channels.legend(loc="upper right", fontsize=8, framealpha=0.15, labelcolor=config.COLOR_TEXT)

        # ------------------------------------------------------------
        # Tab buttons — switch between the Flow and Channel-trend charts
        # ------------------------------------------------------------
        self.active_tab = "flow"

        self.ax_tab_flow  = self.fig.add_axes([0.08, 0.90, 0.17, 0.06])
        self.btn_tab_flow = Button(self.ax_tab_flow, "Flow vs ΔP", color=config.COLOR_ACCENT, hovercolor=config.COLOR_ACCENT)
        self.btn_tab_flow.label.set_color(config.COLOR_ON_PRIMARY)
        self.btn_tab_flow.label.set_fontweight("bold")
        self.btn_tab_flow.on_clicked(lambda _e: self._switch_tab("flow"))

        self.ax_tab_channels  = self.fig.add_axes([0.27, 0.90, 0.21, 0.06])
        self.btn_tab_channels = Button(self.ax_tab_channels, "4-Channel Trend", color=config.COLOR_MUTED_HOVER, hovercolor=config.COLOR_MUTED_HOVER)
        self.btn_tab_channels.label.set_color(config.COLOR_TEXT)
        self.btn_tab_channels.label.set_fontweight("bold")
        self.btn_tab_channels.on_clicked(lambda _e: self._switch_tab("channels"))

    def _init_state(self) -> None:
        """Initialise all mutable state containers."""
        self.series_data:   Dict[str, Dict[str, list]] = {}
        self.recorded_time: Series = Series(SID_TIME)
        self.recorded_flow: Series = Series(SID_FLOW)

        # Rolling history buffers for the 4-channel trend chart
        for sid in config.CHANNEL_SERIES:
            self.series_data[sid] = {
                "X": deque(maxlen=config.CHANNEL_MAXLEN),
                "Y": deque(maxlen=config.CHANNEL_MAXLEN),
            }

        self.lines: Dict[str, plt.Line2D] = {}

        self.is_running:       bool  = False
        self.is_recording:     bool  = False
        self.reset_time_flag:  bool  = False
        self.current_loop_time: float = 0.0
        self._start_time:      float = time.time()
        self._timing_text_val: str   = ""  # tracks last-written value to skip no-op set_text calls
        self.last_saved_path:  str | None = None

        self.data_queue:       queue.Queue[DataPoint] = queue.Queue()
        self.event_queue:      queue.Queue[dict]      = queue.Queue()
        self._remote_cmd_queue: queue.Queue[str]      = queue.Queue()
        self.stop_event = threading.Event()
        self._remote_server: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _start_background_thread(self) -> None:
        self._event_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._event_thread.start()

    def _start_remote_control_server(self) -> None:
        """Serve the localhost-only remote-control HTTP API on a daemon thread."""
        handler = type("_BoundRemoteControlHandler", (_RemoteControlHandler,), {"dashboard": self})
        self._remote_server = ThreadingHTTPServer((config.REMOTE_CONTROL_HOST, config.REMOTE_CONTROL_PORT), handler)
        threading.Thread(target=self._remote_server.serve_forever, daemon=True).start()
        print(f"[Dashboard] Remote control server listening on "
              f"http://{config.REMOTE_CONTROL_HOST}:{config.REMOTE_CONTROL_PORT} (status, toggle_record).")

    def _stop_remote_control_server(self) -> None:
        if self._remote_server is not None:
            self._remote_server.shutdown()
            self._remote_server.server_close()
            self._remote_server = None

    def _event_loop(self) -> None:
        """
        QMH-style event loop: blocking get handles commands immediately;
        queue.Empty is the timeout / idle case.
        """
        while not self.stop_event.is_set():
            try:
                cmd_dict = self.event_queue.get(timeout=self.update_interval / 1000.0)
                self._handle_command(cmd_dict)
            except queue.Empty:
                pass

    def _handle_command(self, cmd_dict: dict) -> None:
        cmd = cmd_dict.get("cmd", "")
        if cmd == CMD_START:
            self.clear_data_queue()
        elif cmd == CMD_EXIT:
            self.stop_event.set()
        # CMD_STOP: intentionally no-op; pause is handled via the is_running flag

    def clear_data_queue(self) -> None:
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

        # Dispatch any remotely-queued commands on the UI thread, exactly as if
        # the user had clicked the button or pressed F8.
        while True:
            try:
                remote_cmd = self._remote_cmd_queue.get_nowait()
            except queue.Empty:
                break
            if remote_cmd == REMOTE_CMD_TOGGLE_RECORD:
                self._on_record_clicked(None)

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

        if self.is_recording:
            blink_on = int(now * 2) % 2 == 0
            self.rec_indicator.set_color(config.COLOR_RECORDING)
            self.rec_indicator.set_alpha(1.0 if blink_on else 0.25)
        else:
            self.rec_indicator.set_color(config.COLOR_MUTED)
            self.rec_indicator.set_alpha(1.0)

        has_new = False
        has_new_channels = False
        while True:
            try:
                series_id, x, y = self.data_queue.get_nowait()
            except queue.Empty:
                break

            self._ensure_series(series_id)

            if series_id in self.channel_lines:
                self.series_data[series_id]["X"].append(x)
                self.series_data[series_id]["Y"].append(y)
                has_new_channels = True
                continue

            if self.is_recording:
                sample_count = None
                if series_id == SID_TIME:
                    self.recorded_time.append(x, y)
                    sample_count = len(self.recorded_time.xs)
                elif series_id == SID_FLOW:
                    self.recorded_flow.append(x, y)
                    sample_count = len(self.recorded_flow.xs)

                if sample_count is not None and sample_count % 10 == 0:
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
                if sid == SID_FLOW and d["Y"]:
                    self.live_val_text.set_text(
                        f"dP: {d['X'][-1]:.0f} PSI | Flow: {d['Y'][-1]:.1f} GPM"
                    )

        if has_new_channels:
            for sid, line in self.channel_lines.items():
                d = self.series_data[sid]
                line.set_data(d["X"], d["Y"])
            latest_t = self.series_data[config.SID_CH_HP]["X"][-1]
            self.ax_channels.set_xlim(max(0.0, latest_t - config.CHANNEL_WINDOW_S), max(latest_t, config.CHANNEL_WINDOW_S))

        return (
            list(self.lines.values()) + list(self.channel_lines.values())
            + [self.timing_text, self.live_val_text, self.loop_timing_text, self.rec_indicator]
        )

    def _ensure_series(self, series_id: str) -> None:
        """Create series_data entry and a blank Line2D on first encounter."""
        if series_id in self.series_data:
            return
        self.series_data[series_id] = {"X": [], "Y": []}
        if series_id == SID_FLOW:
            line, = self.ax.plot(
                [], [], marker="o", markersize=5, linewidth=0,
                markerfacecolor=config.COLOR_ACCENT, markeredgecolor="none",
                alpha=0.85, zorder=3,
            )
            self.lines[series_id] = line

    # ------------------------------------------------------------------
    # Public acquisition control
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start (or resume) data acquisition."""
        self.is_running  = True
        self._start_time = time.time()
        self.event_queue.put({"cmd": CMD_START})

    def stop(self) -> None:
        """Pause data acquisition without resetting state."""
        self.is_running = False
        self.event_queue.put({"cmd": CMD_STOP})

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------

    def _on_record_clicked(self, _event) -> None:
        """Toggle recording; save to CSV on a background thread when stopped."""
        if self.is_recording:
            self.is_recording = False
            self.btn_record.label.set_text("●  Start Record")
            self.btn_record.color = config.COLOR_IDLE
            self.btn_record.hovercolor = config.COLOR_IDLE_HOVER
            self.btn_record.ax.set_facecolor(config.COLOR_IDLE)
            # Snapshot recorded series before handing to the background thread
            time_snapshot = self.recorded_time.snapshot()
            flow_snapshot = self.recorded_flow.snapshot()
            threading.Thread(
                target=self._save_and_track_path,
                args=(time_snapshot, flow_snapshot),
                daemon=True,
            ).start()
        else:
            self.is_recording    = True
            self.btn_record.label.set_text("●  Stop Record")
            self.btn_record.color = config.COLOR_RECORDING
            self.btn_record.hovercolor = config.COLOR_RECORDING_HOVER
            self.btn_record.ax.set_facecolor(config.COLOR_RECORDING)
            self.recorded_time.clear()
            self.recorded_flow.clear()
            self.reset_time_flag = True
            self._start_time     = time.time()
            for sid in self.series_data:
                self.series_data[sid]["X"].clear()
                self.series_data[sid]["Y"].clear()
                if sid in self.lines:
                    self.lines[sid].set_data([], [])
                if sid in self.channel_lines:
                    self.channel_lines[sid].set_data([], [])
            self.ax_channels.set_xlim(0, config.CHANNEL_WINDOW_S)
            self.live_val_text.set_text("dP: 0.0 PSI | Flow: 0.0 GPM")

        self.fig.canvas.draw_idle()

    def _save_and_track_path(self, time_series: Series, flow_series: Series) -> None:
        """Background-thread wrapper around DataLogger.save() that records the path for /status."""
        self.last_saved_path = self.data_logger.save(
            time_series, flow_series, self.part_number, self.serial_number
        )

    def _switch_tab(self, tab: str) -> None:
        """Show the Flow chart or the 4-channel trend chart, highlighting the active tab."""
        if tab == self.active_tab:
            return
        self.active_tab = tab
        flow_active = tab == "flow"

        self.ax.set_visible(flow_active)
        self.ax_channels.set_visible(not flow_active)

        for btn, active in ((self.btn_tab_flow, flow_active), (self.btn_tab_channels, not flow_active)):
            color = config.COLOR_ACCENT if active else config.COLOR_MUTED_HOVER
            hover = config.COLOR_ACCENT if active else config.COLOR_MUTED_HOVER
            btn.color, btn.hovercolor = color, hover
            btn.ax.set_facecolor(color)
            btn.label.set_color(config.COLOR_ON_PRIMARY if active else config.COLOR_TEXT)

        self.fig.canvas.draw_idle()

    def _on_close(self, _event) -> None:
        self.stop_event.set()
        self.event_queue.put({"cmd": CMD_EXIT})
        self.is_running = False
        self._stop_remote_control_server()
        anim = getattr(self, "anim", None)
        if anim is not None and anim.event_source is not None:
            anim.event_source.stop()
        for callback in self._on_close_callbacks:
            callback()

    def _on_key(self, event) -> None:
        key = str(getattr(event, "key", "") or "").lower()
        if key == "f8":
            self._on_record_clicked(event)
        elif key == "f4":
            try:
                plt.close(self.fig)
            except Exception:
                pass
