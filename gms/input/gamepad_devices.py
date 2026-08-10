"""Windows gamepad device adapters.

Xbox-compatible controllers use the native XInput state as the primary live
source. SDL is retained for discovery, hot-plug events, and non-XInput devices;
HID remains an explicit fallback for devices that need semantic report decoding.
All adapters expose the small pygame Joystick surface used by GamepadEngine.
"""

from __future__ import annotations

import threading
import time
import ctypes
import sys

import pygame

if sys.platform == "win32":
    try:
        from pywinusb import hid
        from pywinusb.hid.core import HidP_Input, ReportItem
    except Exception:
        hid = None
        HidP_Input = 0
        ReportItem = None
else:
    hid = None
    HidP_Input = 0
    ReportItem = None


HAT_DIRECTIONS = (
    (0, 1), (1, 1), (1, 0), (1, -1),
    (0, -1), (-1, -1), (-1, 0), (-1, 1),
)


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_uint32),
        ("Gamepad", _XInputGamepad),
    ]


class XInputJoystick:
    """Direct XInput reader for Xbox-compatible Windows controllers."""

    standard_layout = False
    backend_name = "XInput"

    _BUTTON_MASKS = (
        0x1000,  # A
        0x2000,  # B
        0x4000,  # X
        0x8000,  # Y
        0x0100,  # LB
        0x0200,  # RB
        0x0020,  # Back
        0x0010,  # Start
        0x0040,  # L3
        0x0080,  # R3
    )

    def __init__(self, source_joystick, dll, get_state, slot, initial_state):
        self._source = source_joystick
        self._dll = dll
        self._get_state = get_state
        self._slot = slot
        self._lock = threading.RLock()
        self._axes, self._buttons, self._hat = self._decode_state(initial_state)
        self._packet = int(initial_state.dwPacketNumber)
        self._changed = True
        self._last_change = time.monotonic()
        self._connected = True

    @staticmethod
    def _load_api():
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                dll = windll.LoadLibrary(name)
                get_state = dll.XInputGetState
                get_state.argtypes = [ctypes.c_uint32, ctypes.POINTER(_XInputState)]
                get_state.restype = ctypes.c_uint32
                return dll, get_state
            except (AttributeError, OSError):
                continue
        return None

    @classmethod
    def try_open(cls, source_joystick=None, preferred_slot=None):
        """Return an active XInput adapter, including without an SDL device."""
        api = cls._load_api()
        if api is None:
            return None
        dll, get_state = api
        slots = range(4)
        if preferred_slot is not None and 0 <= int(preferred_slot) < 4:
            preferred = int(preferred_slot)
            slots = (preferred, *(slot for slot in range(4) if slot != preferred))
        for slot in slots:
            state = _XInputState()
            try:
                result = get_state(slot, ctypes.byref(state))
            except (OSError, ctypes.ArgumentError):
                continue
            if result == 0:
                return cls(source_joystick, dll, get_state, slot, state)
        return None

    @staticmethod
    def _normalize_thumb(value):
        if value >= 0:
            return min(1.0, float(value) / 32767.0)
        return max(-1.0, float(value) / 32768.0)

    @classmethod
    def _decode_state(cls, state):
        gamepad = state.Gamepad
        lx = cls._normalize_thumb(gamepad.sThumbLX)
        ly = cls._normalize_thumb(gamepad.sThumbLY)
        rx = cls._normalize_thumb(gamepad.sThumbRX)
        ry = cls._normalize_thumb(gamepad.sThumbRY)
        buttons = [bool(gamepad.wButtons & mask) for mask in cls._BUTTON_MASKS]
        buttons.append(False)  # Guide is not exposed by XInputGetState.
        hat_x = int(bool(gamepad.wButtons & 0x0008)) - int(bool(gamepad.wButtons & 0x0004))
        hat_y = int(bool(gamepad.wButtons & 0x0001)) - int(bool(gamepad.wButtons & 0x0002))
        axes = [lx, -ly, rx, -ry,
                float(gamepad.bLeftTrigger) / 255.0,
                float(gamepad.bRightTrigger) / 255.0]
        return axes, buttons, (hat_x, hat_y)

    def process_event(self, event) -> bool:
        return False

    def poll_refresh(self):
        state = _XInputState()
        try:
            result = self._get_state(self._slot, ctypes.byref(state))
        except (OSError, ctypes.ArgumentError):
            result = 1
        if result != 0:
            with self._lock:
                self._connected = False
            return False
        axes, buttons, hat = self._decode_state(state)
        with self._lock:
            self._connected = True
            changed = (int(state.dwPacketNumber) != self._packet or
                       axes != self._axes or buttons != self._buttons or hat != self._hat)
            self._packet = int(state.dwPacketNumber)
            self._axes, self._buttons, self._hat = axes, buttons, hat
            self._changed = self._changed or changed
            if changed:
                self._last_change = time.monotonic()
            return changed

    def consume_changed(self):
        with self._lock:
            changed = self._changed
            self._changed = False
            return changed

    def snapshot(self):
        with self._lock:
            return (list(self._axes), list(self._buttons), self._hat,
                    6, len(self._buttons), "xinput")

    def last_change(self):
        with self._lock:
            return self._last_change

    def is_connected(self):
        state = _XInputState()
        try:
            result = self._get_state(self._slot, ctypes.byref(state))
        except (OSError, ctypes.ArgumentError):
            result = 1
        with self._lock:
            self._connected = result == 0
            return self._connected

    def init(self):
        return None

    def quit(self):
        if self._source is not None:
            self._source.quit()

    def get_name(self):
        if self._source is not None:
            return self._source.get_name()
        return f"XInput Controller {self._slot + 1}"

    def get_guid(self):
        if self._source is not None:
            return self._source.get_guid()
        return ""

    def get_instance_id(self):
        if self._source is not None:
            return self._source.get_instance_id()
        return 0x58490000 + self._slot

    def get_numaxes(self):
        return 6

    def get_axis(self, index):
        with self._lock:
            return self._axes[index]

    def get_numbuttons(self):
        with self._lock:
            return len(self._buttons)

    def get_button(self, index):
        with self._lock:
            return self._buttons[index]

    def get_numhats(self):
        return 1

    def get_hat(self, index):
        with self._lock:
            return self._hat if index == 0 else (0, 0)


