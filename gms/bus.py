"""轻量事件总线：后端各模块解耦通信"""

from collections import defaultdict
import sys
from typing import Callable


class EventBus:
    def __init__(self):
        self._subs = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> None:
        self._subs[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        try:
            self._subs[event].remove(handler)
        except ValueError:
            pass

    def emit(self, event: str, **kwargs) -> None:
        for handler in list(self._subs.get(event, [])):
            try:
                handler(**kwargs)
            except Exception as exc:  # 单个订阅者异常不影响主流程
                print(f"[bus] handler error on '{event}': {exc}", file=sys.stderr)