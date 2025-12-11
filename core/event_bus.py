import asyncio
import logging
from collections import defaultdict
from typing import Callable, Any, Coroutine, Dict, List

from .events import GameEvent

logger = logging.getLogger(__name__)

# 非同期の関数をハンドラとして型定義
Handler = Callable[..., Coroutine[Any, Any, None]]

class EventBus:
    """
    非同期イベントを管理し、コンポーネント間の通信を仲介するクラス。
    """
    def __init__(self):
        self._listeners: Dict[GameEvent, List[Handler]] = defaultdict(list)

    def subscribe(self, event_type: GameEvent, handler: Handler):
        """イベントにハンドラ（コールバック関数）を登録する。"""
        self._listeners[event_type].append(handler)
        logger.debug(f"Handler '{handler.__name__}' subscribed to event '{event_type.name}'")

    async def publish(self, event_type: GameEvent, *args, **kwargs):
        """イベントを発行し、登録されたすべてのハンドラを非同期に実行する。"""
        if event_type not in self._listeners:
            logger.warning(f"Event '{event_type.name}' has no listeners.")
            return

        logger.debug(f"Publishing event '{event_type.name}'")
        tasks = [handler(*args, **kwargs) for handler in self._listeners[event_type]]
        await asyncio.gather(*tasks)