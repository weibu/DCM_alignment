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
| **Energy Table** | The energy lookup table (MonoE, UE, harmonic, roll, pitch, detector sensitivities) and, below it, the record of past alignments. Select a row before running. |
| **PV Monitor / Config** | Shared PVs — undulator, BPM, feedback, AutoFeedback, ion chamber — with live readbacks, the shared timeouts, Simulation mode, Test EPICS Connection, and Load/Save Config. |
| **DCM Setup** | The DCM crystal motors and piezos, and every DCM scan parameter including the DCM scan signal. |
| **Mirror Setup** | Everything mirror-related in one place: slit and pitch PVs, the mirror scan parameters, the stage in/out table, and the Step 4 procedure summary. |
| **Alignment** | Run the sequence. Per-chapter and per-step tick boxes, a run button on each chapter, the beam-path indicator, tabbed scan figures, BPM readouts and the log. |
| **Record** | Which PVs are written to the lookup table after a successful run. |

All three settings tabs are the same panel with a different filter, so live
readbacks, monitoring and config handling behave identically on each. The saved
`dcm_config.json` is unchanged by the split — `pvs` and `scan` are still single
flat dictionaries, so an existing config loads untouched.

## Alignment Steps

The five top-level steps are called **chapters**. Every chapter clears
`15IDA:userTran6.O` ("AutoFeedback") first — while that field is 1 the transform
forces both feedback loops on (`.G = (a||o)&&...`, `.H = (b||o)&&...`) and any
attempt to control them from here is ignored.

| Step | Action |
|------|--------|
| 1 | Log MonoE, UE, roll and pitch from the selected row |
| 2 | 2A feedback off → 2B undulator, mono, roll, pitch **and the row's detector sensitivities**, waiting for the undulator to arrive → 2C mirror out |
| 3 | 3A centre DCM piezos at 5 → 3B pitch scan (peak) → 3C roll scan (BPM x = 0) → 3D pitch scan (peak) |
| 4 | 4A slit scan → 4B mirror in → **4B2 centre the mirror pitch piezo at 5** → **4C mirror pitch motor scan (BPM y = 0)** → 4D VDM:Y peak → 4E coupled VFM:Y + VDM:Y |
| 5 | Close the JJC → 5A H feedback on → 5B DCM piezo peak → 5C mirror piezo (BPM y = 0) → 5D V feedback on |

4C drives the pitch **motor** (`ID15A1:DMS:VDM:PI`, µrad), not the piezo — 4B2
parks the piezo mid-range first, mirroring what 3A/3C do for the DCM. Both piezo
records report `DRVL=-2, DRVH=12`, so 5 is genuinely the middle.

### Choosing what to run

Every chapter and every step has a tick box in the left panel; unticking a
chapter unticks its steps, and a partly-ticked chapter shows as such. The **▶**
button on a chapter row runs that chapter on its own without disturbing the tick
boxes. Selections reset to all-enabled each launch, so a forgotten unticked box
cannot silently skip a step days later.

A skipped step never leaves a later one stranded: where a step would have
produced a value — 4A's slit centre, 3B's coarse pitch — the sequence reads the
live position instead. The mirror is inserted before Step 5 whenever it is
actually out, tracked from what ran rather than inferred from a checkbox.

### Beam availability

Every scan first checks the upstream shutter, `S15ID-PSS:SCS:BeamBlockingM`.
It is a bi record with `ZNAM="OFF"` / `ONAM="ON"`, and 0 means nothing is
blocking the beam. If it reads blocking, the run pauses with the usual fault
dialog and waits — the PSS owns the shutter, so unlike the feedback loops this
is not something the app may put right on your behalf. Open it and press
**Try Again**.

Note the record sits at MAJOR severity even when the beam *is* available, so
alarm severity is deliberately not used as the test.

### Feedback during the sequence

Both loops are off from 2A onward. Before every scan the app **reads** the
feedback state back and, if a loop is on, turns it off and logs it. From 5A the
H loop is deliberately on, so only V is asserted off; 5D enables V as the final
handover.

