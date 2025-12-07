from typing import Dict, Any, Optional
import asyncio
from collections import defaultdict

from core.character_manager import Character

class GameSession:
    """個々のゲームセッションの状態を管理するデータクラス"""
    def __init__(self, character: Character, world_setting: str, thread_id: int, legacy_log: Optional[Dict] = None):
        self.character: Character = character
        self.world_setting: str = world_setting
        self.legacy_log: Optional[Dict] = legacy_log
        self.state: str = 'playing'  # 'playing', 'confirming_continue' など
        self.last_response: Optional[Dict] = None
        self.gm_personality: Optional[str] = None # プレイヤーが選択したGM人格
        self.thread_id: int = thread_id
        self.difficulty_level: int = 1 # 動的難易度レベル
        self.is_difficulty_manual: bool = False # 難易度が手動設定されたか

class GameManager:
    """アクティブな全てのゲームセッションを管理するクラス"""
    def __init__(self):
        self._sessions: Dict[int, GameSession] = {}
        # ユーザーIDごとにロックを管理するための辞書
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def has_session(self, user_id: int) -> bool:
        """指定されたユーザーのセッションが存在するかどうかを確認します。"""
        return user_id in self._sessions

    def get_session(self, user_id: int) -> Optional[GameSession]:
        """指定されたユーザーのセッションを取得します。"""
        return self._sessions.get(user_id)

    def get_lock(self, user_id: int) -> asyncio.Lock:
        """指定されたユーザーのロックオブジェクトを取得します。"""
        return self._locks[user_id]

    def create_session(self, user_id: int, character: Character, world_setting: str, thread_id: int, legacy_log: Optional[Dict] = None) -> GameSession:
        """新しいゲームセッションを作成または上書きします。"""
        if self.has_session(user_id):
            print(f"警告: ユーザー({user_id})の既存のセッションを上書きします。")
        
        session = GameSession(character, world_setting, thread_id, legacy_log)
        self._sessions[user_id] = session
        print(f"--- ユーザー({user_id})のゲームセッションを作成しました ---")
        return session

    def delete_session(self, user_id: int):
        """指定されたユーザーのセッションを削除します。"""
        if user_id in self._sessions:
            del self._sessions[user_id]
            print(f"--- ユーザー({user_id})のゲームセッションを削除しました ---")