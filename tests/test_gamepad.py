"""手柄引擎测试：坐标映射模式状态机 + 相对模式（使用 fake 手柄/MIDI）"""

import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

from gms.bus import EventBus
from gms.input.gamepad import GamepadEngine
from gms.input.gamepad_devices import SdlEventJoystick
from gms.learn import LearnManager
from gms.core import axis_to_cc_absolute


class FakeJoystick:
    def __init__(self, axes=None, buttons=None, hat=(0, 0), guid=""):
        self._axes = axes or [0.0] * 6
        self._buttons = buttons or [False] * 12
        self._hat = hat
        self._guid = guid
        self._instance_id = 0

    def get_name(self):
        return "Fake Pad"

    def init(self):
        pass

    def get_guid(self):
        return self._guid

    def get_instance_id(self):
        return self._instance_id

    def get_numaxes(self):
        return len(self._axes)

    def get_axis(self, i):
        return self._axes[i]

    def get_numbuttons(self):
        return len(self._buttons)

    def get_button(self, i):
        return self._buttons[i]

    def get_numhats(self):
        return 1

    def get_hat(self, i):
        return self._hat


class FakeMidi:
    """记录所有发送调用"""
    def __init__(self):
        self.calls = []

    def cc_smoothed(self, control, value, channel=None, smoothing=None):
        self.calls.append(("cc", control, value))

    def note_on(self, note, velocity, channel=None):
        self.calls.append(("note_on", note, velocity))

    def note_off(self, note, channel=None):
        self.calls.append(("note_off", note))

    def cc(self, control, value, channel=None):
        self.calls.append(("cc", control, value))

    def pitch_bend(self, value14, channel=None):
        self.calls.append(("pitch", value14))


def make_engine(config_override=None):
    bus = EventBus()
    cfg = {
        "gamepad": {
            "mode": "relative", "sensitivity": 3.0, "deadzone": 0.15,
            "curve": "linear", "curve_exp": 2.0, "invert_y": True,
            "l3_button": 8, "r3_button": 9, "xy_center_deadzone": 0.05,
            "velocity_mode": "fixed", "velocity_fixed": 127,
            "velocity_min": 40, "velocity_max": 127,
            "trigger_mode": "note", "trigger_cc_lt": 11, "trigger_cc_rt": 12,
            "cc_mappings": {"left_stick_x": 1, "left_stick_y": 2,
                            "right_stick_x": 3, "right_stick_y": 4},
            "note_mappings": {"button_a": 60, "button_b": 62, "button_x": 64,
                              "button_y": 65, "dpad_up": 67, "dpad_down": 69,
                              "dpad_left": 71, "dpad_right": 72, "lb": 74,
                              "rb": 76, "lt": 77, "rt": 79},
        },
        "midi": {"channel": 1, "poll_ms": 5, "cc_min_delta": 1, "smoothing": 0.0},
    }
    if config_override:
        for k, v in config_override.items():
            cfg[k] = v

    midi = FakeMidi()
    learn = LearnManager(bus)
    eng = GamepadEngine(bus, midi, lambda: cfg, learn)
    eng.joystick = FakeJoystick()
    return eng, midi, cfg


