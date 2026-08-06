"""工具基类与上下文"""


class ToolContext:
    def __init__(self, bus, midi, hooks, learn, gamepad, get_config, update_config):
        self.bus = bus
        self.midi = midi
        self.hooks = hooks
        self.learn = learn
        self.gamepad = gamepad
        self.get_config = get_config
        self.update_config = update_config

    def tool_cfg(self, tool_id: str) -> dict:
        return self.get_config()["tools"].get(tool_id, {})


class Tool:
    """工具基类。id 对应 config.tools 键名。"""

    id = "base"
    title = "基础工具"
    category = "通用"
    icon = "◈"

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    def start(self):
        pass

    def stop(self):
        pass

    def get_state(self) -> dict:
        return {}

    def action(self, name: str, payload: dict) -> dict:
        return {}