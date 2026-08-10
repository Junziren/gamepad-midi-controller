"""入口：python -m gms"""

import ctypes
import sys


def _already_running() -> bool:
    """Windows 命名互斥体单实例锁：重复启动时返回 True。"""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        # 句柄是 64 位指针：必须显式声明 restype，否则被截断为 int
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, False, "GamepadMIDIStudio_SingleInstance")
        already = bool(handle) and kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return already
    except Exception:
        return False


def main():
    if _already_running():
        message = "Gamepad MIDI Studio 已在运行。请使用已打开的窗口，不要重复启动。"
        try:
            ctypes.windll.user32.MessageBoxW(None, message, "Gamepad MIDI Studio", 0x40)
        except Exception:
            print(message, file=sys.stderr)
        return 0
    from .app import App
    app = App()
    app.run()


if __name__ == "__main__":
    sys.exit(main())
