import logging
from typing import Dict, Optional
import asyncio
from collections import defaultdict

from game.models.session import GameSession
from game.models.character import Character

logger = logging.getLogger(__name__)

class SessionManager:
    """アクティブな全てのゲームセッションをメモリ上で管理するクラス。"""
    def __init__(self):
        # ユーザーIDをキーとするセッション辞書
        self._sessions_by_user: Dict[int, GameSession] = {}
        # スレッドIDをキーとするセッション辞書
        self._sessions_by_thread: Dict[int, GameSession] = {}
        # ユーザーIDごとにロックを管理するための辞書
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        logger.info("SessionManagerが初期化されました。")

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

    def create_session(self, user_id: int, character: Character, world_name: str) -> GameSession:
        """
        新しいゲームセッションを作成します。
        この時点ではスレッドIDは紐づけられません。
        """
        if self.has_session(user_id):
            logger.warning(f"ユーザー({user_id})の既存のセッションを上書きします。古いセッションを終了します。")
            self.end_session(user_id)

        # Note: この変更に伴い、GameSessionモデルのコンストラクタも変更が必要です。
        # 例: def __init__(self, user_id: int, character: Character, world_name: str):
        session = GameSession(user_id=user_id, character=character, world_name=world_name)
        self._sessions_by_user[user_id] = session
        logger.info(f"ユーザー({user_id})のゲームセッションを作成しました (World: {world_name})。")
        return session

    def associate_thread_to_session(self, user_id: int, thread_id: int):
        """
        既存のセッションにDiscordのスレッドIDを紐付けます。
        """
        session = self.get_session(user_id)
        if not session:
            logger.error(f"スレッド({thread_id})を紐付けようとしましたが、ユーザー({user_id})のセッションが見つかりません。")
            return

        session.thread_id = thread_id
        self._sessions_by_thread[thread_id] = session
        logger.info(f"セッション(User: {user_id})にスレッド(ID: {thread_id})を紐付けました。")

    def end_session(self, user_id: int) -> Optional[GameSession]:
        """指定されたユーザーのセッションを終了し、関連データをクリーンアップします。"""
        session = self._sessions_by_user.pop(user_id, None)
        if not session:
            logger.warning(f"終了しようとしたセッション(User: {user_id})が見つかりませんでした。")
            return None

        if session.thread_id and session.thread_id in self._sessions_by_thread:
            del self._sessions_by_thread[session.thread_id]

        # 関連するロックも削除してメモリを解放
        if user_id in self._locks:
            del self._locks[user_id]
        
        logger.info(f"ユーザー({user_id})のゲームセッションを終了しました。")
        return session