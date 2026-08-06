"""应用壳：pywebview + js_api 桥接 + 组件装配"""

import json
import threading

import webview

from . import __version__, APP_NAME
from .bus import EventBus
from .config import ProfileManager, DEFAULTS
from .input.gamepad import GamepadEngine
from .input.global_hooks import GlobalHooks
from .learn import LearnManager
from .midi.backends import MidiPortManager
from .midi.engine import MidiEngine
from .tools.base import ToolContext
from .tools.registry import TOOL_CLASSES


class Api:
    """暴露给前端的 js_api。方法名即前端 window.pywebview.api 的方法。"""

    def __init__(self, app):
        self.app = app

    # ---- 全局 ----

    def get_app_state(self) -> dict:
        return self.app.app_state()

    def get_config(self) -> dict:
        return self.app.config.current()

    def set_config(self, patch: dict, tool_id: str = "") -> dict:
        self.app.config.update(patch)
        if "virtual_midi" in patch:
            self.app.apply_virtual_midi()
        if tool_id:
            self.app.restart_tool(tool_id)
        self.app.push_state()
        return self.app.config.current()

    def get_defaults(self) -> dict:
        return DEFAULTS

    def get_logs(self, limit: int = 200) -> list:
        return self.app.logs[-int(limit):]

    # ---- Profile ----

    def profile_list(self) -> list:
        return self.app.config.list_profiles()

    def profile_load(self, name: str) -> bool:
        ok = self.app.config.load_profile(name)
        self.app.reload_all()
        return ok

    def profile_new(self, name: str) -> bool:
        return self.app.config.new_profile(name)

    def profile_delete(self, name: str) -> bool:
        return self.app.config.delete_profile(name)

    def profile_save(self):
        self.app.config.save_profile(self.app.config.current_name)

    def profile_export(self, name: str) -> dict:
        return self.app.config.export_profile(name)

    def profile_import(self, name: str, data: dict) -> bool:
        return self.app.config.import_profile(name, data)

    # ---- MIDI ----

    def midi_refresh(self) -> dict:
        return self.app.ports.state()

    def midi_select_output(self, name: str) -> bool:
        return self.app.ports.select_output(name)

    # ---- 手柄 ----

    def gamepad_detect(self) -> list:
        return GamepadEngine.detect()

    def gamepad_start(self) -> bool:
        return self.app.gamepad.start()

    def gamepad_stop(self):
        self.app.gamepad.stop()

    def gamepad_switch(self, joystick_id: int) -> bool:
        """切换手柄设备（按索引），自动重连"""
        self.app.gamepad.stop()
        self.app.config.update({"gamepad": {"joystick_id": int(joystick_id)}})
        return self.app.gamepad.start()

    # ---- MIDI Learn ----

    def learn_start(self, target: dict):
        self.app.learn.start(target)

    def learn_cancel(self):
        self.app.learn.cancel()

    # ---- 工具 ----

    def tool_list(self) -> list:
        return [{"id": c.id, "title": c.title, "category": c.category, "icon": c.icon}
                for c in TOOL_CLASSES]

    def tool_toggle(self, tool_id: str, enabled: bool) -> dict:
        self.app.set_tool_enabled(tool_id, enabled)
        return {"enabled": enabled}

    def tool_action(self, tool_id: str, name: str, payload: dict) -> dict:
        tool = self.app.tools.get(tool_id)
        if tool is None:
            return {}
        return tool.action(name, payload or {})

    def tool_state(self) -> dict:
        return {tid: t.get_state() for tid, t in self.app.tools.items()}


