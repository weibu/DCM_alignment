# -*- coding: utf-8 -*-
"""The operator's real dcm_config.json must survive the settings-tab split.

cfg["pvs"] and cfg["scan"] are single flat dicts assembled from three panels
now. If a key lost its home in the split, it would silently vanish on the first
save. This loads the real file (a copy of it), saves it back and diffs.

    py -3.9 tests/test_config_roundtrip.py
"""
import io
import json
import os
import shutil

import _harness as H

app = H.app
R = H.Report("DCM Alignment Console - config round trip")

REAL = os.path.join(H.REPO, "dcm_config.json")
WORK = os.path.join(H.TMPDIR, "roundtrip.json")

if not os.path.exists(REAL):
    R.fail("no dcm_config.json to round-trip against")
    R.finish()

shutil.copyfile(REAL, WORK)          # never write to the operator's own file
app.AUTO_CONFIG_PATH = WORK

H.silence_dialogs()
qapp = H.qapp()

original = json.load(io.open(WORK, encoding="utf-8"))
win = app.MainWindow()               # constructor calls _auto_load_config
win._save_config()                   # writes back through the merged accessors
after = json.load(io.open(WORK, encoding="utf-8"))

missing_keys = [k for k in original if k not in after]
R.check(not missing_keys, "every top-level key survives%s"
        % (" (lost %s)" % missing_keys if missing_keys else ""))

for section in ("pvs", "scan", "mirror_scan"):
    if section not in original:
        continue
    lost = [k for k in original[section] if k not in after.get(section, {})]
    changed = [(k, v, after[section][k]) for k, v in original[section].items()
               if k in after.get(section, {}) and after[section][k] != v]
    R.check(not lost, "no %s key is lost in the split%s"
            % (section, " (lost %s)" % lost if lost else ""))
    R.check(not changed, "no %s value is altered%s"
            % (section, " (%s)" % changed[:3] if changed else ""))

for section in ("energy_table", "mirror_stages", "record_data"):
    if section in original:
        R.check(after.get(section) == original[section],
                "%s is preserved verbatim" % section)

# The three panels between them must account for every PV and scan key, or a
# setting would exist in the config but be invisible and unreachable in the UI.
owned_pv = set()
owned_scan = set()
for panel in win._pv_panels:
    owned_pv |= set(panel.get_pvs())
    owned_scan |= set(panel.get_scan_params())
R.check(set(app.DEFAULT_PVS) <= owned_pv,
        "every DEFAULT_PVS key is shown on some panel (orphans: %s)"
        % sorted(set(app.DEFAULT_PVS) - owned_pv))
R.check(set(app.DEFAULT_SCAN) <= owned_scan,
        "every DEFAULT_SCAN key is shown on some panel (orphans: %s)"
        % sorted(set(app.DEFAULT_SCAN) - owned_scan))
R.check(not (set(app.PV_TABS["global"]) & set(app.PV_TABS["dcm"])
             | set(app.PV_TABS["dcm"]) & set(app.PV_TABS["mirror"])
             | set(app.PV_TABS["global"]) & set(app.PV_TABS["mirror"])),
        "no PV key is claimed by two panels")

R.finish()
