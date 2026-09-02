"""
DCM Alignment Console — PyQt6 desktop application.

Tabs:
  1. Setup        — PV names, scan parameters, connection test
  2. Energy Table — Editable lookup table (MonoE, UE, Roll, Pitch)
  3. Alignment    — Step-by-step alignment runner with live scan plots
  4. Mirror       — Placeholder for mirror alignment substeps

Run:
    python dcm_align_app.py

Optional EPICS support (pyepics):
    pip install pyepics
    Uncheck "Simulation mode" in Setup to connect to real hardware.
"""

import sys
import time
import csv
import json
import os
import random
import math
import threading
import concurrent.futures
from datetime import datetime
import codecs
from pathlib import Path

# pyepics on Windows passes 'utf-8:surrogatescape' as a codec name, which Python rejects.
# codecs.lookup normalises '-' → '_' before calling search functions, so the name
# arrives as 'utf_8:surrogatescape'. Register an alias so epics can initialise correctly.
try:
    codecs.lookup('utf-8:surrogatescape')
except LookupError:
    codecs.register(lambda name: codecs.lookup('utf-8') if 'surrogateescape' in name else None)

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTabWidget, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QSplitter, QFrame, QFileDialog, QMessageBox, QProgressBar,
    QAbstractItemView, QSizePolicy, QScrollArea, QStatusBar, QDialog,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QObject, QSettings, QSize,
)
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPixmap, QPainter, QPen

import pyqtgraph as pg

# ─── Try importing pyepics; fall back to simulation ──────────────────────────
try:
    import epics
    EPICS_AVAILABLE = True
except ImportError:
    EPICS_AVAILABLE = False

# ─── Colour palettes ─────────────────────────────────────────────────────────
THEMES = {
    "Ocean Light": {
        "bg": "#f5f7fa", "surface": "#eaeef2", "surface_hi": "#dde2e8",
        "border": "#c8d0d8", "cyan": "#0a7a82", "cyan_dim": "#c8eef0",
        "green": "#1a7f37", "amber": "#9a6700", "red": "#cf2218",
        "text_pri": "#1f2328", "text_sec": "#57606a", "text_dim": "#6e7781",
        "tag_green_bg": "#e6f4ea", "tag_amber_bg": "#fff3cd", "tag_red_bg": "#fce8e6",
    },
    "Midnight": {
        "bg": "#0d1117", "surface": "#161b22", "surface_hi": "#21262d",
        "border": "#30363d", "cyan": "#2dd4d9", "cyan_dim": "#0c2e30",
        "green": "#3fb950", "amber": "#e3b341", "red": "#f85149",
        "text_pri": "#e6edf3", "text_sec": "#8b949e", "text_dim": "#6e7781",
        "tag_green_bg": "#1a3224", "tag_amber_bg": "#2d2008", "tag_red_bg": "#2d1618",
    },
    "Slate Blue": {
        "bg": "#f1f5f9", "surface": "#e2e8f0", "surface_hi": "#cbd5e1",
        "border": "#94a3b8", "cyan": "#2563eb", "cyan_dim": "#dbeafe",
        "green": "#16a34a", "amber": "#d97706", "red": "#dc2626",
        "text_pri": "#0f172a", "text_sec": "#334155", "text_dim": "#64748b",
        "tag_green_bg": "#dcfce7", "tag_amber_bg": "#fef3c7", "tag_red_bg": "#fee2e2",
    },
    "Carbon": {
        "bg": "#1c1c1e", "surface": "#2c2c2e", "surface_hi": "#3a3a3c",
        "border": "#48484a", "cyan": "#f5c542", "cyan_dim": "#3a2d00",
        "green": "#30d158", "amber": "#ff9f0a", "red": "#ff453a",
        "text_pri": "#f2f2f7", "text_sec": "#aeaeb2", "text_dim": "#636366",
        "tag_green_bg": "#1a3824", "tag_amber_bg": "#3a2800", "tag_red_bg": "#380c0a",
    },
}
PAL = dict(THEMES["Ocean Light"])


def build_qss(pal):
    return f"""
QMainWindow, QDialog {{
    background: {pal['bg']};
}}
QWidget {{
    background: {pal['bg']};
    color: {pal['text_pri']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {pal['border']};
    background: {pal['surface']};
}}
QTabBar::tab {{
    background: {pal['surface']};
    color: {pal['text_sec']};
    padding: 8px 20px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    color: {pal['cyan']};
    border-bottom: 2px solid {pal['cyan']};
    background: {pal['surface']};
}}
QGroupBox {{
    border: 1px solid {pal['border']};
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px;
    background: {pal['surface']};
    font-weight: 600;
    color: {pal['text_sec']};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QLineEdit {{
    background: {pal['bg']};
    border: 1px solid {pal['border']};
    border-radius: 4px;
    padding: 5px 8px;
    color: {pal['cyan']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 11px;
    selection-background-color: {pal['cyan_dim']};
}}
QLineEdit:focus {{
    border: 1px solid {pal['cyan']};
}}
QDoubleSpinBox, QSpinBox {{
    background: {pal['bg']};
    border: 1px solid {pal['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {pal['cyan']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1px solid {pal['cyan']};
}}
QComboBox {{
    background: {pal['bg']};
    border: 1px solid {pal['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {pal['text_pri']};
}}
QComboBox::drop-down {{
    border: none;
}}
QPushButton {{
    background: {pal['bg']};
    border: 1px solid {pal['border']};
    border-radius: 5px;
    padding: 6px 16px;
    color: {pal['text_sec']};
    font-weight: 600;
    font-size: 12px;
}}
QPushButton:hover {{
    background: {pal['bg']};
    border-color: {pal['cyan']};
    color: {pal['cyan']};
}}
QPushButton:disabled {{
    background: {pal['surface']};
    color: {pal['border']};
    border-color: {pal['surface_hi']};
}}
QPushButton#primary {{
    background: {pal['cyan_dim']};
    color: {pal['text_pri']};
    border: 2px solid {pal['cyan']};
    padding: 7px 20px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#primary:hover {{
    background: {pal['cyan']};
    color: {pal['text_pri']};
    border-color: {pal['cyan']};
}}
QPushButton#primary:disabled {{
    background: {pal['surface_hi']};
    color: {pal['text_dim']};
    border-color: {pal['border']};
}}
QPushButton#danger {{
    border-color: {pal['red']};
    color: {pal['red']};
}}
QPushButton#danger:hover {{
    background: {pal['tag_red_bg']};
}}
QTableWidget {{
    background: {pal['surface']};
    alternate-background-color: {pal['surface_hi']};
    border: 1px solid {pal['border']};
    border-radius: 4px;
    gridline-color: {pal['border']};
    selection-background-color: {pal['cyan_dim']};
    selection-color: {pal['cyan']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 12px;
}}
QHeaderView::section {{
    background: {pal['surface_hi']};
    color: {pal['text_dim']};
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {pal['border']};
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QTextEdit {{
    background: {pal['bg']};
    border: 1px solid {pal['border']};
    border-radius: 4px;
    color: {pal['text_sec']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 11px;
    padding: 6px;
}}
QScrollBar:vertical {{
    background: {pal['bg']};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {pal['border']};
    border-radius: 4px;
    min-height: 20px;
}}
QCheckBox {{
    color: {pal['text_sec']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {pal['border']};
    border-radius: 3px;
    background: {pal['bg']};
}}
QCheckBox::indicator:checked {{
    background: {pal['cyan']};
    border-color: {pal['cyan']};
}}
QProgressBar {{
    background: {pal['surface_hi']};
    border: 1px solid {pal['border']};
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {pal['cyan']};
    border-radius: 3px;
}}
QStatusBar {{
    background: {pal['surface']};
    color: {pal['text_dim']};
    font-size: 11px;
    border-top: 1px solid {pal['border']};
}}
QLabel#readout_value {{
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 20px;
    font-weight: 700;
    color: {pal['cyan']};
}}
QLabel#readout_label {{
    font-size: 10px;
    color: {pal['text_dim']};
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QLabel#step_title {{
    font-size: 13px;
    font-weight: 600;
    color: {pal['text_pri']};
}}
QLabel#tag_green {{
    background: {pal['tag_green_bg']};
    border: 1px solid {pal['green']};
    color: {pal['green']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_amber {{
    background: {pal['tag_amber_bg']};
    border: 1px solid {pal['amber']};
    color: {pal['amber']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_red {{
    background: {pal['tag_red_bg']};
    border: 1px solid {pal['red']};
    color: {pal['red']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_grey {{
    background: {pal['surface_hi']};
    border: 1px solid {pal['border']};
    color: {pal['text_dim']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_cyan {{
    background: {pal['cyan_dim']};
    border: 1px solid {pal['cyan']};
    color: {pal['cyan']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
"""


QSS = build_qss(PAL)

AUTO_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dcm_config.json")

MOTOR_PV_KEYS = {"mono_energy", "roll", "pitch", "mir_slit_top", "mir_slit_bot"}

# ─── Default config ───────────────────────────────────────────────────────────
DEFAULT_PVS = {
    "mono_energy":      "DCM:mono:Energy",
    "und_energy":       "DCM:und:Energy",
    "roll":             "DCM:roll:SP",
    "pitch":            "DCM:pitch:SP",
    "piezo_pitch":      "DCM:piezo:pitch:SP",
    "piezo_roll":       "DCM:piezo:roll:SP",
    "bpm_x":            "BPM:x:readback",
    "bpm_y":            "BPM:y:readback",
    "bpm_intensity":    "BPM:intensity:readback",
    "feedback_h":       "BPM:feedback:H:enable",
    "feedback_v":       "BPM:feedback:V:enable",
    "und_harmonic":     "",
    "und_start":        "",
    "mir_slit_top":     "15IDA:m9",
    "mir_slit_bot":     "15IDA:m10",
    "mir_piezo_pitch":  "",
    "ion_chamber":      "",
    "mir_slit_center":  "",
    "mir_slit_size":    "",
    "bpm_sen":          "15ID:FX4_1:Range",
    "ic_sen_unit":      "15IDC:A2sens_unit.VAL",
    "ic_sen_num":       "15IDC:A2sens_num.VAL",
}

def calc_harmonic(mono_e):
    if mono_e < 13:
        return 1
    elif mono_e < 28:
        return 3
    return 5

DEFAULT_LOOKUP = [
    {"mono_e": 8.0,  "ue": 9.8,  "roll": 0.412, "pitch": 2.341, "harmonic": 1, "bpm_sen": "1", "ic_sen_unit": "2", "ic_sen_num": "2"},
    {"mono_e": 10.0, "ue": 12.1, "roll": 0.398, "pitch": 2.187, "harmonic": 1, "bpm_sen": "1", "ic_sen_unit": "2", "ic_sen_num": "2"},
    {"mono_e": 12.0, "ue": 14.6, "roll": 0.381, "pitch": 2.054, "harmonic": 1, "bpm_sen": "1", "ic_sen_unit": "2", "ic_sen_num": "2"},
    {"mono_e": 15.0, "ue": 18.2, "roll": 0.362, "pitch": 1.893, "harmonic": 3, "bpm_sen": "1", "ic_sen_unit": "2", "ic_sen_num": "2"},
    {"mono_e": 20.0, "ue": 24.1, "roll": 0.344, "pitch": 1.712, "harmonic": 3, "bpm_sen": "1", "ic_sen_unit": "2", "ic_sen_num": "2"},
]

DEFAULT_RECORD_PVS = [
    # ── Core motor / beam settings ──
    {"label": "Mono Energy (keV)",              "pv": "ID15A1:DCMM:XTAL:E.RBV",                   "checked": True,  "locked": True},
    {"label": "XTAL",                           "pv": "ID15A1:DCMM:BLMODE:ACS:RET_RBV",            "checked": True,  "locked": True},
    {"label": "Undulator Energy (keV)",         "pv": "S15ID:USID:EnergyM.VAL",                    "checked": True,  "locked": True},
    {"label": "Undulator Gap (mm)",             "pv": "S15ID:USID:GapM.VAL",                       "checked": True,  "locked": True},
    {"label": "Undulator Harmonic",             "pv": "S15ID:USID:HarmonicValueC",                 "checked": True,  "locked": True},
    {"label": "Ring Current (mA)",              "pv": "S-DCCT:CurrentM",                           "checked": True,  "locked": True},
    {"label": "DCM Pitch Motor (µrad)",         "pv": "ID15A1:DCMM:XTAL:PI2.RBV",                 "checked": True,  "locked": True},
    {"label": "DCM Pitch Encoder",              "pv": "ID15A1:DCMM:XTAL:FIPI2",                    "checked": True,  "locked": True},
    {"label": "DCM Roll Motor (µrad)",          "pv": "ID15A1:DCMM:XTAL:RO2.RBV",                 "checked": True,  "locked": True},
    {"label": "DCM Roll Encoder",               "pv": "ID15A1:DCMM:XTAL:FIRO2.RBV",               "checked": True,  "locked": True},
    {"label": "Mirror Slit Center (mm)",        "pv": "15IDA:MirVt2.D",                            "checked": True,  "locked": True},
    {"label": "Mirror Angle (µrad)",            "pv": "ID15A1:DMS:VFM:PI.RBV",                     "checked": True,  "locked": True},
    {"label": "Mirror 1st Y (µm)",              "pv": "ID15A1:DMS:VFM:PI.RBV",                     "checked": True,  "locked": True},
    {"label": "Mirror 2nd Y (µm)",              "pv": "ID15A1:DMS:VDM:PI.RBV",                     "checked": True,  "locked": True},
    {"label": "BPM Max Intensity",              "pv": "15IDC:userTran10.E",                        "checked": True,  "locked": True},
    {"label": "BPM Sensitivity",                "pv": "15ID:FX4_1:Range_RBV",                      "checked": True,  "locked": True},
    {"label": "MonP Max Intensity",             "pv": "15IDC:scaler1.S3",                          "checked": True,  "locked": True},
    {"label": "MonP Sensitivity Unit",          "pv": "15IDC:A2sens_unit.VAL",                     "checked": True,  "locked": True},
    {"label": "MonP Sensitivity Num",           "pv": "15IDC:A2sens_num.VAL",                      "checked": True,  "locked": True},
    # ── Computed during alignment sequence ──
    {"label": "BPM Max Intensity w/o Mirror",   "pv": "",  "checked": True,  "locked": True, "source": "scan_result"},
    {"label": "MonP Max Intensity w/o Mirror",  "pv": "",  "checked": True,  "locked": True, "source": "scan_result"},
    {"label": "Mirror Stripe",                  "pv": "",  "checked": True,  "locked": True, "source": "scan_result"},
    {"label": "BPM Y @ 5B (µm)",                 "pv": "",  "checked": True,  "locked": True, "source": "scan_result"},
    {"label": "VDM Y FWHM @ 4D (µm)",          "pv": "",  "checked": True,  "locked": True, "source": "scan_result"},
    {"label": "VFM Y FWHM @ 4E (µm)",          "pv": "",  "checked": True,  "locked": True, "source": "scan_result"},
    # ── Optional / unchecked by default ──
    {"label": "2nd Xtal Temp (°C)",             "pv": "15ID:BLEPS:TEMP23_CURRENT",                 "checked": False, "locked": True},
    {"label": "RF BPM Vertical (µrad)",         "pv": "S15:ID:SrcPt:VAngleM",                      "checked": False, "locked": True},
    {"label": "RF BPM Horizontal (µrad)",       "pv": "S15:ID:SrcPt:HAngleM",                      "checked": False, "locked": True},
    {"label": "XBPM US X (µm)",                 "pv": "S15IDFE-XBPM:P1us:x:LowPass1s_DecimatedM", "checked": False, "locked": True},
    {"label": "XBPM US Y (µm)",                 "pv": "S15IDFE-XBPM:P1us:y:LowPass1s_DecimatedM", "checked": False, "locked": True},
    {"label": "XBPM DS X (µm)",                 "pv": "S15IDFE-XBPM:P1ds:x:LowPass1s_DecimatedM", "checked": False, "locked": True},
    {"label": "XBPM DS Y (µm)",                 "pv": "S15IDFE-XBPM:P1ds:y:LowPass1s_DecimatedM", "checked": False, "locked": True},
]

DEFAULT_MIRROR_STAGES = [
    {"name": "JJC Center",           "pv": "15IDC:Slit4VDcenter.VAL",  "val_in":  0.0,    "val_out": -2.0},
    {"name": "JJC Size",             "pv": "15IDC:Slit4VDsize.VAL",    "val_in":  0.4,    "val_out":  4.0},
    {"name": "CRL Y",                "pv": "15IDMini:m2",              "val_in":  2.0,    "val_out":  0.0},
    {"name": "VFM Y",                "pv": "ID15A1:DMS:VFM:Y",         "val_in":  0.0,    "val_out": -3000.0},
    {"name": "VDM Y",                "pv": "ID15A1:DMS:VDM:Y",         "val_in":  0.0,    "val_out":  3000.0},
    {"name": "BPM Y",                "pv": "15IDC:m3",                 "val_in":  0.0,    "val_out": -2.0},
    {"name": "BPM Scale Y",          "pv": "15IDA:userTran10.CLCI",    "val_in":  51.2,   "val_out":  512.0},
    {"name": "Vertical Feedback P",  "pv": "15ID1:BeamPosY.KP",        "val_in":  0.0001, "val_out":  0.001},
]

DEFAULT_SCAN = {
    "pitch_start": -0.05,
    "pitch_stop":   0.05,
    "pitch_steps":  25,
    "roll_start":  -0.05,
    "roll_stop":    0.05,
    "roll_steps":   21,
    "settle_time":        0.1,
    "piezo_settle_time":  0.2,
    "piezo_center": 5.0,
    "smart_edge_fraction":    0.2,
    "smart_max_extend_steps": 10,
    "smart_fine_sigma_range": 2.0,
    "smart_fine_scan_iter":   3,
    "dcm_piezo_start":  -1.0,
    "dcm_piezo_stop":    1.0,
    "dcm_piezo_steps":  21,
    "mir_piezo_start":  -1.0,
    "mir_piezo_stop":    1.0,
    "mir_piezo_steps":  21,
}

DEFAULT_MIRROR_SCAN = {
    "mir_signal":         "BPM Intensity",
    "mir_slit_size_a":    0.1,
    "mir_slit_cen_start": -2.0,
    "mir_slit_cen_stop":  2.0,
    "mir_slit_cen_steps": 21,
    "mir_slit_size_b":    0.2,
    "mir_vdm_start":      -500.0,
    "mir_vdm_stop":        500.0,
    "mir_vdm_steps":       21,
    "mir_vfm_start":      -250.0,
    "mir_vfm_stop":        250.0,
    "mir_vfm_steps":       21,
    "mir_slit_size_c":    2.0,
}

