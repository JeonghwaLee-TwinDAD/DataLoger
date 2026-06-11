"""
config.py
---------
Tunable configuration for the F18 Blowdown Chamber data logger.

Everything that is specific to a test stand, hardware wiring, or visual theme
lives here so that retargeting the logger to a different stand or DAQ
configuration does not require touching acquisition, processing, or UI code.
"""

# ---------------------------------------------------------------------------
# Test-stand identity & operating envelope
# ---------------------------------------------------------------------------
PRESSURE_MAX:      int = 7000
FLOW_MAX:          int = 600
PART_NUMBER:       str = "1D8674-P0100"
TEST_STAND_NUMBER: str = "F18_BD_001"

# Hydraulic blowdown calculation parameters (see processing.process_data)
PARAMETERS = {
    "CIS/GPM":        3.85,
    "Area Attention": 24.2,
    "Area RAM":       4.8852,
    "Length":         24,
    "Beta":           250000,
}

# ---------------------------------------------------------------------------
# Application timing & I/O
# ---------------------------------------------------------------------------
UPDATE_INTERVAL:     int = 500     # milliseconds
DATALOG_PATH:        str = "C:\\_Data_Log\\"
REMOTE_CONTROL_HOST: str = "127.0.0.1"
REMOTE_CONTROL_PORT: int = 8787

# ---------------------------------------------------------------------------
# DAQ hardware configuration
# ---------------------------------------------------------------------------
DAQ_DEVICE       = "Dev1"
SAMPLE_RATE      = 1000   # Hz
SAMPLES_PER_READ = 10     # samples per channel per read (~10 ms per chunk at 1 kHz)

# Channel indices within the 4-channel task ({DAQ_DEVICE}/ai0:3)
CH_HIGH_PRESSURE    = 0   # ai0 — high-pressure transducer
CH_LOW_PRESSURE     = 1   # ai1 — low-pressure transducer
CH_VELOCITY         = 2   # ai2 — velocity sensor
CH_SOLENOID_VOLTAGE = 3   # ai3 — solenoid voltage

# Series identifiers for the raw 4-channel trend chart (one per AI channel)
SID_CH_HP  = "AI0_HighPressure"
SID_CH_LP  = "AI1_LowPressure"
SID_CH_VEL = "AI2_Velocity"
SID_CH_SOL = "AI3_SolenoidVoltage"
CHANNEL_SERIES = (SID_CH_HP, SID_CH_LP, SID_CH_VEL, SID_CH_SOL)
CHANNEL_LABELS = {
    SID_CH_HP:  "AI0 — High Pressure",
    SID_CH_LP:  "AI1 — Low Pressure",
    SID_CH_VEL: "AI2 — Velocity",
    SID_CH_SOL: "AI3 — Solenoid Voltage",
}

CHANNEL_WINDOW_S = 10   # seconds of history shown on the 4-channel trend chart
CHANNEL_MAXLEN   = SAMPLE_RATE * (CHANNEL_WINDOW_S + 2)

# ---------------------------------------------------------------------------
# Visual theme — Google Material Design palette
# ---------------------------------------------------------------------------
FONT_FAMILY = ["Segoe UI", "Arial", "DejaVu Sans", "sans-serif"]

COLOR_BG              = "#F1F3F4"   # app background (Material surface-dim)
COLOR_PLOT_BG         = "#FFFFFF"   # chart card surface
COLOR_GRID            = "#E8EAED"   # gridlines / card outline
COLOR_TEXT            = "#202124"   # on-surface (primary text)
COLOR_MUTED           = "#5F6368"   # on-surface-variant (secondary text)
COLOR_MUTED_HOVER     = "#DADCE0"   # surface-variant (inactive tab / hover)
COLOR_ON_PRIMARY      = "#FFFFFF"   # text/icons on filled colored buttons
COLOR_ACCENT          = "#1A73E8"   # Google Blue 600 (primary)
COLOR_ENVELOPE        = "#1E8E3E"   # Google Green 700 (operating envelope)
COLOR_IDLE            = "#1E8E3E"   # Google Green 600 (Start Record)
COLOR_IDLE_HOVER      = "#188038"   # Google Green 700
COLOR_RECORDING       = "#D93025"   # Google Red 600 (Stop Record / live indicator)
COLOR_RECORDING_HOVER = "#B31412"   # Google Red 700

# Google's classic four-color brand palette for the per-channel trend chart
CHANNEL_COLORS = {
    SID_CH_HP:  "#EA4335",  # Google Red
    SID_CH_LP:  "#FBBC04",  # Google Yellow
    SID_CH_VEL: "#34A853",  # Google Green
    SID_CH_SOL: "#4285F4",  # Google Blue
}
