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

# ─── Colour palette ──────────────────────────────────────────────────────────
PAL = {
    "bg":          "#f5f7fa",
    "surface":     "#eaeef2",
    "surface_hi":  "#dde2e8",
    "border":      "#c8d0d8",
    "cyan":        "#0a7a82",
    "cyan_dim":    "#c8eef0",
    "green":       "#1a7f37",
    "amber":       "#9a6700",
    "red":         "#cf2218",
    "text_pri":    "#1f2328",
    "text_sec":    "#57606a",
    "text_dim":    "#6e7781",
}

QSS = f"""
QMainWindow, QDialog {{
    background: {PAL['bg']};
}}
QWidget {{
    background: {PAL['bg']};
    color: {PAL['text_pri']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {PAL['border']};
    background: {PAL['surface']};
}}
QTabBar::tab {{
    background: {PAL['surface']};
    color: {PAL['text_sec']};
    padding: 8px 20px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    color: {PAL['cyan']};
    border-bottom: 2px solid {PAL['cyan']};
    background: {PAL['surface']};
}}
QGroupBox {{
    border: 1px solid {PAL['border']};
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px;
    background: {PAL['surface']};
    font-weight: 600;
    color: {PAL['text_sec']};
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
    background: {PAL['bg']};
    border: 1px solid {PAL['border']};
    border-radius: 4px;
    padding: 5px 8px;
    color: {PAL['cyan']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 11px;
    selection-background-color: {PAL['cyan_dim']};
}}
QLineEdit:focus {{
    border: 1px solid {PAL['cyan']};
}}
QDoubleSpinBox, QSpinBox {{
    background: {PAL['bg']};
    border: 1px solid {PAL['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {PAL['cyan']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1px solid {PAL['cyan']};
}}
QComboBox {{
    background: {PAL['bg']};
    border: 1px solid {PAL['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {PAL['text_pri']};
}}
QComboBox::drop-down {{
    border: none;
}}
QPushButton {{
    background: transparent;
    border: 1px solid {PAL['border']};
    border-radius: 5px;
    padding: 6px 16px;
    color: {PAL['text_sec']};
    font-weight: 600;
    font-size: 12px;
}}
QPushButton:hover {{
    border-color: {PAL['cyan']};
    color: {PAL['cyan']};
}}
QPushButton:disabled {{
    opacity: 0.4;
    color: {PAL['text_dim']};
    border-color: {PAL['border']};
}}
QPushButton#primary {{
    background: {PAL['cyan']};
    color: {PAL['bg']};
    border: none;
    padding: 7px 20px;
}}
QPushButton#primary:hover {{
    background: #09686f;
    color: {PAL['bg']};
}}
QPushButton#primary:disabled {{
    background: {PAL['cyan_dim']};
    color: {PAL['text_dim']};
}}
QPushButton#danger {{
    border-color: {PAL['red']};
    color: {PAL['red']};
}}
QPushButton#danger:hover {{
    background: #fce8e6;
}}
QTableWidget {{
    background: {PAL['surface']};
    alternate-background-color: {PAL['surface_hi']};
    border: 1px solid {PAL['border']};
    border-radius: 4px;
    gridline-color: {PAL['border']};
    selection-background-color: {PAL['cyan_dim']};
    selection-color: {PAL['cyan']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 12px;
}}
QHeaderView::section {{
    background: {PAL['surface_hi']};
    color: {PAL['text_dim']};
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {PAL['border']};
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QTextEdit {{
    background: {PAL['bg']};
    border: 1px solid {PAL['border']};
    border-radius: 4px;
    color: {PAL['text_sec']};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 11px;
    padding: 6px;
}}
QScrollBar:vertical {{
    background: {PAL['bg']};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {PAL['border']};
    border-radius: 4px;
    min-height: 20px;
}}
QCheckBox {{
    color: {PAL['text_sec']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {PAL['border']};
    border-radius: 3px;
    background: {PAL['bg']};
}}
QCheckBox::indicator:checked {{
    background: {PAL['cyan']};
    border-color: {PAL['cyan']};
}}
QProgressBar {{
    background: {PAL['surface_hi']};
    border: 1px solid {PAL['border']};
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {PAL['cyan']};
    border-radius: 3px;
}}
QStatusBar {{
    background: {PAL['surface']};
    color: {PAL['text_dim']};
    font-size: 11px;
    border-top: 1px solid {PAL['border']};
}}
QLabel#readout_value {{
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 20px;
    font-weight: 700;
    color: {PAL['cyan']};
}}
QLabel#readout_label {{
    font-size: 10px;
    color: {PAL['text_dim']};
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QLabel#step_title {{
    font-size: 13px;
    font-weight: 600;
    color: {PAL['text_pri']};
}}
QLabel#tag_green {{
    background: #e6f4ea;
    border: 1px solid {PAL['green']};
    color: {PAL['green']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_amber {{
    background: #fff3cd;
    border: 1px solid {PAL['amber']};
    color: {PAL['amber']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_red {{
    background: #fce8e6;
    border: 1px solid {PAL['red']};
    color: {PAL['red']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_grey {{
    background: {PAL['surface_hi']};
    border: 1px solid {PAL['border']};
    color: {PAL['text_dim']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#tag_cyan {{
    background: {PAL['cyan_dim']};
    border: 1px solid {PAL['cyan']};
    color: {PAL['cyan']};
    border-radius: 3px;
    padding: 2px 8px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
}}
"""