class App:
    """组件装配 + pywebview 窗口管理"""

    def __init__(self, ui_path=None):
        self.bus = EventBus()
        self.config = ProfileManager()
        self.config.migrate_legacy()   # 迁移旧版配置
        self.ports = MidiPortManager(self.bus)
        self.midi = MidiEngine(self.bus, self.ports, self.config.current)
        self.hooks = GlobalHooks(self.bus)
        self.learn = LearnManager(self.bus)
        self.gamepad = GamepadEngine(self.bus, self.midi, self.config.current, self.learn)
        self.tools = {}
        self.logs = []
        self._ui_path = ui_path
        self._window = None
        self._state_lock = threading.Lock()
        self._setup_bus()

    # ---- 装配 ----

    def _setup_bus(self):
        self.bus.subscribe("log", self._on_log)
        self.bus.subscribe("gamepad.state", self._on_gamepad_state)
        self.bus.subscribe("virtual.state", self._on_virtual_state)
        self.bus.subscribe("sequencer.state", self._on_sequencer_state)
        self.bus.subscribe("learn.state", self._on_learn_state)
        self.bus.subscribe("learn.result", self._on_learn_result)
        self.bus.subscribe("midi.activity", self._on_midi_activity)

    def _on_log(self, message):
        self.logs.append(message)
        if len(self.logs) > 1000:
            self.logs = self.logs[-500:]
        self.push_state(fragment={"log": message})

    def _on_gamepad_state(self, connected, name, axes, buttons, mode):
        self.push_state(fragment={
            "gamepad": {"connected": connected, "name": name, "axes": axes,
                        "buttons": buttons, "mode": mode}})

    def _on_virtual_state(self, available, running, error):
        self.push_state(fragment={"virtual": {"available": available, "running": running,
                                              "error": error}})

    def _on_sequencer_state(self, playing, step):
        self.push_state(fragment={"sequencer": {"playing": playing, "step": step}})

    def _on_learn_state(self, active, target):
        self.push_state(fragment={"learn": {"active": active, "target": target}})

    def _on_midi_activity(self, kind):
        self.push_state(fragment={"midi_activity": {"kind": kind, "t": threading.get_ident() % 1000}})

    def _on_learn_result(self, target, **result):
        """MIDI Learn 结果写入配置并提示"""
        cfg = self.config.current()
        kind = target.get("kind")
        try:
            if kind == "note":
                idx = result.get("index")
                new_key = {8: "l3", 9: "r3"}.get(idx) or \
                    {0: "button_a", 1: "button_b", 2: "button_x", 3: "button_y",
                     4: "lb", 5: "rb", 6: "button_back", 7: "button_start"}.get(idx)
                if new_key:
                    nm = dict(cfg["gamepad"]["note_mappings"])
                    note = nm.pop(target.get("key"), 60)
                    nm[new_key] = note
                    self.config.update({"gamepad": {"note_mappings": nm}})
                    self.bus.emit("log", message=f"MIDI Learn：按键 {target.get('key')} → {new_key}（音符 {note}）")
            elif kind == "cc":
                axis_map = {0: "left_stick_x", 1: "left_stick_y",
                            2: "right_stick_x", 3: "right_stick_y"}
                new_key = axis_map.get(result.get("index"))
                if new_key:
                    cm = dict(cfg["gamepad"]["cc_mappings"])
                    cc = cm.pop(target.get("key"), 1)
                    cm[new_key] = cc
                    self.config.update({"gamepad": {"cc_mappings": cm}})
                    self.bus.emit("log", message=f"MIDI Learn：轴 {target.get('key')} → {new_key}（CC {cc}）")
            elif kind in ("pad_key", "chord_key"):
                key = result.get("key")
                idx = target.get("index")
                if key is not None:
                    tool_id = "keyboard_pads" if kind == "pad_key" else "chord_arp"
                    pads = [dict(p) for p in cfg["tools"].get(tool_id, {}).get("pads", [])]
                    if 0 <= idx < len(pads):
                        pads[idx]["key"] = key
                        self.config.update({"tools": {tool_id: {"pads": pads}}})
                        self.bus.emit("log", message=f"MIDI Learn：{tool_id} 第{idx + 1}键 → {key}")
        except Exception as exc:
            self.bus.emit("log", message=f"MIDI Learn 写入失败: {exc}")
        self.push_state()

    # ---- 工具管理 ----

    def apply_virtual_midi(self):
        """按配置重启虚拟 MIDI 端口（热应用）"""
        vm = self.config.current()["virtual_midi"]
        if vm.get("enabled"):
            self.ports.start(vm.get("port_name", "Gamepad MIDI 1"),
                             backend_name=vm.get("backend", "tevirtualmidi"))
        else:
            self.ports.stop()
            self.bus.emit("virtual.state", available=self.ports.backend.is_available(),
                          running=False, error="已停用")

    def set_tool_enabled(self, tool_id: str, enabled: bool):
        self.config.update({"tools": {tool_id: {"enabled": bool(enabled)}}})
        if enabled:
            self.start_tool(tool_id)
        else:
            self.stop_tool(tool_id)

    def start_tool(self, tool_id: str):
        if tool_id in self.tools:
            return
        cls = next((c for c in TOOL_CLASSES if c.id == tool_id), None)
        if cls is None:
            return
        ctx = ToolContext(self.bus, self.midi, self.hooks, self.learn, self.gamepad,
                          self.config.current, self.config.update)
        tool = cls(ctx)
        tool.start()
        self.tools[tool_id] = tool
        self.bus.emit("log", message=f"工具已启用：{cls.title}")

    def stop_tool(self, tool_id: str):
        tool = self.tools.pop(tool_id, None)
        if tool:
            tool.stop()
            cls = next((c for c in TOOL_CLASSES if c.id == tool_id), None)
            self.bus.emit("log", message=f"工具已停用：{getattr(cls, 'title', tool_id)}")

    def restart_tool(self, tool_id: str):
        """配置变化后重启工具以应用新设置"""
        if tool_id in self.tools:
            self.stop_tool(tool_id)
            self.start_tool(tool_id)

    def reload_all(self):
        """Profile 切换后重建工具"""
        for tid in list(self.tools):
            self.stop_tool(tid)
        self.start_all_enabled()

    def start_all_enabled(self):
        cfg = self.config.current()
        for cls in TOOL_CLASSES:
            if cfg["tools"].get(cls.id, {}).get("enabled"):
                self.start_tool(cls.id)

    # ---- 启动/停止 ----

    def startup(self):
        self.hooks.start()
        vm = self.config.current()["virtual_midi"]
        if vm.get("enabled"):
            self.ports.start(vm.get("port_name", "Gamepad MIDI 1"))
        # 手柄引擎常驻启动
        self.gamepad.start()
        self.start_all_enabled()
        self.bus.emit("log", message=f"{APP_NAME} v{__version__} 已启动")

    def shutdown(self):
        for tid in list(self.tools):
            self.stop_tool(tid)
        self.gamepad.stop()
        self.ports.stop()
        self.hooks.stop()

    # ---- 状态推送 ----

    def app_state(self) -> dict:
        return {
            "version": __version__,
            "app_name": APP_NAME,
            "profiles": self.config.list_profiles(),
            "current_profile": self.config.current_name,
            "ports": self.ports.state(),
            "gamepad": self._gamepad_state_snapshot(),
            "tools": self.tool_states(),
            "log": self.logs[-50:],
        }

    def _gamepad_state_snapshot(self) -> dict:
        gp = self.gamepad
        if gp.joystick is None:
            return {"connected": False, "name": "", "axes": [], "buttons": [], "mode": ""}
        try:
            return {"connected": True, "name": gp.joystick.get_name(),
                    "axes": [round(gp.joystick.get_axis(i), 3) for i in range(gp.joystick.get_numaxes())],
                    "buttons": [bool(gp.joystick.get_button(i)) for i in range(gp.joystick.get_numbuttons())],
                    "mode": self.config.current()["gamepad"].get("mode", "relative")}
        except Exception:
            return {"connected": False, "name": "", "axes": [], "buttons": [], "mode": ""}

    def tool_states(self) -> dict:
        return {tid: t.get_state() for tid, t in self.tools.items()}

    def push_state(self, fragment: dict | None = None, throttle: float = 0.05):
        """向 UI 推送状态（含节流）"""
        if self._window is None:
            return
        try:
            if fragment is not None:
                payload = json.dumps(fragment, ensure_ascii=False)
                self._window.evaluate_js(f"window.__pushFragment({payload})")
            else:
                payload = json.dumps(self.app_state(), ensure_ascii=False)
                self._window.evaluate_js(f"window.__pushState({payload})")
        except Exception:
            pass

    # ---- 运行 ----

    def run(self):
        self.startup()
        ui = self._ui_path or (__file__.rsplit("\\", 1)[0] + "\\ui\\index.html")
        self._window = webview.create_window(
            APP_NAME, ui, js_api=Api(self), width=1280, height=860,
            min_size=(1024, 700), background_color="#0d1017")
        self._window.events.loaded += self._on_loaded
        try:
            webview.start(debug=False)
        finally:
            self.shutdown()

    def _on_loaded(self):
        threading.Thread(target=self._initial_push, daemon=True).start()

    def _initial_push(self):
        import time
        time.sleep(0.3)
        self.push_state()
        self.bus.emit("log", message="界面已就绪")