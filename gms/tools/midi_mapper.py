"""MIDI 映射层：虚拟输入端口 → 规则链 → 输出端口（中间件）"""

from ..core import apply_mapper_rules
from .base import Tool


class MidiMapper(Tool):
    id = "midi_mapper"
    title = "MIDI 映射层"
    category = "中间件"
    icon = "⇄"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._sub = None
        self.routed = 0

    def start(self):
        if self._sub is None:
            self._sub = self.ctx.bus.subscribe("midi.input", self._on_input)

    def stop(self):
        if self._sub is not None:
            self.ctx.bus.unsubscribe("midi.input", self._sub)
            self._sub = None

    def _on_input(self, data: bytes):
        cfg = self.ctx.tool_cfg(self.id)
        rules = cfg.get("rules", [])
        try:
            import mido
            msg = mido.Message.from_bytes(bytes(data))
        except Exception:
            return
        msg_type = msg.type
        if msg_type in ("note_on", "note_off"):
            fields = {"note": msg.note, "velocity": getattr(msg, "velocity", 0)}
        elif msg_type == "control_change":
            fields = {"control": msg.control, "value": msg.value}
        elif msg_type == "pitchwheel":
            fields = {"pitch": msg.pitch}
        else:
            return
        results = apply_mapper_rules(msg_type, msg.channel, fields, rules)
        for rtype, rch, rfields in results:
            self.ctx.midi.send_message(rtype, channel=rch + 1, **rfields)
            self.routed += 1

    def get_state(self) -> dict:
        return {"routed": self.routed}