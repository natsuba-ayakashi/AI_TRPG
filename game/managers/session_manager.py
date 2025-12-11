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
        # スレッドIDをキーとするセッション辞書
        self._sessions_by_thread: Dict[int, GameSession] = {}
        # ユーザーIDごとにロックを管理するための辞書
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def has_session(self, user_id: int) -> bool:
        """指定されたユーザーのセッションが存在するかどうかを確認します。"""
        return user_id in self._sessions_by_user

    def get_session(self, user_id: int) -> Optional[GameSession]:
        """指定されたユーザーのセッションを取得します。"""
        return self._sessions_by_user.get(user_id)

    def get_session_by_thread_id(self, thread_id: int) -> Optional[GameSession]:
        """指定されたスレッドIDのセッションを取得します。"""
        return self._sessions_by_thread.get(thread_id)

    def get_lock(self, user_id: int) -> asyncio.Lock:
        """指定されたユーザーのロックオブジェクトを取得します。"""
        return self._locks[user_id]

    def create_session(self, user_id: int, character: Character, thread_id: int, initial_npc_states: Dict) -> GameSession:
        """新しいゲームセッションを作成または上書きします。"""
        if self.has_session(user_id):
            print(f"警告: ユーザー({user_id})の既存のセッションを上書きします。")
            # 古いセッションがあれば、thread_idのマッピングからも削除
            old_session = self.get_session(user_id)
            if old_session and old_session.thread_id in self._sessions_by_thread:
                del self._sessions_by_thread[old_session.thread_id]

        session = GameSession(user_id, character, thread_id, initial_npc_states)
        self._sessions_by_user[user_id] = session
        self._sessions_by_thread[thread_id] = session
        print(f"--- ユーザー({user_id})のゲームセッションを作成しました (Thread: {thread_id}) ---")
        return session

    def delete_session(self, user_id: int):
        """指定されたユーザーのセッションを削除します。"""
        if user_id in self._sessions_by_user:
            session = self._sessions_by_user.pop(user_id)
            if session and session.thread_id in self._sessions_by_thread:
                del self._sessions_by_thread[session.thread_id]
            print(f"--- ユーザー({user_id})のゲームセッションを削除しました ---")