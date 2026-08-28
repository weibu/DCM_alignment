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
    mir_substep      = pyqtSignal(str, str)            # (step_id "A"–"D", status)
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
            vdm_start      = p.get("mir_vdm_start", -500.0)
            vdm_stop       = p.get("mir_vdm_stop", 500.0)
            vdm_steps      = int(p.get("mir_vdm_steps", 21))
            vfm_start      = p.get("mir_vfm_start", -250.0)
            vfm_stop       = p.get("mir_vfm_stop", 250.0)
            vfm_steps      = int(p.get("mir_vfm_steps", 21))

            # ── 4A: Slit scan (mirror out) → find beam center ─────────
            self.mir_substep.emit("A", "running")
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
                    if not self._sleep(p["settle_time"] * 0.5): return self._abort_cleanup()

                slit_peak = find_peak_centroid(xs_slit, np.array(ys_slit))
                self.scan_peak.emit("mir_slit_cen", slit_peak)
                self.log(f"  Beam center at {slit_peak:.4f} mm → moving slit", "ok")
                self.epics.put(top_pv, slit_peak + slit_size_a / 2.0)
                self.epics.put(bot_pv, slit_peak - slit_size_a / 2.0)
                if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                if not self._wait_motor_done(bot_pv): return self._abort_cleanup()
            else:
                self.log("  Slit PVs not configured — skipping 4A slit scan.", "warn")
            self.mir_substep.emit("A", "done")

            # ── 4B: Mirror in → close slit → pitch piezo → BPMY = 0 ──
            self.mir_substep.emit("B", "running")
            self.log("  4B: Moving mirror into beam path…")
            for stage in self.mirror_stages:
                if stage["pv"].strip():
                    self.epics.put(stage["pv"], stage["val_in"])
                    self.log(f"  [{stage['pv']}] → {stage['val_in']}  ({stage['name']} IN)", "ok")
                    if not self._sleep(0.1): return self._abort_cleanup()
            if not self._sleep(0.5): return self._abort_cleanup()
            self.log("  Mirror in position.", "ok")

            if top_pv and bot_pv:
                self.log(f"  Narrowing slit to {slit_size_b} mm for mirror scan")
                self.epics.put(top_pv, slit_peak + slit_size_b / 2.0)
                self.epics.put(bot_pv, slit_peak - slit_size_b / 2.0)
                if not self._wait_motor_done(top_pv): return self._abort_cleanup()
                if not self._wait_motor_done(bot_pv): return self._abort_cleanup()

            if mir_piezo_pv:
                self.log("  Scanning mirror pitch piezo → BPMY = 0…")
                piezo_cur = self.epics.get(mir_piezo_pv) or p.get("piezo_center", 5.0)
                xs_piezo = np.linspace(piezo_cur - 1.0, piezo_cur + 1.0, 21)
                ys_bpmy = []
                _piezo_zero = piezo_cur + random.uniform(-0.1, 0.1)
                for px in xs_piezo:
                    if self._abort: return self._abort_cleanup()
                    self.epics.put(mir_piezo_pv, px)
                    if not self._sleep(p["settle_time"] * 0.5): return self._abort_cleanup()
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
            self.mir_substep.emit("B", "done")

            # ── 4C: Scan VDM:Y → find peak → move ────────────────────
            self.mir_substep.emit("C", "running")
            self.log("  4C: Scanning VDM:Y → finding signal peak…")
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
                if not self._sleep(p["settle_time"] * 0.5): return self._abort_cleanup()

            vdm_peak = find_peak_centroid(xs_vdm, np.array(ys_vdm))
            self.scan_peak.emit("mir_vdm", vdm_peak)
            self.epics.put(vdm_pv, vdm_peak)
            if not self._wait_motor_done(vdm_pv): return self._abort_cleanup()
            self.log(f"  VDM:Y peak at {vdm_peak:.2f} → moved", "ok")
            self.mir_substep.emit("C", "done")

            # ── 4D: Coupled VFM+VDM scan (VDM step = 2× VFM step) ────
            self.mir_substep.emit("D", "running")
            self.log("  4D: Coupled VFM:Y + VDM:Y scan (VDM step = 2× VFM step)…")
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
                if not self._sleep(p["settle_time"] * 0.5): return self._abort_cleanup()

            vfm_peak_pos    = find_peak_centroid(xs_vfm, np.array(ys_coupled))
            vfm_delta_final = vfm_peak_pos - vfm_cur
            vdm_final       = vdm_ref + 2.0 * vfm_delta_final
            self.scan_peak.emit("mir_coupled", vfm_peak_pos)
            self.epics.put(vfm_pv, vfm_peak_pos)
            if not self._wait_motor_done(vfm_pv): return self._abort_cleanup()
            self.epics.put(vdm_pv, vdm_final)
            if not self._wait_motor_done(vdm_pv): return self._abort_cleanup()
            self.log(f"  VFM:Y → {vfm_peak_pos:.2f}  VDM:Y → {vdm_final:.2f}  (2× delta applied)", "ok")
            self.mir_substep.emit("D", "done")

            self.step_status.emit(4, "done")
            self.log("Step 4 complete.", "ok")

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
            "mono_energy":   "Mono Energy",
            "roll":          "DCM Roll",
            "pitch":         "DCM Pitch",
            "mir_slit_top":  "Mirror Slit Top",
            "mir_slit_bot":  "Mirror Slit Bottom",
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
            "und_energy":      "Undulator Energy",
            "piezo_pitch":     "DCM Piezo Pitch",
            "piezo_roll":      "DCM Piezo Roll",
            "bpm_x":           "BPM X readback",
            "bpm_y":           "BPM Y readback",
            "bpm_intensity":   "BPM Intensity",
            "feedback_h":      "H Feedback PV",
            "feedback_v":      "V Feedback PV",
            "und_harmonic":    "Undulator Harmonic PV",
            "und_start":       "Undulator Start PV",
            "mir_piezo_pitch": "Mirror Piezo Pitch",
            "ion_chamber":     "Ion Chamber",
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


