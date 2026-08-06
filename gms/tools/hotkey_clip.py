"""全局热键触发 MIDI Clip：预设事件序列播放 + 表演录制"""

import threading
import time

from ..core import clip_event_times, clip_total_ms
from .base import Tool


class HotkeyClip(Tool):
    id = "hotkey_clip"
    title = "热键 MIDI Clip"
    category = "序列工具"
    icon = "▶"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._registered = False
        self._players = {}   # clip名 -> {"thread":..., "stop":..., "notes": set}
        self._recording = False
        self._rec_events = []
        self._rec_start = 0.0
        self._rec_sub = None

    def start(self):
        self._sync_hotkeys()

    def stop(self):
        for name in list(self._players):
            self._stop_player(name)
        self._stop_record_silent()

    def _sync_hotkeys(self):
        if not self._registered:
            cfg = self.ctx.tool_cfg(self.id)
            for clip in cfg.get("clips", []):
                if clip.get("hotkey"):
                    self.ctx.hooks.add_hotkey(clip["hotkey"], lambda c=clip: self._toggle(c))
            self._registered = True

    # ---- 播放 ----

    def _toggle(self, clip):
        name = clip.get("name", "clip")
        if name in self._players:
            self._stop_player(name)
        else:
            self._start_player(name, clip)

    def _start_player(self, name, clip):
        thread = threading.Thread(target=self._play_loop, args=(name, clip),
                                  daemon=True, name=f"clip_{name}")
        self._players[name] = {"thread": thread, "stop": False, "notes": set()}
        thread.start()

    def _play_loop(self, name, clip):
        events = clip.get("events", [])
        if not events:
            return
        channel = clip.get("channel")
        loop = bool(clip.get("loop", False))
        while True:
            state = self._players.get(name)
            if not state or state["stop"]:
                break
            schedule = clip_event_times(events)
            total = clip_total_ms(events)
            t0 = time.time()
            for t_ms, ev in schedule:
                state = self._players.get(name)
                if not state or state["stop"]:
                    break
                wait = t0 + t_ms / 1000.0 - time.time()
                if wait > 0:
                    time.sleep(wait)
                self._send_event(ev, channel, name)
            remain = t0 + total / 1000.0 - time.time()
            if remain > 0:
                time.sleep(remain)
            state = self._players.get(name)
            if not state or state["stop"]:
                break
            if not loop:
                self._players.pop(name, None)
                break

    def _send_event(self, ev, channel, name):
        t = ev.get("type")
        if t == "note_on":
            self.ctx.midi.note_on(int(ev["note"]), int(ev.get("velocity", 100)), channel=channel)
            self._players[name]["notes"].add(int(ev["note"]))
        elif t == "note_off":
            self.ctx.midi.note_off(int(ev["note"]), channel=channel)
            self._players[name]["notes"].discard(int(ev["note"]))
        elif t == "control_change":
            self.ctx.midi.cc(int(ev["control"]), int(ev.get("value", 0)), channel=channel)

    def _stop_player(self, name):
        state = self._players.pop(name, None)
        if not state:
            return
        state["stop"] = True
        for note in state["notes"]:
            self.ctx.midi.note_off(note)

    # ---- 录制 ----

    def _stop_record_silent(self):
        self._recording = False
        if self._rec_sub:
            self.ctx.bus.unsubscribe("midi.event", self._rec_sub)
            self._rec_sub = None

    def _record_events(self, type, channel, fields):
        if type not in ("note_on", "note_off", "control_change", "pitchwheel"):
            return
        t_ms = int((time.time() - self._rec_start) * 1000)
        if type == "note_on":
            self._rec_events.append({"type": type, "note": fields["note"],
                                     "velocity": fields.get("velocity", 100), "t": t_ms})
        elif type == "note_off":
            self._rec_events.append({"type": type, "note": fields["note"], "t": t_ms})
        elif type == "control_change":
            self._rec_events.append({"type": type, "control": fields["control"],
                                     "value": fields["value"], "t": t_ms})
        elif type == "pitchwheel":
            self._rec_events.append({"type": type, "pitch": fields["pitch"], "t": t_ms})

    def action(self, name: str, payload: dict) -> dict:
        cfg = self.ctx.tool_cfg(self.id)
        if name == "record_start":
            if not self._recording:
                self._recording = True
                self._rec_events = []
                self._rec_start = time.time()
                self._rec_sub = self.ctx.bus.subscribe("midi.event", self._record_events)
        elif name == "record_stop":
            if self._recording:
                self._recording = False
                if self._rec_sub:
                    self.ctx.bus.unsubscribe("midi.event", self._rec_sub)
                    self._rec_sub = None
                events = self._rec_events
                clips = list(cfg.get("clips", []))
                clips.append({"name": "录制 " + str(len(clips) + 1), "hotkey": "",
                              "loop": False, "channel": None, "events": events})
                self.ctx.update_config({"tools": {self.id: {"clips": clips}}})
        elif name == "play":
            for clip in cfg.get("clips", []):
                if clip.get("name") == payload.get("name"):
                    self._toggle(clip)
        elif name == "stop_all":
            for cname in list(self._players):
                self._stop_player(cname)
        return self.get_state()

    def get_state(self) -> dict:
        return {
            "playing": [name for name in self._players],
            "recording": self._recording,
        }