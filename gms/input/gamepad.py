# -*- coding: utf-8 -*-
"""手柄引擎：热插拔自动重连 + SDL 布局感知按钮/轴映射 + 相对/坐标映射模式"""

import ctypes
import os
import threading
import time

import pygame

from .gamepad_devices import open_gamepad

from ..core import (
    apply_deadzone, apply_curve, axis_to_cc_absolute_centered,
    velocity_random, velocity_hold_pressure, trigger_axis_to_value,
)

# ---- 按钮/轴布局 -----------------------------------------------------------
# SDL2 (Windows) 不同手柄的原始按钮索引不同：
#   Xbox 360 (rawinput)：A=0,B=1,X=2,Y=3,LB=4,RB=5,Back=6,Start=7,L3=8,R3=9,Guide=10
#   Xbox One S 蓝牙 BLE：A=0,B=1,X=2,Y=3,LB=4,RB=5,Back=6,Start=7,Guide=8,L3=9,R3=10
# 连接时优先查询 SDL 控制器映射表（SDL_GameControllerMappingForGUID）自动适配，
# 未知设备回退 LEGACY 表；l3_button/r3_button >= 0 时手动覆盖。

LEGACY_BUTTON_MAP = {
    0: "button_a", 1: "button_b", 2: "button_x", 3: "button_y",
    4: "lb", 5: "rb", 6: "button_back", 7: "button_start",
    8: "l3", 9: "r3",
}
XBOX_ONE_BUTTON_MAP = {
    0: "button_a", 1: "button_b", 2: "button_x", 3: "button_y",
    4: "lb", 5: "rb", 6: "button_back", 7: "button_start",
    9: "l3", 10: "r3",
}
# Xbox One/Series 家族（USB/BLE rawinput 均为 HID 报告序；360 家族不在此列）
# 注意：0x02E0 是 Xbox 360 无线接收器（按钮序为 XInput 序 L3=8/R3=9），
# 不属于 One 家族，曾误入此表导致 SDL 路径 L3/R3 错位。
XBOX_ONE_PIDS = {0x02D1, 0x02DD, 0x02EA, 0x02FD,
                 0x0B00, 0x0B12, 0x0B13, 0x0B20, 0x0B21, 0x0B22, 0x0B2A}

SDL_BUTTON_NAMES = {
    "a": "button_a", "b": "button_b", "x": "button_x", "y": "button_y",
    "back": "button_back", "start": "button_start",
    "leftshoulder": "lb", "rightshoulder": "rb",
    "leftstick": "l3", "rightstick": "r3",
    "dpup": "dpad_up", "dpdown": "dpad_down",
    "dpleft": "dpad_left", "dpright": "dpad_right",
}
SDL_AXIS_NAMES = {
    "leftx": "lx", "lefty": "ly", "rightx": "rx", "righty": "ry",
    "lefttrigger": "lt", "righttrigger": "rt",
}
DEFAULT_AXIS_SRC = {"lx": 0, "ly": 1, "rx": 2, "ry": 3, "lt": 4, "rt": 5}