# ─── Mirror stripe selection ─────────────────────────────────────────────────
_STRIPE_VFM_X_PV = "ID15A1:DMS:VFM:X"
_STRIPE_VDM_X_PV = "ID15A1:DMS:VDM:X"
_STRIPE_POSITIONS = {
    "Si": {"vfm_x":      0, "vdm_x":      0},
    "Rh": {"vfm_x":  13000, "vdm_x": -13000},
    "Pt": {"vfm_x": -13000, "vdm_x":  13000},
}

def select_stripe(energy_kev):
    if energy_kev <= 12:
        return "Si"
    elif energy_kev <= 23:
        return "Rh"
    else:
        return "Pt"

# ─── Simulation helpers ───────────────────────────────────────────────────────
def gaussian(x, center, sigma, amp, offset=0.0):
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset

def super_gaussian(x, amplitude, center, sigma, p, offset):
    return amplitude * np.exp(-np.abs((x - center) / sigma) ** p) + offset

def fit_super_gaussian(xs, ys):
    """Multi-start super-Gaussian fit (p∈{2,4,8,16}). Returns [amp,center,sigma,p,offset] or None."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if len(xs) < 5:
        return None
    amp0 = float(np.max(ys) - np.min(ys))
    cen0 = float(xs[np.argmax(ys)])
    sig0 = float(max((xs[-1] - xs[0]) / 4.0, 1e-9))
    off0 = float(np.min(ys))
    best, best_rms = None, np.inf
    for p_init in [2.0, 4.0, 8.0, 16.0]:
        try:
            lo = [0.0, xs[0], 1e-9, 0.5, -np.inf]
            hi = [np.inf, xs[-1], xs[-1] - xs[0] + 1e-9, 64.0, np.inf]
            popt, _ = curve_fit(super_gaussian, xs, ys,
                                p0=[amp0, cen0, sig0, p_init, off0],
                                bounds=(lo, hi), maxfev=3000)
            rms = float(np.sqrt(np.mean((ys - super_gaussian(xs, *popt)) ** 2)))
            if rms < best_rms:
                best_rms, best = rms, popt
        except Exception:
            pass
    return best

def sim_scan_pitch(start, stop, nsteps, true_center, sigma=0.015, amp=1000.0, noise=20.0):
    xs = np.linspace(start, stop, nsteps)
    ys = gaussian(xs, true_center, sigma, amp, 10.0) + np.random.normal(0, noise, nsteps)
    return xs, np.maximum(ys, 0.0)

def sim_scan_roll_bpm(start, stop, nsteps, true_zero, noise=0.003):
    xs = np.linspace(start, stop, nsteps)
    ys = -(xs - true_zero) * 10.0 + np.random.normal(0, noise, nsteps)
    return xs, ys

def find_peak_centroid(xs, ys):
    ys_c = np.clip(ys - np.min(ys), 0, None)
    if ys_c.sum() == 0:
        return float(xs[len(xs)//2])
    return float(np.average(xs, weights=ys_c))

def find_zero_crossing(xs, ys):
    """Find where ys crosses zero by linear interpolation."""
    for i in range(len(ys) - 1):
        if ys[i] * ys[i+1] <= 0:
            x0, x1 = xs[i], xs[i+1]
            y0, y1 = ys[i], ys[i+1]
            if (y1 - y0) != 0:
                return float(x0 - y0 * (x1 - x0) / (y1 - y0))
    return float(xs[np.argmin(np.abs(ys))])

def fwhm_half_max(xs, ys):
    """FWHM via linear interpolation at half-maximum. Suitable for square/flat-top profiles."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    baseline = np.min(ys)
    peak     = np.max(ys)
    if peak <= baseline:
        return None
    half = baseline + (peak - baseline) / 2.0
    left = right = None
    for i in range(len(ys) - 1):
        if ys[i] <= half <= ys[i + 1] or ys[i] >= half >= ys[i + 1]:
            t = (half - ys[i]) / (ys[i + 1] - ys[i])
            x = xs[i] + t * (xs[i + 1] - xs[i])
            if left is None:
                left = x
            else:
                right = x
    if left is None or right is None:
        return None
    return abs(right - left)

# ─── EPICS interface (real or simulated) ─────────────────────────────────────
class EpicsInterface:
    def __init__(self, simulate=True):
        self.simulate = simulate
        self._sim_vals = {}

    def get(self, pv):
        if self.simulate:
            return self._sim_vals.get(pv, 0.0)
        if EPICS_AVAILABLE:
            return epics.caget(pv)
        return None

    def put(self, pv, value, wait=True):
        if self.simulate:
            self._sim_vals[pv] = value
            return True
        if EPICS_AVAILABLE:
            epics.caput(pv, value, wait=wait)
            return True
        return False