# ─── Motor → scan plot mapping ────────────────────────────────────────────────
# Plot A: position/zero-crossing scans. Plot B: intensity peak scans.
_SCAN_PLOT_A = {
    "roll":         ("Roll Scan",              "BPM X (mm)",      "Roll position"),
    "mir_slit_cen": ("Slit Scan  4A",          "Signal",          "Slit center (mm)"),
    "mir_piezo":    ("Mirror Piezo  4B",        "BPM Y (mm)",      "Piezo position"),
}
_SCAN_PLOT_B = {
    "pitch":        ("Pitch Scan",             "Intensity (a.u.)", "Pitch position"),
    "mir_vdm":      ("VDM Scan  4C",           "Signal",          "VDM:Y"),
    "mir_coupled":  ("VFM+VDM Scan  4D",       "Signal",          "VFM:Y"),
}

# ─── Alignment Tab ────────────────────────────────────────────────────────────
class AlignmentTab(QWidget):
    _SUBSTEP_TEXT = {
        "3_3a": "Set piezos to center",
        "3_3b": "Roll scan → BPM x = 0",
        "3_3c": "Pitch scan → intensity peak",
        "4_4A": "Slit scan → beam center",
        "4_4B": "Mirror in + piezo → BPMY = 0",
        "4_4C": "Scan VDM:Y → peak",
        "4_4D": "Coupled VFM+VDM → peak",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_row = None
        self._worker = None
        self._thread = None
        self._build()

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
        self.start_btn = styled_button("▶  Start Alignment", "primary", 150)
        self.abort_btn = styled_button("■  Abort", "danger", 80)
        self.abort_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.abort_btn)
        btn_row.addStretch()
        ctrl_l.addLayout(btn_row)
        self.skip_mirror_chk = QCheckBox("Skip mirror alignment (Step 4)")
        self.skip_mirror_chk.setChecked(True)
        self.skip_mirror_chk.setToolTip(
            "When checked, Step 4 is bypassed; mirror is inserted before Step 5"
        )
        ctrl_l.addWidget(self.skip_mirror_chk)
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
            (1, "Load Lookup Table Settings", []),
            (2, "Disable BPM → Motors → Mirror Out", []),
            (3, "DCM Piezo Alignment",
             [("3a", "Set piezos to center"),
              ("3b", "Roll scan → BPM x = 0"),
              ("3c", "Pitch scan → intensity peak")]),
            (4, "Mirror Alignment",
             [("4A", "Slit scan → beam center"),
              ("4B", "Mirror in + piezo → BPMY = 0"),
              ("4C", "Scan VDM:Y → peak"),
              ("4D", "Coupled VFM+VDM → peak")]),
            (5, "Enable Feedback Loops", []),
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
                sub_lbl = QLabel(f"    ○  {sub_txt}")
                sub_lbl.setStyleSheet(
                    f"color: {PAL['text_dim']}; font-size: 11px;"
                )
                self._substep_labels[f"{step_num}_{sub_id}"] = sub_lbl
                steps_lay.addWidget(sub_lbl)

        steps_lay.addStretch()
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

    def _set_substep(self, key, status, detail=""):
        lbl = self._substep_labels.get(key)
        if not lbl:
            return
        base = self._SUBSTEP_TEXT.get(key, key)
        suffix = f" ({detail})" if detail else ""
        if status == "running":
            lbl.setText(f"    ⟳  {base}")
            lbl.setStyleSheet(
                f"color: {PAL['amber']}; font-size: 11px; font-weight: 600;"
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
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self._on_log)
        self._worker.step_status.connect(self._on_step_status)
        self._worker.scan_point.connect(self._on_scan_point)
        self._worker.scan_peak.connect(self._on_scan_peak)
        self._worker.bpm_update.connect(self._on_bpm_update)
        self._worker.feedback_update.connect(self._on_feedback)
        self._worker.mir_substep.connect(self._on_mir_substep)
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
        if step == 3 and status == "running":
            self._set_substep("3_3a", "done")
            self._set_substep("3_3b", "done")

    def _on_scan_point(self, motor, x, y):
        if motor in _SCAN_PLOT_A:
            if self._pa_motor != motor:
                self._start_scan("A", motor)
                sub = {"roll": "3_3b", "mir_slit_cen": "4_4A",
                       "mir_piezo": "4_4B"}.get(motor)
                if sub:
                    self._set_substep(sub, "running")
            self._pa_xs.append(x); self._pa_ys.append(y)
            self._pa_curve.setData(self._pa_xs, self._pa_ys)
            self._pa_scatter.setData(self._pa_xs, self._pa_ys)
        elif motor in _SCAN_PLOT_B:
            if self._pb_motor != motor:
                self._start_scan("B", motor)
                sub = {"pitch": "3_3c", "mir_vdm": "4_4C",
                       "mir_coupled": "4_4D"}.get(motor)
                if sub:
                    self._set_substep(sub, "running")
            self._pb_xs.append(x); self._pb_ys.append(y)
            self._pb_curve.setData(self._pb_xs, self._pb_ys)
            self._pb_scatter.setData(self._pb_xs, self._pb_ys)

    def _on_scan_peak(self, motor, peak):
        if motor in _SCAN_PLOT_A:
            self._pa_peak.setValue(peak)
            self._pa_peak.setVisible(True)
            sub = {"roll": "3_3b", "mir_slit_cen": "4_4A",
                   "mir_piezo": "4_4B"}.get(motor)
            if sub:
                self._set_substep(sub, "done", f"{peak:.5f}")
        elif motor in _SCAN_PLOT_B:
            self._pb_peak.setValue(peak)
            self._pb_peak.setVisible(True)
            sub = {"pitch": "3_3c", "mir_vdm": "4_4C",
                   "mir_coupled": "4_4D"}.get(motor)
            if sub:
                self._set_substep(sub, "done", f"{peak:.3f}")

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

    def _on_mir_substep(self, step_id, status):
        self._set_substep(f"4_{step_id}", status)

    def _on_finished(self, success):
        self.start_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait()

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
        self._scan_fields = {}
        self._build()

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

        # ── Mirror Scan Parameters ──
        scan_box = QGroupBox("Mirror Scan Parameters")
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
            ("mir_slit_size_b",    "Slit size 4B (mm)",     QDoubleSpinBox,  0.01,  5.0,   0.2,  3),
            ("mir_vdm_start",      "VDM scan start offset", QDoubleSpinBox, -5000., 0.,  -500.,  1),
            ("mir_vdm_stop",       "VDM scan stop offset",  QDoubleSpinBox,  0., 5000.,   500.,  1),
            ("mir_vdm_steps",      "VDM scan steps",        QSpinBox,        3,    200,    21,   0),
            ("mir_vfm_start",      "VFM scan start offset", QDoubleSpinBox, -5000., 0.,  -250.,  1),
            ("mir_vfm_stop",       "VFM scan stop offset",  QDoubleSpinBox,  0., 5000.,   250.,  1),
            ("mir_vfm_steps",      "VFM scan steps",        QSpinBox,        3,    200,    21,   0),
        ]
        for r, (key, lbl, cls, mn, mx, dflt, dec) in enumerate(mir_scan_defs, start=1):
            scan_lay.addWidget(QLabel(lbl), r, 0)
            if cls == QDoubleSpinBox:
                sb = QDoubleSpinBox()
                sb.setDecimals(dec)
                sb.setRange(mn, mx)
                sb.setValue(dflt)
            else:
                sb = QSpinBox()
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
            "<b>4A</b> Slit scan (mirror out): scan slit center → signal peak → move.<br>"
            "<b>4B</b> Mirror in, BPMY centering: insert mirror → narrow slit → scan mirror "
            "pitch piezo → BPMY = 0.<br>"
            "<b>4C</b> VDM:Y scan: scan VDM:Y → signal peak → move.<br>"
            "<b>4D</b> Coupled VFM+VDM: scan VFM:Y (VDM step = 2× VFM step) → move VFM to "
            "peak; move VDM by 2× VFM delta."
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
        if not EPICS_AVAILABLE:
            QMessageBox.warning(self, "Test PVs", "pyepics is not installed.")
            return
        import epics
        timeout = 2.0
        results = {}

        def _check(i, stage):
            pv_name = stage["pv"].strip()
            if not pv_name:
                results[i] = (stage["name"], pv_name, "skipped")
                return
            try:
                pv = epics.PV(pv_name, connection_timeout=timeout)
                connected = pv.wait_for_connection(timeout=timeout)
                if connected:
                    pv.disconnect()
                results[i] = (stage["name"], pv_name, "ok" if connected else "timeout")
            except Exception as e:
                msg = str(e)
                results[i] = (stage["name"], pv_name,
                              "timeout" if "access violation" in msg.lower() else f"error: {msg}")

        threads = [threading.Thread(target=_check, args=(i, s))
                   for i, s in enumerate(self._mirror_stages)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = ""
        for i in sorted(results):
            name, pv_name, status = results[i]
            icon, color = (("✓", PAL["green"]) if status == "ok"
                           else ("—", PAL["text_dim"]) if status == "skipped"
                           else ("✗", PAL["red"]))
            rows += (
                f'<tr>'
                f'<td style="padding:3px 8px;color:{PAL["text_sec"]}">{name}</td>'
                f'<td style="padding:3px 8px;font-family:monospace;color:{PAL["text_dim"]}">'
                f'{pv_name or "(empty)"}</td>'
                f'<td style="padding:3px 8px;color:{color};font-weight:600">'
                f'{icon} {status}</td>'
                f'</tr>'
            )
        n_ok = sum(1 for _, _, s in results.values() if s == "ok")
        n_total = sum(1 for _, _, s in results.values() if s != "skipped")
        dlg = QDialog(self)
        dlg.setWindowTitle("Mirror Stage PV Test")
        dlg.setMinimumWidth(500)
        dlg_l = QVBoxLayout(dlg)
        summary = QLabel(f"<b>{n_ok} / {n_total} mirror stage PVs connected</b>")
        summary.setStyleSheet(
            f"font-size:13px; color:{PAL['green'] if n_ok == n_total else PAL['amber']};"
        )
        dlg_l.addWidget(summary)
        text = QLabel(f'<table cellspacing="0">{rows}</table>')
        text.setTextFormat(Qt.TextFormat.RichText)
        dlg_l.addWidget(text)
        close_btn = styled_button("Close")
        close_btn.clicked.connect(dlg.accept)
        dlg_l.addWidget(close_btn)
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
        self.mirror_tab.changed.connect(self._save_config)

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
