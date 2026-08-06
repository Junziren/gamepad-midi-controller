"""键盘打击垫：电脑键盘 → MIDI 音符"""

from .base import Tool


class KeyboardPads(Tool):
    id = "keyboard_pads"
    title = "键盘打击垫"
    category = "演奏工具"
    icon = "⌨"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.held = {}  # key -> note
        self._registered = False

    def start(self):
        if not self._registered:
            self.ctx.hooks.add_key_handler(self._on_key)
            self._registered = True

    def stop(self):
        for note in list(self.held.values()):
            self.ctx.midi.note_off(note)
        self.held.clear()

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
            note = int(pad["note"])
            self.held[ks] = note
            vel = self._velocity(cfg)
            self.ctx.midi.note_on(note, vel)
        else:
            note = self.held.pop(ks, None)
            if note is not None:
                self.ctx.midi.note_off(note)
        return bool(cfg.get("suppress", False))

    def _velocity(self, cfg) -> int:
        mode = cfg.get("velocity_mode", "fixed")
        if mode == "random":
            import random
            return random.randint(40, 127)
        return int(cfg.get("velocity_fixed", 100))