# ─── Alignment worker thread ─────────────────────────────────────────────────
class AlignmentWorker(QObject):
    log_signal       = pyqtSignal(str, str)   # (message, level)
    step_status      = pyqtSignal(int, str)   # (step_num, status)
    scan_point       = pyqtSignal(str, float, float)  # (motor, x, y)
    scan_peak        = pyqtSignal(str, float)          # (motor, peak_x)
    bpm_update       = pyqtSignal(float, float, float) # x, y, intensity
    feedback_update  = pyqtSignal(bool, bool)          # h, v
    substep_status   = pyqtSignal(str, str)            # (key "step_sub", status)
    finished         = pyqtSignal(bool)                # success
    confirm_needed   = pyqtSignal(str)                 # substep key, waiting for operator
    scan_results_ready = pyqtSignal(dict)              # fit results keyed by label
    stripe_status      = pyqtSignal(str)               # "Si"/"Rh"/"Pt"/"changing"

    def __init__(self, pvs, scan_params, row, simulate=True, skip_mirror=True,
                 mirror_stages=None, confirm_mode=False):
        super().__init__()
        self.pvs = pvs
        self.params = scan_params
        self.row = row
        self.simulate = simulate
        self.skip_mirror = skip_mirror
        self.mirror_stages = mirror_stages or []
        self.confirm_mode = confirm_mode
        self._abort        = False
        self._scan_results = {}   # populated during scans; emitted via scan_results_ready
        self._confirm_event = threading.Event()
        self.epics = EpicsInterface(simulate=simulate)

    def abort(self):
        self._abort = True

    def _check_abort(self):
        return self._abort

    def _sleep(self, secs):
        steps = max(1, int(secs / 0.05))
        for _ in range(steps):
            if self._abort:
                return False
            time.sleep(0.05)
        return True

    def log(self, msg, level="info"):
        self.log_signal.emit(msg, level)

    def _wait_motor_done(self, motor_pv, timeout=30.0):
        if self.simulate:
            return self._sleep(0.05)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._abort:
                return False
            try:
                dmov = self.epics.get(motor_pv + ".DMOV")
                if dmov:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        self.log(f"  Warning: motor {motor_pv} did not finish in {timeout}s", "warn")
        return True

    def confirm(self):
        """Called from the UI thread when operator clicks Proceed."""
        self._confirm_event.set()

    def request_confirm(self, substep_key):
        """Pause worker until operator clicks Proceed (or abort). Returns False if aborted."""
        if not self.confirm_mode:
            return True
        self._confirm_event.clear()
        self.confirm_needed.emit(substep_key)
        while not self._confirm_event.is_set():
            if self._abort:
                return False
            time.sleep(0.05)
        return True

    def _smart_scan_peak(self, scan_key, motor_pv, center, half_range, steps,
                         sim_fn, substep_key):
        """Adaptive scan for intensity peak. Returns (peak_pos, sigma) or (None, None)."""
        p = self.params
        edge_frac  = p.get("smart_edge_fraction",    0.2)
        max_ext    = p.get("smart_max_extend_steps", 10)
        fine_range = p.get("smart_fine_sigma_range", 2.0)
        fine_iter  = p.get("smart_fine_scan_iter",   3)

        lo, hi = center - half_range, center + half_range
        step_size = (hi - lo) / max(steps - 1, 1)

        xs_all, ys_all = [], []

        def do_scan(a, b, n):
            if self.simulate:
                scan_xs, scan_ys = sim_fn(a, b, n)
            else:
                scan_xs = list(np.linspace(a, b, n))
                scan_ys = []
                for x in scan_xs:
                    if self._abort: return None, None
                    self.epics.put(motor_pv, x)
                    if not self._wait_motor_done(motor_pv): return None, None
                    if not self._sleep(p["settle_time"]): return None, None
                    scan_ys.append(self.epics.get(self.pvs.get("i0", "I0")))
            for x, y in zip(scan_xs, scan_ys):
                if self._abort: return None, None
                self.scan_point.emit(scan_key, float(x), float(y))
                xs_all.append(float(x)); ys_all.append(float(y))
                if not self._sleep(p["settle_time"]): return None, None
            return scan_xs, scan_ys

        # initial scan
        rx, ry = do_scan(lo, hi, steps)
        if rx is None: return None, None

        # extend if peak near boundary
        for _ in range(max_ext):
            popt = fit_super_gaussian(xs_all, ys_all)
            if popt is None: break
            pk = popt[1]
            span = xs_all[-1] - xs_all[0]
            if pk < xs_all[0] + edge_frac * span:
                new_lo = xs_all[0] - step_size * steps // 4
                rx, ry = do_scan(new_lo, xs_all[0] - step_size, steps // 4 + 1)
                if rx is None: return None, None
            elif pk > xs_all[-1] - edge_frac * span:
                new_hi = xs_all[-1] + step_size * steps // 4
                rx, ry = do_scan(xs_all[-1] + step_size, new_hi, steps // 4 + 1)
                if rx is None: return None, None
            else:
                break

        popt = fit_super_gaussian(xs_all, ys_all)
        if popt is None:
            self.log(f"  WARNING: could not fit peak in {substep_key} scan — using best estimate", "warn")
            best_x = float(np.asarray(xs_all)[np.argmax(ys_all)])
            return best_x, None

        pk, sig = popt[1], popt[2]

        # fine scan iterations
        prev_sig = sig
        for _ in range(fine_iter):
            fr = fine_range * abs(prev_sig)
            rx, ry = do_scan(pk - fr, pk + fr, steps)
            if rx is None: return None, None
            popt2 = fit_super_gaussian(xs_all, ys_all)
            if popt2 is None: break
            pk, sig = popt2[1], popt2[2]
            if prev_sig / (sig + 1e-30) < 2.0: break
            prev_sig = sig

        fwhm = 2.0 * sig * (np.log(2) ** (1.0 / max(popt[3], 0.5)))
        if abs(pk - float(np.asarray(xs_all)[np.argmax(ys_all)])) < fwhm:
            final = pk
        else:
            final = float(np.asarray(xs_all)[np.argmax(ys_all)])
        self.scan_peak.emit(scan_key, final)
        return final, sig

    def _smart_scan_zero(self, scan_key, motor_pv, center, half_range, steps,
                         sim_fn, substep_key):
        """Adaptive scan for BPM zero-crossing. Returns zero_pos or None."""
        p = self.params
        edge_frac = p.get("smart_edge_fraction",    0.2)
        max_ext   = p.get("smart_max_extend_steps", 10)

        lo, hi = center - half_range, center + half_range
        step_size = (hi - lo) / max(steps - 1, 1)
        xs_all, ys_all = [], []

        def do_scan(a, b, n):
            if self.simulate:
                scan_xs, scan_ys = sim_fn(a, b, n)
            else:
                scan_xs = list(np.linspace(a, b, n))
                scan_ys = []
                for x in scan_xs:
                    if self._abort: return None, None
                    self.epics.put(motor_pv, x)
                    if not self._wait_motor_done(motor_pv): return None, None
                    if not self._sleep(p["settle_time"]): return None, None
                    scan_ys.append(self.epics.get(self.pvs.get("bpm_x", "BPMX")))
            for x, y in zip(scan_xs, scan_ys):
                if self._abort: return None, None
                self.scan_point.emit(scan_key, float(x), float(y))
                xs_all.append(float(x)); ys_all.append(float(y))
                if not self._sleep(p["settle_time"]): return None, None
            return scan_xs, scan_ys

        rx, ry = do_scan(lo, hi, steps)
        if rx is None: return None

        # check if zero crossing is within the scan range, extend if not
        for _ in range(max_ext):
            arr = np.asarray(ys_all)
            crosses = np.where(np.diff(np.sign(arr)))[0]
            if len(crosses) > 0: break
            span = xs_all[-1] - xs_all[0]
            if arr[-1] < arr[0]:  # descending, zero may be to the right
                rx, ry = do_scan(xs_all[-1] + step_size,
                                 xs_all[-1] + step_size * (steps // 4), steps // 4 + 1)
            else:
                rx, ry = do_scan(xs_all[0] - step_size * (steps // 4),
                                 xs_all[0] - step_size, steps // 4 + 1)
            if rx is None: return None

        zero = find_zero_crossing(xs_all, ys_all)
        self.scan_peak.emit(scan_key, zero)
        return zero

    def run(self):
        try:
            self._run_sequence()
        except Exception as e:
            self.log(f"Unexpected error: {e}", "error")
            self.finished.emit(False)

    def _run_sequence(self):
        pvs = self.pvs
        row = self.row
        p   = self.params

        # Emit initial BPM values so readouts are populated immediately
        self.bpm_update.emit(0.0, 0.0, 0.0)
        self.feedback_update.emit(False, False)

        # ── Step 1: Load settings ──────────────────────────────────────
        self.step_status.emit(1, "running")
        self.log("━━ Step 1 — Load energy table settings ━━")
        self.substep_status.emit("1_1a", "running")
        if not self._sleep(0.3): return self._abort_cleanup()
        self.log(f"  Mono E   = {row['mono_e']} keV")
        self.log(f"  Und E    = {row['ue']} keV")
        self.log(f"  Roll SP  = {row['roll']}")
        self.log(f"  Pitch SP = {row['pitch']}")
        self.substep_status.emit("1_1a", "done")
        self.step_status.emit(1, "done")
        self.log("Step 1 complete.", "ok")

        # ── Step 2: Apply energy table settings ───────────────────────
        self.step_status.emit(2, "running")
        self.log("━━ Step 2 — Apply energy table settings ━━")

        # 2a: Turn off BPM feedback
        self.substep_status.emit("2_2a", "running")
        self.log(f"  [{pvs['feedback_h']}] → 0  (H feedback OFF)", "warn")
        self.epics.put(pvs['feedback_h'], 0)
        self.log(f"  [{pvs['feedback_v']}] → 0  (V feedback OFF)", "warn")
        self.epics.put(pvs['feedback_v'], 0)
        self.feedback_update.emit(False, False)
        if not self._sleep(0.4): return self._abort_cleanup()
        self.substep_status.emit("2_2a", "done")

        # 2b: Apply energy table settings (undulator + DCM)
        self.substep_status.emit("2_2b", "running")
        self.log("  Moving motors to energy table setpoints…")
        if pvs.get("und_harmonic"):
            self.epics.put(pvs["und_harmonic"], row["harmonic"])
            self.log(f"  [{pvs['und_harmonic']}] → {row['harmonic']}  (harmonic)", "ok")
            if not self._sleep(0.15): return self._abort_cleanup()
        self.epics.put(pvs["und_energy"], row["ue"])
        self.log(f"  [{pvs['und_energy']}] → {row['ue']} keV  (undulator energy)", "ok")
        if not self._sleep(0.15): return self._abort_cleanup()
        if pvs.get("und_start"):
            self.epics.put(pvs["und_start"], 1)
            self.log(f"  [{pvs['und_start']}] → 1  (start undulator move)", "ok")
            if not self._sleep(0.15): return self._abort_cleanup()
        for key, pv_key, unit in [
            ("mono_e", "mono_energy", "keV"),
            ("roll",   "roll",        ""),
            ("pitch",  "pitch",       ""),
        ]:
            self.epics.put(pvs[pv_key], row[key])
            self.log(f"  [{pvs[pv_key]}] → {row[key]} {unit}", "ok")
            if not self._sleep(0.15): return self._abort_cleanup()
        self.substep_status.emit("2_2b", "done")

        # 2c: Mirror out
        self.substep_status.emit("2_2c", "running")
        self.log("  Retracting mirror from beam path…")
        for stage in self.mirror_stages:
            if stage["pv"].strip():
                self.epics.put(stage["pv"], stage["val_out"])
                self.log(f"  [{stage['pv']}] → {stage['val_out']}  ({stage['name']} OUT)", "ok")
                if not self._sleep(0.1): return self._abort_cleanup()
        if not self._sleep(0.4): return self._abort_cleanup()
        self.log("  Mirror retracted.", "ok")
        self.substep_status.emit("2_2c", "done")
        self.step_status.emit(2, "done")
        self.log("Step 2 complete.", "ok")

        # ── Step 3: DCM piezo alignment ────────────────────────────────
        self.step_status.emit(3, "running")
        self.log("━━ Step 3 — DCM piezo alignment ━━")

        # 3a: Center piezos
        self.substep_status.emit("3_3a", "running")
        center = p["piezo_center"]
        self.log(f"  [{pvs['piezo_pitch']}] → {center}  (center)")
        self.epics.put(pvs['piezo_pitch'], center)
        self.log(f"  [{pvs['piezo_roll']}] → {center}  (center)")
        self.epics.put(pvs['piezo_roll'], center)
        if not self._sleep(0.4): return self._abort_cleanup()
        self.substep_status.emit("3_3a", "done")

        # 3b: Pitch scan → intensity peak (coarse, before roll)
        self.substep_status.emit("3_3b", "running")
        self.log("  Scanning DCM pitch → finding intensity peak (coarse)…")
        _true_peak_coarse = row["pitch"] + random.uniform(-0.01, 0.01)
        def _sim_pitch_coarse(a, b, n):
            return sim_scan_pitch(a, b, n, _true_peak_coarse)
        pitch_coarse, _sig3b = self._smart_scan_peak(
            "pitch", pvs['pitch'],
            center=row["pitch"],
            half_range=(p["pitch_stop"] - p["pitch_start"]) / 2.0,
            steps=p["pitch_steps"],
            sim_fn=_sim_pitch_coarse,
            substep_key="3_3b",
        )
        if self._abort: return self._abort_cleanup()
        if pitch_coarse is None:
            pitch_coarse = row["pitch"]
            self.log("  INSUFFICIENT DATA: using table pitch value as fallback", "warn")
        self.epics.put(pvs['pitch'], pitch_coarse)
        self.log(f"  Intensity peak at pitch = {pitch_coarse:.6f} → moved", "ok")
        self.substep_status.emit("3_3b", "waiting")
        if not self.request_confirm("3_3b"): return self._abort_cleanup()
        self.substep_status.emit("3_3b", "done")

        # 3c: Roll scan → BPM x = 0
        self.substep_status.emit("3_3c", "running")
        self.log("  Scanning DCM roll → finding BPM x = 0 zero-crossing…")
        _true_zero = random.uniform(-0.005, 0.005)
        def _sim_roll(a, b, n):
            return sim_scan_roll_bpm(a, b, n, _true_zero)
        roll_zero = self._smart_scan_zero(
            "roll", pvs['roll'],
            center=row["roll"],
            half_range=(p["roll_stop"] - p["roll_start"]) / 2.0,
            steps=p["roll_steps"],
            sim_fn=_sim_roll,
            substep_key="3_3c",
        )
        if self._abort: return self._abort_cleanup()
        if roll_zero is None:
            roll_zero = row["roll"]
            self.log("  INSUFFICIENT DATA: using table roll value as fallback", "warn")
        self.epics.put(pvs['roll'], roll_zero)
        self.log(f"  BPM x zero-crossing at roll = {roll_zero:.6f} → moved", "ok")
        self.substep_status.emit("3_3c", "waiting")
        if not self.request_confirm("3_3c"): return self._abort_cleanup()
        self.substep_status.emit("3_3c", "done")

        # 3d: Pitch scan → intensity peak (fine, after roll)
        self.substep_status.emit("3_3d", "running")
        self.log("  Scanning DCM pitch → finding intensity peak (fine)…")
        _true_peak = pitch_coarse + random.uniform(-0.005, 0.005)
        def _sim_pitch_fine(a, b, n):
            return sim_scan_pitch(a, b, n, _true_peak)
        pitch_peak, _sig3d = self._smart_scan_peak(
            "pitch", pvs['pitch'],
            center=pitch_coarse,
            half_range=(p["pitch_stop"] - p["pitch_start"]) / 2.0,
            steps=p["pitch_steps"],
            sim_fn=_sim_pitch_fine,
            substep_key="3_3d",
        )
        if self._abort: return self._abort_cleanup()
        if pitch_peak is None:
            pitch_peak = pitch_coarse
            self.log("  INSUFFICIENT DATA: using coarse pitch value as fallback", "warn")
        self.epics.put(pvs['pitch'], pitch_peak)
        self.log(f"  Intensity peak at pitch = {pitch_peak:.6f} → moved", "ok")
        self.bpm_update.emit(roll_zero + random.uniform(-0.0005, 0.0005),
                             random.uniform(-0.001, 0.001), 0.97)
        self.substep_status.emit("3_3d", "waiting")
        if not self.request_confirm("3_3d"): return self._abort_cleanup()
        self.substep_status.emit("3_3d", "done")
        self.step_status.emit(3, "done")
        self.log("Step 3 complete.", "ok")

        # Snapshot intensities before mirror goes in
        if self.simulate:
            self._scan_results["BPM Max Intensity w/o Mirror"]  = "sim"
            self._scan_results["MonP Max Intensity w/o Mirror"] = "sim"
        else:
            _bpm_i  = self.epics.get(pvs.get("bpm_intensity", ""))
            _monp_i = self.epics.get(pvs.get("ion_chamber", ""))
            self._scan_results["BPM Max Intensity w/o Mirror"]  = (
                f"{_bpm_i:.6g}" if isinstance(_bpm_i, (int, float)) else "—")
            self._scan_results["MonP Max Intensity w/o Mirror"] = (
                f"{_monp_i:.6g}" if isinstance(_monp_i, (int, float)) else "—")

        # ── Step 4: Mirror alignment (optional) ───────────────────────
        if self.skip_mirror:
            self.step_status.emit(4, "done")
            self.log("━━ Step 4 — Mirror alignment skipped ━━", "warn")
        else:
            self.step_status.emit(4, "running")
            self.log("━━ Step 4 — Mirror alignment ━━")

            top_pv  = pvs.get("mir_slit_top", "")
            bot_pv  = pvs.get("mir_slit_bot", "")
            mir_piezo_pv = pvs.get("mir_piezo_pitch", "")
            signal_key   = p.get("mir_signal", "BPM Intensity")
            signal_pv    = pvs["bpm_intensity"] if signal_key == "BPM Intensity" else pvs.get("ion_chamber", pvs["bpm_intensity"])

            # Resolve VFM/VDM PVs from mirror stages table
            vdm_pv = "ID15A1:DMS:VDM:Y"
            vfm_pv = "ID15A1:DMS:VFM:Y"
            for stage in self.mirror_stages:
                nm = stage.get("name", "")
                if "VDM" in nm:
                    vdm_pv = stage["pv"]
                elif "VFM" in nm:
                    vfm_pv = stage["pv"]

            slit_size_a    = p.get("mir_slit_size_a", 0.1)
            slit_cen_start = p.get("mir_slit_cen_start", -2.0)
            slit_cen_stop  = p.get("mir_slit_cen_stop", 2.0)
            slit_cen_steps = int(p.get("mir_slit_cen_steps", 21))
            slit_size_b    = p.get("mir_slit_size_b", 0.2)
            slit_size_c    = p.get("mir_slit_size_c", 2.0)
            vdm_start      = p.get("mir_vdm_start", -500.0)
            vdm_stop       = p.get("mir_vdm_stop", 500.0)
            vdm_steps      = int(p.get("mir_vdm_steps", 21))
            vfm_start      = p.get("mir_vfm_start", -250.0)
            vfm_stop       = p.get("mir_vfm_stop", 250.0)
            vfm_steps      = int(p.get("mir_vfm_steps", 21))

            # ── 4A: Slit scan (mirror out) → find beam center ─────────
            self.substep_status.emit("4_4A", "running")
            self.log("  4A: Slit center scan — mirror out, finding beam center…")
            slit_peak = 0.0
            if top_pv and bot_pv:
                cur_top = self.epics.get(top_pv) or 0.0
                cur_bot = self.epics.get(bot_pv) or 0.0
                cur_cen = (cur_top + cur_bot) / 2.0
                self.log(f"  Closing slit to {slit_size_a} mm (center ≈ {cur_cen:.3f})")
                self.epics.put(top_pv, cur_cen + slit_size_a / 2.0)
                self.epics.put(bot_pv, cur_cen - slit_size_a / 2.0)
                if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                if not self._wait_motor_done(bot_pv): return self._abort_cleanup()

                xs_slit = np.linspace(cur_cen + slit_cen_start, cur_cen + slit_cen_stop, slit_cen_steps)
                ys_slit = []
                _true_cen = cur_cen + random.uniform(-0.3, 0.3)
                for cen in xs_slit:
                    if self._abort: return self._abort_cleanup()
                    self.epics.put(top_pv, cen + slit_size_a / 2.0)
                    self.epics.put(bot_pv, cen - slit_size_a / 2.0)
                    if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                    if not self._wait_motor_done(bot_pv): return self._abort_cleanup()
                    sig = (gaussian(cen, _true_cen, 0.5, 1000.0, 10.0) + random.uniform(-5, 5)
                           if self.simulate else (self.epics.get(signal_pv) or 0.0))
                    ys_slit.append(sig)
                    self.scan_point.emit("mir_slit_cen", float(cen), float(sig))
                    if not self._sleep(p["settle_time"]): return self._abort_cleanup()

                slit_peak = find_peak_centroid(xs_slit, np.array(ys_slit))
                self.scan_peak.emit("mir_slit_cen", slit_peak)
                self.log(f"  Beam center at {slit_peak:.4f} mm → moving slit", "ok")
                self.epics.put(top_pv, slit_peak + slit_size_a / 2.0)
                self.epics.put(bot_pv, slit_peak - slit_size_a / 2.0)
                if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                if not self._wait_motor_done(bot_pv): return self._abort_cleanup()
            else:
                self.log("  Slit PVs not configured — skipping 4A slit scan.", "warn")
            self.substep_status.emit("4_4A", "waiting")
            if not self.request_confirm("4_4A"): return self._abort_cleanup()
            self.substep_status.emit("4_4A", "done")

            # ── 4B: Mirror in + stripe selection ──────────────────────
            self.substep_status.emit("4_4B", "running")
            self.log("  4B: Moving mirror into beam path…")
            for stage in self.mirror_stages:
                if stage["pv"].strip():
                    self.epics.put(stage["pv"], stage["val_in"])
                    self.log(f"  [{stage['pv']}] → {stage['val_in']}  ({stage['name']} IN)", "ok")
                    if not self._sleep(0.1): return self._abort_cleanup()
            if not self._sleep(0.5): return self._abort_cleanup()
            self.log("  Mirror in position.", "ok")
            if not self._apply_mirror_stripe(float(self.row.get("mono_e", 0))):
                return self._abort_cleanup()
            self.substep_status.emit("4_4B", "done")

            # ── 4C: Close slit → pitch piezo → BPMY = 0 ──────────────
            self.substep_status.emit("4_4C", "running")
            if top_pv and bot_pv:
                self.log(f"  Narrowing slit to {slit_size_b} mm for mirror scan")
                self.epics.put(top_pv, slit_peak + slit_size_b / 2.0)
                self.epics.put(bot_pv, slit_peak - slit_size_b / 2.0)
                if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                if not self._wait_motor_done(bot_pv): return self._abort_cleanup()

            if mir_piezo_pv:
                self.log("  Scanning mirror pitch piezo → BPMY = 0…")
                piezo_cur = self.epics.get(mir_piezo_pv) or p.get("piezo_center", 5.0)
                mp_start = p.get("mir_piezo_start", -1.0)
                mp_stop  = p.get("mir_piezo_stop",   1.0)
                mp_steps = int(p.get("mir_piezo_steps", 21))
                xs_piezo = np.linspace(piezo_cur + mp_start, piezo_cur + mp_stop, mp_steps)
                ys_bpmy = []
                _piezo_zero = piezo_cur + random.uniform(-0.1, 0.1)
                for px in xs_piezo:
                    if self._abort: return self._abort_cleanup()
                    self.epics.put(mir_piezo_pv, px)
                    if not self._sleep(p.get("piezo_settle_time", 0.2)): return self._abort_cleanup()
                    bpmy = (-(px - _piezo_zero) * 0.5 + random.uniform(-0.002, 0.002)
                            if self.simulate else (self.epics.get(pvs["bpm_y"]) or 0.0))
                    ys_bpmy.append(bpmy)
                    self.scan_point.emit("mir_piezo", float(px), float(bpmy))
                    self.bpm_update.emit(0.0, float(bpmy), 0.5)

                piezo_zero = find_zero_crossing(xs_piezo, np.array(ys_bpmy))
                self.scan_peak.emit("mir_piezo", piezo_zero)
                self.epics.put(mir_piezo_pv, piezo_zero)
                self.log(f"  BPMY zero-crossing at piezo = {piezo_zero:.5f} → moved", "ok")
            else:
                self.log("  Mirror piezo pitch PV not configured — skipping BPMY centering.", "warn")
            self.substep_status.emit("4_4C", "waiting")
            if not self.request_confirm("4_4C"): return self._abort_cleanup()
            self.substep_status.emit("4_4C", "done")

            # ── 4D: Scan VDM:Y → find peak → move ────────────────────
            self.substep_status.emit("4_4D", "running")
            self.log("  4D: Scanning VDM:Y → finding signal peak…")
            vdm_cur = self.epics.get(vdm_pv) or 0.0
            xs_vdm = np.linspace(vdm_cur + vdm_start, vdm_cur + vdm_stop, vdm_steps)
            ys_vdm = []
            _vdm_true = vdm_cur + random.uniform(-50, 50)
            for vdm_pos in xs_vdm:
                if self._abort: return self._abort_cleanup()
                self.epics.put(vdm_pv, vdm_pos)
                if not self._wait_motor_done(vdm_pv): return self._abort_cleanup()
                sig = (gaussian(vdm_pos, _vdm_true, 150.0, 1000.0, 10.0) + random.uniform(-5, 5)
                       if self.simulate else (self.epics.get(signal_pv) or 0.0))
                ys_vdm.append(sig)
                self.scan_point.emit("mir_vdm", float(vdm_pos), float(sig))
                if not self._sleep(p["settle_time"]): return self._abort_cleanup()

            vdm_peak = find_peak_centroid(xs_vdm, np.array(ys_vdm))
            self.scan_peak.emit("mir_vdm", vdm_peak)
            _fwhm4d = fwhm_half_max(xs_vdm, np.array(ys_vdm))
            if _fwhm4d is not None:
                self._scan_results["VDM Y FWHM @ 4D (µm)"] = f"{_fwhm4d:.2f}"
            self.epics.put(vdm_pv, vdm_peak)
            if not self._wait_motor_done(vdm_pv): return self._abort_cleanup()
            self.log(f"  VDM:Y peak at {vdm_peak:.2f} → moved", "ok")
            self.substep_status.emit("4_4D", "waiting")
            if not self.request_confirm("4_4D"): return self._abort_cleanup()
            self.substep_status.emit("4_4D", "done")

            # ── 4E: Coupled VFM+VDM scan (VDM step = 2× VFM step) ────
            self.substep_status.emit("4_4E", "running")
            self.log("  4E: Coupled VFM:Y + VDM:Y scan (VDM step = 2× VFM step)…")
            vfm_cur  = self.epics.get(vfm_pv) or 0.0
            vdm_ref  = self.epics.get(vdm_pv) or vdm_peak
            xs_vfm   = np.linspace(vfm_cur + vfm_start, vfm_cur + vfm_stop, vfm_steps)
            ys_coupled = []
            _vfm_true = vfm_cur + random.uniform(-30, 30)
            for vfm_pos in xs_vfm:
                if self._abort: return self._abort_cleanup()
                vfm_delta = vfm_pos - vfm_cur
                vdm_pos   = vdm_ref + 2.0 * vfm_delta
                self.epics.put(vfm_pv, vfm_pos)
                self.epics.put(vdm_pv, vdm_pos)
                if not self._wait_motor_done(vfm_pv): return self._abort_cleanup()
                if not self._wait_motor_done(vdm_pv): return self._abort_cleanup()
                sig = (gaussian(vfm_pos, _vfm_true, 80.0, 1000.0, 10.0) + random.uniform(-5, 5)
                       if self.simulate else (self.epics.get(signal_pv) or 0.0))
                ys_coupled.append(sig)
                self.scan_point.emit("mir_coupled", float(vfm_pos), float(sig))
                if not self._sleep(p["settle_time"]): return self._abort_cleanup()

            vfm_peak_pos    = find_peak_centroid(xs_vfm, np.array(ys_coupled))
            vfm_delta_final = vfm_peak_pos - vfm_cur
            vdm_final       = vdm_ref + 2.0 * vfm_delta_final
            self.scan_peak.emit("mir_coupled", vfm_peak_pos)
            _fwhm4e = fwhm_half_max(xs_vfm, np.array(ys_coupled))
            if _fwhm4e is not None:
                self._scan_results["VFM Y FWHM @ 4E (µm)"] = f"{_fwhm4e:.2f}"
            self.epics.put(vfm_pv, vfm_peak_pos)
            if not self._wait_motor_done(vfm_pv): return self._abort_cleanup()
            self.epics.put(vdm_pv, vdm_final)
            if not self._wait_motor_done(vdm_pv): return self._abort_cleanup()
            self.log(f"  VFM:Y → {vfm_peak_pos:.2f}  VDM:Y → {vdm_final:.2f}  (2× delta applied)", "ok")
            self.substep_status.emit("4_4E", "waiting")
            if not self.request_confirm("4_4E"): return self._abort_cleanup()
            self.substep_status.emit("4_4E", "done")

            if top_pv and bot_pv:
                self.log(f"  Opening slit to {slit_size_c} mm after 4E")
                self.epics.put(top_pv, slit_peak + slit_size_c / 2.0)
                self.epics.put(bot_pv, slit_peak - slit_size_c / 2.0)
                if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                if not self._wait_motor_done(bot_pv): return self._abort_cleanup()

            self.step_status.emit(4, "done")
            self.log("Step 4 complete.", "ok")

        # ── Step 5: Enable feedback loops ──────────────────────────────
        self.step_status.emit(5, "running")
        self.log("━━ Step 5 — Enable feedback loops ━━")

        # If step 4 was skipped, mirror was retracted in step 2 — insert it now
        if self.skip_mirror:
            self.substep_status.emit("5_5mir", "running")
            self.log("  Step 4 skipped — moving mirror into beam path now…")
            for stage in self.mirror_stages:
                if stage["pv"].strip():
                    self.epics.put(stage["pv"], stage["val_in"])
                    self.log(f"  [{stage['pv']}] → {stage['val_in']}  ({stage['name']} IN)", "ok")
                    if not self._sleep(0.1): return self._abort_cleanup()
            if not self._sleep(0.4): return self._abort_cleanup()
            self.log("  Mirror in position.", "ok")
            if not self._apply_mirror_stripe(float(self.row.get("mono_e", 0))):
                return self._abort_cleanup()
            self.substep_status.emit("5_5mir", "done")

        self.substep_status.emit("5_5a", "running")
        self.log(f"  Enabling H feedback: DCM piezo roll → BPM x = 0…")
        if not self._sleep(0.5): return self._abort_cleanup()
        self.epics.put(pvs['feedback_h'], 1)
        self.feedback_update.emit(True, False)
        self.bpm_update.emit(random.uniform(-0.0002, 0.0002),
                             random.uniform(-0.001, 0.001), 0.97)
        self.log(f"  [{pvs['feedback_h']}] → 1  (H feedback ON)", "ok")
        self.substep_status.emit("5_5a", "done")

        self.substep_status.emit("5_5b", "running")
        self.log("  Scanning DCM piezo pitch → max intensity…")
        dcm_piezo_pv = pvs.get("piezo_pitch", "")
        dp_start = p.get("dcm_piezo_start", -1.0)
        dp_stop  = p.get("dcm_piezo_stop",   1.0)
        dp_steps = int(p.get("dcm_piezo_steps", 21))
        if dcm_piezo_pv:
            piezo_cur = self.epics.get(dcm_piezo_pv) or p.get("piezo_center", 5.0)
            xs_dcm = np.linspace(piezo_cur + dp_start, piezo_cur + dp_stop, dp_steps)
            ys_dcm = []
            _dcm_true = piezo_cur + random.uniform(-0.2, 0.2)
            for px in xs_dcm:
                if self._abort: return self._abort_cleanup()
                self.epics.put(dcm_piezo_pv, px)
                if not self._sleep(p.get("piezo_settle_time", 0.2)): return self._abort_cleanup()
                sig = (gaussian(px, _dcm_true, 0.3, 1000.0, 10.0) + random.uniform(-5, 5)
                       if self.simulate else (self.epics.get(pvs.get("i0", "")) or 0.0))
                ys_dcm.append(sig)
                self.scan_point.emit("pitch", float(px), float(sig))
                self.bpm_update.emit(random.uniform(-0.0001, 0.0001),
                                     random.uniform(-0.001, 0.001), float(sig) / 1000.0)
            dcm_piezo_peak = find_peak_centroid(xs_dcm, np.array(ys_dcm))
            self.scan_peak.emit("pitch", dcm_piezo_peak)
            self.epics.put(dcm_piezo_pv, dcm_piezo_peak)
            self.log(f"  Intensity peak at DCM piezo = {dcm_piezo_peak:.5f} → moved", "ok")
        else:
            self.log("  DCM piezo pitch PV not configured — skipping.", "warn")
        self.substep_status.emit("5_5b", "waiting")
        if not self.request_confirm("5_5b"): return self._abort_cleanup()
        self.substep_status.emit("5_5b", "done")

        # Snapshot BPM y after DCM piezo pitch optimisation
        if self.simulate:
            self._scan_results["BPM Y @ 5B (µm)"] = "sim"
        else:
            _bpmy_5b = self.epics.get(pvs.get("bpm_y", ""))
            self._scan_results["BPM Y @ 5B (µm)"] = (
                f"{_bpmy_5b:.6g}" if isinstance(_bpmy_5b, (int, float)) else "—")

        self.substep_status.emit("5_5c", "running")
        self.log("  Scanning mirror piezo pitch → BPM y = 0…")
        mir_piezo_pv5 = pvs.get("mir_piezo_pitch", "")
        mp_start = p.get("mir_piezo_start", -1.0)
        mp_stop  = p.get("mir_piezo_stop",   1.0)
        mp_steps = int(p.get("mir_piezo_steps", 21))
        if mir_piezo_pv5:
            piezo_cur5 = self.epics.get(mir_piezo_pv5) or p.get("piezo_center", 5.0)
            xs_mp = np.linspace(piezo_cur5 + mp_start, piezo_cur5 + mp_stop, mp_steps)
            ys_mp = []
            _mp_zero = piezo_cur5 + random.uniform(-0.1, 0.1)
            for px in xs_mp:
                if self._abort: return self._abort_cleanup()
                self.epics.put(mir_piezo_pv5, px)
                if not self._sleep(p.get("piezo_settle_time", 0.2)): return self._abort_cleanup()
                bpmy = (-(px - _mp_zero) * 0.5 + random.uniform(-0.002, 0.002)
                        if self.simulate else (self.epics.get(pvs.get("bpm_y", "")) or 0.0))
                ys_mp.append(bpmy)
                self.scan_point.emit("mir_piezo", float(px), float(bpmy))
                self.bpm_update.emit(random.uniform(-0.0001, 0.0001), float(bpmy), 0.98)
            mp_zero = find_zero_crossing(xs_mp, np.array(ys_mp))
            self.scan_peak.emit("mir_piezo", mp_zero)
            self.epics.put(mir_piezo_pv5, mp_zero)
            self.log(f"  BPM y zero-crossing at mirror piezo = {mp_zero:.5f} → moved", "ok")
        else:
            self.log("  Mirror piezo pitch PV not configured — skipping.", "warn")
        self.substep_status.emit("5_5c", "waiting")
        if not self.request_confirm("5_5c"): return self._abort_cleanup()
        self.substep_status.emit("5_5c", "done")

        self.substep_status.emit("5_5d", "running")
        self.log(f"  Enabling V feedback: DCM piezo pitch → BPM y = 0…")
        if not self._sleep(0.4): return self._abort_cleanup()
        self.epics.put(pvs['feedback_v'], 1)
        self.feedback_update.emit(True, True)
        self.log(f"  [{pvs['feedback_v']}] → 1  (V feedback ON)", "ok")
        self.substep_status.emit("5_5d", "done")

        self.step_status.emit(5, "done")
        self.log("Step 5 complete.", "ok")
        self.log("━━ Alignment sequence finished successfully ━━", "ok")
        self.scan_results_ready.emit(dict(self._scan_results))
        self.finished.emit(True)

    def _apply_mirror_stripe(self, energy_kev):
        """Select mirror stripe based on energy. Checks RBV first; skips move if already within tolerance."""
        stripe = select_stripe(energy_kev)
        pos = _STRIPE_POSITIONS[stripe]
        vfm_rbv_pv = _STRIPE_VFM_X_PV + ".RBV"
        vdm_rbv_pv = _STRIPE_VDM_X_PV + ".RBV"
        if self.simulate:
            vfm_cur = self.epics.get(_STRIPE_VFM_X_PV)
            vdm_cur = self.epics.get(_STRIPE_VDM_X_PV)
        else:
            vfm_cur = self.epics.get(vfm_rbv_pv)
            vdm_cur = self.epics.get(vdm_rbv_pv)
        vfm_cur = vfm_cur or 0.0
        vdm_cur = vdm_cur or 0.0
        if abs(vfm_cur - pos["vfm_x"]) <= 10 and abs(vdm_cur - pos["vdm_x"]) <= 10:
            self.log(f"  Already on {stripe} stripe — no move needed", "ok")
            self.stripe_status.emit(stripe)
            self._scan_results["Mirror Stripe"] = stripe
            return True
        self.log(f"  Selecting mirror stripe: {stripe} (energy {energy_kev} keV)")
        self.stripe_status.emit("changing")
        self.epics.put(_STRIPE_VFM_X_PV, pos["vfm_x"])
        self.epics.put(_STRIPE_VDM_X_PV, pos["vdm_x"])
        if not self._wait_motor_done(_STRIPE_VFM_X_PV): return False
        if not self._wait_motor_done(_STRIPE_VDM_X_PV): return False
        self.log(f"  VFM:X → {pos['vfm_x']}  VDM:X → {pos['vdm_x']}  ({stripe} stripe)", "ok")
        self.stripe_status.emit(stripe)
        self._scan_results["Mirror Stripe"] = stripe
        return True

    def _abort_cleanup(self):
        self.log("Alignment aborted by user.", "error")
        self.finished.emit(False)


# ─── Reusable widgets ─────────────────────────────────────────────────────────

def make_tag(text, color="grey"):
    lbl = QLabel(text)
    obj = {"green": "tag_green", "amber": "tag_amber",
           "red": "tag_red", "cyan": "tag_cyan"}.get(color, "tag_grey")
    lbl.setObjectName(obj)
    return lbl


def make_readout(label_text, value="—", unit="", value_color=None):
    """Returns (container_widget, value_label) so caller can update."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    lbl = QLabel(label_text.upper())
    lbl.setObjectName("readout_label")
    val = QLabel(f"{value}")
    val.setObjectName("readout_value")
    if value_color:
        val.setStyleSheet(f"color: {value_color};")
    unit_lbl = QLabel(unit)
    unit_lbl.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 10px;")
    row = QWidget()
    rh = QHBoxLayout(row)
    rh.setContentsMargins(0, 0, 0, 0)
    rh.setSpacing(4)
    rh.addWidget(val)
    rh.addWidget(unit_lbl)
    rh.addStretch()
    v.addWidget(lbl)
    v.addWidget(row)
    return w, val


def make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet(f"color: {PAL['border']};")
    return line


class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()

def styled_button(text, obj_name="", min_width=0):
    btn = QPushButton(text)
    if obj_name:
        btn.setObjectName(obj_name)
    if min_width:
        btn.setMinimumWidth(min_width)
    return btn


def make_plot(title="", y_label="Signal", x_label="Motor position"):
    pg.setConfigOptions(antialias=True)
    plot = pg.PlotWidget(background=PAL["bg"])
    plot.setLabel("bottom", x_label, color=PAL["text_dim"])
    plot.setLabel("left", y_label, color=PAL["text_dim"])
    plot.getAxis("bottom").setPen(pg.mkPen(color=PAL["border"]))
    plot.getAxis("left").setPen(pg.mkPen(color=PAL["border"]))
    plot.getAxis("bottom").setTextPen(pg.mkPen(color=PAL["text_sec"]))
    plot.getAxis("left").setTextPen(pg.mkPen(color=PAL["text_sec"]))
    plot.showGrid(x=True, y=True, alpha=0.15)
    if title:
        plot.setTitle(title, color=PAL["text_sec"], size="11pt")
    return plot


# ─── Step header widget ───────────────────────────────────────────────────────
class StepHeader(QWidget):
    STATUS_COLORS = {
        "idle":    PAL["text_dim"],
        "running": PAL["amber"],
        "done":    PAL["green"],
        "error":   PAL["red"],
    }

    def __init__(self, step_num, title, parent=None):
        super().__init__(parent)
        self.step_num = step_num
        self._status = "idle"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)

        self.circle = QLabel(str(step_num))
        self.circle.setFixedSize(28, 28)
        self.circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.circle.setStyleSheet(f"""
            border: 2px solid {PAL['text_dim']};
            border-radius: 14px;
            color: {PAL['text_dim']};
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            font-weight: 700;
        """)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("step_title")
        self.tag = make_tag("Idle", "grey")

        lay.addWidget(self.circle)
        lay.addWidget(title_lbl)
        lay.addStretch()
        lay.addWidget(self.tag)

    def set_status(self, status):
        self._status = status
        color = self.STATUS_COLORS.get(status, PAL["text_dim"])
        self.circle.setStyleSheet(f"""
            border: 2px solid {color};
            border-radius: 14px;
            color: {color};
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            font-weight: 700;
        """)
        tag_color = {"idle": "grey", "running": "amber", "done": "green", "error": "red"}.get(status, "grey")
        tag_text  = {"idle": "Idle", "running": "Running…", "done": "Complete", "error": "Error"}.get(status, "Idle")
        self.tag.setObjectName({"grey": "tag_grey", "amber": "tag_amber", "green": "tag_green", "red": "tag_red"}.get(tag_color, "tag_grey"))
        self.tag.setText(tag_text)
        self.tag.style().unpolish(self.tag)
        self.tag.style().polish(self.tag)


# ─── Beam path widget ─────────────────────────────────────────────────────────
class BeamPathWidget(QWidget):
    ELEMENTS = [
        ("Source",  None),
        ("Xtal",    3),
        ("Mirror",  4),
        ("BPM",     5),
        ("Sample",  None),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._step_status = {}
        self.setFixedHeight(70)
        self.setStyleSheet(f"background: {PAL['surface']}; border: 1px solid {PAL['border']}; border-radius: 6px;")

    def update_step(self, step, status):
        self._step_status[step] = status
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        n = len(self.ELEMENTS)
        el_w = 48
        gap = (W - n * el_w) // (n + 1)
        cx_start = gap + el_w // 2

        for i, (label, step) in enumerate(self.ELEMENTS):
            cx = cx_start + i * (el_w + gap)
            cy = H // 2 - 6

            active  = (step is None and i == 0) or (step and self._step_status.get(step) == "done")
            running = step and self._step_status.get(step) == "running"

            if running:
                border_col = QColor(PAL["amber"])
                fill_col   = QColor(PAL["cyan_dim"])
                text_col   = QColor(PAL["amber"])
            elif active:
                border_col = QColor(PAL["green"])
                fill_col   = QColor("#e6f4ea")
                text_col   = QColor(PAL["green"])
            else:
                border_col = QColor(PAL["border"])
                fill_col   = QColor(PAL["surface_hi"])
                text_col   = QColor(PAL["text_dim"])

            # Draw box
            painter.setBrush(fill_col)
            painter.setPen(QPen(border_col, 2))
            painter.drawRoundedRect(cx - 18, cy - 14, 36, 28, 4, 4)

            # Draw label
            painter.setPen(text_col)
            font = QFont("Consolas", 8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(cx - 18, cy - 14, 36, 28, Qt.AlignmentFlag.AlignCenter, label)

            # Draw connector line
            if i < n - 1:
                next_cx = cx_start + (i + 1) * (el_w + gap)
                line_col = QColor(PAL["green"]) if active else QColor(PAL["border"])
                painter.setPen(QPen(line_col, 2))
                painter.drawLine(cx + 18, cy, next_cx - 18, cy)

        # "Beam Path" label top-left
        painter.setPen(QColor(PAL["text_dim"]))
        font = QFont("Consolas", 8)
        painter.setFont(font)
        painter.drawText(8, 12, "BEAM PATH")


# ─── Log widget ───────────────────────────────────────────────────────────────
class LogWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(200)

    def append_log(self, msg, level="info"):
        _colors = {"info": PAL["text_sec"], "ok": PAL["green"],
                   "warn": PAL["amber"],    "error": PAL["red"]}
        color = _colors.get(level, PAL["text_sec"])
        ts = time.strftime("%H:%M:%S")
        self.append(
            f'<span style="color:{PAL["text_dim"]}">{ts}</span> '
            f'<span style="color:{color}">{msg}</span>'
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ─── Setup Tab ───────────────────────────────────────────────────────────────
class SetupTab(QWidget):
    changed          = pyqtSignal()
    pv_readback      = pyqtSignal(str, str)   # (key, value_str)
    _string_refresh  = pyqtSignal(str)         # key — triggers Qt-thread string read

    _RBK_MONO = "font-family: 'JetBrains Mono',Consolas,monospace; font-size: 11px; padding: 0 6px; min-width: 88px;"

    @staticmethod
    def _rbk_style(variant: str) -> str:
        c = PAL['cyan'] if variant == "ok" else (PAL['amber'] if variant == "err" else PAL['text_dim'])
        return f"color: {c}; {SetupTab._RBK_MONO}"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pv_fields          = {}
        self._scan_fields        = {}
        self._pv_value_labels    = {}
        self._monitored_pvs      = {}   # key → epics.PV object
        self._resubscribe_timers = {}   # key → QTimer (debounce)
        self._string_refresh.connect(self._on_string_refresh)
        self._build()

    def _build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner_vlay = QVBoxLayout(inner)
        inner_vlay.setSpacing(12)
        inner_vlay.setContentsMargins(16, 16, 16, 16)
        top_w = QWidget()
        lay = QHBoxLayout(top_w)
        lay.setSpacing(16)
        lay.setContentsMargins(0, 0, 0, 0)

        # PV names — left column has two stacked group boxes
        pv_col = QVBoxLayout()

        motor_labels = {
            "mono_energy":   "Mono Energy",
            "roll":          "DCM Roll",
            "pitch":         "DCM Pitch",
            "mir_slit_top":  "Mirror Slit Top",
            "mir_slit_bot":  "Mirror Slit Bottom",
        }
        motor_box = QGroupBox("Motor PVs")
        motor_lay = QGridLayout(motor_box)
        motor_lay.setSpacing(8)
        motor_lay.setColumnStretch(1, 1)
        hdr_rbv = QLabel("RBV")
        hdr_rbv.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 10px; letter-spacing: 1px;")
        motor_lay.addWidget(hdr_rbv, 0, 2, Qt.AlignmentFlag.AlignHCenter)
        for row, (key, label) in enumerate(motor_labels.items()):
            motor_lay.addWidget(QLabel(label), row, 0)
            ed = QLineEdit(DEFAULT_PVS[key])
            self._pv_fields[key] = ed
            motor_lay.addWidget(ed, row, 1)
            rbk = QLabel("—")
            rbk.setStyleSheet(self._rbk_style("dim"))
            rbk.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._pv_value_labels[key] = rbk
            motor_lay.addWidget(rbk, row, 2)

        other_labels = {
            # Undulator
            "und_energy":      "Undulator Energy",
            "und_harmonic":    "Undulator Harmonic",
            "und_start":       "Undulator Start",
            # DCM Piezos
            "piezo_pitch":     "DCM Piezo Pitch",
            "piezo_roll":      "DCM Piezo Roll",
            # BPM
            "bpm_x":           "BPM X readback",
            "bpm_y":           "BPM Y readback",
            "bpm_intensity":   "BPM Intensity",
            "bpm_sen":         "BPM Sensitivity",
            # Feedback
            "feedback_h":      "H Feedback PV",
            "feedback_v":      "V Feedback PV",
            # Mirror
            "mir_piezo_pitch": "Mirror Piezo Pitch",
            "mir_slit_center": "Mirror Slit Center",
            "mir_slit_size":   "Mirror Slit Size",
            # Ion Chamber
            "ion_chamber":     "Ion Chamber",
            "ic_sen_unit":     "Ion Chamber Sen Unit",
            "ic_sen_num":      "Ion Chamber Sen Num",
        }
        other_box = QGroupBox("Other PVs")
        other_lay = QGridLayout(other_box)
        other_lay.setSpacing(8)
        other_lay.setColumnStretch(1, 1)
        hdr_rbv2 = QLabel("Value")
        hdr_rbv2.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 10px; letter-spacing: 1px;")
        other_lay.addWidget(hdr_rbv2, 0, 2, Qt.AlignmentFlag.AlignHCenter)
        for row, (key, label) in enumerate(other_labels.items()):
            other_lay.addWidget(QLabel(label), row, 0)
            ed = QLineEdit(DEFAULT_PVS[key])
            self._pv_fields[key] = ed
            other_lay.addWidget(ed, row, 1)
            rbk = QLabel("—")
            rbk.setStyleSheet(self._rbk_style("dim"))
            rbk.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._pv_value_labels[key] = rbk
            other_lay.addWidget(rbk, row, 2)

        pv_col.addWidget(motor_box)
        pv_col.addWidget(other_box)
        pv_col.addStretch()

        # Right column
        right = QVBoxLayout()

        scan_box = QGroupBox("Scan Parameters")
        scan_lay = QGridLayout(scan_box)
        scan_defs = [
            ("pitch_start",  "Pitch scan start",  QDoubleSpinBox, -1000.0, 0.0, -0.05, 4),
            ("pitch_stop",   "Pitch scan stop",   QDoubleSpinBox,     0.0, 1000.0,  0.05, 4),
            ("pitch_steps",  "Pitch scan steps",  QSpinBox,        5, 200,   25,   0),
            ("roll_start",   "Roll scan start",   QDoubleSpinBox, -1000.0, 0.0, -0.05, 4),
            ("roll_stop",    "Roll scan stop",    QDoubleSpinBox,     0.0, 1000.0,  0.05, 4),
            ("roll_steps",   "Roll scan steps",   QSpinBox,        5, 200,   21,   0),
            ("settle_time",        "Settle time (s)",        QDoubleSpinBox, 0.0, 5.0, 0.1, 2),
            ("piezo_settle_time",  "Piezo settle time (s)",  QDoubleSpinBox, 0.0, 5.0, 0.2, 2),
            ("piezo_center", "Piezo center value",QDoubleSpinBox,  0.0, 10.0, 5.0,  1),
            ("smart_edge_fraction",    "Smart scan edge fraction",   QDoubleSpinBox, 0.05, 0.5,  0.2, 2),
            ("smart_max_extend_steps", "Smart scan max extend steps",QSpinBox,       1,    50,   10,  0),
            ("smart_fine_sigma_range", "Fine scan range (σ)",        QDoubleSpinBox, 0.5,  10.0, 2.0, 1),
            ("smart_fine_scan_iter",   "Fine scan iterations",       QSpinBox,       1,    10,   3,   0),
            ("dcm_piezo_start",  "DCM pitch piezo scan start",    QDoubleSpinBox, -1000.0, 0.0,  -1.0, 3),
            ("dcm_piezo_stop",   "DCM pitch piezo scan stop",     QDoubleSpinBox,     0.0, 1000.0, 1.0, 3),
            ("dcm_piezo_steps",  "DCM pitch piezo scan steps",    QSpinBox,        3, 200,   21,   0),
            ("mir_piezo_start",  "Mirror pitch piezo scan start", QDoubleSpinBox, -1000.0, 0.0,  -1.0, 3),
            ("mir_piezo_stop",   "Mirror pitch piezo scan stop",  QDoubleSpinBox,     0.0, 1000.0, 1.0, 3),
            ("mir_piezo_steps",  "Mirror pitch piezo scan steps", QSpinBox,        3, 200,   21,   0),
        ]
        for r, (key, lbl, cls, mn, mx, dflt, dec) in enumerate(scan_defs):
            scan_lay.addWidget(QLabel(lbl), r, 0)
            if cls == QDoubleSpinBox:
                sb = NoScrollDoubleSpinBox()
                sb.setDecimals(dec)
                sb.setRange(mn, mx)
                sb.setValue(dflt)
            else:
                sb = NoScrollSpinBox()
                sb.setRange(mn, mx)
                sb.setValue(dflt)
            sb.setMinimumWidth(100)
            self._scan_fields[key] = sb
            scan_lay.addWidget(sb, r, 1)

        conn_box = QGroupBox("Connection")
        conn_lay = QVBoxLayout(conn_box)
        self.sim_check = QCheckBox("Simulation mode (no EPICS required)")
        self.sim_check.setChecked(True)
        if not EPICS_AVAILABLE:
            self.sim_check.setChecked(True)
            self.sim_check.setEnabled(False)
            self.sim_check.setToolTip("pyepics not installed — simulation only")
        conn_lay.addWidget(self.sim_check)

        btn_row = QHBoxLayout()
        test_btn = styled_button("Test EPICS Connection")
        test_btn.clicked.connect(self._test_epics)
        load_btn = styled_button("Load Config…")
        save_btn = styled_button("Save Config…")
        load_btn.clicked.connect(self._load_config)
        save_btn.clicked.connect(self._save_config)
        btn_row.addWidget(test_btn)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        conn_lay.addLayout(btn_row)

        epics_note = QLabel(
            "pyepics available ✓" if EPICS_AVAILABLE
            else "pyepics not installed — running in simulation mode"
        )
        epics_note.setStyleSheet(f"color: {PAL['green'] if EPICS_AVAILABLE else PAL['amber']}; font-size: 11px;")
        conn_lay.addWidget(epics_note)

        right.addWidget(scan_box)
        right.addWidget(conn_box)
        right.addStretch()

        lay.addLayout(pv_col, 2)
        lay.addLayout(right, 1)
        inner_vlay.addWidget(top_w)

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        for ed in self._pv_fields.values():
            ed.textChanged.connect(self.changed)
        for w in self._scan_fields.values():
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.changed)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(self.changed)
        self.sim_check.toggled.connect(self.changed)
        self.sim_check.toggled.connect(self._on_sim_toggled)

        # Live readback via EPICS monitors (callbacks → Qt signal → label update)
        self.pv_readback.connect(self._on_pv_readback)
        # Debounce re-subscribe when a PV name is edited
        for key, ed in self._pv_fields.items():
            ed.textChanged.connect(lambda _text, k=key: self._schedule_resubscribe(k))
        if EPICS_AVAILABLE and not self.sim_check.isChecked():
            self._start_monitoring()

    # ── sim-mode toggle ──────────────────────────────────────────────────────
    def _on_sim_toggled(self, is_sim: bool):
        if is_sim or not EPICS_AVAILABLE:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    # ── EPICS monitor management ─────────────────────────────────────────────
    def _start_monitoring(self):
        for key in self._pv_fields:
            self._subscribe_pv(key)

    def _stop_monitoring(self):
        for pv in self._monitored_pvs.values():
            try:
                pv.disconnect()
            except Exception:
                pass
        self._monitored_pvs.clear()
        for lbl in self._pv_value_labels.values():
            lbl.setText("—")
            lbl.setStyleSheet(self._RBK_STYLE_DIM)

    def _subscribe_pv(self, key: str):
        # Tear down any existing subscription for this key
        old = self._monitored_pvs.pop(key, None)
        if old is not None:
            try:
                old.disconnect()
            except Exception:
                pass

        pv_name = self._pv_fields[key].text().strip()
        if not pv_name or self.sim_check.isChecked() or not EPICS_AVAILABLE:
            self.pv_readback.emit(key, "—")
            return

        # Motors: monitor .RBV field
        actual = (pv_name + ".RBV") if key in MOTOR_PV_KEYS else pv_name

        _string_keys = {"bpm_sen", "ic_sen_unit", "ic_sen_num"}

        def _value_cb(value=None, char_value=None, **_kw):
            if value is None:
                return
            if key in _string_keys:
                # Emit signal to do pv.get(as_string=True) on the Qt thread
                self._string_refresh.emit(key)
                return
            try:
                if isinstance(value, (int, float)):
                    self.pv_readback.emit(key, f"{float(value):.6g}")
                else:
                    # numpy scalar or array
                    v = float(value) if hasattr(value, '__float__') else str(value)[:16]
                    self.pv_readback.emit(key, f"{v:.6g}" if isinstance(v, float) else v)
            except Exception:
                self.pv_readback.emit(key, str(char_value or value)[:16])

        def _conn_cb(pvname=None, conn=None, **_kw):
            if not conn:
                self.pv_readback.emit(key, "n/c")
            elif key in _string_keys:
                self._string_refresh.emit(key)

        import epics as _epics
        try:
            pv = _epics.PV(actual, callback=_value_cb,
                           connection_callback=_conn_cb, auto_monitor=True)
            self._monitored_pvs[key] = pv
        except Exception:
            self.pv_readback.emit(key, "err")

    def _schedule_resubscribe(self, key: str):
        """Debounce PV name edits: wait 1 s of inactivity before re-subscribing."""
        if not EPICS_AVAILABLE or self.sim_check.isChecked():
            return
        t = self._resubscribe_timers.get(key)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda k=key: self._subscribe_pv(k))
            self._resubscribe_timers[key] = t
        t.start(1000)

    def _on_string_refresh(self, key: str):
        pv = self._monitored_pvs.get(key)
        if pv is None:
            return
        try:
            val = pv.get(as_string=True)
            if val is not None:
                self.pv_readback.emit(key, str(val)[:16])
        except Exception:
            pass

    def _on_pv_readback(self, key: str, value: str):
        lbl = self._pv_value_labels.get(key)
        if lbl is None:
            return
        if value in ("—", "n/c", "err"):
            lbl.setStyleSheet(self._rbk_style("err" if value == "err" else "dim"))
        else:
            lbl.setStyleSheet(self._rbk_style("ok"))
        lbl.setText(value)

    def _test_epics(self):
        if not EPICS_AVAILABLE:
            QMessageBox.warning(self, "Test EPICS Connection",
                                "pyepics is not installed — cannot test connections.")
            return
        import epics
        pvs = self.get_pvs()
        timeout = 2.0
        results = {}

        def _check(key, pv_name):
            if not pv_name.strip():
                results[key] = (pv_name, "skipped")
                return
            try:
                pv = epics.PV(pv_name, connection_timeout=timeout)
                connected = pv.wait_for_connection(timeout=timeout)
                if connected:
                    pv.disconnect()
                    results[key] = (pv_name, "ok")
                elif key in MOTOR_PV_KEYS:
                    rbv = epics.PV(pv_name + ".RBV", connection_timeout=timeout)
                    connected_rbv = rbv.wait_for_connection(timeout=timeout)
                    if connected_rbv:
                        rbv.disconnect()
                    results[key] = (pv_name, "ok (via .RBV)" if connected_rbv else "timeout")
                else:
                    results[key] = (pv_name, "timeout")
            except Exception as e:
                msg = str(e)
                results[key] = (pv_name, "timeout" if "access violation" in msg.lower() else f"error: {msg}")

        threads = [threading.Thread(target=_check, args=(k, v)) for k, v in pvs.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        labels = {
            "mono_energy": "Mono Energy", "roll": "DCM Roll", "pitch": "DCM Pitch",
            "mir_slit_top": "Mirror Slit Top", "mir_slit_bot": "Mirror Slit Bottom",
            "und_energy": "Undulator Energy",
            "piezo_pitch": "DCM Piezo Pitch", "piezo_roll": "DCM Piezo Roll",
            "bpm_x": "BPM X", "bpm_y": "BPM Y", "bpm_intensity": "BPM Intensity",
            "feedback_h": "H Feedback", "feedback_v": "V Feedback",
            "und_harmonic": "Und Harmonic", "und_start": "Und Start",
            "mir_piezo_pitch": "Mirror Piezo Pitch", "ion_chamber": "Ion Chamber",
        }
        n_ok = sum(1 for _, (_, s) in results.items() if s in ("ok", "ok (via .RBV)"))
        n_total = sum(1 for _, (pv, s) in results.items() if s != "skipped")

        rows = ""
        for key, (pv_name, status) in results.items():
            label = labels.get(key, key)
            if status in ("ok", "ok (via .RBV)"):
                icon, color = "✓", PAL["green"]
            elif status == "skipped":
                icon, color = "—", PAL["text_dim"]
            else:
                icon, color = "✗", PAL["red"]
            rows += (
                f'<tr>'
                f'<td style="padding:3px 8px;color:{PAL["text_sec"]}">{label}</td>'
                f'<td style="padding:3px 8px;font-family:monospace;color:{PAL["text_dim"]}">{pv_name or "(empty)"}</td>'
                f'<td style="padding:3px 8px;color:{color};font-weight:600">{icon} {status}</td>'
                f'</tr>'
            )

        dlg = QDialog(self)
        dlg.setWindowTitle("EPICS Connection Test")
        dlg.setMinimumWidth(560)
        layout = QVBoxLayout(dlg)
        summary = QLabel(f"<b>{n_ok} / {n_total} PVs connected</b>")
        summary.setStyleSheet(f"font-size:13px; color:{PAL['green'] if n_ok == n_total else PAL['amber']};")
        layout.addWidget(summary)
        text = QLabel(f'<table cellspacing="0">{rows}</table>')
        text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(text)
        close_btn = styled_button("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Config", "dcm_config.json", "JSON files (*.json)")
        if not path:
            return
        cfg = {
            "pvs": self.get_pvs(),
            "scan": self.get_scan_params(),
            "simulate": self.is_simulate(),
        }
        try:
            with open(path, "w") as f:
                json.dump(cfg, f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Save Config", f"Could not write file:\n{e}")

    def _apply_config(self, cfg):
        for k, v in cfg.get("pvs", {}).items():
            if k in self._pv_fields:
                self._pv_fields[k].setText(str(v))
        for k, v in cfg.get("scan", {}).items():
            if k not in self._scan_fields:
                continue
            w = self._scan_fields[k]
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.setValue(v)
            elif isinstance(w, QComboBox):
                idx = w.findText(str(v))
                if idx >= 0:
                    w.setCurrentIndex(idx)
        if "simulate" in cfg:
            self.sim_check.setChecked(bool(cfg["simulate"]))

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Config", "", "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Load Config", f"Could not read file:\n{e}")
            return
        self._apply_config(cfg)

    def get_pvs(self):
        return {k: v.text() for k, v in self._pv_fields.items()}

    def get_scan_params(self):
        out = {}
        for k, w in self._scan_fields.items():
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText()
        return out

    def is_simulate(self):
        return self.sim_check.isChecked()


# ─── Energy Table Tab ─────────────────────────────────────────────────────────
class EnergyTableTab(QWidget):
    row_selected = pyqtSignal(dict)
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data     = [dict(r) for r in DEFAULT_LOOKUP]
        self._selected = None
        self._records  = []
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        # ── Top: energy table ──
        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 8)
        top_lay.setSpacing(8)

        bar = QHBoxLayout()
        add_btn    = styled_button("+ Add Row")
        del_btn    = styled_button("Remove Row")
        imp_btn    = styled_button("Import CSV…")
        exp_btn    = styled_button("Export CSV…")
        sort_lbl   = QLabel("Sort by:")
        sort_lbl.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 11px;")
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Mono E (keV)", "Undulator E (keV)", "Harmonic", "Roll", "Pitch"])
        self._sort_combo.setFixedWidth(140)
        sort_btn = styled_button("↑ Sort")
        sort_btn.setFixedWidth(60)
        for b in [add_btn, del_btn, imp_btn, exp_btn]:
            bar.addWidget(b)
        bar.addSpacing(12)
        bar.addWidget(sort_lbl)
        bar.addWidget(self._sort_combo)
        bar.addWidget(sort_btn)
        bar.addStretch()
        self.sel_label = QLabel("No row selected")
        self.sel_label.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 11px;")
        bar.addWidget(self.sel_label)
        top_lay.addLayout(bar)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Mono E (keV)", "Undulator E (keV)", "Harmonic", "Roll", "Pitch",
            "BPM Sen", "IC Sen Unit", "IC Sen Num",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellChanged.connect(self._on_cell_changed)
        top_lay.addWidget(self.table)

        add_btn.clicked.connect(self._add_row)
        del_btn.clicked.connect(self._del_row)
        imp_btn.clicked.connect(self._import_csv)
        exp_btn.clicked.connect(self._export_csv)
        sort_btn.clicked.connect(self._sort_rows)

        self._refresh_table()
        splitter.addWidget(top)

        # ── Bottom: lookup table ──
        bot_box = QGroupBox("Lookup Table")
        bot_lay = QVBoxLayout(bot_box)

        lk_bar = QHBoxLayout()
        lk_imp_btn  = styled_button("Import CSV…")
        lk_exp_btn  = styled_button("Export CSV…")
        lk_del_btn  = styled_button("Remove Row")
        lk_clr_btn  = styled_button("Clear All")
        for b in [lk_imp_btn, lk_exp_btn, lk_del_btn, lk_clr_btn]:
            lk_bar.addWidget(b)
        lk_bar.addStretch()
        bot_lay.addLayout(lk_bar)

        self._lookup_table = QTableWidget()
        self._lookup_table.setAlternatingRowColors(True)
        self._lookup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._lookup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        bot_lay.addWidget(self._lookup_table)

        lk_imp_btn.clicked.connect(self._import_lookup_csv)
        lk_exp_btn.clicked.connect(self._export_lookup_csv)
        lk_del_btn.clicked.connect(self._del_record_row)
        lk_clr_btn.clicked.connect(self._clear_records)

        self._refresh_lookup_table()
        splitter.addWidget(bot_box)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        lay.addWidget(splitter)

    _COLS = ["mono_e", "ue", "harmonic", "roll", "pitch", "bpm_sen", "ic_sen_unit", "ic_sen_num"]
    _SORT_KEYS = ["mono_e", "ue", "harmonic", "roll", "pitch"]

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._data))
        for r, row in enumerate(self._data):
            for c, key in enumerate(self._COLS):
                val = row.get(key, "")
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

    def _on_cell_changed(self, r, c):
        if r >= len(self._data):
            return
        key = self._COLS[c]
        text = self.table.item(r, c).text()
        if key in ("bpm_sen", "ic_sen_unit", "ic_sen_num"):
            self._data[r][key] = text
            self.changed.emit()
            return
        try:
            val = int(text) if key == "harmonic" else float(text)
            self._data[r][key] = val
            self.changed.emit()
        except ValueError:
            pass

    def _sort_rows(self):
        idx = self._sort_combo.currentIndex()
        key = self._SORT_KEYS[idx] if idx < len(self._SORT_KEYS) else "mono_e"
        self._data.sort(key=lambda r: r.get(key, 0))
        self._refresh_table()
        self.changed.emit()

    def _on_select(self):
        rows = self.table.selectedItems()
        if not rows:
            self._selected = None
            self.sel_label.setText("No row selected")
            return
        r = self.table.currentRow()
        self._selected = self._data[r]
        self.sel_label.setText(
            f"Selected: MonoE = {self._selected['mono_e']} keV  |  UE = {self._selected['ue']} keV"
        )
        self.sel_label.setStyleSheet(f"color: {PAL['cyan']}; font-size: 11px; font-family: 'JetBrains Mono', monospace;")
        self.row_selected.emit(self._selected)

    def _add_row(self):
        if self._data:
            new_row = dict(self._data[-1])
        else:
            new_row = {"mono_e": 0.0, "ue": 0.0, "harmonic": 1, "roll": 0.0, "pitch": 0.0,
                       "bpm_sen": "1", "ic_sen_unit": "2", "ic_sen_num": "2"}
        self._data.append(new_row)
        self._refresh_table()
        self.table.selectRow(len(self._data) - 1)
        self.changed.emit()

    def _del_row(self):
        r = self.table.currentRow()
        if r < 0:
            return
        self._data.pop(r)
        self._refresh_table()
        self.changed.emit()

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV files (*.csv)")
        if not path:
            return
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            self._data = []
            for row in reader:
                try:
                    mono_e = float(row.get("mono_e", 0))
                    self._data.append({
                        "mono_e":      mono_e,
                        "ue":          float(row.get("ue", 0)),
                        "harmonic":    int(row["harmonic"]) if "harmonic" in row else calc_harmonic(mono_e),
                        "roll":        float(row.get("roll", 0)),
                        "pitch":       float(row.get("pitch", 0)),
                        "bpm_sen":     str(row.get("bpm_sen", "1")),
                        "ic_sen_unit": str(row.get("ic_sen_unit", "2")),
                        "ic_sen_num":  str(row.get("ic_sen_num", "2")),
                    })
                except (ValueError, KeyError):
                    pass
        self._refresh_table()
        self.changed.emit()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Energy Table CSV", "energy_table.csv", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["mono_e", "ue", "harmonic", "roll", "pitch",
                                                    "bpm_sen", "ic_sen_unit", "ic_sen_num"])
            writer.writeheader()
            writer.writerows(self._data)

    def selected_row(self):
        return self._selected

    def get_table_data(self):
        return [dict(r) for r in self._data]

    def set_table_data(self, data):
        self._data = [dict(r) for r in data]
        self._refresh_table()

    # ── Lookup table (record of past alignments) ──

    def _refresh_lookup_table(self):
        all_keys = list(dict.fromkeys(k for row in self._records for k in row))
        # ensure Timestamp is always first
        if "Timestamp" in all_keys:
            all_keys.remove("Timestamp")
            all_keys.insert(0, "Timestamp")
        self._lookup_table.blockSignals(True)
        self._lookup_table.setColumnCount(len(all_keys))
        self._lookup_table.setHorizontalHeaderLabels(all_keys)
        self._lookup_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._lookup_table.setRowCount(len(self._records))
        for r, row in enumerate(self._records):
            for c, lbl in enumerate(all_keys):
                item = QTableWidgetItem(str(row.get(lbl, "")))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._lookup_table.setItem(r, c, item)
        self._lookup_table.blockSignals(False)

    def append_record_row(self, values: dict):
        self._records.append(dict(values))
        self._refresh_lookup_table()
        self.changed.emit()

    def _del_record_row(self):
        r = self._lookup_table.currentRow()
        if r < 0:
            return
        self._records.pop(r)
        self._refresh_lookup_table()
        self.changed.emit()

    def _clear_records(self):
        reply = QMessageBox.question(self, "Clear Lookup Table",
                                     "Remove all rows from the lookup table?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._records.clear()
            self._refresh_lookup_table()
            self.changed.emit()

    def _import_lookup_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Lookup CSV", "", "CSV files (*.csv)")
        if not path:
            return
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self._records.append(dict(row))
        self._refresh_lookup_table()
        self.changed.emit()

    def _export_lookup_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Lookup CSV", "lookup_table.csv", "CSV files (*.csv)")
        if not path:
            return
        all_keys = list(dict.fromkeys(k for row in self._records for k in row))
        if "Timestamp" in all_keys:
            all_keys.remove("Timestamp")
            all_keys.insert(0, "Timestamp")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            for row in self._records:
                writer.writerow({k: row.get(k, "") for k in all_keys})

    def get_record_data(self):
        return [dict(r) for r in self._records]

    def set_record_data(self, data):
        self._records = [dict(r) for r in data]
        self._refresh_lookup_table()


# ─── Mirror stripe indicator ──────────────────────────────────────────────────
class MirrorStripeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        lbl = QLabel("Mirror Stripe:")
        lbl.setStyleSheet(f"color: {PAL['text_sec']}; font-size: 11px;")
        lay.addWidget(lbl)
        self._btns = {}
        for stripe in ("Si", "Rh", "Pt"):
            b = QLabel(stripe)
            b.setFixedSize(38, 22)
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setStyleSheet(self._off_style())
            self._btns[stripe] = b
            lay.addWidget(b)
        self._changing = QLabel("Changing…")
        self._changing.setStyleSheet(f"color: {PAL['amber']}; font-size: 11px; font-style: italic;")
        self._changing.setVisible(False)
        lay.addWidget(self._changing)
        lay.addStretch()

    def _off_style(self):
        return (f"background: {PAL['surface']}; border: 1px solid {PAL['border']};"
                f" border-radius: 3px; color: {PAL['text_dim']}; font-size: 11px;")

    def _on_style(self):
        return (f"background: {PAL['green']}; border: 1px solid {PAL['green']};"
                f" border-radius: 3px; color: white; font-size: 11px; font-weight: 700;")

    def set_stripe(self, stripe):
        if stripe == "changing":
            for b in self._btns.values():
                b.setStyleSheet(self._off_style())
            self._changing.setVisible(True)
        else:
            self._changing.setVisible(False)
            for name, b in self._btns.items():
                b.setStyleSheet(self._on_style() if name == stripe else self._off_style())

# ─── Motor → scan plot mapping ────────────────────────────────────────────────
# Plot A: position/zero-crossing scans. Plot B: intensity peak scans.
_SCAN_PLOT_A = {
    "roll":         ("Roll Scan",              "BPM X (mm)",      "Roll position"),
    "mir_slit_cen": ("Slit Scan  4A",          "Signal",          "Slit center (mm)"),
    "mir_piezo":    ("Mirror Piezo Pitch  4C",   "BPM Y (mm)",      "Piezo position"),
}
_SCAN_PLOT_B = {
    "pitch":        ("Pitch Scan",             "Intensity (a.u.)", "Pitch position"),
    "mir_vdm":      ("VDM Scan  4D",           "Signal",          "VDM:Y"),
    "mir_coupled":  ("VFM+VDM Scan  4E",       "Signal",          "VFM:Y"),
}

# ─── Alignment Tab ────────────────────────────────────────────────────────────
class AlignmentTab(QWidget):
    alignment_done = pyqtSignal(bool)   # emitted after worker finishes; True = success

    _SUBSTEP_TEXT = {
        "1_1a": "Read Energy table",
        "2_2a": "Turn off BPM feedback",
        "2_2b": "Apply Energy table settings",
        "2_2c": "Mirror out",
        "3_3a": "Puts DCM Piezo at 5",
        "3_3b": "Pitch scan → intensity peak",
        "3_3c": "Roll scan → BPM x = 0",
        "3_3d": "Pitch scan → intensity peak",
        "4_4A": "Slit scan → beam center",
        "4_4B": "Mirror in",
        "4_4C": "Mirror piezo pitch scan → BPM y = 0",
        "4_4D": "VDM:Y scan → peak",
        "4_4E": "Coupled VFM:Y+VDM:Y → peak",
        "5_5mir": "Mirror in",
        "5_5a": "Turn on H feedback",
        "5_5b": "DCM piezo pitch scan → max intensity",
        "5_5c": "Mirror piezo pitch scan → BPM y = 0",
        "5_5d": "Turn on V feedback",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_row     = None
        self._worker           = None
        self._thread           = None
        self._last_scan_results = {}
        self._build()
        self._on_skip_mirror_changed()
        QTimer.singleShot(800, self._refresh_stripe_display)

    @staticmethod
    def _badge_style(color):
        return (f"border: 2px solid {color}; border-radius: 11px; color: {color};"
                f" font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 700;")

    def _build(self):
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ═══════════════════ LEFT PANEL ═════════════════════════════
        left = QWidget()
        left.setFixedWidth(310)
        left.setStyleSheet(
            f"background: {PAL['surface']}; border-right: 1px solid {PAL['border']};"
        )
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 12, 12, 12)
        left_lay.setSpacing(8)

        # Controls
        ctrl_box = QGroupBox()
        ctrl_l = QVBoxLayout(ctrl_box)
        ctrl_l.setSpacing(6)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.start_btn = QPushButton("▶  Start Alignment")
        self.start_btn.setFixedWidth(160)
        self.abort_btn = QPushButton("■  Abort")
        self.abort_btn.setFixedWidth(80)
        self.abort_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.abort_btn)
        btn_row.addStretch()
        ctrl_l.addLayout(btn_row)
        self._refresh_start_btn()
        self._refresh_abort_btn()
        self.skip_mirror_chk = QCheckBox("Skip mirror alignment (Step 4)")
        self.skip_mirror_chk.setChecked(True)
        self.skip_mirror_chk.setToolTip(
            "When checked, Step 4 is bypassed; mirror is inserted before Step 5"
        )
        self.skip_mirror_chk.stateChanged.connect(self._on_skip_mirror_changed)
        ctrl_l.addWidget(self.skip_mirror_chk)
        self.confirm_chk = QCheckBox("Confirm each step")
        self.confirm_chk.setChecked(False)
        self.confirm_chk.setToolTip(
            "When checked, alignment pauses after each scan substep for operator review"
        )
        ctrl_l.addWidget(self.confirm_chk)
        self.proceed_btn = QPushButton("▶  Proceed")
        self.proceed_btn.setFixedWidth(120)
        self.proceed_btn.setVisible(False)
        self.proceed_btn.clicked.connect(self._proceed_clicked)
        ctrl_l.addWidget(self.proceed_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        ctrl_l.addWidget(self.progress)
        self.row_label = QLabel("No energy row selected — choose one in Energy Table")
        self.row_label.setStyleSheet(f"color: {PAL['amber']}; font-size: 10px;")
        self.row_label.setWordWrap(True)
        ctrl_l.addWidget(self.row_label)
        left_lay.addWidget(ctrl_box)

        # Beam path
        self.beam_path = BeamPathWidget()
        left_lay.addWidget(self.beam_path)

        # Step list (scrollable)
        step_scroll = QScrollArea()
        step_scroll.setWidgetResizable(True)
        step_scroll.setFrameShape(QFrame.Shape.NoFrame)
        step_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        steps_inner = QWidget()
        steps_lay = QVBoxLayout(steps_inner)
        steps_lay.setContentsMargins(0, 4, 0, 4)
        steps_lay.setSpacing(1)

        self._step_row_info = {}    # step_num → {"widget", "badge", "tag"}
        self._substep_labels = {}   # "step_substep" → QLabel

        step_defs = [
            (1, "Load Energy Table Settings",
             [("1a", "Read Energy table")]),
            (2, "Apply Energy Table Settings",
             [("2a", "Turn off BPM feedback"),
              ("2b", "Apply Energy table settings"),
              ("2c", "Mirror out")]),
            (3, "DCM Piezo Alignment",
             [("3a", "Puts DCM Piezo at 5"),
              ("3b", "Pitch scan → intensity peak"),
              ("3c", "Roll scan → BPM x = 0"),
              ("3d", "Pitch scan → intensity peak")]),
            (4, "Mirror Alignment",
             [("4A", "Slit scan → beam center"),
              ("4B", "Mirror in"),
              ("4C", "Mirror piezo pitch scan → BPM y = 0"),
              ("4D", "VDM:Y scan → peak"),
              ("4E", "Coupled VFM:Y+VDM:Y → peak")]),
            (5, "Enable Feedback Loops",
             [("5mir", "Mirror in"),
              ("5a", "Turn on H feedback"),
              ("5b", "DCM piezo pitch scan → max intensity"),
              ("5c", "Mirror piezo pitch scan → BPM y = 0"),
              ("5d", "Turn on V feedback")]),
        ]

        for step_num, title, substeps in step_defs:
            step_w = QWidget()
            sh = QHBoxLayout(step_w)
            sh.setContentsMargins(6, 5, 6, 5)
            sh.setSpacing(8)
            badge = QLabel(str(step_num))
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(self._badge_style(PAL["text_dim"]))
            title_lbl = QLabel(title)
            title_lbl.setWordWrap(True)
            title_lbl.setStyleSheet(
                f"color: {PAL['text_sec']}; font-size: 11px; font-weight: 600;"
            )
            tag = make_tag("Idle", "grey")
            sh.addWidget(badge)
            sh.addWidget(title_lbl, 1)
            sh.addWidget(tag)
            self._step_row_info[step_num] = {"widget": step_w, "badge": badge, "tag": tag}
            steps_lay.addWidget(step_w)

            for sub_id, sub_txt in substeps:
                sub_lbl = QLabel(f"    ○  {sub_id.upper()}: {sub_txt}")
                sub_lbl.setStyleSheet(
                    f"color: {PAL['text_dim']}; font-size: 11px;"
                )
                self._substep_labels[f"{step_num}_{sub_id}"] = sub_lbl
                steps_lay.addWidget(sub_lbl)

        steps_lay.addStretch()

        # Visibility is set by _on_skip_mirror_changed() called after _build()
        self._substep_labels["5_5mir"].setVisible(False)

        step_scroll.setWidget(steps_inner)
        left_lay.addWidget(step_scroll, 1)
        main_lay.addWidget(left)

        # ═══════════════════ RIGHT PANEL ════════════════════════════
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 12, 12, 12)
        right_lay.setSpacing(8)

        # BPM strip
        bpm_w = QGroupBox("Live BPM")
        bpm_l = QHBoxLayout(bpm_w)
        bpm_l.setSpacing(16)
        for attr, label, unit in [
            ("_bpm_x_lbl", "BPM X", "mm"),
            ("_bpm_y_lbl", "BPM Y", "mm"),
            ("_bpm_i_lbl", "Intensity", "a.u."),
        ]:
            w, val = make_readout(label, "—", unit)
            setattr(self, attr, val)
            bpm_l.addWidget(w)
            bpm_l.addWidget(make_separator())
        fb_w = QWidget()
        fb_l = QVBoxLayout(fb_w)
        fb_l.setContentsMargins(0, 0, 0, 0)
        self._fb_h = make_tag("H FB  OFF", "grey")
        self._fb_v = make_tag("V FB  OFF", "grey")
        fb_l.addWidget(self._fb_h)
        fb_l.addWidget(self._fb_v)
        bpm_l.addWidget(fb_w)
        bpm_l.addStretch()
        right_lay.addWidget(bpm_w)

        self._stripe_widget = MirrorStripeWidget()
        right_lay.addWidget(self._stripe_widget)

        # Scan plots (always visible, updated per scan type)
        plot_w = QWidget()
        plot_lay = QHBoxLayout(plot_w)
        plot_lay.setContentsMargins(0, 0, 0, 0)
        plot_lay.setSpacing(8)
        self._plot_a = make_plot("Scan A", "Signal", "Motor position")
        self._plot_b = make_plot("Scan B", "Intensity", "Motor position")
        self._pa_curve   = self._plot_a.plot([], [], pen=pg.mkPen(PAL["cyan"], width=2))
        self._pa_scatter = pg.ScatterPlotItem(size=5, brush=pg.mkBrush(PAL["cyan"]))
        self._plot_a.addItem(self._pa_scatter)
        self._pa_peak = pg.InfiniteLine(angle=90, pen=pg.mkPen(PAL["amber"], width=1.5,
                                                                style=Qt.PenStyle.DashLine))
        self._plot_a.addItem(self._pa_peak)
        self._pa_peak.setVisible(False)
        self._pb_curve   = self._plot_b.plot([], [], pen=pg.mkPen(PAL["cyan"], width=2),
                                              fillLevel=0,
                                              brush=pg.mkBrush(PAL["cyan_dim"] + "88"))
        self._pb_scatter = pg.ScatterPlotItem(size=5, brush=pg.mkBrush(PAL["cyan"]))
        self._plot_b.addItem(self._pb_scatter)
        self._pb_peak = pg.InfiniteLine(angle=90, pen=pg.mkPen(PAL["amber"], width=1.5,
                                                                style=Qt.PenStyle.DashLine))
        self._plot_b.addItem(self._pb_peak)
        self._pb_peak.setVisible(False)
        self._pa_xs, self._pa_ys, self._pa_motor = [], [], None
        self._pb_xs, self._pb_ys, self._pb_motor = [], [], None
        plot_lay.addWidget(self._plot_a)
        plot_lay.addWidget(self._plot_b)
        right_lay.addWidget(plot_w, 1)

        # Log
        log_box = QGroupBox("Alignment Log")
        log_l = QVBoxLayout(log_box)
        log_l.setContentsMargins(8, 8, 8, 8)
        self.log = LogWidget()
        self.log.setMaximumHeight(180)
        clr = styled_button("Clear")
        clr.setMaximumWidth(80)
        clr.clicked.connect(self.log.clear)
        log_l.addWidget(self.log)
        log_l.addWidget(clr)
        right_lay.addWidget(log_box)

        main_lay.addWidget(right, 1)
        self.start_btn.clicked.connect(self.start_alignment)
        self.abort_btn.clicked.connect(self.abort_alignment)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_tag(self, tag, text, color):
        tag.setText(text)
        obj = {"green": "tag_green", "amber": "tag_amber",
               "red": "tag_red", "cyan": "tag_cyan"}.get(color, "tag_grey")
        tag.setObjectName(obj)
        tag.style().unpolish(tag)
        tag.style().polish(tag)

    def _set_step_ui(self, step_num, status):
        info = self._step_row_info.get(step_num)
        if not info:
            return
        color = {"idle": PAL["text_dim"], "running": PAL["amber"],
                 "done": PAL["green"],    "error":   PAL["red"]}.get(status, PAL["text_dim"])
        info["badge"].setStyleSheet(self._badge_style(color))
        tag_map = {"idle": ("Idle", "grey"), "running": ("Running…", "amber"),
                   "done": ("Done", "green"), "error": ("Error", "red")}
        self._set_tag(info["tag"], *tag_map.get(status, ("Idle", "grey")))
        if status == "running":
            info["widget"].setStyleSheet(
                f"background: #fff8e7; border-radius: 4px;"
            )
        else:
            info["widget"].setStyleSheet("background: transparent; border-radius: 4px;")

    def _on_skip_mirror_changed(self, _=None):
        skip = self.skip_mirror_chk.isChecked()
        lbl = self._substep_labels.get("5_5mir")
        if lbl:
            lbl.setVisible(skip)

    def _refresh_stripe_display(self):
        if not EPICS_AVAILABLE:
            return
        import concurrent.futures
        def _read():
            try:
                import epics as _epics
                vfm = _epics.caget(_STRIPE_VFM_X_PV + ".RBV", timeout=2.0)
                vdm = _epics.caget(_STRIPE_VDM_X_PV + ".RBV", timeout=2.0)
                if vfm is None or vdm is None:
                    return None
                for stripe, pos in _STRIPE_POSITIONS.items():
                    if abs(vfm - pos["vfm_x"]) <= 10 and abs(vdm - pos["vdm_x"]) <= 10:
                        return stripe
            except Exception:
                pass
            return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_read)
            while not fut.done():
                QApplication.processEvents()
            stripe = fut.result()
        if stripe:
            self._stripe_widget.set_stripe(stripe)

    def _set_substep(self, key, status, detail=""):
        lbl = self._substep_labels.get(key)
        if not lbl:
            return
        sub_id = (key.split("_", 1)[1] if "_" in key else key).upper()
        base = f"{sub_id}: {self._SUBSTEP_TEXT.get(key, key)}"
        suffix = f" ({detail})" if detail else ""
        if status == "running":
            lbl.setText(f"    ⟳  {base}")
            lbl.setStyleSheet(
                f"color: {PAL['amber']}; font-size: 11px; font-weight: 600;"
            )
        elif status == "waiting":
            lbl.setText(f"    ⏸  {base}{suffix}")
            lbl.setStyleSheet(
                f"color: {PAL['amber']}; font-size: 11px; font-style: italic;"
            )
        elif status == "done":
            lbl.setText(f"    ✓  {base}{suffix}")
            lbl.setStyleSheet(f"color: {PAL['green']}; font-size: 11px;")
        else:
            lbl.setText(f"    ○  {base}")
            lbl.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 11px;")

    def _start_scan(self, plot_id, motor):
        title, y_label, x_label = (_SCAN_PLOT_A if plot_id == "A" else _SCAN_PLOT_B)[motor]
        if plot_id == "A":
            self._pa_xs.clear(); self._pa_ys.clear()
            self._pa_motor = motor
            self._pa_curve.setData([], [])
            self._pa_scatter.setData([], [])
            self._pa_peak.setVisible(False)
            self._plot_a.setLabel("left",   y_label, color=PAL["text_dim"])
            self._plot_a.setLabel("bottom", x_label, color=PAL["text_dim"])
            self._plot_a.setTitle(title, color=PAL["text_sec"], size="11pt")
        else:
            self._pb_xs.clear(); self._pb_ys.clear()
            self._pb_motor = motor
            self._pb_curve.setData([], [])
            self._pb_scatter.setData([], [])
            self._pb_peak.setVisible(False)
            self._plot_b.setLabel("left",   y_label, color=PAL["text_dim"])
            self._plot_b.setLabel("bottom", x_label, color=PAL["text_dim"])
            self._plot_b.setTitle(title, color=PAL["text_sec"], size="11pt")

    # ── Public ────────────────────────────────────────────────────────────────

    def _refresh_abort_btn(self):
        self.abort_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PAL['bg']};"
            f"  color: {PAL['red']};"
            f"  border: 2px solid {PAL['red']};"
            f"  border-radius: 5px;"
            f"  padding: 6px 16px;"
            f"  font-weight: 600;"
            f"  font-size: 12px;"
            f"}}"
            f"QPushButton:hover {{ background: {PAL['tag_red_bg']}; }}"
            f"QPushButton:disabled {{"
            f"  background: {PAL['surface']};"
            f"  color: {PAL['border']};"
            f"  border-color: {PAL['surface_hi']};"
            f"}}"
        )

    def _refresh_start_btn(self):
        self.start_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PAL['cyan_dim']};"
            f"  color: {PAL['text_pri']};"
            f"  border: 2px solid {PAL['cyan']};"
            f"  border-radius: 5px;"
            f"  padding: 7px 20px;"
            f"  font-size: 13px;"
            f"  font-weight: 700;"
            f"}}"
            f"QPushButton:hover {{ background: {PAL['cyan']}; color: {PAL['text_pri']}; }}"
            f"QPushButton:disabled {{"
            f"  background: {PAL['surface_hi']};"
            f"  color: {PAL['text_dim']};"
            f"  border-color: {PAL['border']};"
            f"}}"
        )

    def set_selected_row(self, row):
        self._selected_row = row
        self.row_label.setText(
            f"MonoE={row['mono_e']} keV  UE={row['ue']} keV  "
            f"Roll={row['roll']}  Pitch={row['pitch']}"
        )
        self.row_label.setStyleSheet(
            f"color: {PAL['cyan']}; font-size: 10px;"
            f" font-family: 'JetBrains Mono', monospace;"
        )

    def start_alignment(self, pvs=None, scan_params=None, simulate=True, mirror_stages=None):
        if not self._selected_row:
            QMessageBox.warning(self, "No row selected",
                                "Please select an energy row in the Energy Table tab first.")
            return
        pvs           = pvs          or DEFAULT_PVS
        scan_params   = scan_params  or DEFAULT_SCAN
        mirror_stages = mirror_stages or DEFAULT_MIRROR_STAGES

        self._reset_ui()
        self.start_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)

        self._thread = QThread()
        self._worker = AlignmentWorker(
            pvs, scan_params, self._selected_row,
            simulate=simulate,
            skip_mirror=self.skip_mirror_chk.isChecked(),
            mirror_stages=mirror_stages,
            confirm_mode=self.confirm_chk.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self._on_log)
        self._worker.step_status.connect(self._on_step_status)
        self._worker.scan_point.connect(self._on_scan_point)
        self._worker.scan_peak.connect(self._on_scan_peak)
        self._worker.bpm_update.connect(self._on_bpm_update)
        self._worker.feedback_update.connect(self._on_feedback)
        self._worker.substep_status.connect(self._set_substep)
        self._worker.confirm_needed.connect(self._on_confirm_needed)
        self._worker.scan_results_ready.connect(self._on_scan_results)
        self._worker.stripe_status.connect(self._stripe_widget.set_stripe)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def abort_alignment(self):
        if self._worker:
            self._worker.abort()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_log(self, msg, level):
        self.log.append_log(msg, level)

    def _on_step_status(self, step, status):
        self._set_step_ui(step, status)
        self.beam_path.update_step(step, status)
        done = sum(
            1 for info in self._step_row_info.values()
            if info["tag"].text() == "Done"
        )
        self.progress.setValue(done)

    def _on_scan_point(self, motor, x, y):
        if motor in _SCAN_PLOT_A:
            if self._pa_motor != motor:
                self._start_scan("A", motor)
            self._pa_xs.append(x); self._pa_ys.append(y)
            self._pa_curve.setData(self._pa_xs, self._pa_ys)
            self._pa_scatter.setData(self._pa_xs, self._pa_ys)
        elif motor in _SCAN_PLOT_B:
            if self._pb_motor != motor:
                self._start_scan("B", motor)
            self._pb_xs.append(x); self._pb_ys.append(y)
            self._pb_curve.setData(self._pb_xs, self._pb_ys)
            self._pb_scatter.setData(self._pb_xs, self._pb_ys)

    def _on_scan_peak(self, motor, peak):
        if motor in _SCAN_PLOT_A:
            self._pa_peak.setValue(peak)
            self._pa_peak.setVisible(True)
        elif motor in _SCAN_PLOT_B:
            self._pb_peak.setValue(peak)
            self._pb_peak.setVisible(True)

    def _on_bpm_update(self, x, y, intensity):
        self._bpm_x_lbl.setText(f"{x:+.4f}")
        self._bpm_y_lbl.setText(f"{y:+.4f}")
        self._bpm_i_lbl.setText(f"{intensity:.3f}")
        _s = "font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700;"
        self._bpm_x_lbl.setStyleSheet(
            f"color: {PAL['green'] if abs(x) < 0.005 else PAL['amber']}; {_s}"
        )
        self._bpm_y_lbl.setStyleSheet(
            f"color: {PAL['green'] if abs(y) < 0.005 else PAL['amber']}; {_s}"
        )
        self._bpm_i_lbl.setStyleSheet(
            f"color: {PAL['green'] if intensity > 0.9 else PAL['cyan']}; {_s}"
        )

    def _on_feedback(self, h, v):
        self._set_tag(self._fb_h, f"H FB  {'ON' if h else 'OFF'}", "green" if h else "grey")
        self._set_tag(self._fb_v, f"V FB  {'ON' if v else 'OFF'}", "green" if v else "grey")

    def _on_scan_results(self, results: dict):
        self._last_scan_results = results

    def _on_confirm_needed(self, substep_key):
        self.proceed_btn.setVisible(True)
        self.proceed_btn.setEnabled(True)
        self.log.append_log(f"  ⏸  Waiting for operator confirmation after {substep_key} — click Proceed to continue", "warn")

    def _proceed_clicked(self):
        self.proceed_btn.setEnabled(False)
        self.proceed_btn.setVisible(False)
        if self._worker:
            self._worker.confirm()

    def _on_finished(self, success):
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        self.proceed_btn.setVisible(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self.alignment_done.emit(success)

    def _reset_ui(self):
        for step_num in self._step_row_info:
            self._set_step_ui(step_num, "idle")
        for step in range(1, 6):
            self.beam_path.update_step(step, "idle")
        self.progress.setValue(0)
        for key in self._substep_labels:
            self._set_substep(key, "idle")
        self._pa_xs.clear(); self._pa_ys.clear(); self._pa_motor = None
        self._pb_xs.clear(); self._pb_ys.clear(); self._pb_motor = None
        self._pa_curve.setData([], [])
        self._pa_scatter.setData([], [])
        self._pb_curve.setData([], [])
        self._pb_scatter.setData([], [])
        self._pa_peak.setVisible(False)
        self._pb_peak.setVisible(False)
        self._plot_a.setTitle("Scan A", color=PAL["text_sec"], size="11pt")
        self._plot_b.setTitle("Scan B", color=PAL["text_sec"], size="11pt")
        self.log.clear()


# ─── Mirror Tab ───────────────────────────────────────────────────────────────
class MirrorTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mirror_stages = [dict(s) for s in DEFAULT_MIRROR_STAGES]
        self._scan_fields   = {}
        self._is_simulate   = lambda: False
        self._build()

    def set_simulate_fn(self, fn):
        self._is_simulate = fn

    def _build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        # ── Mirror Alignment Parameters ──
        scan_box = QGroupBox("Mirror Alignment Parameters")
        scan_lay = QGridLayout(scan_box)
        scan_lay.setSpacing(8)
        scan_lay.addWidget(QLabel("Signal source"), 0, 0)
        sig_cb = QComboBox()
        sig_cb.addItems(["BPM Intensity", "Ion Chamber"])
        self._scan_fields["mir_signal"] = sig_cb
        scan_lay.addWidget(sig_cb, 0, 1)
        sig_cb.currentTextChanged.connect(self.changed)

        mir_scan_defs = [
            ("mir_slit_size_a",    "Slit size 4A (mm)",     QDoubleSpinBox,  0.01,  5.0,   0.1,  3),
            ("mir_slit_cen_start", "Slit scan start (mm)",  QDoubleSpinBox, -20.0,  0.0,  -2.0,  2),
            ("mir_slit_cen_stop",  "Slit scan stop (mm)",   QDoubleSpinBox,  0.0,  20.0,   2.0,  2),
            ("mir_slit_cen_steps", "Slit scan steps",       QSpinBox,        3,    200,    21,   0),
            ("mir_slit_size_b",    "Slit size 4C (mm)",     QDoubleSpinBox,  0.01,  5.0,   0.2,  3),
            ("mir_vdm_start",      "VDM scan start offset", QDoubleSpinBox, -5000., 0.,  -500.,  1),
            ("mir_vdm_stop",       "VDM scan stop offset",  QDoubleSpinBox,  0., 5000.,   500.,  1),
            ("mir_vdm_steps",      "VDM scan steps",        QSpinBox,        3,    200,    21,   0),
            ("mir_vfm_start",      "VFM scan start offset", QDoubleSpinBox, -5000., 0.,  -250.,  1),
            ("mir_vfm_stop",       "VFM scan stop offset",  QDoubleSpinBox,  0., 5000.,   250.,  1),
            ("mir_vfm_steps",      "VFM scan steps",        QSpinBox,        3,    200,    21,   0),
            ("mir_slit_size_c",    "Slit size after 4E (mm)", QDoubleSpinBox, 0.01, 20.0,  2.0,  3),
        ]
        for r, (key, lbl, cls, mn, mx, dflt, dec) in enumerate(mir_scan_defs, start=1):
            scan_lay.addWidget(QLabel(lbl), r, 0)
            if cls == QDoubleSpinBox:
                sb = NoScrollDoubleSpinBox()
                sb.setDecimals(dec)
                sb.setRange(mn, mx)
                sb.setValue(dflt)
            else:
                sb = NoScrollSpinBox()
                sb.setRange(int(mn), int(mx))
                sb.setValue(int(dflt))
            sb.setMinimumWidth(100)
            self._scan_fields[key] = sb
            scan_lay.addWidget(sb, r, 1)
            sb.valueChanged.connect(self.changed)
        top_row.addWidget(scan_box, 1)

        # ── Procedure summary ──
        proc_box = QGroupBox("Procedure Overview")
        proc_l = QVBoxLayout(proc_box)
        proc_lbl = QLabel(
            "<b>4A</b> Slit scan (mirror out): scan slit center → signal peak → center slit.<br>"
            "<b>4B</b> Mirror in: insert all mirror stages into beam path.<br>"
            "<b>4C</b> Mirror piezo pitch scan: narrow slit → scan mirror pitch piezo → BPM y = 0.<br>"
            "<b>4D</b> VDM:Y scan: scan VDM:Y → signal peak → move.<br>"
            "<b>4E</b> Coupled VFM+VDM scan: scan VFM:Y with VDM step = 2× VFM step → move both to peak."
        )
        proc_lbl.setWordWrap(True)
        proc_lbl.setTextFormat(Qt.TextFormat.RichText)
        proc_lbl.setStyleSheet(f"color: {PAL['text_sec']}; font-size: 12px; padding: 4px;")
        proc_l.addWidget(proc_lbl)
        top_row.addWidget(proc_box, 1)
        lay.addLayout(top_row)

        # ── Mirror Stages table ──
        stages_box = QGroupBox("Mirror Stages — In / Out Positions")
        stages_l = QVBoxLayout(stages_box)
        btn_bar = QHBoxLayout()
        add_btn  = styled_button("+ Add Stage")
        del_btn  = styled_button("Remove Stage")
        test_btn = styled_button("Test Stage PVs")
        for b in [add_btn, del_btn, test_btn]:
            btn_bar.addWidget(b)
        btn_bar.addStretch()
        stages_l.addLayout(btn_bar)

        self._mirror_table = QTableWidget()
        self._mirror_table.setColumnCount(4)
        self._mirror_table.setHorizontalHeaderLabels(["Name", "PV", "Value (In)", "Value (Out)"])
        self._mirror_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._mirror_table.setAlternatingRowColors(True)
        self._mirror_table.setRowCount(len(self._mirror_stages))
        for r, stage in enumerate(self._mirror_stages):
            for c, key in enumerate(["name", "pv", "val_in", "val_out"]):
                self._mirror_table.setItem(r, c, QTableWidgetItem(str(stage[key])))
        self._mirror_table.cellChanged.connect(self._on_mirror_cell_changed)
        stages_l.addWidget(self._mirror_table)
        lay.addWidget(stages_box, 1)

        add_btn.clicked.connect(self._add_stage)
        del_btn.clicked.connect(self._del_stage)
        test_btn.clicked.connect(self._test_stage_pvs)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_mirror_cell_changed(self, r, c):
        if r >= len(self._mirror_stages):
            return
        key = ["name", "pv", "val_in", "val_out"][c]
        text = self._mirror_table.item(r, c).text()
        if key in ("val_in", "val_out"):
            try:
                self._mirror_stages[r][key] = float(text)
            except ValueError:
                return
        else:
            self._mirror_stages[r][key] = text
        self.changed.emit()

    def _add_stage(self):
        self._mirror_stages.append(
            {"name": "New Stage", "pv": "", "val_in": 0.0, "val_out": 0.0}
        )
        self._mirror_table.blockSignals(True)
        self._mirror_table.setRowCount(len(self._mirror_stages))
        r = len(self._mirror_stages) - 1
        for c, key in enumerate(["name", "pv", "val_in", "val_out"]):
            self._mirror_table.setItem(r, c, QTableWidgetItem(str(self._mirror_stages[r][key])))
        self._mirror_table.blockSignals(False)
        self.changed.emit()

    def _del_stage(self):
        r = self._mirror_table.currentRow()
        if r < 0:
            return
        self._mirror_stages.pop(r)
        self._mirror_table.blockSignals(True)
        self._mirror_table.removeRow(r)
        self._mirror_table.blockSignals(False)
        self.changed.emit()

    def _test_stage_pvs(self):
        simulate = self._is_simulate()
        stages   = list(self._mirror_stages)
        results  = [None] * len(stages)

        def test_one(stage):
            name, pv = stage["name"], stage["pv"].strip()
            if not pv:
                return (name, "—", "— (no PV)")
            if simulate:
                return (name, pv, "sim")
            if not EPICS_AVAILABLE:
                return (name, pv, "no EPICS")
            try:
                import epics as _epics
                val = _epics.caget(pv, timeout=2.0)
                if val is None:
                    return (name, pv, "✗  timeout / not found")
                return (name, pv, f"✓  {val}")
            except Exception as exc:
                return (name, pv, f"✗  {exc}")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = max(len(stages), 1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                future_map = {ex.submit(test_one, s): i for i, s in enumerate(stages)}
                pending    = set(future_map)
                while pending:
                    done, pending = concurrent.futures.wait(pending, timeout=0.05)
                    QApplication.processEvents()
                    for f in done:
                        results[future_map[f]] = f.result()
        finally:
            QApplication.restoreOverrideCursor()

        dlg = QDialog(self)
        dlg.setWindowTitle("Mirror Stage PV Test")
        dlg.resize(700, 380)
        lay = QVBoxLayout(dlg)

        tbl = QTableWidget(len(results), 3)
        tbl.setHorizontalHeaderLabels(["Stage Name", "PV Name", "Current Value / Status"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setAlternatingRowColors(True)

        ok_color  = QColor("#2e7d32")
        err_color = QColor("#b71c1c")
        dim_color = QColor("#888888")

        for r, (name, pv, status) in enumerate(results):
            tbl.setItem(r, 0, QTableWidgetItem(name))
            tbl.setItem(r, 1, QTableWidgetItem(pv))
            st_item = QTableWidgetItem(status)
            if status.startswith("✓"):
                st_item.setForeground(ok_color)
            elif status.startswith("✗"):
                st_item.setForeground(err_color)
            else:
                st_item.setForeground(dim_color)
            tbl.setItem(r, 2, st_item)

        lay.addWidget(tbl)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def get_mirror_stages(self):
        return [dict(s) for s in self._mirror_stages]

    def get_mirror_scan_params(self):
        out = {}
        for k, w in self._scan_fields.items():
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText()
        return out

    def apply_config(self, cfg):
        if "mirror_stages" in cfg:
            self._mirror_stages = [dict(s) for s in cfg["mirror_stages"]]
            self._mirror_table.blockSignals(True)
            self._mirror_table.setRowCount(len(self._mirror_stages))
            for r, stage in enumerate(self._mirror_stages):
                for c, key in enumerate(["name", "pv", "val_in", "val_out"]):
                    self._mirror_table.setItem(r, c, QTableWidgetItem(str(stage[key])))
            self._mirror_table.blockSignals(False)
        for k, v in cfg.get("mirror_scan", {}).items():
            if k not in self._scan_fields:
                continue
            w = self._scan_fields[k]
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.setValue(v)
            elif isinstance(w, QComboBox):
                idx = w.findText(str(v))
                if idx >= 0:
                    w.setCurrentIndex(idx)


# ─── Main Window ─────────────────────────────────────────────────────────────
class RecordTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pv_config   = [dict(r) for r in DEFAULT_RECORD_PVS]
        self._is_simulate = lambda: False
        self._build()

    def set_simulate_fn(self, fn):
        self._is_simulate = fn

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # ── PV config ──
        pv_box = QGroupBox("PVs to Record")
        pv_lay = QVBoxLayout(pv_box)

        pv_bar = QHBoxLayout()
        add_pv_btn  = styled_button("+ Add PV")
        del_pv_btn  = styled_button("Remove PV")
        test_pv_btn = styled_button("Test PVs")
        all_btn     = styled_button("Include All")
        pv_bar.addWidget(add_pv_btn)
        pv_bar.addWidget(del_pv_btn)
        pv_bar.addWidget(test_pv_btn)
        pv_bar.addWidget(all_btn)
        pv_bar.addStretch()
        pv_bar.addWidget(QLabel("☑ = include in next save   |   timestamp is always recorded"))
        pv_lay.addLayout(pv_bar)

        self._pv_table = QTableWidget()
        self._pv_table.setColumnCount(3)
        self._pv_table.setHorizontalHeaderLabels(["Include", "Label", "PV Name"])
        self._pv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._pv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._pv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._pv_table.setAlternatingRowColors(True)
        pv_lay.addWidget(self._pv_table)
        lay.addWidget(pv_box, 1)

        add_pv_btn.clicked.connect(self._add_pv)
        del_pv_btn.clicked.connect(self._del_pv)
        test_pv_btn.clicked.connect(self._test_pvs)
        all_btn.clicked.connect(self._include_all)
        self._pv_table.cellChanged.connect(self._on_pv_cell_changed)
        self._pv_table.itemChanged.connect(self._on_pv_item_changed)

        self._refresh_pv_table()

    def _refresh_pv_table(self):
        self._pv_table.blockSignals(True)
        self._pv_table.setRowCount(len(self._pv_config))
        for r, entry in enumerate(self._pv_config):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if entry["checked"] else Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pv_table.setItem(r, 0, chk)
            lbl_item = QTableWidgetItem(entry["label"])
            if entry.get("locked", False):
                lbl_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                lbl_item.setToolTip("Label is locked to preserve CSV compatibility")
            self._pv_table.setItem(r, 1, lbl_item)
            self._pv_table.setItem(r, 2, QTableWidgetItem(entry["pv"]))
        self._pv_table.blockSignals(False)

    def _on_pv_item_changed(self, item):
        if item.column() != 0:
            return
        r = item.row()
        if r >= len(self._pv_config):
            return
        self._pv_config[r]["checked"] = (item.checkState() == Qt.CheckState.Checked)
        self.changed.emit()

    def _on_pv_cell_changed(self, r, c):
        if c == 0 or r >= len(self._pv_config):
            return
        text = self._pv_table.item(r, c).text()
        if c == 1:
            if self._pv_config[r].get("locked", False):
                return
            self._pv_config[r]["label"] = text
        elif c == 2:
            self._pv_config[r]["pv"] = text
        self.changed.emit()

    def _include_all(self):
        for entry in self._pv_config:
            entry["checked"] = True
        self._refresh_pv_table()
        self.changed.emit()

    def _add_pv(self):
        self._pv_config.append({"label": "New PV", "pv": "", "checked": False, "locked": False})
        self._refresh_pv_table()
        self.changed.emit()

    def _del_pv(self):
        r = self._pv_table.currentRow()
        if r < 0:
            return
        self._pv_config.pop(r)
        self._refresh_pv_table()
        self.changed.emit()

    def _test_pvs(self):
        simulate = self._is_simulate()
        entries  = list(self._pv_config)
        results  = [None] * len(entries)

        def test_one(entry):
            label, pv = entry["label"], entry["pv"]
            if entry.get("source") == "scan_result":
                if label == "Mirror Stripe":
                    if simulate:
                        return (label, "—", "sim")
                    if not EPICS_AVAILABLE:
                        return (label, "—", "no EPICS")
                    try:
                        import epics as _epics
                        vfm = _epics.caget(_STRIPE_VFM_X_PV + ".RBV", timeout=2.0)
                        vdm = _epics.caget(_STRIPE_VDM_X_PV + ".RBV", timeout=2.0)
                        if vfm is None or vdm is None:
                            return (label, "—", "✗  timeout")
                        for s, pos in _STRIPE_POSITIONS.items():
                            if abs(vfm - pos["vfm_x"]) <= 10 and abs(vdm - pos["vdm_x"]) <= 10:
                                return (label, "—", f"✓  {s}")
                        return (label, "—", f"✗  unknown  (VFM:X={vfm:.0f}  VDM:X={vdm:.0f})")
                    except Exception as exc:
                        return (label, "—", f"✗  {exc}")
                return (label, "—", "— (computed after alignment)")
            if not pv:
                return (label, "—", "— (no PV)")
            if simulate:
                return (label, pv, "sim")
            if not EPICS_AVAILABLE:
                return (label, pv, "no EPICS")
            _STRING_LABELS = {"BPM Sensitivity", "MonP Sensitivity Unit", "MonP Sensitivity Num"}
            try:
                import epics as _epics
                if label in _STRING_LABELS:
                    val = _epics.caget(pv, as_string=True, timeout=2.0)
                    if val is None:
                        return (label, pv, "✗  timeout / not found")
                    return (label, pv, f"✓  {val}")
                val = _epics.caget(pv, timeout=2.0)
                if val is None:
                    return (label, pv, "✗  timeout / not found")
                if label == "XTAL":
                    display = {0: "111", 1: "311"}.get(int(val), str(val))
                    return (label, pv, f"✓  {display}")
                return (label, pv, f"✓  {val}")
            except Exception as exc:
                return (label, pv, f"✗  {exc}")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = max(len(entries), 1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                future_map = {ex.submit(test_one, e): i for i, e in enumerate(entries)}
                pending    = set(future_map)
                while pending:
                    done, pending = concurrent.futures.wait(pending, timeout=0.05)
                    QApplication.processEvents()
                    for f in done:
                        results[future_map[f]] = f.result()
        finally:
            QApplication.restoreOverrideCursor()

        dlg = QDialog(self)
        dlg.setWindowTitle("PV Connection Test")
        dlg.resize(700, 400)
        lay = QVBoxLayout(dlg)

        tbl = QTableWidget(len(results), 3)
        tbl.setHorizontalHeaderLabels(["Label", "PV Name", "Status"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setAlternatingRowColors(True)

        ok_color  = QColor("#2e7d32")
        err_color = QColor("#b71c1c")
        dim_color = QColor("#888888")

        for r, (label, pv, status) in enumerate(results):
            tbl.setItem(r, 0, QTableWidgetItem(label))
            tbl.setItem(r, 1, QTableWidgetItem(pv))
            st_item = QTableWidgetItem(status)
            if status.startswith("✓"):
                st_item.setForeground(ok_color)
            elif status.startswith("✗"):
                st_item.setForeground(err_color)
            else:
                st_item.setForeground(dim_color)
            tbl.setItem(r, 2, st_item)

        lay.addWidget(tbl)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def get_checked_pvs(self):
        return [{"label": e["label"], "pv": e["pv"]}
                for e in self._pv_config if e["checked"]]

    def get_pv_config(self):
        return [dict(r) for r in self._pv_config]

    def set_pv_config(self, config):
        self._pv_config = [{**r, "locked": r.get("locked", True)}
                           for r in config if r.get("label") != "Timestamp"]
        self._refresh_pv_table()


class MainWindow(QMainWindow):
    _bpm_polled = pyqtSignal(float, float, float)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DCM Alignment Console")
        self.resize(1280, 860)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(QSS)

        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ── Top bar ──
        topbar = QWidget()
        topbar.setStyleSheet(f"background: {PAL['surface']}; border-bottom: 1px solid {PAL['border']};")
        topbar.setFixedHeight(56)
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel()
        title.setText(
            f'<span style="color:{PAL["cyan"]}; font-family: JetBrains Mono, Consolas, monospace; font-size: 16px; font-weight: 700;">DCM</span>'
            f'<span style="color:{PAL["text_pri"]}; font-size: 15px; font-weight: 400;"> Alignment Console</span>'
        )
        sub = QLabel("Double Crystal Monochromator")
        sub.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 10px; letter-spacing: 2px; text-transform: uppercase;")

        title_w = QVBoxLayout()
        title_w.setSpacing(1)
        title_w.addWidget(title)
        title_w.addWidget(sub)
        tb_lay.addLayout(title_w)
        tb_lay.addStretch()

        epics_tag = make_tag("EPICS available" if EPICS_AVAILABLE else "Simulation mode", "green" if EPICS_AVAILABLE else "amber")
        tb_lay.addWidget(epics_tag)

        theme_lbl = QLabel("Theme:")
        theme_lbl.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 11px;")
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(list(THEMES.keys()))
        self._theme_combo.setFixedWidth(130)
        self._theme_combo.currentTextChanged.connect(self._apply_theme)
        tb_lay.addSpacing(12)
        tb_lay.addWidget(theme_lbl)
        tb_lay.addWidget(self._theme_combo)

        main_lay.addWidget(topbar)

        # ── Tabs ──
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        main_lay.addWidget(self.tabs, 1)

        self.setup_tab     = SetupTab()
        self.energy_tab    = EnergyTableTab()
        self.alignment_tab = AlignmentTab()
        self.mirror_tab    = MirrorTab()
        self.record_tab    = RecordTab()
        self.record_tab.set_simulate_fn(self.setup_tab.is_simulate)
        self.mirror_tab.set_simulate_fn(self.setup_tab.is_simulate)

        self.tabs.addTab(self.setup_tab,     "  Setup  ")
        self.tabs.addTab(self.energy_tab,    "  Energy Table  ")
        self.tabs.addTab(self.alignment_tab, "  Alignment  ")
        self.tabs.addTab(self.mirror_tab,    "  Mirror  ")
        self.tabs.addTab(self.record_tab,    "  Record  ")

        # Wire up row selection → alignment tab
        self.energy_tab.row_selected.connect(self.alignment_tab.set_selected_row)

        # Wire start button to use current Setup settings
        self.alignment_tab.start_btn.clicked.disconnect()
        self.alignment_tab.start_btn.clicked.connect(self._start_alignment)

        # ── Status bar ──
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        self._auto_load_config()

        self.setup_tab.changed.connect(self._save_config)
        self.energy_tab.changed.connect(self._save_config)
        self.mirror_tab.changed.connect(self._save_config)
        self.record_tab.changed.connect(self._save_config)
        self.alignment_tab.alignment_done.connect(self._on_alignment_done)

        # Continuous BPM monitor via EPICS CA subscriptions
        self._bpm_monitored = {}  # "bpm_x"/"bpm_y"/"bpm_intensity" → epics.PV
        self._bpm_vals      = {"bpm_x": 0.0, "bpm_y": 0.0, "bpm_intensity": 0.0}
        self._bpm_polled.connect(self.alignment_tab._on_bpm_update)
        self.setup_tab.sim_check.toggled.connect(self._on_sim_toggled_bpm)
        # Re-subscribe when PV names change
        self.setup_tab.changed.connect(self._refresh_bpm_monitors)
        if EPICS_AVAILABLE and not self.setup_tab.is_simulate():
            self._start_bpm_monitoring()

    def _on_alignment_done(self, success):
        if not success:
            return
        reply = QMessageBox.question(
            self, "Save to Lookup Table",
            "Alignment completed successfully.\nSave results to the lookup table?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        checked      = self.record_tab.get_checked_pvs()
        simulate     = self.setup_tab.is_simulate()
        scan_results = self.alignment_tab._last_scan_results
        _STRING_LABELS = {"BPM Sensitivity", "MonP Sensitivity Unit", "MonP Sensitivity Num"}
        row = {"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        for entry in checked:
            label  = entry["label"]
            pv     = entry["pv"]
            source = entry.get("source", "")
            if source == "scan_result":
                row[label] = scan_results.get(label, "—")
                continue
            if not pv:
                continue
            if simulate:
                row[label] = "sim"
            else:
                try:
                    import epics as _epics
                    if label in _STRING_LABELS:
                        val = _epics.caget(pv, as_string=True)
                        row[label] = str(val) if val is not None else "—"
                    elif label == "XTAL":
                        val = _epics.caget(pv)
                        row[label] = {0: "111", 1: "311"}.get(int(val), str(val)) if val is not None else "—"
                    else:
                        val = _epics.caget(pv)
                        row[label] = f"{val:.6g}" if isinstance(val, (int, float)) else str(val) if val is not None else "—"
                except Exception:
                    row[label] = "err"
        self.energy_tab.append_record_row(row)
        self.tabs.setCurrentWidget(self.energy_tab)

    def _apply_theme(self, theme_name: str):
        if theme_name not in THEMES:
            return
        PAL.update(THEMES[theme_name])
        QApplication.instance().setStyleSheet(build_qss(PAL))
        self.alignment_tab._refresh_start_btn()
        self.alignment_tab._refresh_abort_btn()
        # Refresh readback label styles on next PV update (they read PAL live)
        # Force-refresh topbar theme label color
        self._theme_combo.parentWidget().findChild(
            type(QLabel()), "").setStyleSheet(f"color: {PAL['text_dim']}; font-size: 11px;")

    def _auto_load_config(self):
        if not os.path.exists(AUTO_CONFIG_PATH):
            return
        try:
            with open(AUTO_CONFIG_PATH) as f:
                cfg = json.load(f)
            self.setup_tab._apply_config(cfg)
            if "energy_table" in cfg:
                self.energy_tab.set_table_data(cfg["energy_table"])
            self.mirror_tab.apply_config(cfg)
            if "record_pv_config" in cfg:
                self.record_tab.set_pv_config(cfg["record_pv_config"])
            if "record_data" in cfg:
                self.energy_tab.set_record_data(cfg["record_data"])
            if "theme" in cfg:
                idx = self._theme_combo.findText(cfg["theme"])
                if idx >= 0:
                    self._theme_combo.setCurrentIndex(idx)
            self.status.showMessage(f"Config restored from {AUTO_CONFIG_PATH}")
        except Exception as e:
            self.status.showMessage(f"Could not restore config: {e}")

    def _save_config(self):
        cfg = {
            "pvs": self.setup_tab.get_pvs(),
            "scan": self.setup_tab.get_scan_params(),
            "simulate": self.setup_tab.is_simulate(),
            "energy_table": self.energy_tab.get_table_data(),
            "mirror_stages": self.mirror_tab.get_mirror_stages(),
            "mirror_scan": self.mirror_tab.get_mirror_scan_params(),
            "record_pv_config": self.record_tab.get_pv_config(),
            "record_data": self.energy_tab.get_record_data(),
            "theme": self._theme_combo.currentText(),
        }
        try:
            with open(AUTO_CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _on_sim_toggled_bpm(self, is_sim: bool):
        if is_sim or not EPICS_AVAILABLE:
            self._stop_bpm_monitoring()
        else:
            self._start_bpm_monitoring()

    def _start_bpm_monitoring(self):
        import epics as _epics
        pvs = self.setup_tab.get_pvs()
        BPM_KEYS = ("bpm_x", "bpm_y", "bpm_intensity")
        for key in BPM_KEYS:
            old = self._bpm_monitored.pop(key, None)
            if old is not None:
                try:
                    old.disconnect()
                except Exception:
                    pass
            pv_name = pvs.get(key, "").strip()
            if not pv_name:
                continue

            def _cb(value=None, pvname=None, bk=key, **_kw):
                # Skip updates while alignment worker owns BPM display
                if self.alignment_tab.abort_btn.isEnabled():
                    return
                if value is None:
                    return
                try:
                    self._bpm_vals[bk] = float(value)
                except Exception:
                    return
                self._bpm_polled.emit(
                    self._bpm_vals["bpm_x"],
                    self._bpm_vals["bpm_y"],
                    self._bpm_vals["bpm_intensity"],
                )

            try:
                pv = _epics.PV(pv_name, callback=_cb, auto_monitor=True)
                self._bpm_monitored[key] = pv
            except Exception:
                pass

    def _stop_bpm_monitoring(self):
        for pv in self._bpm_monitored.values():
            try:
                pv.disconnect()
            except Exception:
                pass
        self._bpm_monitored.clear()

    def _refresh_bpm_monitors(self):
        """Re-subscribe BPM PVs when setup changes (debounced by Qt signal coalescing)."""
        if EPICS_AVAILABLE and not self.setup_tab.is_simulate():
            self._start_bpm_monitoring()

    def closeEvent(self, event):
        self._stop_bpm_monitoring()
        self.setup_tab._stop_monitoring()
        self._save_config()
        super().closeEvent(event)

    def _start_alignment(self):
        pvs = self.setup_tab.get_pvs()
        params = self.setup_tab.get_scan_params()
        params.update(self.mirror_tab.get_mirror_scan_params())
        simulate = self.setup_tab.is_simulate()
        mirror_stages = self.mirror_tab.get_mirror_stages()
        self.alignment_tab.start_alignment(pvs=pvs, scan_params=params, simulate=simulate,
                                           mirror_stages=mirror_stages)
        self.tabs.setCurrentWidget(self.alignment_tab)
        self.status.showMessage("Alignment running…")
        self.alignment_tab._worker.finished.connect(
            lambda ok: self.status.showMessage("Alignment complete ✓" if ok else "Alignment aborted")
        )


# ─── Entry point ─────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DCM Alignment Console")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