class SdlEventJoystick:
    """pygame joystick whose state is updated from SDL events.

    On Windows, JOY* events can arrive while Joystick.get_* keeps returning a
    stale snapshot. Caching event payloads avoids that split-brain behavior.
    """

    standard_layout = False
    backend_name = "SDL 事件"

    def __init__(self, joystick):
        self._lock = threading.RLock()
        self._joystick = joystick
        self._instance_id = joystick.get_instance_id()
        self._axes = [float(joystick.get_axis(i))
                      for i in range(joystick.get_numaxes())]
        self._buttons = [bool(joystick.get_button(i))
                         for i in range(joystick.get_numbuttons())]
        self._has_hat = bool(joystick.get_numhats())
        self._hat = joystick.get_hat(0) if self._has_hat else (0, 0)
        self._changed = False
        self._last_change = 0.0
        self._event_wins_axes = {}     # axis idx -> monotonic ts
        self._event_wins_buttons = {}  # button idx -> monotonic ts
        self._event_win_seconds = 0.5
        self._event_axes_seen = set()
        self._event_buttons_seen = set()
        self._event_hat_seen = False

    def process_event(self, event) -> bool:
        instance_id = getattr(event, "instance_id", None)
        if instance_id is None:
            instance_id = getattr(event, "joy", None)
        if instance_id is not None and instance_id != self._instance_id:
            return False
        with self._lock:
            changed = False
            if event.type == pygame.JOYAXISMOTION:
                axis = int(event.axis)
                self._ensure_axes(axis + 1)
                value = float(event.value)
                changed = self._axes[axis] != value
                self._axes[axis] = value
                self._event_wins_axes[axis] = time.monotonic()
                self._event_axes_seen.add(axis)
            elif event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                button = int(event.button)
                self._ensure_buttons(button + 1)
                value = event.type == pygame.JOYBUTTONDOWN
                changed = self._buttons[button] != value
                self._buttons[button] = value
                self._event_wins_buttons[button] = time.monotonic()
                self._event_buttons_seen.add(button)
            elif event.type == pygame.JOYHATMOTION:
                value = tuple(event.value)
                changed = self._hat != value
                self._hat = value
                self._event_hat_seen = True
            self._changed = self._changed or changed
            if changed:
                self._last_change = time.monotonic()
            return changed

    def poll_refresh(self):
        """每帧直读 SDL 实时状态；最近收到过事件的索引保持事件值。"""
        with self._lock:
            now = time.monotonic()
            changed = False
            n = self._joystick.get_numaxes()
            self._ensure_axes(n)
            for i in range(n):
                if i in self._event_axes_seen:
                    continue
                if now - self._event_wins_axes.get(i, 0.0) < self._event_win_seconds:
                    continue
                value = float(self._joystick.get_axis(i))
                if self._axes[i] != value:
                    self._axes[i] = value
                    changed = True
            m = self._joystick.get_numbuttons()
            self._ensure_buttons(m)
            for i in range(m):
                if i in self._event_buttons_seen:
                    continue
                if now - self._event_wins_buttons.get(i, 0.0) < self._event_win_seconds:
                    continue
                value = bool(self._joystick.get_button(i))
                if self._buttons[i] != value:
                    self._buttons[i] = value
                    changed = True
            if self._joystick.get_numhats() and not self._event_hat_seen:
                hat = self._joystick.get_hat(0)
                if hat != self._hat:
                    self._hat = hat
                    changed = True
            self._changed = self._changed or changed
            if changed:
                self._last_change = time.monotonic()
            return changed

    def consume_changed(self) -> bool:
        with self._lock:
            changed = self._changed
            self._changed = False
            return changed

    def snapshot(self):
        """一次性取回当前状态：同一来源的轴/按钮/十字键快照。"""
        with self._lock:
            return (list(self._axes), list(self._buttons),
                    self._hat if self._has_hat else None,
                    len(self._axes), len(self._buttons), "sdl")

    def last_change(self) -> float:
        with self._lock:
            return self._last_change

    def _ensure_axes(self, size):
        if len(self._axes) < size:
            self._axes.extend([0.0] * (size - len(self._axes)))

    def _ensure_buttons(self, size):
        if len(self._buttons) < size:
            self._buttons.extend([False] * (size - len(self._buttons)))

    def init(self):
        return None

    def quit(self):
        self._joystick.quit()

    def get_name(self):
        return self._joystick.get_name()

    def get_guid(self):
        return self._joystick.get_guid()

    def get_instance_id(self):
        return self._instance_id

    def get_numaxes(self):
        with self._lock:
            return len(self._axes)

    def get_axis(self, index):
        with self._lock:
            return self._axes[index]

    def get_numbuttons(self):
        with self._lock:
            return len(self._buttons)

    def get_button(self, index):
        with self._lock:
            return self._buttons[index]

    def get_numhats(self):
        return 1

    def get_hat(self, index):
        with self._lock:
            return self._hat if index == 0 else (0, 0)


