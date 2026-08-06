"""手柄引擎：相对(加速度)模式 + 坐标映射模式 + 扳机/力度/曲线 + MIDI Learn"""

import threading
import time

import pygame

from ..core import (
    apply_deadzone, apply_curve, axis_to_cc_absolute_centered,
    velocity_random, velocity_hold_pressure, trigger_axis_to_value,
)


class GamepadEngine:
    """常驻引擎：负责读取手柄并生成 MIDI 输出。"""

    def __init__(self, bus, midi, config_getter, learn):
        self.bus = bus
        self.midi = midi
        self.get_config = config_getter
        self.learn = learn
        self.joystick = None
        self._thread = None
        self._stop = threading.Event()
        self.running = False
        self.button_states = {}       # 按钮idx -> 是否按下
        self.trigger_states = {"lt": False, "rt": False}
        self.last_hat = (0, 0)
        self.hold_start = {}          # 按钮idx -> 按下时刻(力度hold模式)
        self.cc_values = {}           # cc -> float（相对模式当前值）
        self._last_abs = {}           # (channel,cc) -> 上次绝对值
        self._last_state_push = 0.0
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
        if self.running:
            return True
        if pygame.joystick.get_count() == 0:
            self.bus.emit("log", message="未检测到手柄")
            self.bus.emit("gamepad.state", connected=False, name="", axes=[], buttons=[], mode="")
            return False
        try:
            joystick_id = int(self.get_config()["gamepad"].get("joystick_id", 0))
            joystick_id = max(0, min(joystick_id, pygame.joystick.get_count() - 1))
            self.joystick = pygame.joystick.Joystick(joystick_id)
            self.joystick.init()
        except Exception as exc:
            self.bus.emit("log", message=f"手柄初始化失败: {exc}")
            return False
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gamepad")
        self._thread.start()
        self.bus.emit("log", message=f"手柄已连接: {self.joystick.get_name()}")
        return True

    def stop(self):
        self.running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        # 停止时释放所有按住的音符
        for idx, state in list(self.button_states.items()):
            if state:
                self._note_off_for_button(idx)
        for side in ("lt", "rt"):
            if self.trigger_states[side]:
                self._trigger_note_off(side)
        hat_dir = {(0, 1): "dpad_up", (0, -1): "dpad_down",
                   (-1, 0): "dpad_left", (1, 0): "dpad_right"}.get(self.last_hat)
        if hat_dir and hat_dir in cfg["note_mappings"]:
            self.midi.note_off(int(cfg["note_mappings"][hat_dir]))
        self.last_hat = (0, 0)
        self.button_states.clear()
        self.trigger_states = {"lt": False, "rt": False}

    # ---- 主循环 ----

    def _loop(self):
        cfg = self.get_config()["gamepad"]
        poll_ms = max(1, int(self.get_config()["midi"].get("poll_ms", 5)))
        while not self._stop.is_set():
            try:
                pygame.event.pump()
                cfg = self.get_config()["gamepad"]
                mode = cfg.get("mode", "relative")
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

    def _axes(self, cfg):
        n = self.joystick.get_numaxes()
        out = []
        for i in range(4):
            if i < n:
                v = self.joystick.get_axis(i)
                if i in (1, 3) and cfg.get("invert_y", True):
                    v = -v
                out.append(v)
            else:
                out.append(0.0)
        return out

    # ---- 摇杆：坐标映射模式（按住L3/R3绝对映射） ----

    def _handle_xy_absolute(self, cfg):
        axes = self._axes(cfg)
        l3 = int(cfg.get("l3_button", 8))
        r3 = int(cfg.get("r3_button", 9))
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

    def _button_down(self, idx) -> bool:
        return idx < self.joystick.get_numbuttons() and bool(self.joystick.get_button(idx))

    # ---- 扳机 ----

    def _handle_triggers(self, cfg):
        n = self.joystick.get_numaxes()
        if n <= 4:
            return
        lt_raw = self.joystick.get_axis(4)
        rt_raw = self.joystick.get_axis(5)
        mode = cfg.get("trigger_mode", "note")
        if mode == "cc":
            self.midi.cc_smoothed(int(cfg.get("trigger_cc_lt", 11)), trigger_axis_to_value(lt_raw))
            self.midi.cc_smoothed(int(cfg.get("trigger_cc_rt", 12)), trigger_axis_to_value(rt_raw))
            return
        # note / velocity 模式
        threshold = 0.5 if mode == "note" else 0.05
        lt_down = lt_raw > threshold
        rt_down = rt_raw > threshold
        for side, down in (("lt", lt_down), ("rt", rt_down)):
            was = self.trigger_states[side]
            if down and not was:
                self.trigger_states[side] = True
                if mode == "velocity":
                    vel = trigger_axis_to_value(lt_raw if side == "lt" else rt_raw)
                    self._trigger_note_on(side, cfg, vel)
                else:
                    self._trigger_note_on(side, cfg, None)
            elif not down and was:
                self.trigger_states[side] = False
                self._trigger_note_off(side)

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
        if self.joystick.get_numhats() < 1:
            return
        hat = self.joystick.get_hat(0)
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
            skip = {int(cfg.get("l3_button", 8)), int(cfg.get("r3_button", 9))}
        for i in range(self.joystick.get_numbuttons()):
            pressed = bool(self.joystick.get_button(i))
            was = self.button_states.get(i, False)
            if i in skip:
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
        key = self._button_key(idx)
        if key is None:
            return
        note = int(cfg["note_mappings"].get(key, 60))
        velocity = self._velocity_for(cfg)
        self.hold_start[idx] = time.time()
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
        key = self._button_key(idx)
        if key is None:
            return
        note = int(cfg["note_mappings"].get(key, 60))
        self.midi.note_on(note, vel)

    def _button_released(self, idx, cfg):
        self.hold_start.pop(idx, None)
        key = self._button_key(idx)
        if key is None:
            return
        note = int(cfg["note_mappings"].get(key, 60))
        self.midi.note_off(note)

    def _button_key(self, idx) -> str | None:
        return {0: "button_a", 1: "button_b", 2: "button_x", 3: "button_y",
                4: "lb", 5: "rb", 6: "button_back", 7: "button_start",
                8: "l3", 9: "r3"}.get(idx)

    def _note_off_for_button(self, idx):
        cfg = self.get_config()["gamepad"]
        key = self._button_key(idx)
        if key and key in cfg["note_mappings"]:
            self.midi.note_off(int(cfg["note_mappings"][key]))

    def _velocity_for(self, cfg) -> int:
        mode = cfg.get("velocity_mode", "fixed")
        if mode == "random":
            return velocity_random(int(cfg.get("velocity_min", 40)),
                                   int(cfg.get("velocity_max", 127)))
        return int(cfg.get("velocity_fixed", 127))

    # ---- 状态推送 ----

    def _push_state(self):
        now = time.time()
        if now - self._last_state_push < 0.1:
            return
        self._last_state_push = now
        cfg = self.get_config()["gamepad"]
        axes = [round(self.joystick.get_axis(i), 3) for i in range(self.joystick.get_numaxes())]
        buttons = [bool(self.joystick.get_button(i)) for i in range(self.joystick.get_numbuttons())]
        # 十字键合成到 buttons[10..13]：↑ ↓ ← →
        buttons += [False] * max(0, 4 - len(buttons))
        hat = self.last_hat
        buttons[10] = buttons[10] or (hat == (0, 1))
        buttons[11] = buttons[11] or (hat == (0, -1))
        buttons[12] = buttons[12] or (hat == (-1, 0))
        buttons[13] = buttons[13] or (hat == (1, 0))
        self.bus.emit("gamepad.state",
                      connected=True,
                      name=self.joystick.get_name(),
                      axes=axes,
                      buttons=buttons,
                      mode=cfg.get("mode", "relative"))