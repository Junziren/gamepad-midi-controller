import ctypes
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

from gms.input.gamepad_devices import (
    HidJoystick, SdlEventJoystick, XInputJoystick, _XInputState, open_gamepad,
)


class FakeSdlJoystick:
    def __init__(self):
        self.axes = [0.0] * 6
        self.buttons = [False] * 11
        self.hat = (0, 0)

    def get_instance_id(self):
        return 7

    def get_numaxes(self):
        return len(self.axes)

    def get_axis(self, index):
        return self.axes[index]

    def get_numbuttons(self):
        return len(self.buttons)

    def get_button(self, index):
        return self.buttons[index]

    def get_numhats(self):
        return 1

    def get_hat(self, index):
        return self.hat

    def get_name(self):
        return "Fake"

    def get_guid(self):
        return "03000000000000000000000000000000"

    def quit(self):
        return None


class TestSdlEventState(unittest.TestCase):
    def setUp(self):
        self.raw = FakeSdlJoystick()
        self.joystick = SdlEventJoystick(self.raw)
        # 关闭事件优先窗口，让 poll_refresh 立即生效
        self.joystick._event_win_seconds = 0.0

    def test_button_event_wins_over_stale_polling_state(self):
        event = SimpleNamespace(type=pygame.JOYBUTTONDOWN, instance_id=7, button=0)
        self.assertTrue(self.joystick.process_event(event))
        self.assertTrue(self.joystick.get_button(0))
        self.assertFalse(self.raw.get_button(0))
        self.assertTrue(self.joystick.consume_changed())
        self.assertFalse(self.joystick.consume_changed())

    def test_axis_and_hat_events_update_cache(self):
        axis = SimpleNamespace(type=pygame.JOYAXISMOTION, instance_id=7,
                               axis=2, value=-0.75)
        hat = SimpleNamespace(type=pygame.JOYHATMOTION, instance_id=7,
                              value=(1, 0))
        self.joystick.process_event(axis)
        self.joystick.process_event(hat)
        self.assertEqual(self.joystick.get_axis(2), -0.75)
        self.assertEqual(self.joystick.get_hat(0), (1, 0))

    def test_other_device_event_is_ignored(self):
        event = SimpleNamespace(type=pygame.JOYBUTTONDOWN, instance_id=8, button=0)
        self.assertFalse(self.joystick.process_event(event))
        self.assertFalse(self.joystick.get_button(0))

    def test_poll_refresh_falls_back_to_sdl_state(self):
        """事件丢失时，直读 SDL 状态兜底更新缓存。"""
        self.raw.axes[0] = 0.9
        self.raw.buttons[3] = True
        self.raw.hat = (-1, 0)
        self.assertTrue(self.joystick.poll_refresh())
        self.assertAlmostEqual(self.joystick.get_axis(0), 0.9)
        self.assertTrue(self.joystick.get_button(3))
        self.assertEqual(self.joystick.get_hat(0), (-1, 0))
        self.assertTrue(self.joystick.consume_changed())

    def test_event_wins_window_keeps_event_value(self):
        """事件优先窗口内，直读旧值不得覆盖事件新值。"""
        self.joystick._event_win_seconds = 1.0
        event = SimpleNamespace(type=pygame.JOYBUTTONDOWN, instance_id=7, button=0)
        self.joystick.process_event(event)
        self.raw.buttons[0] = False  # SDL 直读仍是旧值
        self.assertFalse(self.joystick.poll_refresh())
        self.assertTrue(self.joystick.get_button(0))

    def test_event_value_survives_stale_direct_read_after_window(self):
        """事件已接管的按钮，窗口过后也不能被旧直读值清掉。"""
        self.joystick._event_win_seconds = 0.0
        event = SimpleNamespace(type=pygame.JOYBUTTONDOWN, instance_id=7, button=0)
        self.joystick.process_event(event)
        self.raw.buttons[0] = False
        self.assertFalse(self.joystick.poll_refresh())
        self.assertTrue(self.joystick.get_button(0))

    def test_open_gamepad_defaults_to_sdl_primary(self):
        adapter = open_gamepad(self.raw, 0x1234, 0x5678)
        self.assertNotIsInstance(adapter, XInputJoystick)
        self.assertIsInstance(adapter, SdlEventJoystick)
        adapter.quit()


