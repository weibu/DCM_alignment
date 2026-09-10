# -*- coding: utf-8 -*-
"""Headless simulation tests. No EPICS connection required.

Runs the full alignment sequence in every skip-mirror / confirm combination and
checks the behaviours that have regressed before.

    py -3.9 tests/test_simulation.py
"""
import _harness as H

app = H.app
R = H.Report("DCM Alignment Console - simulation suite")

H.silence_dialogs()
qapp = H.qapp()
win = app.MainWindow()
win.show()

# mir_piezo_pitch used to ship blank, which silently skipped 4B2 and 5C on a
# fresh config -- the run "succeeded" with two steps quietly missing. Every PV a
# scan drives must have a real default.
_blank = [k for k in ("mir_piezo_pitch", "mir_pitch_motor", "piezo_pitch",
                      "piezo_roll", "bpm_x", "bpm_y", "mir_slit_top", "mir_slit_bot")
          if not (app.DEFAULT_PVS.get(k) or "").strip()]
R.check(not _blank, "no PV a scan drives ships blank%s"
        % (" (blank: %s)" % _blank if _blank else ""))


def run_sequence(skip_mirror, confirm):
    """Run one full sequence to completion. Returns the success flag, or None on timeout."""
    win.alignment_tab.set_chapter_enabled(4, not skip_mirror)
    win.alignment_tab.confirm_chk.setChecked(confirm)
    win.setup_tab.sim_check.setChecked(True)
    win.energy_tab.table.selectRow(0)

    result = {}
    win.alignment_tab.alignment_done.connect(lambda ok: result.setdefault("ok", ok))
    win._start_alignment()
    # With "Confirm each step" on, nothing advances until Proceed is clicked.
    win.alignment_tab._worker.confirm_needed.connect(
        lambda _key: H.QTimer.singleShot(10, win.alignment_tab._proceed_clicked))

    if not H.pump(lambda: "ok" in result, 180000):
        return None
    return result.get("ok")


for skip, conf in [(True, False), (False, False), (True, True)]:
    tag = "skip_mirror=%s confirm=%s" % (skip, conf)
    ok = run_sequence(skip, conf)
    if ok is None:
        R.fail("TIMED OUT: " + tag)
    else:
        R.check(ok, "full sequence completes (%s)" % tag)

# A blank stage PV makes _mirror_yz_pvs() hand back an empty VDM:Y name. In
# simulation _fault() returns "retry", so an unguarded blank name would spin the
# checked-read retry loop forever.
saved_stages = win.mirror_tab.get_mirror_stages()
blanked = [dict(st, pv="") if "VDM" in st.get("name", "") else st
           for st in saved_stages]
win.mirror_tab.apply_config({"mirror_stages": blanked})
ok = run_sequence(False, False)
R.check(bool(ok), "a blank VDM stage PV does not hang simulation")
win.mirror_tab.apply_config({"mirror_stages": saved_stages})

# get_checked_pvs() used to drop the "source" key, so every computed scan result
# failed the `if not pv: continue` test and never reached the lookup table.
records = win.energy_tab.get_record_data()
if not R.check(bool(records), "an alignment writes a lookup-table row"):
    pass
else:
    want = ["BPM Max Intensity w/o Mirror", "MonP Max Intensity w/o Mirror",
            "Mirror Stripe", "BPM Y @ 3D (µm)",
            "VDM Y FWHM @ 4D (µm)", "VFM Y FWHM @ 4E (µm)"]
    missing = [w for w in want if w not in records[-1]]
    R.check(not missing,
            "lookup row carries all six computed scan results%s"
            % (" (missing %s)" % missing if missing else ""))

# The JJC stays open at 4 for the whole alignment and is closed to its operating
# size only in Step 5, immediately before the feedback loops are enabled -- in
# both the Step-4-ran and Step-4-skipped branches.
WRITES = []
_real_put = app.EpicsInterface.put


def recording_put(self, pv, value, wait=True, timeout=30.0):
    WRITES.append((pv, value))
    return _real_put(self, pv, value, wait=wait, timeout=timeout)


app.EpicsInterface.put = recording_put
jjc_pv = next(st["pv"] for st in win.mirror_tab.get_mirror_stages()
              if "JJC" in st["name"] and "Size" in st["name"])
fb_h = win.get_pvs()["feedback_h"]
target = win.mirror_tab.get_mirror_scan_params()["jjc_size_pre_feedback"]

for skip in (True, False):
    WRITES[:] = []
    tag = "skip_mirror=%s" % skip
    if not run_sequence(skip, False):
        R.fail("JJC ordering: sequence did not complete (%s)" % tag)
        continue
    jjc_all = [(i, v) for i, (pv, v) in enumerate(WRITES) if pv == jjc_pv]
    closes = [i for i, v in jjc_all if abs(float(v) - target) < 1e-9]
    fb_on = [i for i, (pv, v) in enumerate(WRITES) if pv == fb_h and float(v) == 1.0]
    if not closes:
        R.fail("JJC never closed to %s (%s); writes were %s" % (target, tag, jjc_all))
    elif not fb_on:
        R.fail("H feedback was never enabled (%s)" % tag)
    elif closes[0] > fb_on[0]:
        R.fail("JJC closed AFTER feedback was enabled (%s)" % tag)
    else:
        early = [v for i, v in jjc_all if i < closes[0]]
        if any(abs(float(v) - target) < 1e-9 for v in early):
            R.fail("JJC reached %s before the final close (%s)" % (target, tag))
        else:
            R.check(True, "JJC closed to %s before feedback, open (%s) until then (%s)"
                    % (target, ", ".join(str(v) for v in early) or "no earlier writes", tag))

app.EpicsInterface.put = _real_put

