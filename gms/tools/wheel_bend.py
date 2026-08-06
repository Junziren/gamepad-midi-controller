"""滚轮弯音：按住热键 + 鼠标滚轮 → Pitch Bend / CC"""

from ..core import clamp, pitch_bend_from_wheel
from .base import Tool


class WheelBend(Tool):
    id = "wheel_bend"
    title = "滚轮弯音"
    category = "调制工具"
    icon = "🔄"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._registered = False
        self.pitch = 0
        self.cc_value = 64

    def start(self):
        if not self._registered:
            self.ctx.hooks.add_scroll_handler(self._on_scroll)
            self._registered = True

    def stop(self):
        self.pitch = 0
        self.cc_value = 64

    def _on_scroll(self, dy):
        cfg = self.ctx.tool_cfg(self.id)
        if not self.ctx.hooks.is_active(cfg.get("hotkey", ["ctrl", "shift"])):
            return
        step = 1 if dy > 0 else -1
        if cfg.get("mode", "pitch") == "pitch":
            self.pitch = pitch_bend_from_wheel(step, int(cfg.get("step_size", 341)), self.pitch)
            self.ctx.midi.pitch_bend(self.pitch)
        else:
            self.cc_value = int(round(clamp(self.cc_value + step * int(cfg.get("step_size", 4)), 0, 127)))
            self.ctx.midi.cc(int(cfg.get("cc", 74)), self.cc_value)

    def get_state(self) -> dict:
        return {"pitch": self.pitch, "cc": self.cc_value}