class TestXInputDecode(unittest.TestCase):
    def test_decode_all_axes_buttons_triggers_and_hat(self):
        state = SimpleNamespace(Gamepad=SimpleNamespace(
            wButtons=0x1000 | 0x0100 | 0x0040 | 0x0001,
            bLeftTrigger=255,
            bRightTrigger=128,
            sThumbLX=32767,
            sThumbLY=-32768,
            sThumbRX=-32768,
            sThumbRY=0,
        ))
        axes, buttons, hat = XInputJoystick._decode_state(state)
        self.assertAlmostEqual(axes[0], 1.0)
        self.assertAlmostEqual(axes[1], 1.0)
        self.assertAlmostEqual(axes[2], -1.0)
        self.assertAlmostEqual(axes[3], 0.0)
        self.assertEqual(axes[4], 1.0)
        self.assertAlmostEqual(axes[5], 128 / 255)
        self.assertTrue(buttons[0])
        self.assertTrue(buttons[4])
        self.assertTrue(buttons[8])
        self.assertEqual(hat, (0, 1))

    def test_headless_xinput_adapter_has_safe_metadata(self):
        state = _XInputState()
        state.dwPacketNumber = 7

        def get_state(slot, pointer):
            target = ctypes.cast(pointer, ctypes.POINTER(_XInputState)).contents
            target.dwPacketNumber = 7
            return 0

        joystick = XInputJoystick(None, None, get_state, 0, state)
        self.assertEqual(joystick.get_name(), "XInput Controller 1")
        self.assertEqual(joystick.get_guid(), "")
        self.assertTrue(joystick.is_connected())
        self.assertEqual(joystick.get_instance_id(), 0x58490000)

    def test_open_gamepad_prefers_xinput_for_xbox_source(self):
        native = object()
        with mock.patch.object(XInputJoystick, "try_open", return_value=native):
            adapter = open_gamepad(self._source(), 0x045E, 0x02E0)
        self.assertIs(adapter, native)

    def test_xbox_falls_back_to_hid_before_sdl(self):
        fake_hid = mock.Mock()
        fake_hid.HidDeviceFilter.return_value.get_devices.return_value = []
        with mock.patch.object(XInputJoystick, "try_open", return_value=None), \
                mock.patch("gms.input.gamepad_devices.hid", fake_hid):
            adapter = open_gamepad(self._source(), 0x045E, 0x02E0)
        fake_hid.HidDeviceFilter.assert_called_once_with(
            vendor_id=0x045E, product_id=0x02E0)
        self.assertIsInstance(adapter, SdlEventJoystick)
        adapter.quit()

    @staticmethod
    def _source():
        return FakeSdlJoystick()


class FakeValueCaps:
    def __init__(self, low=0, high=-1, bit_size=16):
        self.logical_min = low
        self.logical_max = high
        self.bit_size = bit_size


