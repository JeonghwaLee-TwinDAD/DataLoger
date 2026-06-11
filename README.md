# F18 Blowdown Chamber - High-Speed Data Logger

A high-speed data acquisition system and live visualization dashboard designed for the F18 Blowdown Chamber test stand.

This project utilizes NI DAQ hardware to capture high-pressure, low-pressure, velocity, and solenoid voltage signals. It computes differential pressure (Delta-P) and flow rates in real-time, displaying them on a Matplotlib UI.

## Features

- **High-Speed Acquisition:** Hardware polling at ~1 kHz (~800 Hz target loop rate) for precise measurements.
- **Live Dashboard:** Real-time GUI built with Matplotlib, showing Delta-P vs. Flow alongside a visual Region of Interest (ROI).
- **Multithreaded Architecture:** Producer/Consumer design pattern (mirroring a LabVIEW QMH) offloads hardware polling and CSV file I/O to background daemon threads, keeping the UI responsive.
- **Compressibility Compensation:** Corrects measured flow for pressure-transient effects within the test rig's hydraulic lines.
- **Data Export:** Seamlessly exports recorded series data (without blocking the plot) to timestamped CSV files in the `C:\_Data_Log\` directory.

## Hardware Configuration

Assumes an NI DAQ device at `Dev1` with the following channel mappings:
- `Dev1/ai0`: High-pressure transducer
- `Dev1/ai1`: Low-pressure transducer
- `Dev1/ai2`: Velocity sensor
- `Dev1/ai3`: Solenoid voltage

## Requirements

The following Python libraries are required (see `environment.yml` for conda environment details if applicable):

- `nidaqmx`
- `matplotlib`
- `pandas`
- `numpy`

## Usage

Launch the data logger by executing the main script:

```bash
python High_Speed_Logger.py
```

### Keyboard & UI Controls

- **Start / Stop Record:** Click the UI button or press **F8** to toggle recording. When stopped, the data is automatically collated and saved to a CSV on disk.
- **Exit:** Close the Matplotlib window or press **F4** to safely disconnect from the DAQ and stop background threads.

## Architecture Notes

The application is split into the `f18_blowdown` package (see `f18_blowdown/__init__.py`),
with `High_Speed_Logger.py` as a thin entry point that wires the pieces together:

- **`f18_blowdown/config.py`:** All tunable constants — hardware wiring (DAQ device,
  channels, sample rate), test-stand identity, hydraulic parameters, file paths,
  remote-control port, and the dashboard's visual theme.
- **`f18_blowdown/models.py`:** The `Series` data model (parallel `xs`/`ys` lists with
  `snapshot()` for thread-safe handoff) and the queue-protocol constants shared
  between acquisition and the dashboard.
- **`f18_blowdown/acquisition.py`:** `DataProducer` owns the NI DAQ task. Its
  `run_producer_loop()` polls hardware at ~800 Hz, runs the hydraulic
  calculations (`processing.process_data`), and pushes resulting `DataPoint`
  tuples to the dashboard's thread-safe Queue.
- **`f18_blowdown/processing.py`:** Pure `process_data()` function implementing the
  compressibility-corrected flow calculation.
- **`f18_blowdown/dashboard.py`:** `BlowdownDashboard` (the consumer/UI). Uses
  Matplotlib's `FuncAnimation` to drain the queue every 500 ms, appending data to
  line plots and safely down-sampling background data to prevent clutter. Also
  hosts the background event loop (`START`/`STOP`/`EXIT` tokens) and the
  localhost remote-control HTTP API.
- **`f18_blowdown/logger.py`:** `DataLogger` — a stateless CSV exporter
  (`save()` / `save_async()`) that serialises recorded Time/Flow `Series` to
  timestamped CSV files. `save_async()` snapshots the series and dispatches
  `pandas.DataFrame.to_csv` to an isolated daemon thread so large recordings
  never block the UI.