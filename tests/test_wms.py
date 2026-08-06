"""Windows MIDI Services 备选内核测试：检测层 + 回退逻辑"""

import unittest

from gms.bus import EventBus
from gms.midi.backends import MidiPortManager
from gms.midi.wms_backend import (
    WindowsMidiServicesBackend,
    _midisrv_running,
    _midi2_runtime_registered,
    PROJECTION_MODULES,
)


class TestWmsDetection(unittest.TestCase):
    def test_midisrv_status(self):
        # 本机 Win11 24H2 应返回 True；若环境异常返回 False 也应兼容
        result = _midisrv_running()
        self.assertIsInstance(result, bool)

    def test_projection_module_names_defined(self):
        self.assertTrue(PROJECTION_MODULES)
        self.assertIn("winrt_microsoft_windows_devices_midi2", PROJECTION_MODULES)

    def test_backend_unavailable_with_reason(self):
        """本机（无 MIDI2 运行时/投影）应给出明确不可用原因"""
        backend = WindowsMidiServicesBackend()
        if backend.is_available():
            self.skipTest("本机已具备 MIDI2 投影")
        self.assertTrue(backend.error)
        self.assertIn("MIDI2", backend.error)


class TestBackendSelection(unittest.TestCase):
    def test_default_backend_is_tevirtualmidi(self):
        bus = EventBus()
        pm = MidiPortManager(bus)
        self.assertEqual(pm.backend.name, "tevirtualmidi")
        self.assertTrue(pm.backend.is_available())

    def test_backends_reported_in_state(self):
        bus = EventBus()
        pm = MidiPortManager(bus)
        st = pm.state()
        self.assertIn("backends", st)
        self.assertIn("tevirtualmidi", st["backends"])
        self.assertIn("windows_midi_services", st["backends"])
        self.assertEqual(st["virtual_backend"], "tevirtualmidi")

    def test_wms_unavailable_falls_back(self):
        """选择 WMS 但不可用时自动回退 teVirtualMIDI 并成功创建端口"""
        bus = EventBus()
        logs = []
        bus.subscribe("log", lambda message: logs.append(message))
        pm = MidiPortManager(bus)
        wms = pm.backends["windows_midi_services"]
        if wms.is_available():
            self.skipTest("本机已具备 MIDI2，不触发回退路径")
        pm.start("GMS WMS Test", backend_name="windows_midi_services")
        try:
            self.assertEqual(pm.backend.name, "tevirtualmidi")
            self.assertTrue(pm.virtual_handle, "回退后应成功创建虚拟端口")
            self.assertTrue(any("回退" in m for m in logs))
        finally:
            pm.stop()

    def test_explicit_tevirtualmidi(self):
        bus = EventBus()
        pm = MidiPortManager(bus)
        pm.start("GMS TEV Test", backend_name="tevirtualmidi")
        try:
            self.assertTrue(pm.virtual_handle)
            self.assertEqual(pm.backend.name, "tevirtualmidi")
        finally:
            pm.stop()


if __name__ == "__main__":
    unittest.main()