class TestHidSemanticDecode(unittest.TestCase):
    def setUp(self):
        self.joystick = HidJoystick.__new__(HidJoystick)
        self.joystick._caps = {
            (1, 0x30): FakeValueCaps(),
            (1, 0x31): FakeValueCaps(),
            (1, 0x33): FakeValueCaps(),
            (1, 0x34): FakeValueCaps(),
            (1, 0x32): FakeValueCaps(),
            (1, 0x39): FakeValueCaps(1, 8, 4),
        }
        self.joystick._button_usages = list(range(1, 11))
        self.joystick._bitfield_usages = []

    def test_buttons_usage_zero_based(self):
        """按钮 usage 从 0 开始时同样按升序映射，不漏 A 键。"""
        self.joystick._button_usages = list(range(0, 10))
        usages = {(9, 0): 1, (9, 3): 1}
        buttons = self.joystick._decode_buttons(usages)
        self.assertEqual(len(buttons), 10)
        self.assertTrue(buttons[0])
        self.assertTrue(buttons[3])
        self.assertFalse(buttons[1])

    def test_buttons_bitfield_expansion(self):
        """按钮位域：usage 1 的 16bit value 按位展开。"""
        self.joystick._button_usages = list(range(1, 17))
        self.joystick._bitfield_usages = [(1, 16)]
        usages = {(9, 1): 0b101}
        buttons = self.joystick._decode_buttons(usages)
        self.assertTrue(buttons[0])
        self.assertFalse(buttons[1])
        self.assertTrue(buttons[2])

    def test_unsigned_hid_range_normalizes_to_center(self):
        self.assertAlmostEqual(
            self.joystick._normalized({(1, 0x30): 32768}, 1, 0x30),
            0.0,
            places=3,
        )

    def test_combined_trigger_axis_splits_left_and_right(self):
        self.joystick._caps[(1, 0x32)] = FakeValueCaps(bit_size=8)
        common = {
            (1, 0x30): 32768, (1, 0x31): 32768,
            (1, 0x33): 32768, (1, 0x34): 32768,
        }
        left = self.joystick._decode_axes({**common, (1, 0x32): 65535})
        right = self.joystick._decode_axes({**common, (1, 0x32): 0})
        self.assertGreater(left[4], 0.99)
        self.assertEqual(left[5], -1.0)
        self.assertEqual(right[4], -1.0)
        self.assertGreater(right[5], 0.99)

    def test_one_ble_layout_z_is_right_stick(self):
        """One/BLE 布局（0x32 位宽 16）：Z=右摇杆X、Rx=右摇杆Y、Ry=左扳机。"""
        common = {
            (1, 0x30): 32768, (1, 0x31): 32768,
            (1, 0x33): 32768, (1, 0x34): 0,      # 左扳机静止=逻辑最小值
        }
        axes = self.joystick._decode_axes({**common, (1, 0x32): 65535})
        self.assertGreater(axes[2], 0.99)          # 右摇杆 X = Z
        self.assertAlmostEqual(axes[3], 0.0, places=3)  # 右摇杆 Y = Rx 居中
        self.assertEqual(axes[4], -1.0)            # 左扳机 = Ry 静止
        self.assertEqual(axes[5], -1.0)            # 无 0x35 且无额外值项
        axes = self.joystick._decode_axes({**common, (1, 0x32): 0})
        self.assertLess(axes[2], -0.99)

    def test_one_ble_layout_extra_trigger_from_other_page(self):
        """BLE 变体：右扳机声明在其它 usage page 时取自第一个未用值项。"""
        self.joystick._caps[(0xFF00, 0x05)] = FakeValueCaps(bit_size=8)
        axes = self.joystick._decode_axes({
            (1, 0x30): 32768, (1, 0x31): 32768,
            (1, 0x32): 32768, (1, 0x33): 32768, (1, 0x34): 0,
            (0xFF00, 0x05): 255,
        })
        self.assertGreater(axes[5], 0.99)
        self.assertEqual(axes[4], -1.0)

    def test_hat_null_and_directions(self):
        self.assertEqual(self.joystick._decode_hat(0), (0, 0))
        self.assertEqual(self.joystick._decode_hat(1), (0, 1))
        self.assertEqual(self.joystick._decode_hat(3), (1, 0))
        self.assertEqual(self.joystick._decode_hat(5), (0, -1))


class FakeUsageCap:
    def __init__(self, page, usage, bits=16, is_value=True, is_range=False,
                 logical=(0, 65535), report_id=0):
        self.usage_page = page
        self.is_value = is_value
        self.is_button = not is_value
        self.is_range = is_range
        self.usage = usage
        self.usage_min = usage
        self.usage_max = usage
        self.bit_size = bits
        self.report_count = 1
        self.logical_min, self.logical_max = logical
        self.report_id = report_id


