"""
acquisition.py
---------------
NI-DAQ hardware interface and the producer loop that feeds the dashboard's
data queue.

Design pattern (mirrors LabVIEW QMH + Producer/Consumer):
  • DataProducer owns the DAQ task and exposes read_voltages().
  • run_producer_loop() polls hardware at ~800 Hz, runs the hydraulic
    calculation, and pushes DataPoints onto the dashboard's data_queue.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Dict

import numpy as np
import nidaqmx
from nidaqmx.constants import AcquisitionType

from . import config
from .models import SID_FLOW, SID_TIME
from .processing import process_data

if TYPE_CHECKING:
    from .dashboard import BlowdownDashboard


class DataProducer:
    """Owns a continuous-acquisition NI-DAQ task on {device}/ai0:3."""

    def __init__(self, device: str = config.DAQ_DEVICE) -> None:
        self.device = device
        self.daq_task: nidaqmx.Task | None = None
        self._sim_start: float | None = None

    @property
    def is_connected(self) -> bool:
        return self.daq_task is not None

    def connect(self) -> None:
        """Open a 4-channel continuous acquisition task on {device}/ai0:3."""
        try:
            self.daq_task = nidaqmx.Task("DataLoggerDAQ")
            self.daq_task.ai_channels.add_ai_voltage_chan(
                f"{self.device}/ai0:3", min_val=-10.0, max_val=10.0
            )
            self.daq_task.timing.cfg_samp_clk_timing(
                rate=config.SAMPLE_RATE,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=config.SAMPLES_PER_READ * 10,   # buffer = 10x read chunk
            )
            self.daq_task.start()
            print(f"[Acquisition] DAQ task started -> {self.device}/ai0:3 "
                  "(high-pressure, low-pressure, velocity, solenoid-voltage).")
        except nidaqmx.DaqError as e:
            print(f"[Acquisition] DAQmx task failed to start: {e}")
            self.daq_task = None

    def disconnect(self) -> None:
        """Safely stop and close the DAQ task."""
        if self.daq_task is not None:
            try:
                self.daq_task.stop()
            except nidaqmx.DaqError:
                pass
            self.daq_task.close()
            self.daq_task = None
            print("[Acquisition] DAQ task closed.")

    def read_voltages(self) -> "np.ndarray":
        """
        Read one chunk from all four channels and return per-channel mean voltages.

        Returns:
            np.ndarray shape (4,): [high_pressure_V, low_pressure_V,
                                    velocity_V, solenoid_voltage_V]
            Falls back to simulated signals if the DAQ task is unavailable
            (see _simulate_voltages).
        """
        if self.daq_task is None:
            return self._simulate_voltages()
        data = self.daq_task.read(number_of_samples_per_channel=config.SAMPLES_PER_READ)
        arr = np.array(data)                      # shape: (4, SAMPLES_PER_READ)
        if arr.ndim == 1:                         # single-sample edge case
            arr = arr.reshape(4, config.SAMPLES_PER_READ)
        return arr.mean(axis=1)                   # (4,) one mean voltage per channel

    def _simulate_voltages(self) -> "np.ndarray":
        """
        Generate synthetic voltages spanning the sensors' calibrated ranges
        when no DAQ hardware is connected, so the rest of the pipeline
        (processing, plotting, recording) can be exercised end-to-end.

        Returns:
            np.ndarray shape (4,): [high_pressure_V, low_pressure_V,
                                    velocity_V, solenoid_voltage_V]
        """
        if self._sim_start is None:
            self._sim_start = time.time()
        t = time.time() - self._sim_start

        hp_v  = 2.5 + 2.3 * math.sin(2 * math.pi * t / 24.0)
        lp_v  = 0.5
        vel_v = 2.7 + 2.6 * math.sin(2 * math.pi * t / 24.0 - math.pi / 6)
        sol_v = 2.5 + 2.5 * math.sin(2 * math.pi * t / 10.0)

        return np.array([hp_v, lp_v, vel_v, sol_v])


def run_producer_loop(
    producer: DataProducer,
    dashboard: "BlowdownDashboard",
    parameters: Dict[str, float],
) -> None:
    """Poll the DAQ at ~800 Hz, run the hydraulic calc, and push DataPoints to dashboard.data_queue."""
    dashboard.start()
    start_time = time.time()
    last_time  = start_time
    last_hp    = 0.0
    last_len   = parameters.get("Length", 0.0)

    while not dashboard.stop_event.is_set():
        if dashboard.reset_time_flag:
            start_time = time.time()
            last_time  = start_time
            dashboard.reset_time_flag = False
            dashboard.clear_data_queue()

        now = time.time()
        dt  = now - last_time

        # Target ~800 Hz; sleep briefly to avoid burning a full CPU core
        if dt < 0.00125:
            time.sleep(0.0005)
            continue

        last_time = now
        dashboard.current_loop_time = dt
        t = now - start_time

        voltages = producer.read_voltages()
        hp_val  = float(voltages[config.CH_HIGH_PRESSURE]) * 1500.0
        lp_val  = float(voltages[config.CH_LOW_PRESSURE]) * 150.0
        vel_val = float(voltages[config.CH_VELOCITY]) * 17.5

        processed = process_data(
            hp=hp_val, lp=lp_val, vel=vel_val,
            last_hp=last_hp, last_len=last_len, delta_t=dt,
            parameters=parameters,
        )
        last_hp  = processed["last_hp_out"]
        last_len = processed["last_len_out"]

        dashboard.data_queue.put((SID_TIME, t, t))
        dashboard.data_queue.put((SID_FLOW, processed["delta_pressure"], processed["flow"]))

        for sid, voltage in zip(config.CHANNEL_SERIES, voltages):
            dashboard.data_queue.put((sid, t, float(voltage)))
