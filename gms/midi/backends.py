"""虚拟 MIDI 端口内核抽象与 teVirtualMIDI 实现。
teVirtualMIDI 为 loopMIDI 同款底层驱动（签名驱动，Win7-11）。
找不到 DLL 时自动降级为"仅使用系统现有端口"。"""

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

try:
    import mido
    import mido.backends.pygame
    mido.set_backend("mido.backends.pygame")
except Exception:  # 环境缺依赖时保持可导入
    mido = None


# ---- DLL 定位 ----

def _find_tevirtualmidi_dll() -> str | None:
    bundle = getattr(sys, "_MEIPASS", "")
    candidates = [
        os.environ.get("TEVIRTUALMIDI_DLL", ""),
        r"C:\Windows\System32\teVirtualMIDI64.dll",
        r"C:\Windows\System32\teVirtualMIDI.dll",
        r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\teVirtualMIDI64.dll",
        str(Path(__file__).resolve().parent.parent.parent / "teVirtualMIDI64.dll"),
        str(Path(bundle) / "teVirtualMIDI64.dll") if bundle else "",
        str(Path(sys.executable).resolve().parent / "teVirtualMIDI64.dll"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


# ---- 抽象 ----

class VirtualMidiBackend:
    """虚拟 MIDI 端口内核接口。实现二（Windows MIDI Services）预留。"""

    name = "base"

    def is_available(self) -> bool:
        return False

    def create_port(self, port_name: str, on_input) -> object:
        """创建端口，返回句柄；on_input(bytes) 为接收回调（可为 None）"""
        raise NotImplementedError

    def close_port(self, handle) -> None:
        raise NotImplementedError

    def send(self, handle, data: bytes) -> bool:
        raise NotImplementedError


class TeVirtualMidiBackend(VirtualMidiBackend):
    """teVirtualMIDI 内核（ctypes 直调，无第三方 Python 绑定）"""

    name = "tevirtualmidi"

    def __init__(self):
        self._dll = None
        self._err = ""
        self._callback = None  # 保持回调引用，防止被 GC
        dll_path = _find_tevirtualmidi_dll()
        if not dll_path:
            self._err = "未找到 teVirtualMIDI64.dll"
            return
        try:
            self._dll = ctypes.WinDLL(dll_path)
        except OSError as exc:
            self._err = f"加载失败: {exc}"
            return
        self._dll.virtualMIDICreatePortEx2.restype = wintypes.HANDLE
        self._dll.virtualMIDICreatePortEx2.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32,
        ]
        self._dll.virtualMIDIClosePort.restype = wintypes.BOOL
        self._dll.virtualMIDIClosePort.argtypes = [wintypes.HANDLE]
        self._dll.virtualMIDISendData.restype = wintypes.BOOL
        self._dll.virtualMIDISendData.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_uint32]

    @property
    def error(self) -> str:
        return self._err

    def is_available(self) -> bool:
        return self._dll is not None

    def create_port(self, port_name: str, on_input=None):
        if not self.is_available():
            raise RuntimeError(self._err or "内核不可用")
        callback = ctypes.cast(None, ctypes.c_void_p)
        if on_input is not None:
            CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte),
                                  ctypes.c_uint32, ctypes.c_uint32)
            def _cb(port_handle, data_ptr, length, instance):
                try:
                    on_input(bytes(bytearray(data_ptr[i] for i in range(length))))
                except Exception:
                    pass
            self._callback = CB(_cb)
            callback = ctypes.cast(self._callback, ctypes.c_void_p)
        handle = self._dll.virtualMIDICreatePortEx2(
            port_name, "Gamepad MIDI Studio", callback, 0, 0, 65536, 0)
        if not handle:
            raise RuntimeError(f"创建虚拟端口 '{port_name}' 失败（可能端口名已被占用）")
        return handle

    def close_port(self, handle) -> None:
        if handle:
            try:
                self._dll.virtualMIDIClosePort(handle)
            except Exception:
                pass

    def send(self, handle, data) -> bool:
        if not handle or not data:
            return False
        # mido.Message.bytes() 返回 bytearray，而 create_string_buffer 只接受 bytes
        data = bytes(data)
        buf = ctypes.create_string_buffer(data, len(data))
        return bool(self._dll.virtualMIDISendData(handle, buf, len(data)))


# ---- 端口管理 ----

