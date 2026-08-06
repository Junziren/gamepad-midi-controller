"""MIDI Learn 管理器测试"""

import unittest

from gms.bus import EventBus
from gms.learn import LearnManager


class TestLearn(unittest.TestCase):
    def test_start_emit_state(self):
        bus = EventBus()
        states = []
        bus.subscribe("learn.state", lambda **kw: states.append(kw))
        lm = LearnManager(bus)
        lm.start({"kind": "note", "key": "button_a"})
        self.assertTrue(lm.active)
        self.assertTrue(states[-1]["active"])

    def test_handle_returns_result(self):
        bus = EventBus()
        results = []
        bus.subscribe("learn.result", lambda **kw: results.append(kw))
        lm = LearnManager(bus)
        lm.start({"kind": "note", "key": "button_a"})
        lm.handle(kind="button", index=8)
        self.assertEqual(results, [{"target": {"kind": "note", "key": "button_a"},
                                    "kind": "button", "index": 8}])
        self.assertFalse(lm.active)

    def test_handle_when_inactive_ignored(self):
        bus = EventBus()
        results = []
        bus.subscribe("learn.result", lambda **kw: results.append(kw))
        lm = LearnManager(bus)
        lm.handle(kind="button", index=8)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()