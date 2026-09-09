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


def run_sequence(skip_mirror, confirm):
    """Run one full sequence to completion. Returns the success flag, or None on timeout."""
    win.alignment_tab.skip_mirror_chk.setChecked(skip_mirror)
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
fb_h = win.setup_tab.get_pvs()["feedback_h"]
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
