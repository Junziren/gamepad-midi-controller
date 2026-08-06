"""工具注册表"""

from .mouse_xy import MouseXY
from .screen_xy_pad import ScreenXYPad
from .keyboard_pads import KeyboardPads
from .chord_arpeggiator import ChordArp
from .hotkey_clip import HotkeyClip
from .step_sequencer import StepSequencer
from .wheel_bend import WheelBend
from .midi_mapper import MidiMapper

TOOL_CLASSES = [
    MouseXY, ScreenXYPad, KeyboardPads, ChordArp,
    HotkeyClip, StepSequencer, WheelBend, MidiMapper,
]

CATEGORIES = ["演奏工具", "序列工具", "调制工具", "中间件"]