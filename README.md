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
py -3.9 dcm_align_app.py
```

(On the beamline Windows box a bare `python` resolves to the Microsoft Store
stub and fails; use the `py` launcher.)

## Tabs

| Tab | Purpose |
|-----|---------|
| **Setup** | Edit all motor PV names, scan parameters (range/steps/settle time, **DCM scan signal**), and toggle simulation vs. real EPICS |
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
| 5 | Close JJC to its operating size → enable H feedback (piezo roll → BPM x=0) → maximise intensity (piezo pitch) → tweak mirror piezo pitch (BPM y=0) → enable V feedback |

### JJC slit size

The whole alignment runs with the JJC (`15IDC:Slit4VDsize.VAL`) **open at 4**.
It is closed to its operating size — **JJC size before feedback** on the Mirror
tab, default 0.4 mm — as the first substep of Step 5, immediately before the
feedback loops are enabled. This happens whether Step 4 ran or was skipped, so
the mirror is in position either way.

Note that `mirror_in_out.docx` lists 0.4 as the JJC Size *in* value. That is the
post-alignment value; using it as the mirror-in value would close the slit
during Step 4. The mirror-stage default is therefore 4 for both in and out.

## PV Fault Handling

The sequence never guesses. Any PV read that comes back `None` — a disconnected
PV, an unknown name, or a channel-access error — is a **critical fault**, not a
silently substituted zero. The same applies to failed writes and to a motor that
never reports `.DMOV`.

**Pre-flight.** Before Start Alignment moves anything (in particular before
step 2A switches the BPM feedback off), every PV the run will touch is
connect-tested. The set is computed from the current configuration, so it
respects *Skip mirror alignment*, blank PV names, and the selected signal
sources. If any PV fails, the run does not start and the log lists them.

**During the run.** On a fault the worker thread stops where it is, logs
`CRITICAL — PV FAULT` naming the PV and the step it was in, and opens a dialog:

| Button | Effect |
|--------|--------|
| **Check PV** | Connect to that PV right now and report value, type, severity, timestamp and IOC host — plus its `.RBV` and `.DMOV` fields. Does not resume. |
| **Try Again** | Re-read the PV. If it answers, the sequence continues from exactly where it stopped. |
| **Abort Alignment** | Stop the run. |

The dialog is deliberately **not** application-blocking: the sequence is halted
because the worker thread is blocked, so you can still watch the live readouts,
the plots and the log, and switch to the Setup tab to diagnose. Closing the
dialog does **not** resume — the run stays paused and a red
`Review fault…` button reopens it.

**Live monitors.** While a run is in progress, a PV that drops out between reads
is caught by its channel-access connection callback and pauses the sequence at
the next safe point. When no run is in progress a disconnect is shown as a red
`DISCONNECTED` readback in Setup and a status-bar message, with no dialog.

## Simulation Mode

When **Simulation mode** is checked in Setup (default), all motor moves and scans are
replaced by Gaussian/linear synthetic signals. No EPICS connection is required.
Uncheck to connect to real hardware (requires `pyepics` and a running IOC).

Simulation never raises a PV fault and skips pre-flight.

## Scan Signal

The Step 3 pitch scans and the Step 5B DCM piezo scan read whichever detector is
selected as **DCM scan signal** in Setup (default: BPM Intensity). Step 4's
mirror scans have their own **Signal source** selector on the Mirror tab.

## Configuration

PV names and scan parameters are editable in the Setup tab. Use **Save Config…**
and **Load Config…** to export/import `.json` configuration files.

## Lookup Table Format (CSV)

```
mono_e,ue,roll,pitch
8.0,9.8,0.412,2.341
10.0,12.1,0.398,2.187
```
