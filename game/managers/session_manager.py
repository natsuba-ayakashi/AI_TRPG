from typing import Dict, Optional
import asyncio
from collections import defaultdict

from game.models.session import GameSession
from game.models.character import Character

class SessionManager:
    """アクティブな全てのゲームセッションをメモリ上で管理するクラス。"""
    def __init__(self):
        # ユーザーIDをキーとするセッション辞書
        self._sessions_by_user: Dict[int, GameSession] = {}
        # ユーザーIDごとにロックを管理するための辞書
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def has_session(self, user_id: int) -> bool:
        """指定されたユーザーのセッションが存在するかどうかを確認します。"""
        return user_id in self._sessions_by_user

    def get_session(self, user_id: int) -> Optional[GameSession]:
        """指定されたユーザーのセッションを取得します。"""
        return self._sessions_by_user.get(user_id)

    def get_lock(self, user_id: int) -> asyncio.Lock:
        """指定されたユーザーのロックオブジェクトを取得します。"""
        return self._locks[user_id]

    def create_session(self, user_id: int, character: Character, thread_id: int, initial_npc_states: Dict) -> GameSession:
        """新しいゲームセッションを作成または上書きします。"""
        if self.has_session(user_id):
            print(f"警告: ユーザー({user_id})の既存のセッションを上書きします。")
        
        session = GameSession(user_id, character, thread_id, initial_npc_states)
        self._sessions_by_user[user_id] = session
        print(f"--- ユーザー({user_id})のゲームセッションを作成しました ---")
        return session

    def delete_session(self, user_id: int):
        """指定されたユーザーのセッションを削除します。"""
        if user_id in self._sessions_by_user:
            del self._sessions_by_user[user_id]
            print(f"--- ユーザー({user_id})のゲームセッションを削除しました ---")