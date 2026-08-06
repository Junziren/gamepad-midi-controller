"""MIDI 输出引擎：统一通道、消息发送、CC 平滑、事件广播"""

import time

try:
    import mido
except Exception:
    mido = None


class MidiEngine:
    def __init__(self, bus, port_manager, config_getter):
        self.bus = bus
        self.ports = port_manager
        self.get_config = config_getter
        self._smooth = {}      # (channel, cc) -> current value
        self._last_sent = {}   # (channel, cc) -> last int sent

    # ---- 基础发送 ----

    def _channel(self, channel):
        if channel is None:
            channel = int(self.get_config()["midi"].get("channel", 1))
        return max(0, min(15, channel - 1))

    def send_message(self, msg_type: str, channel=None, **fields):
        if mido is None:
            return
        ch = self._channel(channel)
        try:
            msg = mido.Message(msg_type, channel=ch, **fields)
        except Exception as exc:
            self.bus.emit("log", message=f"消息构造失败 {msg_type}: {exc}")
            return
        if not self.ports.send_message(msg):
            return
        self.bus.emit("midi.event", type=msg_type, channel=ch, fields=dict(fields))
        self.bus.emit("midi.activity", kind=msg_type)

    def note_on(self, note: int, velocity: int = 100, channel=None):
        self.send_message("note_on", channel=channel, note=int(note), velocity=int(velocity))

    def note_off(self, note: int, channel=None):
        self.send_message("note_off", channel=channel, note=int(note), velocity=0)

    def cc(self, control: int, value: int, channel=None):
        self.send_message("control_change", channel=channel, control=int(control), value=int(value))

    def pitch_bend(self, value14: int, channel=None):
        self.send_message("pitchwheel", channel=channel, pitch=int(value14))

    # ---- CC 平滑发送 ----

    def cc_smoothed(self, control: int, target: int, channel=None, smoothing: float | None = None):
        """带 EMA 平滑的 CC 发送；值变化小于 cc_min_delta 时不发送"""
        cfg = self.get_config()["midi"]
        if smoothing is None:
            smoothing = float(cfg.get("smoothing", 0.0))
        min_delta = int(cfg.get("cc_min_delta", 1))
        ch = self._channel(channel)
        key = (ch, int(control))
        target = int(target)
        if smoothing > 0 and key in self._smooth:
            cur = self._smooth[key] + smoothing * (target - self._smooth[key])
        else:
            cur = float(target)
        self._smooth[key] = cur
        cur_int = int(round(cur))
        if abs(cur_int - self._last_sent.get(key, -999)) >= min_delta:
            self.cc(int(control), cur_int, channel=ch + 1)
            self._last_sent[key] = cur_int