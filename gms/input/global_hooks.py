"""全局键盘/鼠标钩子（pynput）：热键、打击垫、滚轮弯音、鼠标XY"""

import threading
import ctypes
import sys

from pynput import keyboard, mouse

MOD_MAP = {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt",
           "shift_l": "shift", "shift_r": "shift", "cmd_l": "cmd", "cmd_r": "cmd"}


def key_to_str(key):
    if hasattr(key, "char") and key.char:
        return key.char.lower()
    name = getattr(key, "name", None)
    if name:
        return MOD_MAP.get(name, name)
    return None


def parse_hotkey(spec: str) -> set:
    """'<ctrl>+<alt>+1' -> {'ctrl','alt','1'}"""
    return set(part.strip().strip("<>").lower() for part in spec.split("+") if part.strip())


class GlobalHooks:
    """管理键盘/鼠标监听。key_handlers 返回 True 表示消费(可抑制)该键。"""

    def __init__(self, bus):
        self.bus = bus
        self._kb = None
        self._ms = None
        self._lock = threading.Lock()
        self.pressed = set()
        self.key_handlers = []     # fn(key_str, pressed_set) -> bool 消费
        self.scroll_handlers = []  # fn(dy) -> None
        self.hotkeys = []          # (combo_set, callback)

    # ---- 生命周期 ----

    def start(self):
        if self._kb is not None:
            return
        try:
            self._kb = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._ms = mouse.Listener(on_scroll=self._on_scroll)
            self._kb.daemon = True
            self._ms.daemon = True
            self._kb.start()
            self._ms.start()
        except Exception as exc:
            self.stop()
            self.bus.emit("log", message=f"全局输入钩子不可用：{exc}")

    def stop(self):
        if self._kb:
            self._kb.stop()
            self._kb = None
        if self._ms:
            self._ms.stop()
            self._ms = None
        with self._lock:
            self.pressed.clear()

    # ---- 注册 ----

    def add_key_handler(self, fn):
        self.key_handlers.append(fn)

    def add_scroll_handler(self, fn):
        self.scroll_handlers.append(fn)

    def add_hotkey(self, spec: str, callback):
        self.hotkeys.append((parse_hotkey(spec), callback))

    def is_active(self, keys) -> bool:
        """修饰键组合是否全部按下（如 ['ctrl','alt']）"""
        with self._lock:
            return all(k in self.pressed for k in keys)

    # ---- 回调 ----

    def _on_press(self, key):
        ks = key_to_str(key)
        if ks is None:
            return
        with self._lock:
            self.pressed.add(ks)
            pressed = set(self.pressed)
        # 热键匹配：新按下的键是组合的一部分，且组合全部按下
        for combo, cb in self.hotkeys:
            if ks in combo and combo <= pressed:
                try:
                    cb()
                except Exception:
                    pass
        consumed = False
        for handler in self.key_handlers:
            try:
                if handler(ks, pressed):
                    consumed = True
            except Exception:
                pass
        if consumed:
            return False  # suppress

    def _on_release(self, key):
        ks = key_to_str(key)
        if ks is None:
            return
        with self._lock:
            self.pressed.discard(ks)
            pressed = set(self.pressed)
        # 释放分发：handler 根据 pressed 集合（不含该键）判断松开
        for handler in self.key_handlers:
            try:
                handler(ks, pressed)
            except Exception:
                pass

    def _on_scroll(self, x, y, dx, dy):
        for handler in self.scroll_handlers:
            try:
                handler(dy)
            except Exception:
                pass


def get_cursor_pos():
    """全局鼠标位置 (x, y)，用 GetCursorPos 轮询，比监听事件轻"""
    if sys.platform == "win32":
        from ctypes import wintypes
        pt = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
        return 0, 0
    try:
        x, y = mouse.Controller().position
        return int(round(x)), int(round(y))
    except Exception:
        pass
    return 0, 0


def get_screen_size():
    if sys.platform == "win32":
        return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    if sys.platform == "darwin":
        try:
            from AppKit import NSScreen
            frame = NSScreen.mainScreen().frame()
            return int(frame.size.width), int(frame.size.height)
        except Exception:
            try:
                from Quartz import CGDisplayBounds, CGMainDisplayID
                bounds = CGDisplayBounds(CGMainDisplayID())
                return int(bounds.size.width), int(bounds.size.height)
            except Exception:
                pass
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        size = (root.winfo_screenwidth(), root.winfo_screenheight())
        root.destroy()
        return size
    except Exception:
        return 1, 1
