from typing import Dict, Any, Optional, TYPE_CHECKING
from collections import deque
import copy

if TYPE_CHECKING:
    from .character import Character
    from .enemy import Enemy
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader

class GameSession:
    """個々のゲームセッションの状態を管理するデータクラス"""
    def __init__(self, user_id: int, character: "Character", thread_id: int, initial_npc_states: Dict):
        self.user_id: int = user_id
        self.character: "Character" = character
        self.thread_id: int = thread_id
        self.state: str = 'playing'  # 'playing', 'confirming_continue' など
        self.last_response: Optional[Dict] = None
        self.gm_personality: Optional[str] = None # プレイヤーが選択したGM人格
        self.current_npc_id: Optional[str] = None # 現在対話中のNPCのID
        self.npc_states: Dict[str, Dict[str, Any]] = copy.deepcopy(initial_npc_states) # 世界のNPC状態をセッションにコピー
        self.difficulty_level: int = 1 # 動的難易度レベル
        self.is_difficulty_manual: bool = False # 難易度が手動設定されたか
        self.triggered_event_info: Optional[str] = None # 時間で発生したイベント情報

        # --- 戦闘関連 ---
        self.in_combat: bool = False # 戦闘中フラグ
        self.current_enemies: list["Enemy"] = [] # 現在戦闘中の敵リスト
        self.combat_turn: str = "player" # 'player' or 'enemy'
        self.victory_prompt: Optional[str] = None # 戦闘勝利時の特別なプロンプト

        # --- 時間管理 ---
        self.time_units: int = 0 # 内部的な時間単位カウンター
        self.day: int = 1
        self.time_of_day: str = "朝" # 朝 -> 昼 -> 夕 -> 夜
        self.TIME_CYCLE = ["朝", "昼", "夕", "夜"]

        # --- 対話履歴 ---
        self.conversation_history: deque = deque(maxlen=10) # 直近10件のやり取りを保持

    def advance_time(self, world_data_loader: "WorldDataLoader", units: int = 1):
        """指定された単位だけ時間を進め、日付と時間帯を更新する"""
        self.time_units += units
        
        units_per_day = len(self.TIME_CYCLE)
        
        self.day = 1 + (self.time_units // units_per_day)
        self.time_of_day = self.TIME_CYCLE[self.time_units % units_per_day]
        
        self._check_timed_events(world_data_loader)

    def _check_timed_events(self, world_data_loader: "WorldDataLoader"):
        """現在の時刻に合致する時限イベントがあるか確認する"""
        self.triggered_event_info = None
        timed_events = world_data_loader.get('timed_events')
        if not timed_events:
            return

        for event_id, event_data in timed_events.items():
            trigger = event_data.get('trigger', {})
            day_match = ('day' in trigger and self.day == trigger['day']) or \
                        ('day_modulo' in trigger and self.day % trigger['day_modulo'] == 0)
            time_match = 'time_of_day' in trigger and self.time_of_day == trigger['time_of_day']

            if day_match and time_match:
                self.triggered_event_info = event_data['action']['details']['narrative']
                break

    def switch_combat_turn(self):
        """戦闘のターンを切り替えます。"""
        if self.combat_turn == "player":
            self.combat_turn = "enemy"
        else:
            self.combat_turn = "player"