class TestBuildReports(unittest.TestCase):
    def _make(self, caps):
        from pywinusb.hid.core import HidP_Input
        device = SimpleNamespace(
            usages_storage={HidP_Input: caps},
            find_input_reports=lambda: [],
            set_raw_data_handler=lambda h: None,
        )
        js = HidJoystick.__new__(HidJoystick)
        js._device = device
        js._caps = {}
        js._button_usages = []
        js._bitfield_usages = []
        js._buttons = []
        js._reports = {}
        js._build_reports()
        return js

    def test_range_single_usage_value_cap_is_indexed(self):
        """以 range 形式声明的单值项（usage_min==usage_max）也收录进 _caps，
        BLE 变体右扳机（其它 usage page）不会从 _extra_trigger_value 漏掉。"""
        caps = [
            FakeUsageCap(1, 0x30), FakeUsageCap(1, 0x31), FakeUsageCap(1, 0x32),
            FakeUsageCap(1, 0x33), FakeUsageCap(1, 0x34),
            FakeUsageCap(1, 0x39, bits=4, logical=(1, 8)),
            FakeUsageCap(0x0C, 0x29, bits=8, logical=(0, 255), is_range=True),
        ]
        js = self._make(caps)
        self.assertIn((0x0C, 0x29), js._caps)
        axes = js._decode_axes({
            (1, 0x30): 32768, (1, 0x31): 32768, (1, 0x32): 32768,
            (1, 0x33): 32768, (1, 0x34): 0, (0x0C, 0x29): 255,
        })
        self.assertGreater(axes[5], 0.99)
        self.assertEqual(axes[4], -1.0)

    def test_button_bitfield_range_form_does_not_crash(self):
        """按钮位域以 range 形式声明时不崩溃，并按 usage_min 展开。"""
        caps = [FakeUsageCap(9, 1, bits=16, is_value=True)]
        js = self._make(caps)
        self.assertEqual(js._bitfield_usages, [(1, 16)])
        self.assertEqual(js._button_usages, list(range(1, 17)))

    def test_real_one_s_ble_layout_end_to_end(self):
        """复刻实机 Xbox One S BLE（0x02E0）描述符：
        页1 值项 0x30-0x34（16 位）+ hat 0x39，无 0x35，
        按钮为 usage 1 的 16 位位域。"""
        caps = [
            FakeUsageCap(1, 0x30), FakeUsageCap(1, 0x31), FakeUsageCap(1, 0x32),
            FakeUsageCap(1, 0x33), FakeUsageCap(1, 0x34),
            FakeUsageCap(1, 0x39, bits=4, logical=(1, 8)),
            FakeUsageCap(9, 1, bits=16, is_value=True),
        ]
        js = self._make(caps)
        self.assertEqual(js._button_usages, list(range(1, 17)))
        self.assertEqual(js._bitfield_usages, [(1, 16)])
        # 静止（左扳机在逻辑最小值），右摇杆全偏右
        usages = {
            (1, 0x30): 32768, (1, 0x31): 32768, (1, 0x32): 65535,
            (1, 0x33): 32768, (1, 0x34): 0, (9, 1): 0b1000000000,
        }
        axes = js._decode_axes(usages)
        self.assertAlmostEqual(axes[0], 0.0, places=3)   # LX 居中
        self.assertGreater(axes[2], 0.99)                # RX = Z
        self.assertAlmostEqual(axes[3], 0.0, places=3)   # RY = Rx 居中
        self.assertEqual(axes[4], -1.0)                  # LT 静止
        self.assertEqual(axes[5], -1.0)                  # 无 RT 声明
        buttons = js._decode_buttons(usages)
        self.assertTrue(buttons[9])                      # 位域第 10 位 = L3

    def test_real_one_s_ble_extra_trigger_first_unused_item(self):
        """实机右扳机声明在其它页时，取第一个未用值项（与 SDL a5 枚举一致）。"""
        caps = [
            FakeUsageCap(1, 0x30), FakeUsageCap(1, 0x31), FakeUsageCap(1, 0x32),
            FakeUsageCap(1, 0x33), FakeUsageCap(1, 0x34),
            FakeUsageCap(1, 0x39, bits=4, logical=(1, 8)),
            FakeUsageCap(0xFF00, 0x05, bits=8, logical=(0, 255)),
        ]
        js = self._make(caps)
        axes = js._decode_axes({
            (1, 0x30): 32768, (1, 0x31): 32768, (1, 0x32): 32768,
            (1, 0x33): 32768, (1, 0x34): 0, (0xFF00, 0x05): 255,
        })
        self.assertGreater(axes[5], 0.99)