### Zero-crossing scans

The three BPM-zero scans — 3C, 4C and 5C — start where you configure them and
step at the configured step size, but have no pre-decided end: they stop as soon
as **two points lie past the zero crossing**. If no crossing appears within three
times the configured span the run pauses with the usual fault dialog. Previously
they swept a fixed window and, if the crossing fell outside it, silently moved
the motor to the closest-to-zero point.

### JJC slit size

The whole alignment runs with the JJC (`15IDC:Slit4VDsize.VAL`) **open at 4**.
It is closed to its operating size — **JJC size before feedback** on the Mirror
tab, default 0.4 mm — as the first substep of Step 5, immediately before the
feedback loops are enabled. This happens whether Step 4 ran or was skipped, so
the mirror is in position either way.

Note that `mirror_in_out.docx` lists 0.4 as the JJC Size *in* value. That is the
post-alignment value; using it as the mirror-in value would close the slit
during Step 4. The mirror-stage default is therefore 4 for both in and out.

## Scan Figures

The figure area has two levels of tabs. The outer level picks the **device** —
DCM or Mirror — and inside each device there are two side-by-side panes, each
with its own tab bar, so you can view any two of that device's figures at once.

| Device | Figure | x axis | Traces |
|--------|--------|--------|--------|
| DCM | Pitch motor | µrad | 3B coarse **and** 3D fine, overlaid |
| DCM | Roll | µrad | 3C |
| DCM | Pitch piezo | DCOM | 5B |
| Mirror | Slit | mm | 4A |
| Mirror | Mirror piezo | DCOM | 4C **and** 5C, overlaid |
| Mirror | VDM:Y | µm | 4D |
| Mirror | VFM:Y | µm | 4E |

The piezo scans have their own figures because their x axis is a DCOM demand of
order 5, not a motor position of order 1300 — putting them on the same axis as
the motor scans made both unreadable.

Each scan added to a figure gets its own colour, its own legend entry and its
own peak/zero marker in the matching colour. Trace colours are fixed and do not
change with the theme, so a colour means the same trace in every screenshot.

**Follow scan** (top right of the device tabs) brings the running scan's figure
forward in the *left* pane and switches the device tab to match. The right pane
is always yours. If you pick a tab yourself during a run, Follow switches itself
off so the app stops moving the view; it re-arms at the start of the next run,
when you click Proceed, or when you tick the box again. A figure that received a
scan while hidden is marked with a ● on its tab.

Figures clear at the start of each run.

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

**Motion is never timed out.** A stage is allowed to take as long as it takes —
CRL Y needs about a minute for its in/out travel and a large Mono E change takes
several minutes. Completion is read from the motor record itself (`.DMOV`,
`.DIFF` against `.RDBD`, `.MISS`, `.LVIO`, the `MSTA` problem bits), and PVs are
classified as motor or plain records at pre-flight by whether their `.DMOV`
connects. Three things are timed, and all of them mean *no confirmation
arrived*, not *this is taking a while*:

| Setup parameter | Default | Fires when |
|---|---|---|
| PV write ack timeout | 10 s | A plain record's put-callback never came back |
| Motor start grace | 5 s | The setpoint was accepted but the motor never started |
| Motor stall timeout | 30 s | `.DMOV` says moving but `.RBV` has stopped advancing |

The mirror stages and the undulator are now genuinely waited for: all setpoints
are issued first so the stages travel concurrently, then each is awaited, and
Step 3 does not begin until the undulator's busy flag clears.

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

## Lookup Table

Column headings word-wrap, and columns are resizable by dragging the dividers —
a recorded row can carry 30-odd columns with names like
"MonP Max Intensity w/o Mirror". Widths survive adding a record and are saved to
`dcm_config.json`. The energy table and the mirror stage table are resizable too.

### CSV format

```
mono_e,ue,harmonic,roll,pitch,bpm_sen,ic_sen_unit,ic_sen_num
8.0,8.02,1,-7670,1338,6,2,3
10.0,10.03,1,-7671,1328,6,2,3
```
