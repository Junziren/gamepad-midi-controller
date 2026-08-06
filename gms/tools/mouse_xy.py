"""鼠标 XY 控制器：按住热键时，鼠标屏幕位置 → 两个绝对 CC"""

import threading

from ..core import clamp
from ..input.global_hooks import get_cursor_pos, get_screen_size
from .base import Tool


class MouseXY(Tool):
    id = "mouse_xy"
    title = "鼠标 XY 控制器"
    category = "演奏工具"
    icon = "🖱"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._thread = None
        self._stop = threading.Event()
        self._active = False
        self._last = None

    def start(self):
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mouse_xy")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self):
        while not self._stop.is_set():
            try:
                cfg = self.ctx.tool_cfg(self.id)
                hotkey = cfg.get("hotkey", ["ctrl", "alt"])
                active = self.ctx.hooks.is_active(hotkey)
                if active:
                    x, y = get_cursor_pos()
                    w, h = get_screen_size()
                    cx = int(round(clamp(x / max(1, w) * 127, 0, 127)))
                    cy_raw = y / max(1, h) * 127
                    if cfg.get("invert_y", True):
                        cy_raw = 127 - cy_raw
                    cy = int(round(clamp(cy_raw, 0, 127)))
                    if self._last != (cx, cy):
                        self._last = (cx, cy)
                        self.ctx.midi.cc_smoothed(int(cfg.get("cc_x", 5)), cx)
                        self.ctx.midi.cc_smoothed(int(cfg.get("cc_y", 6)), cy)
                    self._active = True
                else:
                    self._active = False
                    self._last = None
            except Exception:
                pass
            self._stop.wait(0.02)

    def get_state(self) -> dict:
        return {"active": self._active}