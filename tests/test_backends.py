"""MIDI 输出后端回归测试：mido bytearray -> teVirtualMIDI 发送路径"""

import unittest

from gms.bus import EventBus


class FakeDLL:
    """模拟 teVirtualMIDI DLL：记录发送调用。"""

    def __init__(self):
        self.calls = []

    def virtualMIDISendData(self, handle, buf, length):
        self.calls.append((handle, bytes(buf[:length]), length))
        return 1


def make_backend():
    from gms.midi.backends import TeVirtualMidiBackend
    backend = TeVirtualMidiBackend.__new__(TeVirtualMidiBackend)
    backend._dll = FakeDLL()
    backend._err = ""
    return backend


class TestTeVirtualMidiSend(unittest.TestCase):
    def test_send_accepts_bytearray(self):
        """回归：mido.Message.bytes() 返回 bytearray，必须被接受。"""
        backend = make_backend()
        ok = backend.send(object(), bytearray([0x90, 60, 100]))
        self.assertTrue(ok)
        _, data, length = backend._dll.calls[0]
        self.assertEqual(data, b"\x90\x3c\x64")
        self.assertEqual(length, 3)

    def test_send_accepts_bytes(self):
        backend = make_backend()
        ok = backend.send(object(), b"\x90\x3c\x64")
        self.assertTrue(ok)
        _, data, length = backend._dll.calls[0]
        self.assertEqual(data, b"\x90\x3c\x64")

    def test_send_empty_returns_false(self):
        backend = make_backend()
        self.assertFalse(backend.send(None, b""))
        self.assertFalse(backend.send(object(), b""))


class TestPortManagerMidoPath(unittest.TestCase):
    def test_send_message_with_mido_message(self):
        """回归：MidiEngine -> send_message(mido) 全链路不应被 bytearray 拦截。"""
        import mido
        from gms.midi.backends import MidiPortManager

        backend = make_backend()
        pm = MidiPortManager.__new__(MidiPortManager)
        pm.bus = EventBus()
        pm.backend = backend
        pm.virtual_handle = object()
        pm._mido_out = None
        pm.virtual_name = "Test"

        msg = mido.Message("note_on", channel=0, note=60, velocity=100)
        self.assertTrue(pm.send_message(msg))
        _, data, length = backend._dll.calls[0]
        self.assertEqual(data, b"\x90\x3c\x64")
        self.assertEqual(length, 3)


if __name__ == "__main__":
    unittest.main()
