"""
High_Speed_Logger.py
---------------------
Entry point for the F18 Blowdown Chamber high-speed data logger.

Wires together DataProducer (NI-DAQ acquisition + hydraulic calc),
BlowdownDashboard (live Matplotlib UI, recording controls, and the localhost
remote-control API), and DataLogger (CSV export), then runs the application.

See f18_blowdown/__init__.py for the full package layout.
"""

import threading

import matplotlib.pyplot as plt

from f18_blowdown import config
from f18_blowdown.acquisition import DataProducer, run_producer_loop
from f18_blowdown.dashboard import BlowdownDashboard


def main() -> None:
    producer  = DataProducer()
    dashboard = BlowdownDashboard()

    producer.connect()
    dashboard.daq_connected = producer.is_connected
    dashboard.add_close_callback(producer.disconnect)

    dashboard._build_figure()
    dashboard._build_layout()
    dashboard._init_state()
    dashboard._start_background_thread()
    dashboard._start_remote_control_server()
    dashboard._start_animation()

    producer_thread = threading.Thread(
        target=run_producer_loop,
        args=(producer, dashboard, config.PARAMETERS),
        daemon=True,
    )
    producer_thread.start()

    plt.show()


if __name__ == "__main__":
    main()
