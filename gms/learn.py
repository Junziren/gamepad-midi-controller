"""MIDI Learn 管理器：任意输入源捕获 → 绑定目标"""

import time


class LearnManager:
    """学习超时：激活后 LEARN_TIMEOUT 秒无捕获自动取消，避免永久卡住。"""

    LEARN_TIMEOUT = 20.0

    def __init__(self, bus):
        self.bus = bus
        self.target = None  # {"kind": ..., "key": ...}
        self.started_at = 0.0

    @property
    def active(self) -> bool:
        if self.target is not None and time.time() - self.started_at > self.LEARN_TIMEOUT:
            self.cancel()
            self.bus.emit("log", message="MIDI 学习超时已自动取消")
            return False
        return self.target is not None

    def start(self, target: dict):
        self.target = target
        self.started_at = time.time()
        self.bus.emit("learn.state", active=True, target=target)
        self.bus.emit("log", message="MIDI 学习中：请按手柄按键 / 推动摇杆 / 按键盘键（20 秒无输入自动取消）")

    def cancel(self):
        if self.target is not None:
            self.bus.emit("log", message="MIDI 学习已取消")
        self.target = None
        self.bus.emit("learn.state", active=False, target=None)

    def handle(self, **result):
        """输入捕获方调用：正在学习时记录结果并停止学习"""
        if self.target:
            target, self.target = self.target, None
            self.bus.emit("learn.result", target=target, **result)
            self.bus.emit("learn.state", active=False, target=None)