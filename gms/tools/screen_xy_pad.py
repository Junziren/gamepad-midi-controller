"""屏幕 XY Pad：UI 内拖拽 → 绝对双 CC"""

from ..core import clamp
from .base import Tool


class ScreenXYPad(Tool):
    id = "screen_xy_pad"
    title = "屏幕 XY Pad"
    category = "演奏工具"
    icon = "🎛"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.x = 64
        self.y = 64

    def action(self, name: str, payload: dict) -> dict:
        cfg = self.ctx.tool_cfg(self.id)
        if name == "set_xy":
            self.x = int(round(clamp(payload.get("x", 64), 0, 127)))
            y_raw = int(round(clamp(payload.get("y", 64), 0, 127)))
            self.y = y_raw
            if cfg.get("invert_y", True):
                y_raw = 127 - y_raw
            self.ctx.midi.cc_smoothed(int(cfg.get("cc_x", 7)), self.x)
            self.ctx.midi.cc_smoothed(int(cfg.get("cc_y", 8)), y_raw)
        return self.get_state()

    def get_state(self) -> dict:
        return {"x": self.x, "y": self.y}