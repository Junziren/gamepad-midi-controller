"""跨平台边界测试：Windows 专属后端在 macOS 分支必须安全降级。"""

import unittest
from unittest import mock

from gms.input import global_hooks
from gms import main
from gms.midi import backends
from gms.midi import wms_backend


class TestPlatformFallbacks(unittest.TestCase):
    def test_cursor_uses_pynput_on_macos(self):
        with mock.patch.object(global_hooks.sys, "platform", "darwin"), \
                mock.patch.object(global_hooks.mouse, "Controller") as controller:
            controller.return_value.position = (123.4, 56.6)
            self.assertEqual(global_hooks.get_cursor_pos(), (123, 57))

    def test_tevirtualmidi_is_not_loaded_on_macos(self):
        with mock.patch.object(backends.sys, "platform", "darwin"):
            backend = backends.TeVirtualMidiBackend()
        self.assertFalse(backend.is_available())
        self.assertIn("仅支持 Windows", backend.error)

    def test_windows_midi_services_is_not_loaded_on_macos(self):
        with mock.patch.object(wms_backend.sys, "platform", "darwin"):
            backend = wms_backend.WindowsMidiServicesBackend()
        self.assertFalse(backend.is_available())
        self.assertIn("仅支持 Windows", backend.error)

    def test_single_instance_lock_is_noop_on_macos(self):
        with mock.patch.object(main.sys, "platform", "darwin"):
            self.assertFalse(main._already_running())


if __name__ == "__main__":
    unittest.main()
