# DCM Alignment Console

PyQt6 desktop application for aligning a Double Crystal Monochromator (DCM).

## Install

```bash
pip install PyQt6 pyqtgraph numpy scipy
# Optional — only needed for real EPICS hardware:
pip install pyepics
```

## Run

```bash
python dcm_align_app.py
```

## Tabs

| Tab | Purpose |
|-----|---------|
| **Setup** | Edit all motor PV names, scan parameters (range/steps/settle time), and toggle simulation vs. real EPICS |
| **Energy Table** | Load/edit/import/export the lookup table (MonoE, UE, Roll, Pitch). Select a row before running. |
| **Alignment** | Run the full 5-step sequence. Shows beam path indicator, live scan plots, BPM readouts, and log. |
| **Mirror** | Placeholder for mirror alignment substeps (to be filled in when procedure is provided). |

## Alignment Steps

| Step | Action |
|------|--------|
| 1 | Load MonoE, UE, Roll, Pitch from selected lookup table row |
| 2 | Disable BPM H/V feedback → move motors to setpoints → retract mirror |
| 3 | Center DCM piezos (pitch & roll → 5) → scan roll for BPM x = 0 → scan pitch for intensity peak |
| 4 | Mirror alignment (placeholder — substeps TBD) |
| 5 | Enable H feedback (piezo roll → BPM x=0) → maximise intensity (piezo pitch) → tweak mirror piezo pitch (BPM y=0) → enable V feedback |

## Simulation Mode

When **Simulation mode** is checked in Setup (default), all motor moves and scans are
replaced by Gaussian/linear synthetic signals. No EPICS connection is required.
Uncheck to connect to real hardware (requires `pyepics` and a running IOC).

## Configuration

PV names and scan parameters are editable in the Setup tab. Use **Save Config…**
and **Load Config…** to export/import `.json` configuration files.

## Lookup Table Format (CSV)

```
mono_e,ue,roll,pitch
8.0,9.8,0.412,2.341
10.0,12.1,0.398,2.187
```