class FakeReport:
    def __init__(self, values=None, report_id=0):
        self.report_id = report_id
        self.set_called = False
        self._values = values or {}

    def set_raw_data(self, data):
        self.set_called = True

    def items(self):
        return list(self._values.items())


class FakeReportItem:
    def __init__(self, page, usage, value):
        self.page_id = page
        self.usage_id = usage
        self._value = value

    def get_value(self):
        return self._value


class TestHidSdlFallback(unittest.TestCase):
    def _make(self):
        raw = FakeSdlJoystick()
        sdl = SdlEventJoystick(raw)
        joystick = HidJoystick.__new__(HidJoystick)
        joystick._lock = threading.Lock()
        joystick._sdl = sdl
        joystick._fresh_seconds = 2.0
        joystick._axes = [0.0] * 6
        joystick._buttons = [False] * 11
        joystick._hat = (0, 0)
        joystick._changed = False
        joystick._last_update = time.time()
        return joystick, raw, sdl

    def test_sdl_fallback_after_hid_stale(self):
        """HID 超过阈值无数据时，取值回退到 SDL 影子状态。"""
        joystick, raw, sdl = self._make()
        joystick._last_update = time.time() - 10.0
        raw.axes[0] = 0.8
        raw.buttons[3] = True
        self.assertTrue(sdl.poll_refresh())
        self.assertAlmostEqual(joystick.get_axis(0), 0.8)
        self.assertTrue(joystick.get_button(3))
        # HID 新鲜时优先 HID 值
        joystick._last_update = time.time()
        joystick._axes[0] = -0.5
        self.assertAlmostEqual(joystick.get_axis(0), -0.5)
        self.assertFalse(joystick.get_button(3))

    def test_consume_changed_merges_sdl_shadow(self):
        """SDL 影子有变化时 consume_changed 也返回 True。"""
        joystick, raw, sdl = self._make()
        raw.axes[0] = 0.5
        self.assertTrue(sdl.poll_refresh())
        self.assertTrue(joystick.consume_changed())
        self.assertFalse(joystick.consume_changed())

    def test_handle_raw_single_report_matches_without_id(self):
        """无报告 ID 设备：数据首字节非 0 也必须匹配唯一报告。"""
        joystick = HidJoystick.__new__(HidJoystick)
        report = FakeReport()
        joystick._reports = {0: report}
        joystick._caps = {}
        joystick._button_usages = []
        joystick._bitfield_usages = []
        joystick._axes = [0.0] * 6
        joystick._buttons = []
        joystick._hat = (0, 0)
        joystick._changed = False
        joystick._lock = threading.Lock()
        joystick._last_update = 0.0
        joystick._handle_raw(bytes([0x81, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
        self.assertTrue(report.set_called)
        self.assertGreater(joystick._last_update, 0.0)

    def test_multiple_reports_merge_usage_state(self):
        """分报告设备：后到的按钮/轴报告不能清空另一份报告的状态。"""
        joystick = HidJoystick.__new__(HidJoystick)
        joystick._reports = {
            1: FakeReport({
                1: FakeReportItem(1, 0x30, 65535),
                2: FakeReportItem(9, 1, 1),
            }, report_id=1),
            2: FakeReport({
                1: FakeReportItem(1, 0x31, 0),
            }, report_id=2),
        }
        joystick._caps = {
            (1, 0x30): FakeValueCaps(),
            (1, 0x31): FakeValueCaps(),
        }
        joystick._usage_values = {}
        joystick._button_usages = [1]
        joystick._bitfield_usages = []
        joystick._axes = [0.0] * 6
        joystick._buttons = [False]
        joystick._hat = (0, 0)
        joystick._changed = False
        joystick._lock = threading.Lock()
        joystick._last_update = 0.0
        joystick._last_hid_report = 0.0
        joystick._last_hid_change = 0.0
        joystick._last_sdl_change = 0.0

        joystick._handle_raw(bytes([1]))
        self.assertGreater(joystick._axes[0], 0.99)
        self.assertTrue(joystick._buttons[0])

        joystick._handle_raw(bytes([2]))
        self.assertGreater(joystick._axes[0], 0.99)
        self.assertLess(joystick._axes[1], -0.99)
        self.assertTrue(joystick._buttons[0])


class TestSnapshotSourceSelection(unittest.TestCase):
    def _make(self):
        raw = FakeSdlJoystick()
        sdl = SdlEventJoystick(raw)
        joystick = HidJoystick.__new__(HidJoystick)
        joystick._lock = threading.Lock()
        joystick._sdl = sdl
        joystick._fresh_seconds = 2.0
        joystick._axes = [0.0] * 6
        joystick._buttons = [False] * 11
        joystick._hat = (0, 0)
        joystick._changed = False
        joystick._last_update = 0.0
        joystick._last_hid_report = 0.0
        joystick._last_hid_change = 0.0
        joystick._last_sdl_change = 0.0
        return joystick, raw, sdl

    def test_prefers_hid_when_report_recent(self):
        joystick, raw, sdl = self._make()
        joystick._last_hid_report = time.time()
        joystick._axes[0] = -0.5
        joystick._buttons[3] = True
        axes, buttons, hat, nax, nbtn, source = joystick.snapshot()
        self.assertEqual(source, "hid")
        self.assertEqual(axes[0], -0.5)
        self.assertTrue(buttons[3])

    def test_prefers_sdl_after_hid_quiet_and_sdl_live(self):
        joystick, raw, sdl = self._make()
        joystick._last_hid_report = time.time() - 10.0
        raw.axes[0] = 0.8
        raw.buttons[3] = True
        self.assertTrue(joystick.poll_refresh())   # SDL 影子有变化
        axes, buttons, hat, nax, nbtn, source = joystick.snapshot()
        self.assertEqual(source, "sdl")
        self.assertAlmostEqual(axes[0], 0.8)
        self.assertTrue(buttons[3])
        # HID 恢复报告后立即切回 HID
        joystick._last_hid_report = time.time()
        joystick._axes[0] = -0.2
        axes, buttons, hat, nax, nbtn, source = joystick.snapshot()
        self.assertEqual(source, "hid")
        self.assertAlmostEqual(axes[0], -0.2)

    def test_snapshot_is_single_source_no_mixing(self):
        """同一帧不得混读：HID 新鲜时 SDL 的差异值不得混入。"""
        joystick, raw, sdl = self._make()
        joystick._last_hid_report = time.time()
        joystick._axes[0] = 0.3
        joystick._buttons[5] = True
        raw.axes[0] = -0.9
        raw.buttons[5] = False
        joystick.poll_refresh()
        axes, buttons, hat, nax, nbtn, source = joystick.snapshot()
        self.assertEqual(source, "hid")
        self.assertAlmostEqual(axes[0], 0.3)
        self.assertTrue(buttons[5])

    def test_get_numbuttons_matches_hid_usages(self):
        joystick, raw, sdl = self._make()
        joystick._buttons = [False] * 16
        self.assertEqual(joystick.get_numbuttons(), 16)


if __name__ == "__main__":
    unittest.main()
