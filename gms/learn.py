"""MIDI Learn 管理器：任意输入源捕获 → 绑定目标"""


class LearnManager:
    def __init__(self, bus):
        self.bus = bus
        self.target = None  # {"kind": ..., "key": ...}

    @property
    def active(self) -> bool:
        return self.target is not None

    def start(self, target: dict):
        self.target = target
        self.bus.emit("learn.state", active=True, target=target)

    def cancel(self):
        self.target = None
        self.bus.emit("learn.state", active=False, target=None)

    def handle(self, **result):
        """输入捕获方调用：正在学习时记录结果并停止学习"""
        if self.target:
            target, self.target = self.target, None
            self.bus.emit("learn.result", target=target, **result)
            self.bus.emit("learn.state", active=False, target=None)