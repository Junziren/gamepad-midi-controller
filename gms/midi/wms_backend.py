"""Windows MIDI Services 备选内核（Win11 24H2+）。

状态：Windows MIDI Services 的平台服务（midisrv）已随 Win11 24H2 内置，
但应用层 WinRT API（Microsoft.Windows.Devices.Midi2）由独立 SDK/运行时提供，
Python 侧暂无官方投影（PyPI 无 winrt-Microsoft.Windows.Devices.Midi2）。
本模块实现完整的检测层 + 预留 loopback 端点实现：当系统安装 SDK 运行时
且 Python 可导入投影模块时自动启用；否则给出明确的不可用原因。
"""

import ctypes
import importlib
import sys
from pathlib import Path
from ctypes import wintypes

from .backends import VirtualMidiBackend

# 可能的 Python 投影模块名（pywinrt 扁平命名 / winsdk 风格）
PROJECTION_MODULES = [
    "winrt_microsoft_windows_devices_midi2",
    "winrt.microsoft.windows.devices.midi2",
    "winsdk.microsoft.windows.devices.midi2",
]

# 激活类（用于检测 SDK 运行时是否安装）
LOOPBACK_MANAGER_ACTIVATABLE = "Microsoft.Windows.Devices.Midi2.MidiLoopbackEndpointManager"


def _midisrv_running() -> bool:
    """检查 Windows MIDI 服务 (midisrv) 是否运行"""
    try:
        SC_MANAGER_CONNECT = 0x0001
        SERVICE_QUERY_STATUS = 0x0004
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        SC_HANDLE = ctypes.c_void_p

        class SERVICE_STATUS(ctypes.Structure):
            _fields_ = [
                ("dwServiceType", wintypes.DWORD),
                ("dwCurrentState", wintypes.DWORD),
                ("dwControlsAccepted", wintypes.DWORD),
                ("dwWin32ExitCode", wintypes.DWORD),
                ("dwServiceSpecificExitCode", wintypes.DWORD),
                ("dwCheckPoint", wintypes.DWORD),
                ("dwWaitHint", wintypes.DWORD),
            ]

        scm = advapi32.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not scm:
            return False
        try:
            svc = advapi32.OpenServiceW(scm, "midisrv", SERVICE_QUERY_STATUS)
            if not svc:
                return False
            try:
                status = SERVICE_STATUS()
                ok = advapi32.QueryServiceStatus(svc, ctypes.byref(status))
                return bool(ok) and status.dwCurrentState == 4  # SERVICE_RUNNING
            finally:
                advapi32.CloseServiceHandle(svc)
        finally:
            advapi32.CloseServiceHandle(scm)
    except Exception:
        return False


def _midi2_runtime_registered() -> bool:
    """检查系统是否注册了 MIDI2 WinRT 激活类（SDK 运行时已安装）"""
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\WindowsRuntime\ActivatableClassId",
        ) as key:
            idx = 0
            while True:
                try:
                    name = winreg.EnumKey(key, idx)
                except OSError:
                    break
                if "Midi2" in name or "MIDI2" in name:
                    return True
                idx += 1
        return False
    except OSError:
        return False


class WindowsMidiServicesBackend(VirtualMidiBackend):
    """Windows MIDI Services 内核。可用时创建 loopback 端点。"""

    name = "windows_midi_services"

    def __init__(self):
        self._err = ""
        self._mod = None
        self._check()

    # ---- 检测 ----

    def _check(self):
        if not _midisrv_running():
            self._err = "Windows MIDI 服务 (midisrv) 未运行"
            return
        if not _midi2_runtime_registered():
            self._err = ("未检测到 MIDI2 运行时：需安装 Windows MIDI Services SDK/"
                         "运行时（Win11 24H2+）")
            return
        self._mod = self._load_projection()
        if self._mod is None:
            self._err = ("缺少 Python MIDI2 投影模块；安装 winrt-Microsoft.Windows."
                         "Devices.Midi2 或放置投影包到 gms\\winrt_ext 后自动启用")
            return
        self._err = ""

    @staticmethod
    def _load_projection():
        for name in PROJECTION_MODULES:
            try:
                return importlib.import_module(name)
            except ImportError:
                continue
        # 本地投影目录（用户手动放置生成的投影）
        local = Path(__file__).resolve().parent.parent / "winrt_ext"
        if local.exists():
            sys.path.insert(0, str(local))
            for name in PROJECTION_MODULES:
                try:
                    return importlib.import_module(name)
                except ImportError:
                    continue
        return None

    @property
    def error(self) -> str:
        return self._err

    def is_available(self) -> bool:
        return self._mod is not None and not self._err

    # ---- 端口（loopback 端点） ----

    def create_port(self, port_name: str, on_input=None):
        """创建 loopback 端点（MIDI 2.0 双向）。投影可用时执行。"""
        if not self.is_available():
            raise RuntimeError(self._err or "内核不可用")
        mod = self._mod

        def _get(name):
            return getattr(mod, name, None)

        manager_cls = (_get("MidiLoopbackEndpointManager")
                       or _get("MidiVirtualDeviceManager"))
        if manager_cls is None:
            raise RuntimeError("投影中未找到端点管理类")
        manager = manager_cls()
        # 协议参数：MIDI1 兼容端点（DAW 通用）
        endpoint = manager.create_loopback_endpoint(port_name, 0) \
            if "create_loopback_endpoint" in dir(manager) \
            else manager.create_virtual_device(port_name, 0)
        endpoint_id = endpoint.endpoint_device_id

        session_cls = _get("MidiSession")
        conn = None
        session = None
        if session_cls is not None and on_input is not None:
            session = session_cls.create_session("Gamepad MIDI Studio")
            conn = session.create_endpoint_connection(endpoint_id)
            if hasattr(conn, "open"):
                conn.open()
            if on_input is not None and hasattr(conn, "message_received"):
                conn.message_received += lambda sender, args: on_input(
                    bytes(args.message.to_bytes()) if hasattr(args.message, "to_bytes") else b"")

        return {
            "manager": manager,
            "endpoint": endpoint,
            "endpoint_id": endpoint_id,
            "session": session,
            "conn": conn,
            "port_name": port_name,
        }

    def close_port(self, handle) -> None:
        if not handle:
            return
        try:
            conn = handle.get("conn")
            if conn is not None and hasattr(conn, "close"):
                conn.close()
            session = handle.get("session")
            if session is not None and hasattr(session, "dispose"):
                session.dispose()
            endpoint = handle.get("endpoint")
            manager = handle.get("manager")
            if endpoint is not None and manager is not None:
                endpoint_id = handle.get("endpoint_id")
                if endpoint_id and hasattr(manager, "delete_loopback_endpoint"):
                    manager.delete_loopback_endpoint(endpoint_id)
        except Exception:
            pass

    def send(self, handle, data: bytes) -> bool:
        if not handle or not data:
            return False
        try:
            conn = handle.get("conn")
            if conn is None:
                return False
            # 优先 MessageBuilder；退化用 raw UMP 发送
            if hasattr(conn, "send_message"):
                # 尝试用 UMP 消息（MIDI1 消息转换为 UMP 由 SDK 处理）
                if hasattr(conn, "send_word") and len(data) in (1, 2, 3):
                    word = int.from_bytes(data, "big")
                    conn.send_word(word)
                    return True
                return False
            return False
        except Exception:
            return False