class MidiPortManager:
    """管理虚拟端口（双内核）+ 系统端口输出。"""

    def __init__(self, bus):
        self.bus = bus
        from .wms_backend import WindowsMidiServicesBackend
        self.backends = {
            "tevirtualmidi": TeVirtualMidiBackend(),
            "windows_midi_services": WindowsMidiServicesBackend(),
        }
        self.backend = self.backends["tevirtualmidi"]
        self.virtual_handle = None
        self.virtual_name = ""
        self._mido_out = None
        self._mido_out_name = ""
        self._started = False

    # ---- 生命周期 ----

    def start(self, port_name: str, backend_name: str | None = None):
        """按指定内核（缺省 tevirtualmidi）创建虚拟端口"""
        self._started = True
        self.virtual_name = port_name
        if backend_name in self.backends:
            self.backend = self.backends[backend_name]
        self._open_virtual(port_name)

    def stop(self):
        self.close_output()
        self._close_virtual()
        self._started = False

    def _open_virtual(self, port_name: str):
        self._close_virtual()
        if not self.backend.is_available():
            # 首选内核不可用时尝试回退 teVirtualMIDI
            fallback = self.backends["tevirtualmidi"]
            if self.backend.name != "tevirtualmidi" and fallback.is_available():
                self.bus.emit("log", message=(
                    f"内核 {self.backend.name} 不可用：{self.backend.error}；"
                    f"已回退 teVirtualMIDI"))
                self.backend = fallback
            else:
                self.bus.emit("log", message=(
                    f"虚拟MIDI内核不可用：{self.backend.error}，仅使用系统端口"))
                self.bus.emit("virtual.state", available=False, running=False,
                              error=self.backend.error)
                return
        try:
            self.virtual_handle = self.backend.create_port(
                port_name, on_input=lambda data: self.bus.emit("midi.input", data=data))
            self.bus.emit("log", message=f"虚拟MIDI端口已创建：{port_name}")
            self.bus.emit("virtual.state", available=True, running=True, error="")
        except RuntimeError as exc:
            self.bus.emit("log", message=f"虚拟MIDI端口创建失败：{exc}")
            self.bus.emit("virtual.state", available=True, running=False, error=str(exc))

    def _close_virtual(self):
        if self.virtual_handle:
            self.backend.close_port(self.virtual_handle)
            self.virtual_handle = None

    # ---- 输出 ----

    @staticmethod
    def output_names() -> list:
        """枚举系统 MIDI 输出端口。

        mido 的 pygame backend 把设备名硬编码为 UTF-8 解码，而 Windows
        MMSystem 返回 ANSI(GBK) 字节：中文端口名（如 teVirtualMIDI 中文名）
        会让 mido.get_output_names() 抛 UnicodeDecodeError。这里自行枚举并
        按 UTF-8 -> GBK 顺序容错解码。"""
        if mido is None:
            return []
        try:
            import pygame.midi
            pygame.midi.init()
            try:
                names = []
                for i in range(pygame.midi.get_count()):
                    info = pygame.midi.get_device_info(i)
                    if not info:
                        continue
                    # get_device_info 返回 (interf, name, is_input, opened)
                    if info[2]:
                        continue  # 只列输出设备
                    raw = info[1]
                    if isinstance(raw, bytes):
                        try:
                            name = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            name = raw.decode("gbk", errors="replace")
                    else:
                        name = str(raw)
                    names.append(name)
                return names
            finally:
                try:
                    pygame.midi.quit()
                except Exception:
                    pass
        except Exception:
            return []

    def select_output(self, name: str) -> bool:
        """打开系统端口输出（虚拟端口运行时无需调用）"""
        self.close_output()
        if not name:
            return True
        if mido is None:
            return False
        try:
            self._mido_out = mido.open_output(name)
            self._mido_out_name = name
            return True
        except Exception as exc:
            self.bus.emit("log", message=f"打开输出端口失败：{name} ({exc})")
            return False

    def close_output(self):
        if self._mido_out is not None:
            try:
                self._mido_out.close()
            except Exception:
                pass
            self._mido_out = None
            self._mido_out_name = ""

    def send_message(self, msg) -> bool:
        """优先走虚拟端口（低延迟直发原始字节），否则走已选系统端口"""
        if self.virtual_handle:
            try:
                return bool(self.backend.send(self.virtual_handle, msg.bytes()))
            except Exception:
                return False
        if self._mido_out is not None:
            try:
                self._mido_out.send(msg)
                return True
            except Exception:
                return False
        return False

    def send_bytes(self, data: bytes) -> bool:
        """直接发送原始字节（仅虚拟端口）"""
        if self.virtual_handle:
            return bool(self.backend.send(self.virtual_handle, data))
        return False

    def state(self) -> dict:
        return {
            "virtual_available": self.backend.is_available(),
            "virtual_running": bool(self.virtual_handle),
            "virtual_port": self.virtual_name,
            "virtual_error": getattr(self.backend, "error", ""),
            "virtual_backend": self.backend.name,
            "backends": {
                name: {
                    "available": b.is_available(),
                    "error": getattr(b, "error", ""),
                }
                for name, b in self.backends.items()
            },
            "outputs": self.output_names(),
            "selected_output": self._mido_out_name,
        }