class HidJoystick:
    """Semantic HID adapter backed by pywinusb."""

    standard_layout = True
    backend_name = "Windows HID"

    def __init__(self, device, source_joystick):
        self._device = device
        self._source = source_joystick
        self._instance_id = source_joystick.get_instance_id()
        self._lock = threading.Lock()
        self._axes = [0.0, 0.0, 0.0, 0.0, -1.0, -1.0]
        self._hat = (0, 0)
        self._changed = False
        self._last_hid_report = 0.0    # 任何 HID 报告到达时刻（设备存活证据）
        self._last_hid_change = 0.0    # HID 数值发生变化时刻
        self._last_sdl_change = 0.0    # SDL 影子数值发生变化时刻
        self._reports = {}
        self._caps = {}
        self._usage_values = {}
        self._button_usages = []     # 逻辑按钮 -> HID usage（升序）
        self._bitfield_usages = []   # (usage, bit_count) 按钮位域
        self._buttons = []
        self._fault = ""
        self._last_update = 0.0
        self._device.open(shared=True)
        caps = self._device.hid_caps
        if caps.usage_page != 1 or caps.usage not in (4, 5, 8):
            self._device.close()
            raise RuntimeError("HID interface is not a game controller")
        self._build_reports()
        self._device.set_raw_data_handler(self._on_raw_data)
        # SDL 兜底影子：HID 读线程静默（蓝牙 GATT 被系统独占等）时，
        # 用 SDL 事件 + 直读状态维持输入链路，避免引擎永久无数据。
        self._sdl = SdlEventJoystick(source_joystick)
        self._fresh_seconds = 2.0

    def _build_reports(self):
        usage_caps = self._device.usages_storage.get(HidP_Input, [])
        for cap in usage_caps:
            if not cap.is_value:
                continue
            if not cap.is_range:
                self._caps[(cap.usage_page, cap.usage)] = cap
            elif cap.usage_min == cap.usage_max:
                # 单值项以 range 形式声明（usage_min==usage_max）同样按该 usage 收录，
                # 否则 BLE 变体的右扳机（声明在其它页）会从 _extra_trigger_value 漏掉。
                self._caps[(cap.usage_page, cap.usage_min)] = cap
        # 按钮 usage 收集（page 9）：独立按钮优先，缺失时识别 value 位域
        button_usage = set()
        bitfield = []
        for cap in usage_caps:
            if cap.usage_page != 9:
                continue
            if cap.is_button:
                if cap.is_range:
                    button_usage.update(range(cap.usage_min, cap.usage_max + 1))
                else:
                    button_usage.add(cap.usage)
            elif cap.is_value and cap.report_count == 1 and cap.bit_size >= 8:
                usage = cap.usage if hasattr(cap, "usage") else cap.usage_min
                bitfield.append((usage, cap.bit_size))
        if not button_usage and bitfield:
            # 按钮位域（如 usage 1 的 16bit）：按位展开
            for usage, bits in bitfield:
                button_usage.update(range(usage, usage + bits))
            self._bitfield_usages = list(bitfield)
        self._button_usages = sorted(button_usage)
        self._buttons = [False] * len(self._button_usages)
        for report in self._device.find_input_reports():
            self._restore_inclusive_button_ranges(report, usage_caps)
            self._reports[report.report_id] = report

    @staticmethod
    def _restore_inclusive_button_ranges(report, usage_caps):
        # pywinusb 0.4.2 builds range(usage_min, usage_max), dropping usage_max.
        # Add that final item so R3/Guide is not silently lost.
        for cap in usage_caps:
            if not cap.is_button or not cap.is_range or cap.report_id != report.report_id:
                continue
            key = (cap.usage_page << 16) | cap.usage_max
            if report.has_key(key):
                continue
            item = ReportItem(report, cap, cap.usage_max)
            report._HidReport__items[item.key()] = item
            report._HidReport__idx_items[item.data_index] = item

    def _on_raw_data(self, raw_data):
        # pywinusb 处理线程对 handler 异常无保护：一次异常会永久冻结输入流，
        # 因此在这里兜底捕获并标记故障，由引擎层强制重连回退。
        try:
            self._handle_raw(raw_data)
        except Exception as exc:
            with self._lock:
                if not self._fault:
                    self._fault = f"{type(exc).__name__}: {exc}"

    def _handle_raw(self, raw_data):
        if not raw_data:
            return
        if len(self._reports) == 1:
            # 无报告 ID 的设备：raw_data 首字节是数据而非 ID，
            # 直接使用唯一输入报告，避免按首字节查表导致全部报告被丢弃。
            report = next(iter(self._reports.values()))
        else:
            report = self._reports.get(int(raw_data[0]))
            if report is None:
                return
        report.set_raw_data(raw_data)
        values = {(item.page_id, item.usage_id): item.get_value()
                  for _, item in report.items()}
        with self._lock:
            # 某些蓝牙 HID 描述符把轴、按钮和扳机拆到不同报告中。
            # 每份报告只更新自己声明的 usage，不能把缺失字段当成释放/回中。
            usage_values = getattr(self, "_usage_values", None)
            if usage_values is None:
                usage_values = self._usage_values = {}
            usage_values.update(values)
            usages = dict(usage_values)
            axes = self._decode_axes(usages)
            buttons = self._decode_buttons(usages)
            hat = self._decode_hat(usages.get((1, 0x39)))
            changed = (axes != self._axes or buttons != self._buttons or hat != self._hat)
            self._axes = axes
            self._buttons = buttons
            self._hat = hat
            self._last_update = time.time()
            self._last_hid_report = self._last_update
            if changed:
                self._last_hid_change = self._last_update
            self._changed = self._changed or changed

    def _decode_buttons(self, usages):
        out = [False] * len(self._button_usages)
        for i, usage in enumerate(self._button_usages):
            v = usages.get((9, usage))
            if v is not None:
                out[i] = bool(v & 1)
        for usage, bits in self._bitfield_usages:
            v = usages.get((9, usage))
            if v is None:
                continue
            for k in range(bits):
                u = usage + k
                if u in self._button_usages:
                    out[self._button_usages.index(u)] = bool((v >> k) & 1)
        return out

    def has_fault(self) -> bool:
        with self._lock:
            return bool(self._fault)

    def fault_reason(self) -> str:
        with self._lock:
            return self._fault

    def _decode_axes(self, usages):
        """按描述符实际 usage 布局解码（同一组 usage 在两类设备上语义不同）：

        - Xbox 360 家族：Z(0x32) 为 8 位组合扳机轴（-1..1，正=LT 负=RT），
          Rx(0x33)=右摇杆X，Ry(0x34)=右摇杆Y。
        - Xbox One/BLE 家族：Z(0x32)=右摇杆X，Rx(0x33)=右摇杆Y，
          Ry(0x34)=左扳机，Rz(0x35)=右扳机；部分 BLE 固件把右扳机
          声明在其它 usage page（无 0x35），取第一个未用值项（SDL
          官方映射 righttrigger:a5 即按此顺序枚举）。
        用 0x32 的位宽区分两种布局（8 位=360 组合扳机，16 位=One 摇杆）。"""
        lx = self._normalized(usages, 1, 0x30)
        ly = self._normalized(usages, 1, 0x31)
        z = self._normalized(usages, 1, 0x32)
        rx = self._normalized(usages, 1, 0x33)
        ry = self._normalized(usages, 1, 0x34)
        rz = self._normalized(usages, 1, 0x35)

        cap_z = self._caps.get((1, 0x32))
        if z is not None and cap_z is not None and int(cap_z.bit_size) <= 8:
            # Xbox 360 布局：组合扳机轴拆分 LT/RT
            lt = max(0.0, z) * 2.0 - 1.0
            rt = max(0.0, -z) * 2.0 - 1.0
            return [lx or 0.0, ly or 0.0, rx or 0.0, ry or 0.0, lt, rt]

        # One/BLE 布局：Z=右摇杆X，Rx=右摇杆Y，Ry=左扳机，Rz=右扳机
        right_x = z if z is not None else (rx or 0.0)
        right_y = rx if rx is not None else 0.0
        lt = ry if ry is not None else -1.0
        if rz is None:
            rz = self._extra_trigger_value(usages)
        rt = rz if rz is not None else -1.0
        return [lx or 0.0, ly or 0.0, right_x, right_y, lt, rt]

    def _extra_trigger_value(self, usages):
        """BLE 变体：右扳机声明在其它 usage page 时，
        取第一个未用于摇杆/扳机的值项（与 SDL 枚举顺序一致）。"""
        known = {(1, 0x30), (1, 0x31), (1, 0x32), (1, 0x33),
                 (1, 0x34), (1, 0x35), (1, 0x39)}
        for key in self._caps:
            if key in known or key[0] == 9:
                continue
            value = usages.get(key)
            if value is not None:
                return self._normalized_value(key, value)
        return None

    def _normalized_value(self, key, value):
        cap = self._caps.get(key)
        if cap is None:
            return None
        low = int(cap.logical_min)
        high = int(cap.logical_max)
        if high < low:
            high += 1 << int(cap.bit_size)
        if high == low:
            return 0.0
        return max(-1.0, min(1.0, ((float(value) - low) / (high - low)) * 2.0 - 1.0))

    def _normalized(self, usages, page, usage):
        value = usages.get((page, usage))
        cap = self._caps.get((page, usage))
        if value is None or cap is None:
            return None
        low = int(cap.logical_min)
        high = int(cap.logical_max)
        if high < low:
            high += 1 << int(cap.bit_size)
        if high == low:
            return 0.0
        return max(-1.0, min(1.0, ((float(value) - low) / (high - low)) * 2.0 - 1.0))

    def _decode_hat(self, value):
        if value is None:
            return (0, 0)
        cap = self._caps.get((1, 0x39))
        if cap is None:
            return (0, 0)
        low = int(cap.logical_min)
        high = int(cap.logical_max)
        value = int(value)
        if value < low or value > high:
            return (0, 0)
        count = high - low + 1
        if count < 4:
            return (0, 0)
        index = round((value - low) * 8 / count) % 8
        return HAT_DIRECTIONS[index]

    def process_event(self, event):
        if self._sdl.process_event(event):
            with self._lock:
                self._last_sdl_change = time.time()
        return False

    def poll_refresh(self):
        """SDL 直读兜底：每帧刷新影子状态，事件丢失时仍能感知输入。"""
        if self._sdl.poll_refresh():
            with self._lock:
                self._last_sdl_change = time.time()
            return True
        return False

    def _sdl_active(self) -> bool:
        """HID 超过 _fresh_seconds 无数据时，回退使用 SDL 影子状态。"""
        return time.time() - self._last_update > self._fresh_seconds

    def _prefer_hid(self) -> bool:
        """调用方须已持有 _lock。最近 0.5s 内有过 HID 报告（设备存活），
        或 SDL 影子不比 HID 更新时，以 HID 为准；否则回退 SDL。
        防止 HID/SDL 逐帧交替取值造成抖动。"""
        return self._last_hid_report + 0.5 >= self._last_sdl_change

    def snapshot(self):
        """一次性取回快照：整帧只来自一个来源（HID 或 SDL 影子），
        避免同一帧内混读两种数值语义造成跳变。"""
        with self._lock:
            if self._prefer_hid():
                return (list(self._axes), list(self._buttons), self._hat,
                        len(self._axes), len(self._buttons), "hid")
        sdl = self._sdl.snapshot()
        return (sdl[0], sdl[1], sdl[2], sdl[3], sdl[4], "sdl")

    def consume_changed(self):
        with self._lock:
            changed = self._changed
            self._changed = False
        return changed or self._sdl.consume_changed()

    def init(self):
        return None

    def quit(self):
        self._device.close()
        self._source.quit()

    def get_name(self):
        return self._source.get_name()

    def get_guid(self):
        return self._source.get_guid()

    def get_instance_id(self):
        return self._instance_id

    def get_numaxes(self):
        return 6

    def get_axis(self, index):
        if self._sdl_active():
            return self._sdl.get_axis(index)
        with self._lock:
            return self._axes[index]

    def get_numbuttons(self):
        with self._lock:
            return len(self._buttons)

    def get_button(self, index):
        if self._sdl_active():
            return self._sdl.get_button(index)
        with self._lock:
            return self._buttons[index]

    def get_numhats(self):
        return 1

    def get_hat(self, index):
        if self._sdl_active():
            return self._sdl.get_hat(index)
        with self._lock:
            return self._hat if index == 0 else (0, 0)


def open_gamepad(source_joystick, vid: int, pid: int, prefer_sdl: bool = True,
                 prefer_xinput: bool = True):
    """Open the most reliable native source for the discovered controller."""
    name = ""
    try:
        name = str(source_joystick.get_name()).lower()
    except Exception:
        pass
    looks_like_xbox = source_joystick is None or vid == 0x045E or "xbox" in name
    if prefer_xinput and looks_like_xbox:
        joystick = XInputJoystick.try_open(source_joystick)
        if joystick is not None:
            return joystick
    if source_joystick is None:
        return None
    if hid is not None and vid and pid and (not prefer_sdl or looks_like_xbox):
        devices = hid.HidDeviceFilter(vendor_id=vid, product_id=pid).get_devices()
        for device in devices:
            try:
                return HidJoystick(device, source_joystick)
            except Exception:
                try:
                    device.close()
                except Exception:
                    pass
    return SdlEventJoystick(source_joystick)
