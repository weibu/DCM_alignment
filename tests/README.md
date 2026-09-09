# Tests

Two headless suites. Both run offscreen with no display, no EPICS connection and
no IOC, and neither touches the real `dcm_config.json` — the harness redirects
the app's auto-save to a temporary file.

```bash
py -3.9 tests/test_simulation.py
py -3.9 tests/test_pv_faults.py
```

Each exits non-zero and prints a `FAILURES:` list if anything regresses.
`test_simulation.py` takes a couple of minutes; `test_pv_faults.py` about one.

| File | Covers |
|------|--------|
| `test_simulation.py` | The full 5-step sequence in every skip-mirror / confirm-each-step combination; that a blank stage PV cannot hang the checked-read retry loop; that all six computed scan results reach the lookup table; that the JJC stays open at 4 and closes only just before feedback, in both branches; theme switching; clean window close. |
| `test_pv_faults.py` | Stubs the EPICS transport so the fault paths run without hardware: pre-flight blocking the run with zero writes, the fault dialog contents, Check PV diagnosing without resuming, dismissing the dialog leaving the run paused, Try Again resuming once the PVs answer, and Abort stopping cleanly with the interrupted step marked Error. |

`_harness.py` holds the shared setup: offscreen Qt, the import path, the
throwaway config, silenced modal dialogs, an event-loop `pump()` helper and the
pass/fail reporter.

Most of these assertions are regression tests for bugs that were live in the
app — see the commit history for what each one caught.
