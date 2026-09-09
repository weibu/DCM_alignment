# -*- coding: utf-8 -*-
"""PV fault-path tests against a stubbed EPICS layer. No IOC required.

Covers pre-flight blocking before anything moves, the fault dialog contents,
Check PV, dismiss-keeps-paused, Try Again resuming, and Abort stopping cleanly.

    py -3.9 tests/test_pv_faults.py
"""
import _harness as H

app = H.app
R = H.Report("DCM Alignment Console - PV fault suite")

H.silence_dialogs(question=H.QMessageBox.StandardButton.No)

# ── stub the EPICS layer so the fault paths run without hardware ────────────
app.EPICS_AVAILABLE = True
try:
    import epics
    epics.ca.use_initial_context = lambda *a, **k: None
except ImportError:
    pass

STATE = {"probe_ok": False, "get_ok": True, "puts": [], "described": []}

app.probe_pv = lambda pv, timeout=2.0, try_rbv=False: (
    (True, "ok") if STATE["probe_ok"] else (False, "timeout"))
app.describe_pv = lambda pv, timeout=2.0: (
    STATE["described"].append(pv) or "stub diagnostic for %s: NOT CONNECTED" % pv)


def fake_get(self, pv, as_string=False, timeout=3.0):
    if self.simulate:
        return self._sim_vals.get(pv, 0.0)
    if not STATE["get_ok"]:
        return None
    return 1.0 if pv.endswith(".DMOV") else 0.5


def fake_put(self, pv, value, wait=True, timeout=30.0):
    if self.simulate:
        self._sim_vals[pv] = value
        return True, ""
    STATE["puts"].append((pv, value))
    return True, ""


app.EpicsInterface.get = fake_get
app.EpicsInterface.put = fake_put

qapp = H.qapp()
win = app.MainWindow()
win.show()
tab = win.alignment_tab
win.setup_tab.sim_check.setChecked(False)   # hardware mode, but stubbed
win.energy_tab.table.selectRow(0)
tab.skip_mirror_chk.setChecked(True)
tab.confirm_chk.setChecked(False)
# Keep the stubbed run short so a hang is obvious rather than just slow.
for key, val in [("pitch_steps", 7), ("roll_steps", 7), ("dcm_piezo_steps", 5),
                 ("mir_piezo_steps", 5), ("smart_max_extend_steps", 2),
                 ("smart_fine_scan_iter", 1), ("settle_time", 0.0),
                 ("piezo_settle_time", 0.0)]:
    win.setup_tab._scan_fields[key].setValue(val)

# ═══ 1. Pre-flight blocks the run before anything moves ════════════════════
STATE["probe_ok"] = False
STATE["puts"] = []
win._start_alignment()

if not R.check(H.pump(lambda: tab._fault_dlg is not None),
               "a pre-flight failure opens the fault dialog"):
    R.finish()

R.check(tab._faulted, "the tab records the faulted state")
R.check(STATE["puts"] == [],
        "nothing was written to any PV before the pre-flight fault (%d writes)"
        % len(STATE["puts"]))
R.check(tab.fault_banner.isVisible(), "the paused banner is shown")
R.check("PAUSED" in tab.fault_tag.text(), "the banner reads PAUSED")
R.check(len(tab._fault_rows) > 1,
        "every failing PV is listed, not just the first (%d rows)" % len(tab._fault_rows))

# Check PV must diagnose without resuming.
dlg = tab._fault_dlg
dlg._on_check()
H.pump(lambda: "NOT CONNECTED" in dlg._diag.toPlainText())
R.check(bool(STATE["described"]), "Check PV probes the selected PV")
R.check("NOT CONNECTED" in dlg._diag.toPlainText(), "the Check PV result is displayed")
R.check(dlg.retry_btn.isEnabled() and dlg.abort_btn.isEnabled(),
        "Check PV leaves the run paused, with Try Again and Abort still offered")

# Dismissing the dialog must not resume the sequence.
dlg.reject()
H.pump(lambda: tab._fault_dlg is None, 2000)
R.check(tab._fault_dlg is None, "dismissing the dialog closes it")
R.check(tab._worker is not None and tab._worker._paused,
        "the worker stays paused after the dialog is dismissed")
R.check(tab._running, "the run is still active, paused rather than finished")
R.check(tab.fault_btn.isVisible(), "a Review fault button is offered to reopen it")

tab._open_fault_dialog()
R.check(tab._fault_dlg is not None, "Review fault reopens the dialog")

# Try Again with the PVs healthy must resume and finish.
STATE["probe_ok"] = True
done = {}
tab.alignment_done.connect(lambda ok: done.setdefault("ok", ok))
tab._fault_dlg._on_retry()
R.check(H.pump(lambda: "ok" in done, 120000) and done.get("ok") is True,
        "Try Again resumes and the sequence completes once the PVs answer")
R.check(len(STATE["puts"]) > 0, "motors were driven only after the fault cleared")

# ═══ 2. Abort at a mid-sequence read fault ═════════════════════════════════
STATE["probe_ok"] = True    # pre-flight passes
STATE["get_ok"] = False     # every later read returns None
STATE["puts"] = []
done2 = {}
tab.alignment_done.connect(lambda ok: done2.setdefault("ok", ok))
win._start_alignment()

if R.check(H.pump(lambda: tab._fault_dlg is not None),
           "a mid-sequence None read raises a fault"):
    pv, context, reason, _when = tab._fault_rows[-1]
    R.check("None" in reason or "disconnected" in reason,
            "the fault names the disconnect: %r" % (reason,))
    R.check(bool(context), "the fault records where it broke: %r" % (context,))
    tab._fault_dlg._on_abort()
    R.check(H.pump(lambda: "ok" in done2, 60000) and done2.get("ok") is False,
            "Abort stops the sequence")
    R.check(not tab._running, "the run is no longer active after abort")
    R.check(not tab.fault_banner.isVisible(), "the banner clears after abort")
    R.check(any(i["tag"].text() == "Error" for i in tab._step_row_info.values()),
            "the interrupted step is marked Error rather than left Running")

R.finish()
