from enum import Enum, auto

class GameEvent(Enum):
    """
    アプリケーション全体で使用されるイベントの種類を定義するEnum。
    文字列リテラルよりもタイプセーフで、IDEの補完も効くようになります。
    """
    GAME_STARTED = auto()
    GAME_ENDED = auto()
    TURN_PROCESSED = auto()