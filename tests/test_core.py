"""纯函数测试：曲线/死区/绝对映射/力度/音序器/Clip/映射规则"""

import unittest

from gms.core import (
    clamp, apply_deadzone, apply_curve, axis_to_cc_absolute,
    axis_to_cc_absolute_centered, velocity_hold_pressure, trigger_axis_to_value,
    pitch_bend_from_wheel, sequencer_step_duration_ms, gate_duration_ms,
    clip_event_times, clip_total_ms, apply_mapper_rules,
)


class TestBasics(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-1, 0, 3), 0)
        self.assertEqual(clamp(2, 0, 3), 2)

    def test_deadzone(self):
        self.assertEqual(apply_deadzone(0.05, 0.15), 0.0)
        self.assertEqual(apply_deadzone(0.2, 0.15), 0.2)
        self.assertEqual(apply_deadzone(-0.2, 0.15), -0.2)

    def test_curve_linear(self):
        self.assertEqual(apply_curve(0.5, "linear", 3.0), 1.5)
        self.assertEqual(apply_curve(-0.5, "linear", 3.0), -1.5)

    def test_curve_exponential(self):
        v = apply_curve(0.5, "exponential", 3.0, exp=2.0)
        self.assertAlmostEqual(v, 0.75)
        v = apply_curve(-0.5, "exponential", 3.0, exp=2.0)
        self.assertAlmostEqual(v, -0.75)

    def test_axis_absolute(self):
        self.assertEqual(axis_to_cc_absolute(0.0), 64)
        self.assertEqual(axis_to_cc_absolute(1.0), 127)
        self.assertEqual(axis_to_cc_absolute(-1.0), 0)
        self.assertEqual(axis_to_cc_absolute(0.5), 95)

    def test_axis_absolute_centered(self):
        self.assertEqual(axis_to_cc_absolute_centered(0.02), 64)
        self.assertEqual(axis_to_cc_absolute_centered(-0.02), 64)
        self.assertNotEqual(axis_to_cc_absolute_centered(0.5), 64)

    def test_velocity_hold(self):
        self.assertEqual(velocity_hold_pressure(0, 40, 127), 40)
        self.assertEqual(velocity_hold_pressure(1000, 40, 127), 127)
        v = velocity_hold_pressure(75, 40, 127, ramp_ms=150)
        self.assertGreater(v, 40)
        self.assertLessEqual(v, 127)

    def test_trigger_value(self):
        self.assertEqual(trigger_axis_to_value(1.0), 127)
        self.assertEqual(trigger_axis_to_value(0.5), 64)

    def test_pitch_bend(self):
        self.assertEqual(pitch_bend_from_wheel(1, 341, 0), 341)
        self.assertEqual(pitch_bend_from_wheel(-1, 341, 0), -341)
        self.assertEqual(pitch_bend_from_wheel(1, 341, 8191), 8191)


class TestSequencer(unittest.TestCase):
    def test_step_duration(self):
        d = sequencer_step_duration_ms(120, 16)
        self.assertAlmostEqual(d, 125.0)  # 60000/120 * 4/16
        d8 = sequencer_step_duration_ms(120, 8)
        self.assertAlmostEqual(d8, 250.0)

    def test_swing(self):
        even = sequencer_step_duration_ms(120, 16, swing=0.2, step_index=0)
        odd = sequencer_step_duration_ms(120, 16, swing=0.2, step_index=1)
        self.assertGreater(odd, even)

    def test_gate(self):
        self.assertAlmostEqual(gate_duration_ms(125, 0.5), 62.5)
        self.assertAlmostEqual(gate_duration_ms(125, 1.0), 125.0)


class TestClip(unittest.TestCase):
    EVENTS = [
        {"type": "note_on", "note": 60, "t": 0, "duration": 100},
        {"type": "note_off", "note": 60, "t": 100},
        {"type": "note_on", "note": 62, "t": 150, "duration": 100},
        {"type": "note_off", "note": 62, "t": 250},
    ]

    def test_event_times(self):
        times = clip_event_times(self.EVENTS)
        self.assertEqual([round(t) for t, _ in times], [0, 100, 150, 250])

    def test_total(self):
        self.assertEqual(clip_total_ms(self.EVENTS), 250)


class TestMapper(unittest.TestCase):
    def test_channel_forward(self):
        rules = [{"action": "channel", "from": 0, "to": 2}]
        out = apply_mapper_rules("note_on", 0, {"note": 60, "velocity": 100}, rules)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], 2)

    def test_channel_forward_mismatch(self):
        rules = [{"action": "channel", "from": 0, "to": 2}]
        out = apply_mapper_rules("note_on", 1, {"note": 60, "velocity": 100}, rules)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], 1)  # 不匹配则保持

    def test_note_shift(self):
        rules = [{"action": "note_shift", "offset": 12}]
        out = apply_mapper_rules("note_on", 0, {"note": 60, "velocity": 100}, rules)
        self.assertEqual(out[0][2]["note"], 72)

    def test_note_shift_clamp(self):
        rules = [{"action": "note_shift", "offset": 120}]
        out = apply_mapper_rules("note_on", 0, {"note": 60, "velocity": 100}, rules)
        self.assertEqual(out[0][2]["note"], 127)

    def test_cc_scale(self):
        rules = [{"action": "cc_scale", "cc": 1, "factor": 0.5}]
        out = apply_mapper_rules("control_change", 0, {"control": 1, "value": 100}, rules)
        self.assertEqual(out[0][2]["value"], 50)

    def test_cc_scale_reverse(self):
        rules = [{"action": "cc_scale", "cc": 1, "factor": 1.0, "reverse": True}]
        out = apply_mapper_rules("control_change", 0, {"control": 1, "value": 100}, rules)
        self.assertEqual(out[0][2]["value"], 27)

    def test_note_filter_pass(self):
        rules = [{"action": "note_filter", "note_min": 60, "note_max": 72, "pass": True}]
        out = apply_mapper_rules("note_on", 0, {"note": 64, "velocity": 100}, rules)
        self.assertEqual(len(out), 1)
        out = apply_mapper_rules("note_on", 0, {"note": 48, "velocity": 100}, rules)
        self.assertEqual(len(out), 0)

    def test_note_filter_block(self):
        rules = [{"action": "note_filter", "note_min": 60, "note_max": 72, "pass": False}]
        out = apply_mapper_rules("note_on", 0, {"note": 64, "velocity": 100}, rules)
        self.assertEqual(len(out), 0)


if __name__ == "__main__":
    unittest.main()