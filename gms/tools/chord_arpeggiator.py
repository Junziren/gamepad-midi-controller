"""和弦 / 琶音器：一键和弦或按速度循环琶音"""

import random
import threading
import time

from .base import Tool


class ChordArp(Tool):
    id = "chord_arp"
    title = "和弦 / 琶音器"
    category = "演奏工具"
    icon = "🎹"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.playing = {}   # key -> {"pad":..., "notes": set, "thread":..., "stop": bool}
        self._registered = False

    def start(self):
        if not self._registered:
            self.ctx.hooks.add_key_handler(self._on_key)
            self._registered = True

    def stop(self):
        for key in list(self.playing):
            self._release(key)

    def _on_key(self, ks, pressed):
        cfg = self.ctx.tool_cfg(self.id)
        pads = {p["key"]: p for p in cfg.get("pads", [])}
        if self.ctx.learn.active:
            if self.ctx.learn.target.get("kind") in ("pad_key", "chord_key"):
                self.ctx.learn.handle(kind="key", key=ks)
                return True
            return False
        pad = pads.get(ks)
        if pad is None:
            return False
        if ks in pressed:
            self._press(ks, pad)
        else:
            self._release(ks)
        return False

    def _press(self, key, pad):
        if key in self.playing:
            return
        notes = [int(n) for n in pad.get("chord", [])]
        arp = bool(pad.get("arp", False))
        if not notes:
            return
        if arp:
            thread = threading.Thread(target=self._arp_loop, args=(key, notes, pad),
                                      daemon=True, name=f"arp_{key}")
            self.playing[key] = {"pad": pad, "notes": set(), "thread": thread, "stop": False}
            thread.start()
        else:
            for n in notes:
                self.ctx.midi.note_on(n, 100)
            self.playing[key] = {"pad": pad, "notes": set(notes), "thread": None, "stop": False}

    def _arp_loop(self, key, notes, pad):
        mode = pad.get("arp_mode", "up")
        ms = max(30, int(pad.get("arp_ms", 120)))
        idx = 0
        while True:
            state = self.playing.get(key)
            if not state or state.get("stop"):
                break
            seq = self._arp_sequence(notes, mode)
            if not seq:
                break
            n = seq[idx % len(seq)]
            self.ctx.midi.note_on(n, 100)
            state["notes"].add(n)
            time.sleep(ms / 1000.0)
            self.ctx.midi.note_off(n)
            state["notes"].discard(n)
            idx += 1
            time.sleep(0.001)

    @staticmethod
    def _arp_sequence(notes, mode):
        if mode == "down":
            return list(reversed(notes))
        if mode == "updown":
            return notes + list(reversed(notes))[1:-1]
        if mode == "random":
            return random.sample(notes, len(notes))
        return notes

    def _release(self, key):
        state = self.playing.pop(key, None)
        if not state:
            return
        state["stop"] = True
        for n in state.get("notes", set()):
            self.ctx.midi.note_off(n)