"""配置系统：多预设 Profile、默认配置、旧版配置迁移"""

import copy
import json
import os
import threading
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = APP_DIR / "profiles"
LEGACY_CONFIG = APP_DIR / "gamepad_midi_config.json"


DEFAULTS = {
    "midi": {
        "channel": 1,            # 全局 MIDI 通道 1-16
        "poll_ms": 5,            # 手柄轮询间隔
        "cc_min_delta": 1,       # CC 值变化超过该值才发送
        "smoothing": 0.0,        # CC EMA 平滑系数 0(关)..0.9
        "output_port": "",       # 输出端口名（空=自动：虚拟端口优先）
    },
    "virtual_midi": {
        "enabled": True,
        "port_name": "Gamepad MIDI 1",
        "backend": "tevirtualmidi",   # 预留: "windows_midi_services"
    },
    "gamepad": {
        "joystick_id": 0,
        "mode": "relative",          # relative | xy_absolute
        "sensitivity": 3.0,
        "deadzone": 0.15,
        "curve": "linear",           # linear | exponential
        "curve_exp": 2.0,
        "invert_y": True,
        "l3_button": -1,           # -1=自动(SDL映射/设备表)，>=0=手动指定原始按钮索引
        "r3_button": -1,
        "xy_center_deadzone": 0.05,
        "velocity_mode": "fixed",    # fixed | hold | random
        "velocity_fixed": 127,
        "velocity_min": 40,
        "velocity_max": 127,
        "trigger_mode": "note",      # note | cc | velocity
        "trigger_cc_lt": 11,
        "trigger_cc_rt": 12,
        "cc_mappings": {
            "left_stick_x": 1,
            "left_stick_y": 2,
            "right_stick_x": 3,
            "right_stick_y": 4,
        },
        "note_mappings": {
            "button_a": 60, "button_b": 62, "button_x": 64, "button_y": 65,
            "dpad_up": 67, "dpad_down": 69, "dpad_left": 71, "dpad_right": 72,
            "lb": 74, "rb": 76, "lt": 77, "rt": 79,
        },
    },
    "tools": {
        "mouse_xy": {
            "enabled": False, "hotkey": ["ctrl", "alt"],
            "cc_x": 5, "cc_y": 6, "invert_y": True,
        },
        "screen_xy_pad": {
            "enabled": False, "cc_x": 7, "cc_y": 8, "invert_y": True,
        },
        "keyboard_pads": {
            "enabled": False, "suppress": False, "velocity_mode": "fixed",
            "velocity_fixed": 100,
            "pads": [
                {"key": "z", "note": 48}, {"key": "x", "note": 50},
                {"key": "c", "note": 52}, {"key": "v", "note": 53},
                {"key": "b", "note": 55}, {"key": "n", "note": 57},
                {"key": "m", "note": 59},
                {"key": "q", "note": 60}, {"key": "w", "note": 62},
                {"key": "e", "note": 64}, {"key": "r", "note": 65},
                {"key": "t", "note": 67}, {"key": "y", "note": 69},
                {"key": "u", "note": 71},
            ],
        },
        "chord_arp": {
            "enabled": False,
            "pads": [
                {"key": "1", "chord": [60, 64, 67], "arp": False, "arp_mode": "up", "arp_ms": 120},
                {"key": "2", "chord": [57, 60, 64], "arp": False, "arp_mode": "up", "arp_ms": 120},
                {"key": "3", "chord": [65, 69, 72], "arp": False, "arp_mode": "up", "arp_ms": 120},
                {"key": "4", "chord": [55, 59, 62], "arp": False, "arp_mode": "up", "arp_ms": 120},
            ],
        },
        "hotkey_clip": {
            "enabled": False,
            "clips": [
                {
                    "name": "上行音阶",
                    "hotkey": "<ctrl>+<alt>+1",
                    "loop": False,
                    "channel": 1,
                    "events": [
                        {"type": "note_on", "note": 60, "velocity": 100, "t": 0, "duration": 120},
                        {"type": "note_on", "note": 62, "velocity": 100, "t": 120, "duration": 120},
                        {"type": "note_on", "note": 64, "velocity": 100, "t": 240, "duration": 120},
                        {"type": "note_on", "note": 65, "velocity": 100, "t": 360, "duration": 480},
                    ],
                }
            ],
        },
        "step_sequencer": {
            "enabled": False, "steps": 16, "bpm": 120.0, "swing": 0.0,
            "channel": 1, "modulate": "none",  # none | note | cc
            "modulate_cc": 74,
            "notes": [60, 62, 64, 65, 67, 69, 71, 72, 72, 71, 69, 67, 65, 64, 62, 60],
            "velocities": [100] * 16,
            "gates": [0.5] * 16,
            "on": [True, False, True, False, True, False, True, False,
                   True, False, True, False, True, False, True, False],
            "ccs": [None] * 16,
        },
        "wheel_bend": {
            "enabled": False, "hotkey": ["ctrl", "shift"],
            "mode": "pitch",       # pitch | cc
            "cc": 74, "step_size": 341,
        },
        "midi_mapper": {
            "enabled": False,
            "rules": [],
        },
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base 的副本上"""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class ProfileManager:
    """多预设配置管理。current() 返回当前配置 dict（读线程安全）。"""

    def __init__(self, profiles_dir: Path = PROFILES_DIR):
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.current_name = "default"
        self._config = copy.deepcopy(DEFAULTS)
        self._lock = threading.RLock()
        self._ensure_default_profile()

    # ---- 内部 ----

    @staticmethod
    def _normalize(cfg: dict) -> dict:
        """配置归一化：旧版 l3/r3 默认 8/9 改为 -1（自动识别布局）。"""
        gp = cfg.get("gamepad")
        if isinstance(gp, dict) and gp.get("l3_button") == 8 and gp.get("r3_button") == 9:
            gp["l3_button"] = -1
            gp["r3_button"] = -1
        return cfg

    def _profile_path(self, name: str) -> Path:
        return self.profiles_dir / f"{name}.json"

    def _ensure_default_profile(self):
        if not self._profile_path("default").exists():
            self.save_profile("default")
        self.load_profile("default")

    # ---- 读写 ----

    def current(self) -> dict:
        return self._config

    def update(self, patch: dict):
        """合并写入补丁并持久化"""
        with self._lock:
            self._config = deep_merge(self._config, patch)
            self.save_profile(self.current_name)

    def load_profile(self, name: str) -> bool:
        path = self._profile_path(name)
        if not path.exists():
            return False
        with self._lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
            self._config = self._normalize(deep_merge(DEFAULTS, data))
            self.current_name = name
        return True

    def save_profile(self, name: str):
        path = self._profile_path(name)
        path.write_text(json.dumps(self._config, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def new_profile(self, name: str) -> bool:
        path = self._profile_path(name)
        if path.exists():
            return False
        self.save_profile(name)
        return self.load_profile(name)

    def delete_profile(self, name: str) -> bool:
        if name == "default":
            return False
        path = self._profile_path(name)
        if not path.exists():
            return False
        path.unlink()
        if self.current_name == name:
            self.load_profile("default")
        return True

    def list_profiles(self) -> list:
        return sorted(p.stem for p in self.profiles_dir.glob("*.json"))

    def export_profile(self, name: str) -> dict:
        path = self._profile_path(name)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def import_profile(self, name: str, data: dict) -> bool:
        merged = self._normalize(deep_merge(DEFAULTS, data))
        self._profile_path(name).write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    # ---- 旧版迁移 ----

    def migrate_legacy(self) -> bool:
        """读取旧 gamepad_midi_config.json 合并到当前配置，成功返回 True"""
        if not LEGACY_CONFIG.exists():
            return False
        try:
            old = json.loads(LEGACY_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        patch = {}
        if isinstance(old.get("midi_port"), str):
            patch.setdefault("virtual_midi", {})["port_name"] = old["midi_port"]
        if isinstance(old.get("relative_sensitivity"), (int, float)):
            patch.setdefault("gamepad", {})["sensitivity"] = float(old["relative_sensitivity"])
        if isinstance(old.get("stick_deadzone"), (int, float)):
            patch.setdefault("gamepad", {})["deadzone"] = float(old["stick_deadzone"])
        if isinstance(old.get("cc_mappings"), dict):
            patch.setdefault("gamepad", {})["cc_mappings"] = dict(old["cc_mappings"])
        if isinstance(old.get("note_mappings"), dict):
            patch.setdefault("gamepad", {})["note_mappings"] = dict(old["note_mappings"])
        if patch:
            self.update(patch)
            return True
        return False