AUTO_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dcm_config.json")

MOTOR_PV_KEYS = {"mono_energy", "roll", "pitch"}

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
}

def calc_harmonic(mono_e):
    if mono_e < 13:
        return 1
    elif mono_e < 28:
        return 3
    return 5

DEFAULT_LOOKUP = [
    {"mono_e": 8.0,  "ue": 9.8,  "roll": 0.412, "pitch": 2.341, "harmonic": 1},
    {"mono_e": 10.0, "ue": 12.1, "roll": 0.398, "pitch": 2.187, "harmonic": 1},
    {"mono_e": 12.0, "ue": 14.6, "roll": 0.381, "pitch": 2.054, "harmonic": 1},
    {"mono_e": 15.0, "ue": 18.2, "roll": 0.362, "pitch": 1.893, "harmonic": 3},
    {"mono_e": 20.0, "ue": 24.1, "roll": 0.344, "pitch": 1.712, "harmonic": 3},
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
    "settle_time":  0.1,
    "peak_method":  "centroid",
    "piezo_center": 5.0,
}

# ─── Simulation helpers ───────────────────────────────────────────────────────
def gaussian(x, center, sigma, amp, offset=0.0):
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset

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
    finished         = pyqtSignal(bool)                # success

    def __init__(self, pvs, scan_params, row, simulate=True, skip_mirror=True, mirror_stages=None):
        super().__init__()
        self.pvs = pvs
        self.params = scan_params
        self.row = row
        self.simulate = simulate
        self.skip_mirror = skip_mirror
        self.mirror_stages = mirror_stages or []
        self._abort = False
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

        # ── Step 1: Load settings ──────────────────────────────────────
        self.step_status.emit(1, "running")
        self.log("━━ Step 1 — Load lookup table settings ━━")
        if not self._sleep(0.3): return self._abort_cleanup()
        self.log(f"  Mono E   = {row['mono_e']} keV")
        self.log(f"  Und E    = {row['ue']} keV")
        self.log(f"  Roll SP  = {row['roll']}")
        self.log(f"  Pitch SP = {row['pitch']}")
        self.step_status.emit(1, "done")
        self.log("Step 1 complete.", "ok")

        # ── Step 2: BPM off → motors → mirror out ─────────────────────
        self.step_status.emit(2, "running")
        self.log("━━ Step 2 — Disable BPM feedback, move motors, retract mirror ━━")

        self.log(f"  [{pvs['feedback_h']}] → 0  (H feedback OFF)", "warn")
        self.epics.put(pvs['feedback_h'], 0)
        self.log(f"  [{pvs['feedback_v']}] → 0  (V feedback OFF)", "warn")
        self.epics.put(pvs['feedback_v'], 0)
        self.feedback_update.emit(False, False)
        if not self._sleep(0.4): return self._abort_cleanup()

        self.log("  Moving motors to lookup table setpoints…")

        # Undulator: set harmonic → set energy → trigger start
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

        self.log("  Retracting mirror from beam path…")
        for stage in self.mirror_stages:
            if stage["pv"].strip():
                self.epics.put(stage["pv"], stage["val_out"])
                self.log(f"  [{stage['pv']}] → {stage['val_out']}  ({stage['name']} OUT)", "ok")
                if not self._sleep(0.1): return self._abort_cleanup()
        if not self._sleep(0.4): return self._abort_cleanup()
        self.log("  Mirror retracted.", "ok")
        self.step_status.emit(2, "done")
        self.log("Step 2 complete.", "ok")

        # ── Step 3: DCM piezo alignment ────────────────────────────────
        self.step_status.emit(3, "running")
        self.log("━━ Step 3 — DCM piezo alignment ━━")

        # 3a: Center piezos
        center = p["piezo_center"]
        self.log(f"  [{pvs['piezo_pitch']}] → {center}  (center)")
        self.epics.put(pvs['piezo_pitch'], center)
        self.log(f"  [{pvs['piezo_roll']}] → {center}  (center)")
        self.epics.put(pvs['piezo_roll'], center)
        if not self._sleep(0.4): return self._abort_cleanup()

        # 3b: Roll scan → BPM x = 0
        self.log("  Scanning DCM roll → finding BPM x = 0 zero-crossing…")
        true_zero = random.uniform(-0.005, 0.005)
        xs_roll, ys_roll = sim_scan_roll_bpm(
            row["roll"] + p["roll_start"], row["roll"] + p["roll_stop"], p["roll_steps"], true_zero
        )
        for x, y in zip(xs_roll, ys_roll):
            if self._abort: return self._abort_cleanup()
            self.scan_point.emit("roll", float(x), float(y))
            self.bpm_update.emit(float(y), 0.0, 0.5)
            if not self._sleep(p["settle_time"] * 0.5): return self._abort_cleanup()

        roll_zero = find_zero_crossing(xs_roll, ys_roll)
        self.scan_peak.emit("roll", roll_zero)
        self.epics.put(pvs['roll'], roll_zero)
        self.log(f"  BPM x zero-crossing at roll = {roll_zero:.6f} → moved", "ok")

        # 3c: Pitch scan → intensity peak
        self.log("  Scanning DCM pitch → finding intensity peak…")
        true_peak = row["pitch"] + random.uniform(-0.01, 0.01)
        xs_pitch, ys_pitch = sim_scan_pitch(
            row["pitch"] + p["pitch_start"],
            row["pitch"] + p["pitch_stop"],
            p["pitch_steps"],
            true_peak,
        )
        for x, y in zip(xs_pitch, ys_pitch):
            if self._abort: return self._abort_cleanup()
            self.scan_point.emit("pitch", float(x), float(y))
            self.bpm_update.emit(roll_zero + random.uniform(-0.001, 0.001),
                                 random.uniform(-0.002, 0.002), float(y) / 1000.0)
            if not self._sleep(p["settle_time"] * 0.5): return self._abort_cleanup()

        pitch_peak = find_peak_centroid(xs_pitch, ys_pitch)
        self.scan_peak.emit("pitch", pitch_peak)
        self.epics.put(pvs['pitch'], pitch_peak)
        self.log(f"  Intensity peak at pitch = {pitch_peak:.6f} → moved", "ok")
        self.bpm_update.emit(roll_zero + random.uniform(-0.0005, 0.0005),
                             random.uniform(-0.001, 0.001), 0.97)
        self.step_status.emit(3, "done")
        self.log("Step 3 complete.", "ok")

        # ── Step 4: Mirror alignment (optional) ───────────────────────
        if self.skip_mirror:
            self.step_status.emit(4, "done")
            self.log("━━ Step 4 — Mirror alignment skipped ━━", "warn")
            # Mirror was retracted in Step 2; move it back in now
            self.log("  Moving mirror into beam path…")
            for stage in self.mirror_stages:
                if stage["pv"].strip():
                    self.epics.put(stage["pv"], stage["val_in"])
                    self.log(f"  [{stage['pv']}] → {stage['val_in']}  ({stage['name']} IN)", "ok")
                    if not self._sleep(0.1): return self._abort_cleanup()
            if not self._sleep(0.4): return self._abort_cleanup()
            self.log("  Mirror in position.", "ok")
        else:
            self.step_status.emit(4, "running")
            self.log("━━ Step 4 — Mirror alignment ━━")
            self.log("  [Placeholder] Mirror alignment substeps not yet defined.", "warn")
            self.log("  Skipping — configure substeps in the Mirror tab.", "warn")
            if not self._sleep(0.5): return self._abort_cleanup()
            self.step_status.emit(4, "done")

        # ── Step 5: Enable feedback loops ──────────────────────────────
        self.step_status.emit(5, "running")
        self.log("━━ Step 5 — Enable feedback loops ━━")

        self.log(f"  Enabling H feedback: DCM piezo roll → BPM x = 0…")
        if not self._sleep(0.5): return self._abort_cleanup()
        self.epics.put(pvs['feedback_h'], 1)
        self.feedback_update.emit(True, False)
        self.bpm_update.emit(random.uniform(-0.0002, 0.0002),
                             random.uniform(-0.001, 0.001), 0.97)
        self.log(f"  [{pvs['feedback_h']}] → 1  (H feedback ON)", "ok")

        self.log("  Maximising BPM intensity via DCM piezo pitch…")
        if not self._sleep(0.6): return self._abort_cleanup()
        self.bpm_update.emit(random.uniform(-0.0001, 0.0001),
                             random.uniform(-0.001, 0.001), 0.99)
        self.log("  Peak intensity reached.", "ok")

        self.log("  Tweaking mirror piezo pitch → BPM y = 0…")
        if not self._sleep(0.6): return self._abort_cleanup()
        self.bpm_update.emit(random.uniform(-0.0001, 0.0001),
                             random.uniform(-0.0002, 0.0002), 0.98)
        self.log("  BPM y ≈ 0 achieved.", "ok")

        self.log(f"  Enabling V feedback: DCM piezo pitch → BPM y = 0…")
        if not self._sleep(0.4): return self._abort_cleanup()
        self.epics.put(pvs['feedback_v'], 1)
        self.feedback_update.emit(True, True)
        self.log(f"  [{pvs['feedback_v']}] → 1  (V feedback ON)", "ok")

        self.step_status.emit(5, "done")
        self.log("Step 5 complete.", "ok")
        self.log("━━ Alignment sequence finished successfully ━━", "ok")
        self.finished.emit(True)

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
    COLORS = {
        "info":  PAL["text_sec"],
        "ok":    PAL["green"],
        "warn":  PAL["amber"],
        "error": PAL["red"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(200)

    def append_log(self, msg, level="info"):
        color = self.COLORS.get(level, PAL["text_sec"])
        ts = time.strftime("%H:%M:%S")
        self.append(
            f'<span style="color:{PAL["text_dim"]}">{ts}</span> '
            f'<span style="color:{color}">{msg}</span>'
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ─── Setup Tab ───────────────────────────────────────────────────────────────
class SetupTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pv_fields = {}
        self._scan_fields = {}
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
            "mono_energy": "Mono Energy",
            "roll":        "DCM Roll",
            "pitch":       "DCM Pitch",
        }
        motor_box = QGroupBox("Motor PVs")
        motor_lay = QGridLayout(motor_box)
        motor_lay.setSpacing(8)
        for row, (key, label) in enumerate(motor_labels.items()):
            motor_lay.addWidget(QLabel(label), row, 0)
            ed = QLineEdit(DEFAULT_PVS[key])
            self._pv_fields[key] = ed
            motor_lay.addWidget(ed, row, 1)

        other_labels = {
            "und_energy":    "Undulator Energy",
            "piezo_pitch":   "DCM Piezo Pitch",
            "piezo_roll":    "DCM Piezo Roll",
            "bpm_x":         "BPM X readback",
            "bpm_y":         "BPM Y readback",
            "bpm_intensity": "BPM Intensity",
            "feedback_h":    "H Feedback PV",
            "feedback_v":    "V Feedback PV",
            "und_harmonic":  "Undulator Harmonic PV",
            "und_start":     "Undulator Start PV",
        }
        other_box = QGroupBox("Other PVs")
        other_lay = QGridLayout(other_box)
        other_lay.setSpacing(8)
        for row, (key, label) in enumerate(other_labels.items()):
            other_lay.addWidget(QLabel(label), row, 0)
            ed = QLineEdit(DEFAULT_PVS[key])
            self._pv_fields[key] = ed
            other_lay.addWidget(ed, row, 1)

        pv_col.addWidget(motor_box)
        pv_col.addWidget(other_box)
        pv_col.addStretch()

        # Right column
        right = QVBoxLayout()

        scan_box = QGroupBox("Scan Parameters")
        scan_lay = QGridLayout(scan_box)
        scan_defs = [
            ("pitch_start",  "Pitch scan start",  QDoubleSpinBox, -1.0, 0.0, -0.05, 4),
            ("pitch_stop",   "Pitch scan stop",   QDoubleSpinBox,  0.0, 1.0,  0.05, 4),
            ("pitch_steps",  "Pitch scan steps",  QSpinBox,        5, 200,   25,   0),
            ("roll_start",   "Roll scan start",   QDoubleSpinBox, -1.0, 0.0, -0.05, 4),
            ("roll_stop",    "Roll scan stop",    QDoubleSpinBox,  0.0, 1.0,  0.05, 4),
            ("roll_steps",   "Roll scan steps",   QSpinBox,        5, 200,   21,   0),
            ("settle_time",  "Settle time (s)",   QDoubleSpinBox,  0.0, 5.0,  0.1,  2),
            ("piezo_center", "Piezo center value",QDoubleSpinBox,  0.0, 10.0, 5.0,  1),
        ]
        for r, (key, lbl, cls, mn, mx, dflt, dec) in enumerate(scan_defs):
            scan_lay.addWidget(QLabel(lbl), r, 0)
            if cls == QDoubleSpinBox:
                sb = QDoubleSpinBox()
                sb.setDecimals(dec)
                sb.setRange(mn, mx)
                sb.setValue(dflt)
            else:
                sb = QSpinBox()
                sb.setRange(mn, mx)
                sb.setValue(dflt)
            sb.setMinimumWidth(100)
            self._scan_fields[key] = sb
            scan_lay.addWidget(sb, r, 1)

        # Peak method
        scan_lay.addWidget(QLabel("Peak method"), len(scan_defs), 0)
        pm = QComboBox()
        pm.addItems(["centroid", "gaussian_fit"])
        self._scan_fields["peak_method"] = pm
        scan_lay.addWidget(pm, len(scan_defs), 1)

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

        # Mirror Stages table (full width)
        mirror_box = QGroupBox("Mirror Stages (In / Out Positions)")
        mirror_box_lay = QVBoxLayout(mirror_box)
        self._mirror_table = QTableWidget()
        self._mirror_table.setColumnCount(4)
        self._mirror_table.setHorizontalHeaderLabels(["Name", "PV", "Value (In)", "Value (Out)"])
        self._mirror_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._mirror_table.setAlternatingRowColors(True)
        self._mirror_stages = [dict(s) for s in DEFAULT_MIRROR_STAGES]
        self._mirror_table.setRowCount(len(self._mirror_stages))
        for r, stage in enumerate(self._mirror_stages):
            for c, key in enumerate(["name", "pv", "val_in", "val_out"]):
                self._mirror_table.setItem(r, c, QTableWidgetItem(str(stage[key])))
        self._mirror_table.cellChanged.connect(self._on_mirror_cell_changed)
        mirror_box_lay.addWidget(self._mirror_table)
        inner_vlay.addWidget(mirror_box)

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

    def get_mirror_stages(self):
        return [dict(s) for s in self._mirror_stages]

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

        # Add mirror stage PVs (keyed as "mirror:N")
        for i, stage in enumerate(self._mirror_stages):
            pvs[f"mirror:{i}"] = stage["pv"]

        threads = [threading.Thread(target=_check, args=(k, v)) for k, v in pvs.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        labels = {
            "mono_energy": "Mono Energy", "roll": "DCM Roll", "pitch": "DCM Pitch",
            "und_energy": "Undulator Energy",
            "piezo_pitch": "DCM Piezo Pitch", "piezo_roll": "DCM Piezo Roll",
            "bpm_x": "BPM X", "bpm_y": "BPM Y", "bpm_intensity": "BPM Intensity",
            "feedback_h": "H Feedback", "feedback_v": "V Feedback",
            "und_harmonic": "Und Harmonic", "und_start": "Und Start",
        }
        for i, stage in enumerate(self._mirror_stages):
            labels[f"mirror:{i}"] = stage["name"]
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
        if "mirror_stages" in cfg:
            self._mirror_stages = [dict(s) for s in cfg["mirror_stages"]]
            self._mirror_table.blockSignals(True)
            self._mirror_table.setRowCount(len(self._mirror_stages))
            for r, stage in enumerate(self._mirror_stages):
                for c, key in enumerate(["name", "pv", "val_in", "val_out"]):
                    self._mirror_table.setItem(r, c, QTableWidgetItem(str(stage[key])))
            self._mirror_table.blockSignals(False)
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
        self._data = [dict(r) for r in DEFAULT_LOOKUP]
        self._selected = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # Toolbar
        bar = QHBoxLayout()
        add_btn    = styled_button("+ Add Row")
        del_btn    = styled_button("Remove Row")
        imp_btn    = styled_button("Import CSV…")
        exp_btn    = styled_button("Export CSV…")
        for b in [add_btn, del_btn, imp_btn, exp_btn]:
            bar.addWidget(b)
        bar.addStretch()
        self.sel_label = QLabel("No row selected")
        self.sel_label.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 11px;")
        bar.addWidget(self.sel_label)
        lay.addLayout(bar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Mono E (keV)", "Undulator E (keV)", "Harmonic", "Roll", "Pitch"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellChanged.connect(self._on_cell_changed)
        lay.addWidget(self.table)

        add_btn.clicked.connect(self._add_row)
        del_btn.clicked.connect(self._del_row)
        imp_btn.clicked.connect(self._import_csv)
        exp_btn.clicked.connect(self._export_csv)

        self._refresh_table()

    _COLS = ["mono_e", "ue", "harmonic", "roll", "pitch"]

    def _refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._data))
        for r, row in enumerate(self._data):
            for c, key in enumerate(self._COLS):
                item = QTableWidgetItem(str(row[key]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

    def _on_cell_changed(self, r, c):
        if r >= len(self._data):
            return
        key = self._COLS[c]
        text = self.table.item(r, c).text()
        try:
            val = int(text) if key == "harmonic" else float(text)
            self._data[r][key] = val
            self.changed.emit()
        except ValueError:
            pass

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
        self._data.append({"mono_e": 0.0, "ue": 0.0, "harmonic": 1, "roll": 0.0, "pitch": 0.0})
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
                        "mono_e":   mono_e,
                        "ue":       float(row.get("ue", 0)),
                        "harmonic": int(row["harmonic"]) if "harmonic" in row else calc_harmonic(mono_e),
                        "roll":     float(row.get("roll", 0)),
                        "pitch":    float(row.get("pitch", 0)),
                    })
                except (ValueError, KeyError):
                    pass
        self._refresh_table()
        self.changed.emit()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "lookup_table.csv", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["mono_e", "ue", "harmonic", "roll", "pitch"])
            writer.writeheader()
            writer.writerows(self._data)

    def selected_row(self):
        return self._selected

    def get_table_data(self):
        return [dict(r) for r in self._data]

    def set_table_data(self, data):
        self._data = [dict(r) for r in data]
        self._refresh_table()


# ─── Alignment Tab ────────────────────────────────────────────────────────────
class AlignmentTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_row = None
        self._worker = None
        self._thread = None
        self._step_headers = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # ── Header readouts + beam path ──
        top = QHBoxLayout()

        self._bpm_x_val = None
        self._bpm_y_val = None
        self._bpm_i_val = None
        self._fb_h_tag  = None
        self._fb_v_tag  = None

        bpm_w = QGroupBox("Live BPM")
        bpm_l = QHBoxLayout(bpm_w)
        bpm_l.setSpacing(20)
        for attr, label, unit in [
            ("_bpm_x_lbl", "BPM X",     "mm"),
            ("_bpm_y_lbl", "BPM Y",     "mm"),
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
        top.addWidget(bpm_w, 1)
        lay.addLayout(top)

        # Beam path
        self.beam_path = BeamPathWidget()
        lay.addWidget(self.beam_path)

        # ── Controls ──
        ctrl = QHBoxLayout()
        self.start_btn = styled_button("▶  Start Alignment", "primary", 160)
        self.abort_btn = styled_button("■  Abort", "danger", 100)
        self.abort_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.row_label = QLabel("No energy row selected — choose one in the Energy Table tab")
        self.row_label.setStyleSheet(f"color: {PAL['amber']}; font-size: 11px;")
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.abort_btn)
        ctrl.addWidget(self.progress)
        ctrl.addStretch()
        ctrl.addWidget(self.row_label)
        lay.addLayout(ctrl)

        # ── Step cards (scrollable) ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        steps_w = QWidget()
        steps_l = QVBoxLayout(steps_w)
        steps_l.setSpacing(10)

        # Step 1
        s1 = QGroupBox()
        s1l = QVBoxLayout(s1)
        hdr1 = StepHeader(1, "Load Lookup Table Settings")
        self._step_headers[1] = hdr1
        s1l.addWidget(hdr1)
        self._s1_vals = {}
        row_w = QHBoxLayout()
        for key, label, unit in [("mono_e", "Mono E", "keV"), ("ue", "UE", "keV"), ("roll", "Roll SP", ""), ("pitch", "Pitch SP", "")]:
            w, v = make_readout(label, "—", unit)
            self._s1_vals[key] = v
            row_w.addWidget(w)
        row_w.addStretch()
        s1l.addLayout(row_w)
        steps_l.addWidget(s1)

        # Step 2
        s2 = QGroupBox()
        s2l = QVBoxLayout(s2)
        hdr2 = StepHeader(2, "Disable BPM Feedback → Move Motors → Retract Mirror")
        self._step_headers[2] = hdr2
        s2l.addWidget(hdr2)
        g2 = QGridLayout()
        self._s2_tags = {}
        items = [
            ("bpm_h_off", "H BPM feedback", "OFF"),
            ("bpm_v_off", "V BPM feedback", "OFF"),
            ("motors",    "Motors at setpoint", "—"),
            ("mirror",    "Mirror retracted", "—"),
        ]
        for i, (key, lbl, val) in enumerate(items):
            g2.addWidget(QLabel(lbl), i // 2, (i % 2) * 2)
            t = make_tag(val, "grey")
            self._s2_tags[key] = t
            g2.addWidget(t, i // 2, (i % 2) * 2 + 1)
        s2l.addLayout(g2)
        steps_l.addWidget(s2)

        # Step 3
        s3 = QGroupBox()
        s3l = QVBoxLayout(s3)
        hdr3 = StepHeader(3, "DCM Piezo Alignment")
        self._step_headers[3] = hdr3
        s3l.addWidget(hdr3)

        s3_inner = QHBoxLayout()

        # Substep checklist
        check_w = QWidget()
        check_l = QVBoxLayout(check_w)
        check_l.setSpacing(6)
        self._s3_checks = []
        for txt in [
            "Set piezo pitch → center",
            "Set piezo roll → center",
            "Scan roll → BPM x = 0",
            "Scan pitch → intensity peak",
        ]:
            lbl = QLabel(f"○  {txt}")
            lbl.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 12px;")
            self._s3_checks.append(lbl)
            check_l.addWidget(lbl)
        check_l.addStretch()
        s3_inner.addWidget(check_w, 1)

        # Roll scan plot
        self.roll_plot = make_plot("Roll Scan", "BPM X (mm)", "Roll position")
        self.roll_plot.setMinimumHeight(140)
        self.roll_curve   = self.roll_plot.plot([], [], pen=pg.mkPen(PAL["cyan"], width=2))
        self.roll_scatter = pg.ScatterPlotItem(size=5, brush=pg.mkBrush(PAL["cyan"]))
        self.roll_plot.addItem(self.roll_scatter)
        self.roll_peak_line = pg.InfiniteLine(angle=90, pen=pg.mkPen(PAL["amber"], width=1.5, style=Qt.PenStyle.DashLine))
        self.roll_plot.addItem(self.roll_peak_line)
        self.roll_peak_line.setVisible(False)
        self._roll_xs, self._roll_ys = [], []
        s3_inner.addWidget(self.roll_plot, 2)

        # Pitch scan plot
        self.pitch_plot = make_plot("Pitch Scan", "Intensity (a.u.)", "Pitch position")
        self.pitch_plot.setMinimumHeight(140)
        self.pitch_curve   = self.pitch_plot.plot([], [], pen=pg.mkPen(PAL["cyan"], width=2),
                                                   fillLevel=0, brush=pg.mkBrush(PAL["cyan_dim"] + "88"))
        self.pitch_scatter = pg.ScatterPlotItem(size=5, brush=pg.mkBrush(PAL["cyan"]))
        self.pitch_plot.addItem(self.pitch_scatter)
        self.pitch_peak_line = pg.InfiniteLine(angle=90, pen=pg.mkPen(PAL["amber"], width=1.5, style=Qt.PenStyle.DashLine))
        self.pitch_plot.addItem(self.pitch_peak_line)
        self.pitch_peak_line.setVisible(False)
        self._pitch_xs, self._pitch_ys = [], []
        s3_inner.addWidget(self.pitch_plot, 2)

        s3l.addLayout(s3_inner)
        steps_l.addWidget(s3)

        # Step 4
        s4 = QGroupBox()
        s4l = QVBoxLayout(s4)
        hdr4_row = QHBoxLayout()
        hdr4 = StepHeader(4, "Mirror Alignment")
        self._step_headers[4] = hdr4
        hdr4_row.addWidget(hdr4)
        hdr4_row.addStretch()
        self.skip_mirror_chk = QCheckBox("Skip this step")
        self.skip_mirror_chk.setChecked(True)
        self.skip_mirror_chk.setToolTip("When checked, Step 4 is bypassed during alignment")
        hdr4_row.addWidget(self.skip_mirror_chk)
        s4l.addLayout(hdr4_row)
        ph = QLabel("Mirror alignment substeps not yet defined. Configure them in the Mirror tab.")
        ph.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 12px; padding: 10px 0;")
        s4l.addWidget(ph)
        steps_l.addWidget(s4)

        # Step 5
        s5 = QGroupBox()
        s5l = QVBoxLayout(s5)
        hdr5 = StepHeader(5, "Enable Feedback Loops")
        self._step_headers[5] = hdr5
        s5l.addWidget(hdr5)
        g5 = QGridLayout()
        self._s5_rows = {}
        fb_items = [
            ("h_fb",     "H feedback (DCM piezo roll)", "BPM x = 0"),
            ("intensity","Maximise intensity (DCM piezo pitch)", "BPM intensity max"),
            ("mirror_v", "Mirror piezo pitch tweak", "BPM y = 0"),
            ("v_fb",     "V feedback (DCM piezo pitch)", "BPM y = 0"),
        ]
        for i, (key, lbl, target) in enumerate(fb_items):
            g5.addWidget(QLabel(lbl), i, 0)
            g5.addWidget(QLabel(target), i, 1)
            t = make_tag("—", "grey")
            self._s5_rows[key] = t
            g5.addWidget(t, i, 2)
        s5l.addLayout(g5)
        steps_l.addWidget(s5)

        # Log
        log_box = QGroupBox("Alignment Log")
        log_l = QVBoxLayout(log_box)
        self.log = LogWidget()
        clr = styled_button("Clear")
        clr.setMaximumWidth(80)
        clr.clicked.connect(self.log.clear)
        log_l.addWidget(self.log)
        log_l.addWidget(clr)
        steps_l.addWidget(log_box)

        scroll.setWidget(steps_w)
        lay.addWidget(scroll, 1)

        self.start_btn.clicked.connect(self.start_alignment)
        self.abort_btn.clicked.connect(self.abort_alignment)

    # ── Public ────────────────────────────────────────────────────────────────
    def set_selected_row(self, row):
        self._selected_row = row
        self.row_label.setText(
            f"Energy row: MonoE = {row['mono_e']} keV  |  UE = {row['ue']} keV  |  Roll = {row['roll']}  |  Pitch = {row['pitch']}"
        )
        self.row_label.setStyleSheet(f"color: {PAL['cyan']}; font-size: 11px; font-family: 'JetBrains Mono', monospace;")
        for key in ["mono_e", "ue", "roll", "pitch"]:
            self._s1_vals[key].setText(str(row[key]))

    def start_alignment(self, pvs=None, scan_params=None, simulate=True, mirror_stages=None):
        if not self._selected_row:
            QMessageBox.warning(self, "No row selected", "Please select an energy row in the Energy Table tab first.")
            return
        if pvs is None:
            pvs = DEFAULT_PVS
        if scan_params is None:
            scan_params = DEFAULT_SCAN
        if mirror_stages is None:
            mirror_stages = DEFAULT_MIRROR_STAGES

        self._reset_ui()
        self.start_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)

        self._thread = QThread()
        self._worker = AlignmentWorker(pvs, scan_params, self._selected_row, simulate=simulate,
                                       skip_mirror=self.skip_mirror_chk.isChecked(),
                                       mirror_stages=mirror_stages)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self._on_log)
        self._worker.step_status.connect(self._on_step_status)
        self._worker.scan_point.connect(self._on_scan_point)
        self._worker.scan_peak.connect(self._on_scan_peak)
        self._worker.bpm_update.connect(self._on_bpm_update)
        self._worker.feedback_update.connect(self._on_feedback)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def abort_alignment(self):
        if self._worker:
            self._worker.abort()

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_log(self, msg, level):
        self.log.append_log(msg, level)

    def _on_step_status(self, step, status):
        if step in self._step_headers:
            self._step_headers[step].set_status(status)
        self.beam_path.update_step(step, status)
        done_count = sum(1 for h in self._step_headers.values() if h._status == "done")
        self.progress.setValue(done_count)

        if step == 2 and status == "done":
            for key in ["bpm_h_off", "bpm_v_off"]:
                self._set_tag(self._s2_tags[key], "OFF", "amber")
            self._set_tag(self._s2_tags["motors"], "Done", "green")
            self._set_tag(self._s2_tags["mirror"], "Done", "green")

        if step == 3 and status == "running":
            self._s3_checks[0].setText(f"✓  Set piezo pitch → center")
            self._s3_checks[0].setStyleSheet(f"color: {PAL['green']}")
            self._s3_checks[1].setText(f"✓  Set piezo roll → center")
            self._s3_checks[1].setStyleSheet(f"color: {PAL['green']}")

        if step == 5 and status == "done":
            for key in self._s5_rows:
                self._set_tag(self._s5_rows[key], "Active", "green")

    def _set_tag(self, tag, text, color):
        tag.setText(text)
        obj = {"green": "tag_green", "amber": "tag_amber", "red": "tag_red", "cyan": "tag_cyan"}.get(color, "tag_grey")
        tag.setObjectName(obj)
        tag.style().unpolish(tag)
        tag.style().polish(tag)

    def _on_scan_point(self, motor, x, y):
        if motor == "roll":
            self._roll_xs.append(x)
            self._roll_ys.append(y)
            self.roll_curve.setData(self._roll_xs, self._roll_ys)
            self.roll_scatter.setData(self._roll_xs, self._roll_ys)
            # update substep
            if len(self._roll_xs) == 1:
                self._s3_checks[2].setText("⟳  Scan roll → BPM x = 0")
                self._s3_checks[2].setStyleSheet(f"color: {PAL['amber']}")
        elif motor == "pitch":
            self._pitch_xs.append(x)
            self._pitch_ys.append(y)
            self.pitch_curve.setData(self._pitch_xs, self._pitch_ys)
            self.pitch_scatter.setData(self._pitch_xs, self._pitch_ys)
            if len(self._pitch_xs) == 1:
                self._s3_checks[3].setText("⟳  Scan pitch → intensity peak")
                self._s3_checks[3].setStyleSheet(f"color: {PAL['amber']}")

    def _on_scan_peak(self, motor, peak):
        if motor == "roll":
            self.roll_peak_line.setValue(peak)
            self.roll_peak_line.setVisible(True)
            self._s3_checks[2].setText(f"✓  Scan roll → BPM x = 0  ({peak:.5f})")
            self._s3_checks[2].setStyleSheet(f"color: {PAL['green']}")
        elif motor == "pitch":
            self.pitch_peak_line.setValue(peak)
            self.pitch_peak_line.setVisible(True)
            self._s3_checks[3].setText(f"✓  Scan pitch → peak ({peak:.5f})")
            self._s3_checks[3].setStyleSheet(f"color: {PAL['green']}")

    def _on_bpm_update(self, x, y, intensity):
        self._bpm_x_lbl.setText(f"{x:+.4f}")
        self._bpm_y_lbl.setText(f"{y:+.4f}")
        self._bpm_i_lbl.setText(f"{intensity:.3f}")
        self._bpm_x_lbl.setStyleSheet(
            f"color: {PAL['green'] if abs(x) < 0.005 else PAL['amber']}; font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700;"
        )
        self._bpm_y_lbl.setStyleSheet(
            f"color: {PAL['green'] if abs(y) < 0.005 else PAL['amber']}; font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700;"
        )
        self._bpm_i_lbl.setStyleSheet(
            f"color: {PAL['green'] if intensity > 0.9 else PAL['cyan']}; font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700;"
        )

    def _on_feedback(self, h, v):
        self._fb_h.setText(f"H FB  {'ON' if h else 'OFF'}")
        obj = "tag_green" if h else "tag_grey"
        self._fb_h.setObjectName(obj)
        self._fb_h.style().unpolish(self._fb_h)
        self._fb_h.style().polish(self._fb_h)

        self._fb_v.setText(f"V FB  {'ON' if v else 'OFF'}")
        obj = "tag_green" if v else "tag_grey"
        self._fb_v.setObjectName(obj)
        self._fb_v.style().unpolish(self._fb_v)
        self._fb_v.style().polish(self._fb_v)

        if h:
            self._set_tag(self._s5_rows["h_fb"], "Active", "green")
        if v:
            self._set_tag(self._s5_rows["v_fb"], "Active", "green")

    def _on_finished(self, success):
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait()

    def _reset_ui(self):
        for h in self._step_headers.values():
            h.set_status("idle")
        for step in range(1, 6):
            self.beam_path.update_step(step, "idle")
        self.progress.setValue(0)
        self._roll_xs.clear(); self._roll_ys.clear()
        self._pitch_xs.clear(); self._pitch_ys.clear()
        self.roll_curve.setData([], [])
        self.roll_scatter.setData([], [])
        self.pitch_curve.setData([], [])
        self.pitch_scatter.setData([], [])
        self.roll_peak_line.setVisible(False)
        self.pitch_peak_line.setVisible(False)
        for chk in self._s3_checks:
            chk.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 12px;")
        for key in self._s5_rows:
            self._set_tag(self._s5_rows[key], "—", "grey")
        for key in self._s2_tags:
            self._set_tag(self._s2_tags[key], "—", "grey")
        self.log.clear()


# ─── Mirror Tab ───────────────────────────────────────────────────────────────
class MirrorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        hdr = StepHeader(4, "Mirror Alignment")
        lay.addWidget(hdr)

        ph_box = QGroupBox()
        ph_l = QVBoxLayout(ph_box)
        ph_lbl = QLabel(
            "Mirror alignment substeps not yet defined.\n\n"
            "Provide the procedure (motors to move, scan axes, signals to optimise) "
            "and this tab will be built out with the same step-by-step cards, "
            "live scan plots, and motor readbacks as the main Alignment tab."
        )
        ph_lbl.setStyleSheet(f"color: {PAL['text_dim']}; font-size: 13px; padding: 20px;")
        ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lbl.setWordWrap(True)
        ph_l.addWidget(ph_lbl)
        lay.addWidget(ph_box)

        # Placeholder motor readouts
        motor_box = QGroupBox("Mirror Motor Readbacks (Placeholder)")
        m_lay = QHBoxLayout(motor_box)
        for label in ["Mirror TX", "Mirror TY", "Mirror TZ"]:
            w, _ = make_readout(label, "—", "mm")
            m_lay.addWidget(w)
        m_lay.addStretch()
        lay.addWidget(motor_box)
        lay.addStretch()


# ─── Main Window ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
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

        main_lay.addWidget(topbar)

        # ── Tabs ──
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        main_lay.addWidget(self.tabs, 1)

        self.setup_tab     = SetupTab()
        self.energy_tab    = EnergyTableTab()
        self.alignment_tab = AlignmentTab()
        self.mirror_tab    = MirrorTab()

        self.tabs.addTab(self.setup_tab,     "  Setup  ")
        self.tabs.addTab(self.energy_tab,    "  Energy Table  ")
        self.tabs.addTab(self.alignment_tab, "  Alignment  ")
        self.tabs.addTab(self.mirror_tab,    "  Mirror  ")

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

    def _auto_load_config(self):
        if not os.path.exists(AUTO_CONFIG_PATH):
            return
        try:
            with open(AUTO_CONFIG_PATH) as f:
                cfg = json.load(f)
            self.setup_tab._apply_config(cfg)
            if "energy_table" in cfg:
                self.energy_tab.set_table_data(cfg["energy_table"])
            self.status.showMessage(f"Config restored from {AUTO_CONFIG_PATH}")
        except Exception as e:
            self.status.showMessage(f"Could not restore config: {e}")

    def _save_config(self):
        cfg = {
            "pvs": self.setup_tab.get_pvs(),
            "scan": self.setup_tab.get_scan_params(),
            "simulate": self.setup_tab.is_simulate(),
            "energy_table": self.energy_tab.get_table_data(),
            "mirror_stages": self.setup_tab.get_mirror_stages(),
        }
        try:
            with open(AUTO_CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_config()
        super().closeEvent(event)

    def _start_alignment(self):
        pvs = self.setup_tab.get_pvs()
        params = self.setup_tab.get_scan_params()
        simulate = self.setup_tab.is_simulate()
        mirror_stages = self.setup_tab.get_mirror_stages()
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