class TestCoordinateAbsoluteMode(unittest.TestCase):
    def test_l3_held_maps_absolute(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[0] = 0.5   # 左摇杆X
        eng.joystick._buttons[8] = True  # L3 按下
        eng._handle_xy_absolute(cfg["gamepad"])
        expected = axis_to_cc_absolute(0.5)  # 95
        self.assertIn(("cc", 1, expected), midi.calls)

    def test_release_keeps_value(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[0] = 0.5
        eng.joystick._buttons[8] = True
        eng._handle_xy_absolute(cfg["gamepad"])
        n1 = len(midi.calls)
        eng.joystick._buttons[8] = False  # 松开
        eng.joystick._axes[0] = 0.0       # 回正
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertEqual(len(midi.calls), n1)  # 不再发送

    def test_center_deadzone(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[0] = 0.02
        eng.joystick._buttons[8] = True
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertIn(("cc", 1, 64), midi.calls)

    def test_r3_controls_right_stick(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[2] = -0.5
        eng.joystick._buttons[9] = True  # R3
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertIn(("cc", 3, axis_to_cc_absolute(-0.5)), midi.calls)

    def test_absolute_mode_does_not_trigger_relative(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[0] = 0.5
        # L3 未按下：不产生任何 CC
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertEqual(midi.calls, [])

    def test_snapshot_gates_unheld_sticks_in_absolute_mode(self):
        eng, _, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[:4] = [0.8, -0.6, -0.4, 0.7]

        snapshot = eng.state_snapshot()

        self.assertEqual(snapshot["xy_active"], {"left": False, "right": False})
        self.assertEqual(snapshot["axes"][:4], [0.0, 0.0, 0.0, 0.0])

    def test_snapshot_only_exposes_held_stick_in_absolute_mode(self):
        eng, _, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._axes[:4] = [0.8, -0.6, -0.4, 0.7]
        eng.joystick._buttons[8] = True

        snapshot = eng.state_snapshot()

        self.assertEqual(snapshot["xy_active"], {"left": True, "right": False})
        self.assertEqual(snapshot["axes"][:4], [0.8, -0.6, 0.0, 0.0])

    def test_relative_snapshot_keeps_both_sticks_visible(self):
        eng, _, cfg = make_engine()
        eng.joystick._axes[:4] = [0.8, -0.6, -0.4, 0.7]

        snapshot = eng.state_snapshot()

        self.assertEqual(snapshot["xy_active"], {"left": True, "right": True})
        self.assertEqual(snapshot["axes"][:4], [0.8, -0.6, -0.4, 0.7])


class TestRelativeMode(unittest.TestCase):
    def test_stick_creates_cc_delta(self):
        eng, midi, cfg = make_engine()
        eng.joystick._axes[0] = 0.5  # 大于死区
        eng._handle_relative(cfg["gamepad"])
        # 64 + 0.5*3.0 = 65.5 -> 66
        self.assertTrue(any(c[0] == "cc" and c[1] == 1 for c in midi.calls))

    def test_deadzone_no_output(self):
        eng, midi, cfg = make_engine()
        eng.joystick._axes[0] = 0.05  # 死区内
        eng._handle_relative(cfg["gamepad"])
        self.assertEqual(midi.calls, [])

    def test_center_returns_no_change(self):
        eng, midi, cfg = make_engine()
        eng.joystick._axes[0] = 0.0
        eng._handle_relative(cfg["gamepad"])
        self.assertEqual(midi.calls, [])


class TestHat(unittest.TestCase):
    def test_hat_dpad_up_note(self):
        eng, midi, cfg = make_engine()
        eng.joystick._hat = (0, 1)   # 十字键上
        eng._handle_hat(cfg["gamepad"])
        self.assertIn(("note_on", 67, 127), midi.calls)  # dpad_up=67

    def test_hat_release_off(self):
        eng, midi, cfg = make_engine()
        eng.joystick._hat = (1, 0)   # 右
        eng._handle_hat(cfg["gamepad"])
        self.assertIn(("note_on", 72, 127), midi.calls)
        eng.joystick._hat = (0, 0)   # 回中
        eng._handle_hat(cfg["gamepad"])
        self.assertIn(("note_off", 72), midi.calls)

    def test_hat_switch_direction(self):
        eng, midi, cfg = make_engine()
        eng.joystick._hat = (0, -1)  # 下
        eng._handle_hat(cfg["gamepad"])
        self.assertIn(("note_on", 69, 127), midi.calls)
        eng.joystick._hat = (-1, 0)  # 左
        eng._handle_hat(cfg["gamepad"])
        self.assertIn(("note_off", 69), midi.calls)
        self.assertIn(("note_on", 71, 127), midi.calls)

    def test_hat_in_xy_mode_still_works(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._hat = (0, 1)
        eng._handle_hat(cfg["gamepad"])
        self.assertTrue(any(c[0] == "note_on" for c in midi.calls))


class TestButtonsAndTriggers(unittest.TestCase):
    def test_button_note_on_off(self):
        eng, midi, cfg = make_engine()
        eng.joystick._buttons[0] = True
        eng._handle_buttons(cfg["gamepad"])
        self.assertIn(("note_on", 60, 127), midi.calls)
        eng.joystick._buttons[0] = False
        eng._handle_buttons(cfg["gamepad"])
        self.assertIn(("note_off", 60), midi.calls)

    def test_learn_button_captured(self):
        eng, midi, cfg = make_engine()
        results = []
        eng.bus.subscribe("learn.result", lambda **kw: results.append(kw))
        eng.learn.start({"kind": "note", "key": "button_a"})
        eng.joystick._buttons[8] = True  # L3
        eng._handle_buttons(cfg["gamepad"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["index"], 8)
        eng.joystick._buttons[8] = False
        eng._handle_buttons(cfg["gamepad"])
        self.assertEqual(midi.calls, [])  # 学习按下与松开都静默

    def test_unmapped_button_does_not_default_to_note_60(self):
        eng, midi, cfg = make_engine()
        eng.joystick._buttons[8] = True  # L3 默认未映射音符
        eng._handle_buttons(cfg["gamepad"])
        eng.joystick._buttons[8] = False
        eng._handle_buttons(cfg["gamepad"])
        self.assertEqual(midi.calls, [])

    def test_learn_axis_captured(self):
        eng, midi, cfg = make_engine()
        results = []
        eng.bus.subscribe("learn.result", lambda **kw: results.append(kw))
        eng.learn.start({"kind": "cc", "key": "left_stick_x"})
        eng.joystick._axes[0] = 0.6
        eng._handle_relative(cfg["gamepad"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["index"], 0)

    def test_trigger_cc_mode(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["trigger_mode"] = "cc"
        eng.joystick._axes[4] = 1.0  # LT 全按
        eng._handle_triggers(cfg["gamepad"])
        self.assertIn(("cc", 11, 127), midi.calls)

    def test_trigger_velocity_mode(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["trigger_mode"] = "velocity"
        eng.joystick._axes[4] = 1.0
        eng._handle_triggers(cfg["gamepad"])
        self.assertTrue(any(c[0] == "note_on" and c[1] == 77 and c[2] == 127 for c in midi.calls))

    def test_signed_trigger_range_is_normalized(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["trigger_mode"] = "cc"
        eng.joystick._axes[4] = -1.0
        eng._handle_triggers(cfg["gamepad"])
        self.assertIn(("cc", 11, 0), midi.calls)
        eng.joystick._axes[4] = 0.0
        eng._handle_triggers(cfg["gamepad"])
        self.assertIn(("cc", 11, 64), midi.calls)
        eng.joystick._axes[4] = 1.0
        eng._handle_triggers(cfg["gamepad"])
        self.assertIn(("cc", 11, 127), midi.calls)

    def test_xy_mode_skips_l3_r3_notes(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._buttons[8] = True
        eng._handle_buttons(cfg["gamepad"])
        self.assertEqual(midi.calls, [])


class TestSdlEndToEnd(unittest.TestCase):
    def test_all_sdl_controls_reach_midi(self):
        """应用默认 SDL 链路：按钮、摇杆、扳机、十字键都能被消费。"""
        eng, midi, cfg = make_engine()
        raw = FakeJoystick()
        adapter = SdlEventJoystick(raw)
        eng.joystick = adapter
        eng._resolve_layout()

        def consume(event):
            adapter.process_event(event)
            eng._capture_frame()
            eng._handle_relative(cfg["gamepad"])
            eng._handle_triggers(cfg["gamepad"])
            eng._handle_hat(cfg["gamepad"])
            eng._handle_buttons(cfg["gamepad"])

        consume(SimpleNamespace(type=pygame.JOYBUTTONDOWN, instance_id=0, button=0))
        consume(SimpleNamespace(type=pygame.JOYBUTTONUP, instance_id=0, button=0))
        consume(SimpleNamespace(type=pygame.JOYBUTTONDOWN, instance_id=0, button=4))
        consume(SimpleNamespace(type=pygame.JOYBUTTONUP, instance_id=0, button=4))
        consume(SimpleNamespace(type=pygame.JOYAXISMOTION, instance_id=0,
                                axis=0, value=0.8))
        consume(SimpleNamespace(type=pygame.JOYAXISMOTION, instance_id=0,
                                axis=4, value=1.0))
        consume(SimpleNamespace(type=pygame.JOYAXISMOTION, instance_id=0,
                                axis=4, value=0.0))
        consume(SimpleNamespace(type=pygame.JOYHATMOTION, instance_id=0,
                                value=(0, 1)))
        consume(SimpleNamespace(type=pygame.JOYHATMOTION, instance_id=0,
                                value=(0, 0)))

        self.assertIn(("note_on", 60, 127), midi.calls)
        self.assertIn(("note_off", 60), midi.calls)
        self.assertIn(("note_on", 74, 127), midi.calls)
        self.assertIn(("note_off", 74), midi.calls)
        self.assertIn(("cc", 1, 66), midi.calls)
        self.assertIn(("note_on", 77, 127), midi.calls)
        self.assertIn(("note_off", 77), midi.calls)
        self.assertIn(("note_on", 67, 127), midi.calls)
        self.assertIn(("note_off", 67), midi.calls)


class TestLayoutAndHotplug(unittest.TestCase):
    def test_xinput_layout_uses_native_button_order(self):
        eng, midi, cfg = make_engine()
        eng.joystick.backend_name = "XInput"
        eng.joystick._guid = ""
        eng._resolve_layout()
        self.assertEqual(eng.button_key_map[0], "button_a")
        self.assertEqual(eng.button_key_map[8], "l3")
        self.assertEqual(eng.button_key_map[9], "r3")
        self.assertNotIn(10, eng.button_key_map)
        self.assertEqual(eng.axis_src, {"lx": 0, "ly": 1, "rx": 2,
                                       "ry": 3, "lt": 4, "rt": 5})

    def test_parse_sdl_mapping(self):
        parsed = GamepadEngine._parse_sdl_mapping(
            "03000000x,*,a:b0,b:b1,back:b6,leftstick:b9,rightstick:b10,"
            "leftx:a0,lefty:a1,lefttrigger:a4,righttrigger:a5,dpup:h0.1,platform:Windows,")
        self.assertEqual(parsed["buttons"]["leftstick"], 9)
        self.assertEqual(parsed["buttons"]["rightstick"], 10)
        self.assertEqual(parsed["axes"]["lefttrigger"], 4)
        self.assertNotIn("dpup", parsed["buttons"])

    def test_vid_pid_from_guid(self):
        vid, pid = GamepadEngine._vid_pid_from_guid(
            "030082795e040000e002000000007200")
        self.assertEqual((vid, pid), (0x045E, 0x02E0))

    def test_sdl_layout_honors_sdl_mapping_for_360_wireless(self):
        """0x02E0 是 360 无线接收器：SDL 映射 leftstick:b8 描述的就是 SDL 自身按钮序，
        必须直接采用（L3=8/R3=9），不能套用 One 家族 HID 报告序（L3=9/R3=10）。"""
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["l3_button"] = -1
        cfg["gamepad"]["r3_button"] = -1
        eng.joystick._guid = "030082795e040000e002000000007200"
        sdl_map = {"buttons": {"a": 0, "b": 1, "x": 2, "y": 3, "back": 6,
                               "start": 7, "leftstick": 8, "rightstick": 9,
                               "guide": 10},
                   "axes": {"leftx": 0, "lefty": 1, "rightx": 2, "righty": 3,
                            "lefttrigger": 4, "righttrigger": 5}}
        with mock.patch.object(eng, "_sdl_mapping", return_value=sdl_map):
            eng._resolve_layout()
        self.assertEqual(eng.button_key_map[8], "l3")
        self.assertEqual(eng.button_key_map[9], "r3")
        self.assertNotIn(10, eng.button_key_map)  # Guide 不映射音符
        cfg["gamepad"]["mode"] = "xy_absolute"
        # 按住实际 L3(8) -> 左摇杆绝对映射
        eng.joystick._axes[0] = 0.5
        eng.joystick._buttons[8] = True
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertIn(("cc", 1, axis_to_cc_absolute(0.5)), midi.calls)
        # 按住实际 R3(9) -> 右摇杆绝对映射
        eng.joystick._buttons[8] = False
        eng.joystick._buttons[9] = True
        eng.joystick._axes[2] = -0.5
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertIn(("cc", 3, axis_to_cc_absolute(-0.5)), midi.calls)
        # Guide(10) 不得误触发左摇杆
        eng.joystick._buttons[9] = False
        eng.joystick._buttons[10] = True
        n = len(midi.calls)
        eng.joystick._axes[0] = -0.5
        eng._handle_xy_absolute(cfg["gamepad"])
        self.assertEqual(len(midi.calls), n)

    def test_sdl_layout_one_family_without_mapping_falls_back_legacy(self):
        """SDL 适配器查不到映射表时回退传统表：对 SDL 自身（XInput 序）是正确猜测"""
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["l3_button"] = -1
        cfg["gamepad"]["r3_button"] = -1
        eng.joystick._guid = "030082795e040000d102000000007200"
        with mock.patch.object(eng, "_sdl_mapping", return_value=None):
            eng._resolve_layout()
        self.assertEqual(eng.button_key_map[8], "l3")
        self.assertEqual(eng.button_key_map[9], "r3")

    def test_hid_layout_one_family_uses_report_order(self):
        """Windows HID 适配器：One 家族（02D1）按钮为 HID 报告序 L3=9/R3=10"""
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["l3_button"] = -1
        cfg["gamepad"]["r3_button"] = -1
        eng.joystick._guid = "030082795e040000d102000000007200"
        eng.joystick.standard_layout = True
        with mock.patch.object(eng, "_sdl_mapping", return_value=None):
            eng._resolve_layout()
        self.assertEqual(eng.button_key_map[9], "l3")
        self.assertEqual(eng.button_key_map[10], "r3")

    def test_hid_layout_360_wireless_uses_xinput_order(self):
        """Windows HID 适配器：0x02E0（360 无线接收器）按钮序为 XInput 序 L3=8/R3=9"""
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["l3_button"] = -1
        cfg["gamepad"]["r3_button"] = -1
        eng.joystick._guid = "030082795e040000e002000000007200"
        eng.joystick.standard_layout = True
        with mock.patch.object(eng, "_sdl_mapping", return_value=None):
            eng._resolve_layout()
        self.assertEqual(eng.button_key_map[8], "l3")
        self.assertEqual(eng.button_key_map[9], "r3")

    def test_manual_override_beats_auto(self):
        eng, midi, cfg = make_engine()   # l3_button=8 r3_button=9 手动指定
        eng.joystick._guid = "030082795e040000e002000000007200"
        with mock.patch.object(eng, "_sdl_mapping", return_value=None):
            eng._resolve_layout()
        self.assertEqual(eng.button_key_map[8], "l3")
        self.assertEqual(eng.button_key_map[9], "r3")

    def test_sdl_mapping_drives_axes(self):
        """XInput 布局（LT=物理轴2）由 SDL 映射表驱动，扳机读取正确轴"""
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["l3_button"] = -1
        cfg["gamepad"]["r3_button"] = -1
        eng.joystick._guid = "030003f05e0400008e02000000007200"
        mapping = {
            "buttons": {"a": 0, "b": 1, "x": 2, "y": 3, "back": 6, "start": 7,
                        "leftshoulder": 4, "rightshoulder": 5,
                        "leftstick": 9, "rightstick": 10},
            "axes": {"leftx": 0, "lefty": 1, "rightx": 3, "righty": 4,
                     "lefttrigger": 2, "righttrigger": 5},
        }
        with mock.patch.object(eng, "_sdl_mapping", return_value=mapping):
            eng._resolve_layout()
        self.assertEqual(eng.axis_src["lt"], 2)
        self.assertEqual(eng.axis_src["rx"], 3)
        self.assertEqual(eng.button_key_map[9], "l3")
        self.assertEqual(eng.button_key_map[10], "r3")
        self.assertEqual(eng.button_key_map[0], "button_a")
        self.assertEqual(eng.button_key_map[6], "button_back")
        cfg["gamepad"]["trigger_mode"] = "cc"
        eng.joystick._axes[2] = 1.0    # 物理轴2 = LT
        eng._handle_triggers(cfg["gamepad"])
        self.assertIn(("cc", 11, 127), midi.calls)

    def test_manage_joystick_waiting_then_connect(self):
        eng, midi, cfg = make_engine()
        eng.joystick = None
        logs = []
        eng.bus.subscribe("log", lambda **kw: logs.append(kw.get("message")))
        states = []
        eng.bus.subscribe("gamepad.state", lambda **kw: states.append(kw))
        fake = FakeJoystick()
        adapter = SdlEventJoystick(fake)
        with mock.patch.object(pygame.joystick, "get_count", side_effect=[0, 1, 1]), \
                mock.patch.object(pygame.joystick, "Joystick", return_value=fake), \
                mock.patch("gms.input.gamepad.open_gamepad", side_effect=[None, adapter]):
            eng._manage_joystick(cfg["gamepad"])   # 无手柄：等待
            self.assertIsNone(eng.joystick)
            self.assertTrue(any("连接后自动启用" in m for m in logs))
            eng._manage_joystick(cfg["gamepad"])   # 手柄出现：自动连接
        self.assertIsNotNone(eng.joystick)
        self.assertTrue(eng.connected)
        self.assertTrue(any(s.get("connected") for s in states))

    def test_manage_joystick_can_attach_headless_xinput(self):
        eng, midi, cfg = make_engine()
        eng.joystick = None
        native = FakeJoystick()
        native.backend_name = "XInput"
        with mock.patch.object(pygame.joystick, "get_count", return_value=0), \
                mock.patch("gms.input.gamepad.open_gamepad", return_value=native):
            eng._manage_joystick(cfg["gamepad"])
        self.assertIs(eng.joystick, native)
        self.assertTrue(eng.connected)
        self.assertEqual(eng.button_key_map[8], "l3")

    def test_manage_joystick_resets_hid_fault_strikes_on_connect(self):
        """回归：连接成功后必须复位故障计数，否则两次 HID 故障后
        本进程永久锁死 SDL 回退路径，HID 恢复后也无法自愈。"""
        eng, midi, cfg = make_engine()
        eng.joystick = None
        eng._hid_fault_strikes = 5
        fake = FakeJoystick()
        with mock.patch.object(pygame.joystick, "get_count", return_value=1), \
                mock.patch.object(pygame.joystick, "Joystick", return_value=fake):
            eng._manage_joystick(cfg["gamepad"])
        self.assertIsNotNone(eng.joystick)
        self.assertEqual(eng._hid_fault_strikes, 0)

    def test_lost_releases_notes(self):
        eng, midi, cfg = make_engine()
        eng.joystick._buttons[0] = True
        eng._handle_buttons(cfg["gamepad"])
        self.assertIn(("note_on", 60, 127), midi.calls)
        eng._on_lost(cfg["gamepad"])
        self.assertIn(("note_off", 60), midi.calls)
        self.assertIsNone(eng.joystick)
        self.assertFalse(eng.connected)

    def test_push_state_11_buttons(self):
        """回归：Guide 与十字键必须使用不同的 UI 状态索引"""
        eng, midi, cfg = make_engine()
        eng.joystick = FakeJoystick(buttons=[False] * 11)
        states = []
        eng.bus.subscribe("gamepad.state", lambda **kw: states.append(kw))
        eng.last_hat = (0, 1)
        eng._push_state()
        self.assertEqual(len(states), 1)
        self.assertFalse(states[0]["buttons"][10])  # Guide
        self.assertTrue(states[0]["buttons"][11])   # 十字键↑
        self.assertEqual(states[0]["layout"][11], "dpad_up")

    def test_stop_with_hat_no_error(self):
        """回归：stop() 在十字键按下后不应 NameError（cfg 未定义）"""
        eng, midi, cfg = make_engine()
        eng.joystick._hat = (0, 1)
        eng._handle_hat(cfg["gamepad"])
        eng.stop()
        self.assertIn(("note_off", 67), midi.calls)


class TestModeAndLiveLog(unittest.TestCase):
    def test_mode_change_announced_with_l3_r3_indices(self):
        eng, midi, cfg = make_engine()
        logs = []
        eng.bus.subscribe("log", lambda **kw: logs.append(kw.get("message")))
        cfg["gamepad"]["mode"] = "xy_absolute"
        cfg["gamepad"]["l3_button"] = -1
        cfg["gamepad"]["r3_button"] = -1
        eng._resolve_layout()   # LEGACY: L3=8 R3=9
        eng._announce_mode("xy_absolute", cfg["gamepad"])
        self.assertTrue(any("坐标映射模式" in m and "按钮8" in m and "按钮9" in m for m in logs))
        # 重复调用不重复输出
        n = len(logs)
        eng._announce_mode("xy_absolute", cfg["gamepad"])
        self.assertEqual(len(logs), n)

    def test_axis_live_log_edits_in_place(self):
        eng, midi, cfg = make_engine()
        logs = []
        updates = []
        eng.bus.subscribe("log", lambda **kw: logs.append(kw))
        eng.bus.subscribe("log.update", lambda **kw: updates.append(kw))
        eng.joystick._axes[0] = 0.5
        eng._handle_relative(cfg["gamepad"])
        eng.joystick._axes[0] = 0.6
        eng._handle_relative(cfg["gamepad"])
        self.assertEqual(len(logs), 1)
        self.assertIsNotNone(logs[0].get("log_id"))
        self.assertIn("开始输出", logs[0]["message"])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["log_id"], logs[0]["log_id"])
        self.assertIn("值", updates[0]["text"])
        self.assertNotIn("开始输出", updates[0]["text"])

    def test_axis_live_log_new_session_after_idle(self):
        eng, midi, cfg = make_engine()
        logs = []
        eng.bus.subscribe("log", lambda **kw: logs.append(kw))
        eng.joystick._axes[0] = 0.5
        eng._handle_relative(cfg["gamepad"])
        first_id = logs[0]["log_id"]
        eng._live_last_write[cfg["gamepad"]["cc_mappings"]["left_stick_x"]] = 0.0
        eng.joystick._axes[0] = 0.7
        eng._handle_relative(cfg["gamepad"])
        self.assertEqual(len(logs), 2)
        self.assertNotEqual(logs[1]["log_id"], first_id)

    def test_trigger_normalization_scoped_per_source(self):
        """来源切换后不得沿用另一来源的符号判定：HID(-1..1) 与 SDL(0..1) 分开记忆"""
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["trigger_mode"] = "cc"
        # HID 源：静止值 -1 判定为有符号
        eng._trigger_value("lt", -1.0, "hid")
        # SDL 源：静止值 0 判定为无符号，即使 HID 先判定过有符号
        self.assertAlmostEqual(eng._trigger_value("lt", 0.0, "sdl"), 0.0)
        self.assertAlmostEqual(eng._trigger_value("lt", 1.0, "sdl"), 1.0)


if __name__ == "__main__":
    unittest.main()
