"""Profile 配置系统测试"""

import json
import tempfile
import unittest
from pathlib import Path

from gms.config import ProfileManager, DEFAULTS, deep_merge


class TestProfileManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pm = ProfileManager(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_profile_created(self):
        self.assertIn("default", self.pm.list_profiles())
        self.assertEqual(self.pm.current_name, "default")

    def test_update_persist(self):
        self.pm.update({"gamepad": {"sensitivity": 5.0}})
        pm2 = ProfileManager(Path(self.tmp.name))
        self.assertEqual(pm2.current()["gamepad"]["sensitivity"], 5.0)

    def test_new_and_switch(self):
        self.assertTrue(self.pm.new_profile("live"))
        self.assertEqual(self.pm.current_name, "live")
        self.pm.update({"midi": {"channel": 5}})
        self.pm.load_profile("default")
        self.assertEqual(self.pm.current()["midi"]["channel"], 1)

    def test_delete_protects_default(self):
        self.assertFalse(self.pm.delete_profile("default"))

    def test_import_export(self):
        data = {"gamepad": {"sensitivity": 7.0}}
        self.pm.import_profile("custom", data)
        pm2 = ProfileManager(Path(self.tmp.name))
        self.assertEqual(pm2.export_profile("custom")["gamepad"]["sensitivity"], 7.0)
        # 未指定字段用默认值补齐
        self.assertEqual(pm2.export_profile("custom")["midi"]["channel"], 1)

    def test_deep_merge_nested(self):
        out = deep_merge(DEFAULTS, {"gamepad": {"sensitivity": 9.0}})
        self.assertEqual(out["gamepad"]["sensitivity"], 9.0)
        self.assertEqual(out["gamepad"]["deadzone"], 0.15)
        # 新键追加
        out2 = deep_merge(DEFAULTS, {"extra": {"a": 1}})
        self.assertEqual(out2["extra"]["a"], 1)

    def test_migrate_legacy(self):
        import gms.config as cfgmod
        legacy = Path(self.tmp.name) / "legacy.json"
        legacy.write_text(json.dumps({
            "midi_port": "Old Port", "relative_sensitivity": 4.5,
            "stick_deadzone": 0.2,
            "cc_mappings": {"left_stick_x": 20},
            "note_mappings": {"button_a": 36},
        }), encoding="utf-8")
        old = cfgmod.LEGACY_CONFIG
        cfgmod.LEGACY_CONFIG = legacy
        try:
            self.pm.migrate_legacy()
        finally:
            cfgmod.LEGACY_CONFIG = old
        cfg = self.pm.current()
        self.assertEqual(cfg["virtual_midi"]["port_name"], "Old Port")
        self.assertEqual(cfg["gamepad"]["sensitivity"], 4.5)
        self.assertEqual(cfg["gamepad"]["deadzone"], 0.2)
        self.assertEqual(cfg["gamepad"]["cc_mappings"]["left_stick_x"], 20)
        self.assertEqual(cfg["gamepad"]["note_mappings"]["button_a"], 36)
        self.assertEqual(cfg["gamepad"]["note_mappings"]["button_b"], 62)  # 其余保持默认


if __name__ == "__main__":
    unittest.main()