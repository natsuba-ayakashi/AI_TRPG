import logging
from pathlib import Path
from typing import Dict, Any

from core.events import GameEvent

# --- 型チェック用の前方参照 ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.event_bus import EventBus
    from game.models.session import GameSession

# このサービス専用のロガーを作成する
# ファイル出力用のハンドラを別途設定するため、ルートロガーとは別にする
game_log = logging.getLogger("game_event_log")

class LoggingService:
    """
    ゲームの重要なイベントをログファイルに記録するサービス。
    """
    def __init__(self, event_bus: "EventBus", log_file_path: Path):
        self.event_bus = event_bus
        self._setup_file_logger(log_file_path)
        self._subscribe_to_events()
        logging.info("LoggingServiceが初期化され、イベントを購読しました。")

    def _setup_file_logger(self, log_file_path: Path):
        """ゲームイベントログ専用のファイルロガーを設定する。"""
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file_path, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        # 多重にハンドラが追加されるのを防ぐ
        if not game_log.handlers:
            game_log.addHandler(handler)
            game_log.setLevel(logging.INFO)
            # 親ロガー(root)に伝播しないようにする
            game_log.propagate = False

    def _subscribe_to_events(self):
        """イベントバスにハンドラを登録する。"""
        self.event_bus.subscribe(GameEvent.GAME_STARTED, self.on_game_started)
        self.event_bus.subscribe(GameEvent.GAME_ENDED, self.on_game_ended)
        self.event_bus.subscribe(GameEvent.TURN_PROCESSED, self.on_turn_processed)

    async def on_game_started(self, session: "GameSession", **kwargs):
        """ゲーム開始イベントをログに記録する。"""
        game_log.info(f"[GAME START] UserID: {session.user_id}, Character: {session.character.name}, World: {session.world_name}")

    async def on_game_ended(self, session: "GameSession", **kwargs):
        """ゲーム終了イベントをログに記録する。"""
        game_log.info(f"[GAME END] UserID: {session.user_id}, Character: {session.character.name}, Turns: {session.turn_count}")

    async def on_turn_processed(self, session: "GameSession", user_input: str, response_data: Dict[str, Any], **kwargs):
        """ゲームのターン進行をログに記録する。"""
        narrative = response_data.get("narrative", "N/A")
        # ログが長くなりすぎないように調整
        short_narrative = (narrative[:100] + '...') if len(narrative) > 100 else narrative
        game_log.info(f"[TURN {session.turn_count}] UserID: {session.user_id}, Input: '{user_input}', Narrative: '{short_narrative.replace('\n', ' ')}'")