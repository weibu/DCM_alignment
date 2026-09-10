# Tests

Three headless suites. All run offscreen with no display, no EPICS connection and
no IOC, and none of them writes to the real `dcm_config.json` — the harness redirects
the app's auto-save to a temporary file.

```bash
py -3.9 tests/test_simulation.py
py -3.9 tests/test_pv_faults.py
py -3.9 tests/test_config_roundtrip.py
```

Each exits non-zero and prints a `FAILURES:` list if anything regresses.
`test_simulation.py` takes a few minutes, `test_pv_faults.py` about one, and
`test_config_roundtrip.py` a few seconds.

| File | Covers |
|------|--------|
| `test_simulation.py` | The full 5-step sequence in every skip-mirror / confirm-each-step combination; per-step and chapter-only runs, including that disabling 4A leaves 4C working from the live slit centre; the eight scan figures, their overlays, distinct trace colours and monotonic x; that a blank stage PV cannot hang the checked-read retry loop; that all six computed scan results reach the lookup table; that the JJC stays open at 4 and closes only just before feedback, in both branches; theme switching; clean window close. |
| `test_config_roundtrip.py` | Loads a copy of the real `dcm_config.json`, saves it back through the three settings panels and diffs: no key lost, no value altered, every `DEFAULT_PVS`/`DEFAULT_SCAN` key owned by exactly one panel. Guards the tab split. |
| `test_pv_faults.py` | Stubs the EPICS transport so the fault paths run without hardware: pre-flight blocking the run with zero writes, the fault dialog contents, Check PV diagnosing without resuming, dismissing the dialog leaving the run paused, Try Again resuming once the PVs answer, and Abort stopping cleanly with the interrupted step marked Error. |

`_harness.py` holds the shared setup: offscreen Qt, the import path, the
throwaway config, silenced modal dialogs, an event-loop `pump()` helper and the
pass/fail reporter.

Most of these assertions are regression tests for bugs that were live in the
app — see the commit history for what each one caught.
