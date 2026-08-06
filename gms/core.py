"""纯计算函数：曲线、死区、CC 换算、力度、音序器/Clip/映射规则。
全部无副作用，便于单元测试。"""

import random


def clamp(value, low, high):
    return max(low, min(high, value))


def apply_deadzone(value: float, deadzone: float) -> float:
    """死区：|value| < deadzone 归零"""
    return 0.0 if abs(value) < deadzone else value


def apply_curve(value: float, curve: str, sensitivity: float, exp: float = 2.0) -> float:
    """摇杆响应曲线。linear: v*sen；exponential: sign(v)*|v|^exp*sen"""
    v = float(value)
    if curve == "exponential":
        return (1.0 if v >= 0 else -1.0) * (abs(v) ** exp) * sensitivity
    return v * sensitivity


def axis_to_cc_absolute(axis: float) -> int:
    """摇杆轴(-1..1)绝对映射为 CC(0..127)，中心=64"""
    return int(round(clamp((axis + 1.0) * 63.5, 0, 127)))


def axis_to_cc_absolute_centered(axis: float, center_deadzone: float = 0.05) -> int:
    """中心死区：轴偏移小于阈值视为中心(64)，避免漂移跳变"""
    if abs(axis) < center_deadzone:
        return 64
    return axis_to_cc_absolute(axis)


def relative_cc_delta(stick_value: float, sensitivity: float) -> float:
    return stick_value * sensitivity


def velocity_random(min_v: int, max_v: int) -> int:
    return random.randint(min_v, max_v)


def velocity_hold_pressure(elapsed_ms: float, min_v: int, max_v: int, ramp_ms: float = 150.0) -> int:
    """按住时长力度：按住越久力度越大，ramp_ms 后达到 max_v"""
    ratio = clamp(elapsed_ms / max(1.0, ramp_ms), 0.0, 1.0)
    return int(round(min_v + (max_v - min_v) * ratio))


def trigger_axis_to_value(axis: float) -> int:
    """扳机轴(0..1)映射为 CC 值 0..127"""
    return int(round(clamp(axis, 0.0, 1.0) * 127))


def pitch_bend_from_wheel(step: int, step_size: int, current: int) -> int:
    """滚轮增量换算为 14bit pitch bend(-8192..8191)，返回新值"""
    return clamp(current + step * step_size, -8192, 8191)


# ---------- 音序器 ----------


def sequencer_step_duration_ms(bpm: float, steps: int, swing: float = 0.0, step_index: int = 0) -> float:
    """单步时长(ms)。swing 0..1：偶数步缩短、奇数步拉长"""
    base = 60000.0 / bpm * (4.0 / steps)  # 假设 4/4 拍，steps 为每小节步数
    if swing > 0 and step_index % 2 == 1:
        return base * (1.0 + swing)
    if swing > 0 and step_index % 2 == 0:
        return base * (1.0 - swing)
    return base


def gate_duration_ms(step_ms: float, gate: float) -> float:
    """步内 gate 时长(0..1 比例)"""
    return step_ms * clamp(gate, 0.01, 1.0)


# ---------- Clip 时间线 ----------


def clip_event_times(events: list) -> list:
    """Clip 事件表(相对毫秒)展开为绝对时间戳列表（含事件与触发时刻）"""
    schedule = []
    for ev in events:
        schedule.append((ev.get("t", 0), ev))
    schedule.sort(key=lambda x: x[0])
    out, acc = [], 0.0
    for t, ev in schedule:
        acc = t if t >= acc else acc
        out.append((acc, ev))
        acc += ev.get("duration", 0)
    return out


def clip_total_ms(events: list) -> float:
    times = clip_event_times(events)
    if not times:
        return 0.0
    return max(t + ev.get("duration", 0) for t, ev in times)


# ---------- MIDI 映射层规则 ----------


def apply_mapper_rules(msg_type: str, channel: int, data: dict, rules: list) -> list:
    """对一条 MIDI 消息应用规则，返回零或多条 (msg_type, channel, data)。
    data: note/cc/pitch 等字段。规则:
      {"action":"channel","from":ch,"to":ch}
      {"action":"note_shift","offset":n,"channel":ch|None}
      {"action":"cc_scale","cc":n,"factor":f,"offset":n,"reverse":bool,"channel":ch|None}
      {"action":"note_filter","channel":ch|None,"note_min":n,"note_max":n,"pass":true|false}
    """
    out = [(msg_type, channel, dict(data))]
    for rule in rules:
        action = rule.get("action")
        if action == "channel":
            if rule.get("from") is None or rule["from"] == channel:
                out = [(t, rule["to"], d) for t, c, d in out]
        elif action == "note_shift":
            if msg_type in ("note_on", "note_off") and (rule.get("channel") is None or rule["channel"] == channel):
                out = [(t, c, {**d, "note": clamp(d["note"] + rule.get("offset", 0), 0, 127)}) for t, c, d in out]
        elif action == "cc_scale":
            if msg_type == "control_change" and data.get("control") == rule.get("cc") and \
                    (rule.get("channel") is None or rule["channel"] == channel):
                v = data["value"] * rule.get("factor", 1.0) + rule.get("offset", 0)
                if rule.get("reverse"):
                    v = 127 - v
                out = [(t, c, {**d, "value": int(round(clamp(v, 0, 127)))}) for t, c, d in out]
        elif action == "note_filter":
            if msg_type in ("note_on", "note_off"):
                hit = (rule.get("channel") is None or rule["channel"] == channel) and \
                      rule.get("note_min", 0) <= data["note"] <= rule.get("note_max", 127)
                keep = hit if rule.get("pass", True) else not hit
                if not keep:
                    out = []
    return out