"""手柄引擎测试：坐标映射模式状态机 + 相对模式（使用 fake 手柄/MIDI）"""

import unittest
from types import SimpleNamespace

from gms.bus import EventBus
from gms.input.gamepad import GamepadEngine
from gms.learn import LearnManager
from gms.core import axis_to_cc_absolute


class FakeJoystick:
    def __init__(self, axes=None, buttons=None, hat=(0, 0)):
        self._axes = axes or [0.0] * 6
        self._buttons = buttons or [False] * 12
        self._hat = hat

    def get_name(self):
        return "Fake Pad"

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
        self.assertEqual(midi.calls, [])  # 学习时静默

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

    def test_xy_mode_skips_l3_r3_notes(self):
        eng, midi, cfg = make_engine()
        cfg["gamepad"]["mode"] = "xy_absolute"
        eng.joystick._buttons[8] = True
        eng._handle_buttons(cfg["gamepad"])
        self.assertEqual(midi.calls, [])


if __name__ == "__main__":
    unittest.main()