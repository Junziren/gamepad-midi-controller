"""步进音序器：8/16/32 步循环，支持摇杆实时调制"""

import threading

from ..core import sequencer_step_duration_ms, gate_duration_ms, clamp
from .base import Tool


class StepSequencer(Tool):
    id = "step_sequencer"
    title = "步进音序器"
    category = "序列工具"
    icon = "◼"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._thread = None
        self._stop = threading.Event()
        self.playing = False
        self.step = -1
        self._notes_on = set()

    def start(self):
        pass  # 由 UI 播放按钮启动

    def stop(self):
        self._stop_playback()

    # ---- 播放控制 ----

    def action(self, name: str, payload: dict) -> dict:
        if name == "play":
            if not self.playing:
                self._start_playback()
        elif name == "stop":
            self._stop_playback()
        elif name == "toggle_step":
            self._toggle_step(int(payload.get("index", 0)))
        elif name == "set_mod":
            pass  # 调制值直接实时读摇杆
        return self.get_state()

    def _start_playback(self):
        if self._thread:
            return
        self.playing = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sequencer")
        self._thread.start()

    def _stop_playback(self):
        self.playing = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.step = -1
        for n in self._notes_on:
            self.ctx.midi.note_off(n)
        self._notes_on.clear()
        self.ctx.bus.emit("sequencer.state", playing=False, step=-1)

    # ---- 主循环 ----

    def _loop(self):
        cfg = self.ctx.tool_cfg(self.id)
        steps = int(cfg.get("steps", 16))
        self.step = 0
        while not self._stop.is_set():
            cfg = self.ctx.tool_cfg(self.id)
            steps = int(cfg.get("steps", steps))
            step_ms = sequencer_step_duration_ms(float(cfg.get("bpm", 120)), steps,
                                                 float(cfg.get("swing", 0.0)), self.step)
            self._play_step(self.step, cfg)
            self.ctx.bus.emit("sequencer.state", playing=True, step=self.step)
            self._stop.wait(step_ms / 1000.0)
            self.step = (self.step + 1) % steps

    def _play_step(self, idx, cfg):
        channel = cfg.get("channel")
        on = cfg.get("on", [])[idx] if idx < len(cfg.get("on", [])) else False
        if not on:
            return
        notes = cfg.get("notes", [])
        if idx >= len(notes):
            return
        note = int(notes[idx])
        vels = cfg.get("velocities", [])
        vel = int(vels[idx]) if idx < len(vels) else 100
        gates = cfg.get("gates", [])
        gate = float(gates[idx]) if idx < len(gates) else 0.5

        modulate = cfg.get("modulate", "none")
        if modulate == "note":
            note = int(clamp(note + round(self._read_stick() * 12), 0, 127))
        elif modulate == "cc":
            mod = self._read_stick()
            self.ctx.midi.cc(int(cfg.get("modulate_cc", 74)),
                             int(round(clamp(64 + mod * 63, 0, 127))), channel=channel)

        step_ms = sequencer_step_duration_ms(float(cfg.get("bpm", 120)), len(cfg.get("on", [16])),
                                             float(cfg.get("swing", 0.0)), idx)
        dur_ms = gate_duration_ms(step_ms, gate)
        self.ctx.midi.note_on(note, vel, channel=channel)
        self._notes_on.add(note)
        self._stop.wait(dur_ms / 1000.0)
        if self._stop.is_set():
            return
        self.ctx.midi.note_off(note, channel=channel)
        self._notes_on.discard(note)

        ccs = cfg.get("ccs", [])
        if idx < len(ccs) and ccs[idx] is not None:
            self.ctx.midi.cc(int(ccs[idx]), 64, channel=channel)

    def _read_stick(self) -> float:
        gp = self.ctx.gamepad
        if gp and gp.joystick is not None:
            try:
                return gp.joystick.get_axis(0)
            except Exception:
                return 0.0
        return 0.0

    def _toggle_step(self, idx):
        cfg = self.ctx.tool_cfg(self.id)
        on = list(cfg.get("on", []))
        if idx < len(on):
            on[idx] = not on[idx]
            self.ctx.update_config({"tools": {self.id: {"on": on}}})

    def get_state(self) -> dict:
        cfg = self.ctx.tool_cfg(self.id)
        return {"playing": self.playing, "step": self.step,
                "bpm": cfg.get("bpm", 120), "steps": cfg.get("steps", 16)}