# ── Figure routing. The loop above ended on a skip_mirror=False run, so every
#    figure should be populated and the two overlay pairs should each hold two
#    traces. "pitch" used to be one key shared by the DCM pitch motor and the
#    DCM pitch piezo, concatenating incompatible x scales into one polyline.
board = win.alignment_tab._plot_board

# dcm_pitch overlays 3B+3D. mir_pitch (4C, µrad motor) and mir_piezo (5C, DCOM
# piezo) are deliberately separate: since 4C moved to the pitch motor they no
# longer share an x quantity and must not share an axis.
for fig_id, expected in (("dcm_pitch", 2), ("mir_pitch", 1), ("mir_piezo", 1)):
    got = len(board.model(fig_id).order())
    R.check(got == expected,
            "figure %r carries %d trace(s) (got %d)" % (fig_id, expected, got))

R.check(board.model("mir_pitch").x_label != board.model("mir_piezo").x_label,
        "4C and 5C are on figures with different x units (%r vs %r)"
        % (board.model("mir_pitch").x_label, board.model("mir_piezo").x_label))

empty = [f[0] for f in app._FIGURE_DEFS if board.model(f[0]).is_empty()]
R.check(not empty,
        "every figure received its scan%s" % (" (empty: %s)" % empty if empty else ""))

labels = sorted(sr.label for f in app._FIGURE_DEFS
                for sr in board.model(f[0]).order())
R.check(len(labels) == len(set(labels)) == 9,
        "all nine scans are separately labelled: %s" % labels)

colours_ok = all(len({sr.color for sr in board.model(f[0]).order()})
                 == len(board.model(f[0]).order()) for f in app._FIGURE_DEFS)
R.check(colours_ok, "traces sharing a figure have distinct colours")

unsorted_series = [sr.label for f in app._FIGURE_DEFS
                   for sr in board.model(f[0]).order()
                   if any(b < a for a, b in zip(sr.xs, sr.xs[1:]))]
R.check(not unsorted_series,
        "every trace is monotonic in x%s"
        % (" (zig-zag: %s)" % unsorted_series if unsorted_series else ""))

R.check(all(len(sr.raw) == len(sr.xs) for f in app._FIGURE_DEFS
            for sr in board.model(f[0]).order()),
        "acquisition order is preserved alongside the sorted draw order")

snap = board.snapshot()
R.check(isinstance(snap, dict) and len(snap.get("figures", [])) == 8
        and snap.get("meta", {}).get("row"),
        "snapshot() returns the run as plain data for a future history tab")

# ── Per-step enable. Every substep is now gated, and a disabled producer means
#    its consumer works from the live position rather than a remembered result.
def run_with(enabled):
    """Run with an explicit enable set. Returns (ok, statuses seen)."""
    seen = []
    result = {}
    win.setup_tab.sim_check.setChecked(True)
    win.energy_tab.table.selectRow(0)
    win.alignment_tab.alignment_done.connect(lambda ok: result.setdefault("ok", ok))
    win._start_alignment(enabled=enabled)
    win.alignment_tab._worker.substep_status.connect(
        lambda k, st: seen.append((k, st)))
    win.alignment_tab._worker.confirm_needed.connect(
        lambda _k: H.QTimer.singleShot(10, win.alignment_tab._proceed_clicked))
    H.pump(lambda: "ok" in result, 180000)
    return result.get("ok"), seen


all_keys = set(win.alignment_tab._substep_chk)

# 4A produces slit_peak, which 4C and the post-4E reopen consume. It used to be
# initialised inside 4A, so switching 4A off alone raised NameError.
ok, seen = run_with(all_keys - {"4_4A"})
R.check(ok is True, "a run with 4A disabled completes")
R.check(("4_4A", "skipped") in seen, "4A reports itself skipped")
R.check(("4_4C", "done") in seen, "4C still runs with 4A disabled")

# A chapter-only run: chapter 3 plus chapter 1, which only logs the row.
ch3 = set(win.alignment_tab._chapter_steps[3]) | set(win.alignment_tab._chapter_steps[1])
ok, seen = run_with(ch3)
R.check(ok is True, "a chapter-3-only run completes")
ran = {k for k, st in seen if st == "done"}
R.check(ran <= ch3, "a chapter-only run touches nothing outside that chapter: %s"
        % sorted(ran - ch3))
R.check({"3_3a", "3_3b", "3_3c", "3_3d"} <= ran, "all of chapter 3 ran: %s" % sorted(ran))

# The chapter-run button must produce the same enable set.
win.alignment_tab._run_chapter(3)
H.pump(lambda: win.alignment_tab._running, 5000)
R.check(win.alignment_tab._running, "the chapter run button starts a run")
done_btn = {}
win.alignment_tab.alignment_done.connect(lambda ok: done_btn.setdefault("ok", ok))
H.pump(lambda: "ok" in done_btn, 180000)
R.check(done_btn.get("ok") is True, "the chapter run button's run completes")

win.alignment_tab.set_all_enabled(True)
R.check(win.alignment_tab.enabled_keys() == all_keys, "set_all_enabled restores everything")

# _apply_theme used to reach for the theme label with findChild(QLabel, ""),
# which could return None.
try:
    for name in list(app.THEMES):
        win._theme_combo.setCurrentText(name)
    R.check(True, "every theme applies without raising")
except Exception as exc:
    R.fail("theme switching raised %r" % (exc,))

# SetupTab._stop_monitoring referenced an attribute that does not exist, so
# closing the window raised on every run, simulation included.
try:
    win.close()
    R.check(True, "closing the window does not raise")
except Exception as exc:
    R.fail("closeEvent raised %r" % (exc,))

R.finish()