class GamepadEngine:
    """常驻引擎：负责读取手柄并生成 MIDI 输出，支持热插拔自动重连。"""

    def __init__(self, bus, midi, config_getter, learn):
        self.bus = bus
        self.midi = midi
        self.get_config = config_getter
        self.learn = learn
        self.joystick = None
        self._thread = None
        self._stop = threading.Event()
        self.running = False
        self.connected = False
        self.button_states = {}       # 按钮idx -> 是否按下
        self._button_notes = {}       # 按钮idx -> 实际已发送的音符
        self.trigger_states = {"lt": False, "rt": False}
        self.last_hat = (0, 0)
        self.hold_start = {}          # 按钮idx -> 按下时刻(力度hold模式)
        self.cc_values = {}           # cc -> float（相对模式当前值）
        self._last_abs = {}           # (channel,cc) -> 上次绝对值
        self._last_state_push = 0.0
        self.button_key_map = dict(LEGACY_BUTTON_MAP)
        self.axis_src = dict(DEFAULT_AXIS_SRC)
        self._joy_instance_id = None
        self._waiting_emitted = False
        self._last_connect_error = ""
        self.signal = "ok"
        self._last_joy_event = time.time()
        self._hid_fault_strikes = 0
        self._unmapped_warned = set()
        self._active_mode = None
        self._frame = None
        self._live_logs = {}          # cc_num -> 当前活动日志 id
        self._live_last_write = {}    # cc_num -> 最近一次写入时刻
        self._live_seq = 0            # 实时日志 id 递增序号
        self._trigger_signed_src = {} # source -> {lt/rt -> 是否 -1..1 语义}
        pygame.init()
        pygame.joystick.init()

    # ---- 手柄发现 ----

    @staticmethod
    def detect() -> list:
        pygame.init()
        pygame.joystick.init()
        return [pygame.joystick.Joystick(i).get_name()
                for i in range(pygame.joystick.get_count())]

    # ---- 生命周期 ----

    def start(self) -> bool:
        """启动引擎。无手柄时进入等待状态，连接后自动启用。"""
        if self.running:
            return True
        if self._thread is not None and self._thread.is_alive():
            self.bus.emit("log", message="手柄引擎仍在停止中，拒绝重复启动")
            return False
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gamepad")
        self._thread.start()
        self.bus.emit("log", message="手柄引擎已启动，等待手柄…")
        return True

    def restart(self) -> bool:
        """彻底重启引擎（重新检测/强制重建手柄句柄）。"""
        self.stop()
        return self.start()

    def stop(self):
        self.running = False
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if thread is not None and thread.is_alive():
            self.bus.emit("log", message="手柄线程未及时退出，保留线程句柄避免重复启动")
        else:
            self._thread = None
        cfg = self.get_config()["gamepad"]
        self._release_all(cfg)
        self._live_logs.clear()
        self._live_last_write.clear()
        self._close_joystick()
        self.joystick = None
        self._frame = None
        self._joy_instance_id = None
        self.connected = False
        self.signal = "ok"
        self._last_joy_event = time.time()
        self.bus.emit("gamepad.state", connected=False, name="", axes=[], buttons=[],
                      mode=cfg.get("mode", "relative"), running=False, layout={},
                      signal="ok", last_input_ago=0)

    def button_key(self, idx: int):
        """原始按钮索引 -> 逻辑键（供 MIDI Learn / UI 使用）"""
        return self.button_key_map.get(int(idx))

    # ---- 主循环 ----

    def _loop(self):
        poll_ms = max(1, int(self.get_config()["midi"].get("poll_ms", 5)))
        last_manage = 0.0
        while not self._stop.is_set():
            try:
                self._poll_events()
                cfg = self.get_config()["gamepad"]
                now = time.time()
                if now - last_manage >= 0.25:
                    last_manage = now
                    self._manage_joystick(cfg)
                if self.joystick is None:
                    self._stop.wait(0.5)
                    continue
                self._capture_frame()
                mode = cfg.get("mode", "relative")
                self._announce_mode(mode, cfg)
                if mode == "xy_absolute":
                    self._handle_xy_absolute(cfg)
                else:
                    self._handle_relative(cfg)
                self._handle_triggers(cfg)
                self._handle_hat(cfg)
                self._handle_buttons(cfg)
                self._push_state()
            except Exception as exc:
                if self.running:
                    self.bus.emit("log", message=f"控制循环错误: {exc}")
            self._stop.wait(poll_ms / 1000.0)

    # ---- 热插拔管理 ----

    def _manage_joystick(self, cfg):
        """每 ~0.25s 检查：手柄断开自动释放并重连，连接后自动启用。"""
        if self.joystick is not None:
            if not self._joystick_still_present():
                self._on_lost(cfg)
            elif getattr(self.joystick, "has_fault", lambda: False)():
                self._hid_fault_strikes += 1
                reason = self.joystick.fault_reason()
                self.bus.emit("log", message=(
                    f"HID 适配器故障({reason})，第{self._hid_fault_strikes}次，重建读取链路…"))
                self._release_all(cfg)
                self._close_joystick()
                self.joystick = None
                self._frame = None
                self._joy_instance_id = None
                self.connected = False
            else:
                # 真实信号监控：超过 5s 无任何输入变化时，前端应显示
                # 「无输入信号」而非虚假的「信号正常」。
                ago = time.time() - self._last_joy_event
                new_signal = "ok" if ago <= 5.0 else "no_signal"
                if new_signal != self.signal:
                    self.signal = new_signal
                    self.bus.emit("gamepad.state", **self.state_snapshot())
                return
        if pygame.joystick.get_count() == 0:
            native = open_gamepad(None, 0x045E, 0, prefer_sdl=False,
                                  prefer_xinput=True)
            if native is not None:
                try:
                    self._attach_joystick(native)
                except Exception as exc:
                    msg = f"手柄初始化失败: {exc}"
                    if msg != self._last_connect_error:
                        self._last_connect_error = msg
                        self.bus.emit("log", message=msg)
                return
            if not self._waiting_emitted:
                self._waiting_emitted = True
                self.bus.emit("log", message="未检测到手柄：连接后自动启用…")
                self.bus.emit("gamepad.state", connected=False, name="", axes=[],
                              buttons=[], mode=cfg.get("mode", "relative"), running=True,
                              layout={})
            return
        joy_id = int(cfg.get("joystick_id", 0))
        joy_id = max(0, min(joy_id, pygame.joystick.get_count() - 1))
        try:
            source = pygame.joystick.Joystick(joy_id)
            source.init()
            try:
                vid = int(source.get_vendor())
                pid = int(source.get_product())
            except Exception:
                vid, pid = self._vid_pid_from_guid(source.get_guid())
            joystick = open_gamepad(source, vid, pid, prefer_sdl=True,
                                    prefer_xinput=True)
            self._attach_joystick(joystick)
        except Exception as exc:
            msg = f"手柄初始化失败: {exc}"
            if msg != self._last_connect_error:
                self._last_connect_error = msg
                self.bus.emit("log", message=msg)

    def _attach_joystick(self, joystick):
        """Install one complete adapter and resolve its logical layout."""
        try:
            self.joystick = joystick
            self._frame = None
            self._joy_instance_id = joystick.get_instance_id()
            self._resolve_layout()
            self._waiting_emitted = False
            self._last_connect_error = ""
            self._hid_fault_strikes = 0
            self.connected = True
            self.signal = "ok"
            self._last_joy_event = time.time()
            self._active_mode = None
            self._last_abs.clear()
            self._live_logs.clear()
            self._live_last_write.clear()
            self._unmapped_warned.clear()
            self.bus.emit("log", message=(
                f"手柄已连接: {joystick.get_name()} [{joystick.backend_name}] "
                f"按钮{joystick.get_numbuttons()} 轴{joystick.get_numaxes()}"))
            self.bus.emit("gamepad.state", **self.state_snapshot())
        except Exception:
            try:
                joystick.quit()
            except Exception:
                pass
            self.joystick = None
            self._frame = None
            self._joy_instance_id = None
            self.connected = False
            raise

    def _poll_events(self):
        """Pump SDL hotplug events and feed the fallback event-state adapter."""
        pygame.event.pump()
        if self.joystick is not None:
            for event in pygame.event.get():
                self.joystick.process_event(event)
            # 事件缓存之外的直读兜底：SDL 实时状态每帧合并进缓存，
            # 避免事件丢失导致按钮/摇杆冻结。
            refresh = getattr(self.joystick, "poll_refresh", None)
            if refresh is not None:
                try:
                    refresh()
                except Exception:
                    pass
            if self.joystick.consume_changed():
                self._last_joy_event = time.time()
        else:
            pygame.event.get()

    def _capture_frame(self):
        """每帧从单一数据源取回整帧状态，避免同一帧内混读 HID/SDL 两种语义。"""
        js = self.joystick
        if js is None:
            self._frame = None
            return
        snap = getattr(js, "snapshot", None)
        if snap is not None:
            try:
                axes, buttons, hat, nax, nbtn, source = snap()
                self._frame = {"axes": axes, "buttons": buttons, "hat": hat,
                               "nax": nax, "nbtn": nbtn, "source": source}
                return
            except Exception:
                pass
        nax = js.get_numaxes()
        nbtn = js.get_numbuttons()
        hat = js.get_hat(0) if js.get_numhats() else None
        self._frame = {"axes": [float(js.get_axis(i)) for i in range(nax)],
                       "buttons": [bool(js.get_button(i)) for i in range(nbtn)],
                       "hat": hat, "nax": nax, "nbtn": nbtn, "source": "sdl"}

    def _frame_or_live(self):
        """测试/直接调用时帧未建立，退化为逐项直读。"""
        f = self._frame
        if f is not None:
            return f
        js = self.joystick
        snap = getattr(js, "snapshot", None)
        if snap is not None:
            try:
                axes, buttons, hat, nax, nbtn, source = snap()
                return {"axes": axes, "buttons": buttons, "hat": hat,
                        "nax": nax, "nbtn": nbtn, "source": source}
            except Exception:
                pass
        nax = js.get_numaxes()
        nbtn = js.get_numbuttons()
        hat = js.get_hat(0) if js.get_numhats() else None
        return {"axes": [float(js.get_axis(i)) for i in range(nax)],
                "buttons": [bool(js.get_button(i)) for i in range(nbtn)],
                "hat": hat, "nax": nax, "nbtn": nbtn, "source": "sdl"}

    def _announce_mode(self, mode, cfg):
        """模式变化时输出一行日志并推送状态，让引擎实际运行的模式可见。"""
        if mode == self._active_mode:
            return
        self._active_mode = mode
        if mode == "xy_absolute":
            l3, r3 = self._l3_r3(cfg)
            self.bus.emit("log", message=(
                f"已切换到坐标映射模式：按住 L3(按钮{l3}) 控制左摇杆，"
                f"R3(按钮{r3}) 控制右摇杆"))
        else:
            self.bus.emit("log", message="已切换到相对/加速度模式")
        self.bus.emit("gamepad.state", **self.state_snapshot())

    def _joystick_still_present(self) -> bool:
        try:
            if getattr(self.joystick, "backend_name", "") == "XInput":
                checker = getattr(self.joystick, "is_connected", None)
                if checker is not None:
                    return bool(checker())
            count = pygame.joystick.get_count()
            if count == 0:
                return False
            if self._joy_instance_id is not None:
                ids = [pygame.joystick.Joystick(i).get_instance_id()
                       for i in range(count)]
                return self._joy_instance_id in ids
            return True
        except Exception:
            return False

    def _on_lost(self, cfg):
        self._release_all(cfg)
        self._close_joystick()
        self.joystick = None
        self._frame = None
        self._joy_instance_id = None
        self.connected = False
        self.signal = "ok"
        self._last_joy_event = time.time()
        self._waiting_emitted = False
        self.bus.emit("log", message="手柄已断开，等待重新连接…")
        self.bus.emit("gamepad.state", connected=False, name="", axes=[], buttons=[],
                      mode=cfg.get("mode", "relative"), running=True, layout={})

    def _close_joystick(self):
        if self.joystick is None:
            return
        try:
            self.joystick.quit()
        except Exception:
            pass

    def _release_all(self, cfg):
        """释放所有按住的音符（断开/停止时调用）"""
        for note in list(self._button_notes.values()):
            self.midi.note_off(note)
        for side in ("lt", "rt"):
            if self.trigger_states.get(side):
                self._trigger_note_off(side)
        hat_dir = {(0, 1): "dpad_up", (0, -1): "dpad_down",
                   (-1, 0): "dpad_left", (1, 0): "dpad_right"}.get(self.last_hat)
        if hat_dir and hat_dir in cfg["note_mappings"]:
            self.midi.note_off(int(cfg["note_mappings"][hat_dir]))
        self.last_hat = (0, 0)
        self.button_states.clear()
        self._button_notes.clear()
        self.trigger_states = {"lt": False, "rt": False}
        self._trigger_signed_src = {}
        self.hold_start.clear()

    # ---- 布局解析 ----

    def _resolve_layout(self):
        """连接手柄时解析按钮/轴布局。

        两套适配器的按钮序不同，必须分别解析：
        - Windows HID：按钮为 HID 报告序（usages 升序）。One 家族报告序为
          L3=9/R3=10，其余（360 家族/克隆）为 XInput 序 L3=8/R3=9，按 PID 家族选表。
        - SDL 事件：SDL_GameControllerMappingForGUID 描述的就是 SDL 自身的按钮序，
          直接采用；查不到时回退传统表。
        """
        cfg = self.get_config()["gamepad"]
        try:
            guid_hex = self.joystick.get_guid()
        except Exception:
            guid_hex = ""
        vid, pid = self._vid_pid_from_guid(guid_hex)
        name = ""
        try:
            name = str(self.joystick.get_name()).lower()
        except Exception:
            pass
        is_one = (vid == 0x045E and pid in XBOX_ONE_PIDS) or (
            vid == 0x045E and pid == 0x02E0 and
            ("one" in name or "bluetooth" in name or "ble" in name))

        backend_name = getattr(self.joystick, "backend_name", "")
        if backend_name == "XInput":
            btn = dict(LEGACY_BUTTON_MAP)
            axes = dict(DEFAULT_AXIS_SRC)
        elif getattr(self.joystick, "standard_layout", False):
            # HID 适配器：按设备家族选按钮表；轴数组恒为引擎序 [lx,ly,rx,ry,lt,rt]
            btn = dict(XBOX_ONE_BUTTON_MAP if is_one else LEGACY_BUTTON_MAP)
            axes = dict(DEFAULT_AXIS_SRC)
        else:
            # SDL 适配器：SDL 映射表即 SDL 自身按钮序，始终可信
            mapping = self._sdl_mapping(guid_hex) if guid_hex else None
            btn = None
            if mapping and mapping.get("buttons"):
                btn = {}
                for sdl_name, raw in mapping["buttons"].items():
                    key = SDL_BUTTON_NAMES.get(sdl_name)
                    if key and key != "guide":
                        btn[raw] = key
            if not btn:
                btn = dict(LEGACY_BUTTON_MAP)
            axes = dict(DEFAULT_AXIS_SRC)
            if mapping and mapping.get("axes"):
                for sdl_name, raw in mapping["axes"].items():
                    logical = SDL_AXIS_NAMES.get(sdl_name)
                    if logical is not None and raw >= 0:
                        axes[logical] = raw

        # 手动覆盖（配置 >=0 时）
        for key, idx in (("l3", int(cfg.get("l3_button", -1))),
                         ("r3", int(cfg.get("r3_button", -1)))):
            if idx >= 0:
                btn = {k: v for k, v in btn.items() if v != key}
                btn[idx] = key
        self.button_key_map = btn
        self.axis_src = axes

    def _sdl_mapping(self, guid_hex: str):
        """查询 pygame 捆绑 SDL2 的控制器映射表；返回 {buttons, axes} 或 None。"""
        try:
            sdl_path = os.path.join(os.path.dirname(pygame.__file__), "SDL2.dll")
            if not os.path.exists(sdl_path):
                return None

            class _G(ctypes.Structure):
                _fields_ = [("data", ctypes.c_ubyte * 16)]

            sdl = ctypes.CDLL(sdl_path)
            sdl.SDL_GameControllerMappingForGUID.restype = ctypes.c_char_p
            sdl.SDL_GameControllerMappingForGUID.argtypes = [_G]
            g = _G()
            raw = bytes.fromhex(guid_hex)
            for i, byte in enumerate(raw[:16]):
                g.data[i] = byte
            res = sdl.SDL_GameControllerMappingForGUID(g)
            if not res:
                return None
            return self._parse_sdl_mapping(res.decode())
        except Exception:
            return None

    @staticmethod
    def _parse_sdl_mapping(mapping: str) -> dict:
        """解析 SDL 映射串：{buttons: {名称: 原始索引}, axes: {名称: 原始索引}}"""
        out = {"buttons": {}, "axes": {}}
        for part in mapping.split(","):
            name, _, val = part.partition(":")
            if not val:
                continue
            if val[0] == "b":
                out["buttons"][name] = int(val[1:])
            elif val[0] == "a":
                out["axes"][name] = int(val[1:])
        return out

    @staticmethod
    def _vid_pid_from_guid(guid_hex: str):
        """从 SDL GUID 提取 VID/PID（VID 在字节 4-5，PID 在字节 8-9，小端）"""
        try:
            b = bytes.fromhex(guid_hex)
            if len(b) < 10:
                return 0, 0
            return int.from_bytes(b[4:6], "little"), int.from_bytes(b[8:10], "little")
        except Exception:
            return 0, 0

    def _l3_r3(self, cfg):
        l3 = int(cfg.get("l3_button", -1))
        r3 = int(cfg.get("r3_button", -1))
        if l3 < 0:
            l3 = next((i for i, k in self.button_key_map.items() if k == "l3"), 8)
        if r3 < 0:
            r3 = next((i for i, k in self.button_key_map.items() if k == "r3"), 9)
        return l3, r3

    # ---- 摇杆：相对模式 ----

    def _handle_relative(self, cfg):
        axes = self._axes(cfg)
        mappings = cfg["cc_mappings"]
        self._rel_axis(0, axes[0], cfg, mappings.get("left_stick_x"))
        self._rel_axis(1, axes[1], cfg, mappings.get("left_stick_y"))
        self._rel_axis(2, axes[2], cfg, mappings.get("right_stick_x"))
        self._rel_axis(3, axes[3], cfg, mappings.get("right_stick_y"))

    def _rel_axis(self, axis_idx, value, cfg, cc_num):
        if cc_num is None:
            return
        # MIDI Learn：学习 CC 时推动摇杆（超过阈值）即捕获
        if self.learn.active and self.learn.target.get("kind") == "cc" and abs(value) > 0.3:
            self.learn.handle(kind="axis", index=axis_idx)
            return
        v = apply_deadzone(value, float(cfg.get("deadzone", 0.15)))
        if v == 0.0:
            return
        delta = apply_curve(v, cfg.get("curve", "linear"),
                            float(cfg.get("sensitivity", 3.0)),
                            float(cfg.get("curve_exp", 2.0)))
        cur = self.cc_values.get(cc_num, 64.0)
        new = max(0.0, min(127.0, cur + delta))
        self.cc_values[cc_num] = new
        self.midi.cc_smoothed(int(cc_num), int(round(new)))
        self._log_axis_value(cc_num, new, "摇杆")

    def _axes(self, cfg):
        """按解析出的物理轴索引读取：返回 [lx, ly, rx, ry]（引擎顺序）"""
        f = self._frame_or_live()
        n = f["nax"]
        invert = cfg.get("invert_y", True)
        out = []
        for logical, fallback in (("lx", 0), ("ly", 1), ("rx", 2), ("ry", 3)):
            phys = self.axis_src.get(logical, fallback)
            if phys >= n:
                out.append(0.0)
                continue
            v = f["axes"][phys]
            if logical in ("ly", "ry") and invert:
                v = -v
            out.append(v)
        return out


    def _log_axis_value(self, cc_num, value, kind):
        """摇杆数值实时日志：开始输出时创建一条带 id 的日志，
        后续数值变化原地编辑同一条日志（0.8s 无写入视为新一次推动）。"""
        now = time.time()
        log_id = self._live_logs.get(cc_num)
        if log_id is None or now - self._live_last_write.get(cc_num, 0.0) > 0.8:
            self._live_seq += 1
            log_id = f"{kind}-cc{cc_num}-{self._live_seq}"
            self._live_logs[cc_num] = log_id
            self.bus.emit("log", message=f"{kind} -> CC{cc_num} 开始输出：值 {int(round(value))}",
                          log_id=log_id)
        else:
            self.bus.emit("log.update", log_id=log_id,
                          text=f"{kind} -> CC{cc_num} 值 {int(round(value))}")
        self._live_last_write[cc_num] = now

    # ---- 摇杆：坐标映射模式（按住L3/R3绝对映射） ----

    def _handle_xy_absolute(self, cfg):
        axes = self._axes(cfg)
        l3, r3 = self._l3_r3(cfg)
        dz = float(cfg.get("xy_center_deadzone", 0.05))
        mappings = cfg["cc_mappings"]

        l3_down = self._button_down(l3)
        r3_down = self._button_down(r3)

        if l3_down and mappings.get("left_stick_x") is not None:
            self._abs_axis(mappings["left_stick_x"], axes[0], dz)
            self._abs_axis(mappings["left_stick_y"], axes[1], dz)
        if r3_down and mappings.get("right_stick_x") is not None:
            self._abs_axis(mappings["right_stick_x"], axes[2], dz)
            self._abs_axis(mappings["right_stick_y"], axes[3], dz)
        # 松开时：停止更新，CC 值保持（不做任何发送）

    def _abs_axis(self, cc_num, axis_value, dz):
        value = axis_to_cc_absolute_centered(axis_value, dz)
        key = (int(cc_num),)
        if self._last_abs.get(key) != value:
            self._last_abs[key] = value
            self.midi.cc_smoothed(int(cc_num), value)
            self._log_axis_value(cc_num, value, "坐标映射")

    def _button_down(self, idx) -> bool:
        f = self._frame_or_live()
        buttons = f["buttons"]
        return 0 <= idx < len(buttons) and bool(buttons[idx])

    # ---- 扳机 ----

    def _handle_triggers(self, cfg):
        f = self._frame_or_live()
        n = f["nax"]
        lt_i = self.axis_src.get("lt", 4)
        rt_i = self.axis_src.get("rt", 5)
        if max(lt_i, rt_i) >= n:
            return
        lt_raw = f["axes"][lt_i]
        rt_raw = f["axes"][rt_i]
        lt_value = self._trigger_value("lt", lt_raw, f["source"])
        rt_value = self._trigger_value("rt", rt_raw, f["source"])
        mode = cfg.get("trigger_mode", "note")
        if mode == "cc":
            self.midi.cc_smoothed(int(cfg.get("trigger_cc_lt", 11)), trigger_axis_to_value(lt_value))
            self.midi.cc_smoothed(int(cfg.get("trigger_cc_rt", 12)), trigger_axis_to_value(rt_value))
            return
        # note / velocity 模式
        threshold = 0.5 if mode == "note" else 0.05
        for side, value in (("lt", lt_value), ("rt", rt_value)):
            down = value > threshold
            was = self.trigger_states[side]
            if down and not was:
                self.trigger_states[side] = True
                if mode == "velocity":
                    vel = trigger_axis_to_value(value)
                    self._trigger_note_on(side, cfg, vel)
                else:
                    self._trigger_note_on(side, cfg, None)
            elif not down and was:
                self.trigger_states[side] = False
                self._trigger_note_off(side)

    def _trigger_value(self, side, raw, source):
        """按数据源归一化扳机轴。

        HID 解码的 lt/rt 恒为 -1..1（组合轴拆分），SDL 直读可能是 0..1 或 -1..1。
        符号判定按来源分别记忆，避免来源切换后沿用另一套换算导致阈值抖动。"""
        flags = self._trigger_signed_src.setdefault(source, {"lt": None, "rt": None})
        signed = flags[side]
        if signed is None:
            signed = raw < -0.25
            flags[side] = signed
        if signed:
            return max(0.0, min(1.0, (float(raw) + 1.0) * 0.5))
        return max(0.0, min(1.0, float(raw)))

    def _trigger_note_on(self, side, cfg, velocity):
        note = int(cfg["note_mappings"].get(side, 60))
        if velocity is None:
            velocity = self._velocity_for(cfg)
        self.midi.note_on(note, velocity)
        self.bus.emit("log", message=f"{'左' if side=='lt' else '右'}扳机 -> 音符{note} vel={velocity}")

    def _trigger_note_off(self, side):
        cfg = self.get_config()["gamepad"]
        note = int(cfg["note_mappings"].get(side, 60))
        self.midi.note_off(note)

    # ---- 十字键 (hat) ----

    def _handle_hat(self, cfg):
        hat = self._frame_or_live()["hat"]
        if hat is None:
            return
        if hat == self.last_hat:
            return
        old_hat = self.last_hat
        self.last_hat = hat
        dir_map = {(0, 1): "dpad_up", (0, -1): "dpad_down",
                   (-1, 0): "dpad_left", (1, 0): "dpad_right"}
        old_key = dir_map.get(old_hat)
        if old_key and old_key in cfg["note_mappings"]:
            self.midi.note_off(int(cfg["note_mappings"][old_key]))
        new_key = dir_map.get(hat)
        if new_key and new_key in cfg["note_mappings"]:
            note = int(cfg["note_mappings"][new_key])
            velocity = self._velocity_for(cfg)
            self.midi.note_on(note, velocity)
            self.bus.emit("log", message=f"十字键{new_key} -> 音符{note} vel={velocity}")

    # ---- 按钮 ----

    def _handle_buttons(self, cfg):
        # 坐标映射模式下 L3/R3 不触发音符
        mode = cfg.get("mode", "relative")
        skip = set()
        if mode == "xy_absolute":
            l3, r3 = self._l3_r3(cfg)
            skip = {l3, r3}
        f = self._frame_or_live()
        buttons = f["buttons"]
        for i in range(f["nbtn"]):
            pressed = bool(buttons[i]) if i < len(buttons) else False
            was = self.button_states.get(i, False)
            if i in skip:
                if was:
                    self.button_states[i] = False
                    self._button_released(i, cfg)
                continue
            if pressed and not was:
                self.button_states[i] = True
                self._button_pressed(i, cfg)
            elif not pressed and was:
                self.button_states[i] = False
                self._button_released(i, cfg)
            elif pressed and was and cfg.get("velocity_mode") == "hold":
                self._button_hold(i, cfg)

    def _button_pressed(self, idx, cfg):
        if self.learn.active:
            self.learn.handle(kind="button", index=idx)
            return
        key = self.button_key(idx)
        if key is None or key not in cfg["note_mappings"]:
            if idx not in self._unmapped_warned:
                self._unmapped_warned.add(idx)
                self.bus.emit("log", message=(
                    f"按钮{idx} 无音符映射(key={key})，未发送 MIDI；"
                    f"请在设置中为 {key or '该按钮'} 绑定音符或检查按钮布局"))
            return
        note = int(cfg["note_mappings"][key])
        velocity = self._velocity_for(cfg)
        self.hold_start[idx] = time.time()
        self._button_notes[idx] = note
        self.midi.note_on(note, velocity)
        self.bus.emit("log", message=f"按钮{idx}({key}) -> 音符{note} vel={velocity}")

    def _button_hold(self, idx, cfg):
        """hold 力度模式：按住期间力度随时间增长"""
        start = self.hold_start.get(idx)
        if start is None:
            return
        elapsed_ms = (time.time() - start) * 1000.0
        vel = velocity_hold_pressure(elapsed_ms, int(cfg.get("velocity_min", 40)),
                                     int(cfg.get("velocity_max", 127)))
        note = self._button_notes.get(idx)
        if note is None:
            return
        self.midi.note_on(note, vel)

    def _button_released(self, idx, cfg):
        self.hold_start.pop(idx, None)
        note = self._button_notes.pop(idx, None)
        if note is None:
            return
        self.midi.note_off(note)

    def _velocity_for(self, cfg) -> int:
        mode = cfg.get("velocity_mode", "fixed")
        if mode == "random":
            return velocity_random(int(cfg.get("velocity_min", 40)),
                                   int(cfg.get("velocity_max", 127)))
        return int(cfg.get("velocity_fixed", 127))

    # ---- 状态推送 ----

    def state_snapshot(self):
        cfg = self.get_config()["gamepad"]
        if self.joystick is None:
            return {
                "connected": False, "name": "", "axes": [], "buttons": [],
                "mode": cfg.get("mode", "relative"), "running": self.running,
                "layout": {}, "signal": "ok", "last_input_ago": 0,
            }
        f = self._frame_or_live()
        axes = [round(v, 3) for v in f["axes"]]
        buttons = list(f["buttons"])
        dpad_base = max(10, len(buttons))
        buttons += [False] * (dpad_base + 4 - len(buttons))
        hat = self.last_hat
        for offset, direction in enumerate(((0, 1), (0, -1), (-1, 0), (1, 0))):
            buttons[dpad_base + offset] = hat == direction
        layout = dict(self.button_key_map)
        layout.update({
            dpad_base: "dpad_up", dpad_base + 1: "dpad_down",
            dpad_base + 2: "dpad_left", dpad_base + 3: "dpad_right",
        })
        return {
            "connected": True,
            "name": self.joystick.get_name(),
            "axes": axes,
            "buttons": buttons,
            "mode": cfg.get("mode", "relative"),
            "running": self.running,
            "layout": layout,
            "signal": self.signal,
            "last_input_ago": round(time.time() - self._last_joy_event, 1),
        }

    def _push_state(self):
        if self.joystick is None:
            return
        now = time.time()
        if now - self._last_state_push < 0.1:
            return
        self._last_state_push = now
        self.bus.emit("gamepad.state", **self.state_snapshot())
