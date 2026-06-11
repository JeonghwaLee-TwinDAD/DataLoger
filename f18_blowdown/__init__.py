"""
f18_blowdown
------------
F18 Blowdown Chamber high-speed data logger.

Package layout (per DL-REQ-001 "Universal Data Logger" requirements):
  - config.py      Tunable constants: hardware wiring, theme, file paths, parameters.
  - models.py      Series data model and queue-protocol constants.
  - logger.py      DataLogger — stateless CSV export (save / save_async).
  - processing.py  Hydraulic blowdown calculations (process_data).
  - acquisition.py DataProducer — NI-DAQ hardware interface and producer loop.
  - dashboard.py   BlowdownDashboard — live Matplotlib UI, recording controls,
                   and the localhost remote-control API.
"""
