import logging
from typing import Dict, Any
import random

from core.errors import GameError, SessionNotFoundError
from core.events import GameEvent
from game.models.character import Character
from game.models.session import GameSession

# --- 型チェック用の前方参照 ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.event_bus import EventBus
    from game.managers.session_manager import SessionManager
    from game.services.character_service import CharacterService
    from game.services.ai_service import AIService
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader
    from infrastructure.repositories.world_repository import WorldRepository

logger = logging.getLogger(__name__)

class GameService:
    """ゲームの進行ロジックを管理するサービス"""

    def __init__(
        self,
        session_manager: "SessionManager",
        character_service: "CharacterService",
        world_data_loader: "WorldDataLoader",
        world_repository: "WorldRepository",
        ai_service: "AIService",
        event_bus: "EventBus",
    ):
        self.event_bus = event_bus
        self.sessions: "SessionManager" = session_manager
        self.character_service: "CharacterService" = character_service
        self.world_data_loader: "WorldDataLoader" = world_data_loader
        self.world_repository: "WorldRepository" = world_repository
        self.ai_service: "AIService" = ai_service
        logger.info("GameServiceが初期化されました。")

    async def start_game(self, user_id: int, character: "Character", world_name: str) -> tuple["GameSession", str]:
        """
        新しいゲームセッションを開始し、導入ナラティブを生成する。
        
        Returns:
            A tuple containing the created GameSession and the initial narrative string.
        """
        if self.sessions.has_session(user_id):
            raise GameError("既にアクティブなゲームセッションがあります。")

        logger.info(f"ユーザー(ID: {user_id})がキャラクター「{character.name}」でゲームを開始します。")
        
        # 1. セッションを作成
        session = self.sessions.create_session(user_id, character, world_name)
        
        # 初期位置を設定
        world_data = self.world_data_loader.get_world(world_name)
        if world_data:
            session.current_location_id = world_data.get("start_location_id")

        # 2. AIに導入シナリオを生成させる
        logger.info(f"セッション(User: {user_id})の導入シナリオを生成中...")
        intro_data = await self.ai_service.generate_introduction(session)
        initial_narrative = intro_data.get("narrative", "予期せぬ静寂の中、あなたの冒険が始まろうとしています...")

        # イベント発行
        await self.event_bus.publish(GameEvent.GAME_STARTED, session=session)

        return session, initial_narrative

    async def end_game(self, user_id: int) -> "GameSession":
        """ゲームセッションを終了し、キャラクターデータを保存する"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("終了するアクティブなゲームセッションがありません。")

        logger.info(f"ユーザー(ID: {user_id})がゲームを終了します。キャラクター「{session.character.name}」を保存します。")
        
        # キャラクターデータを保存
        await self.character_service.save_character(session.character)
        
        # セッションを終了
        self.sessions.end_session(user_id)

        # イベント発行 (セッション終了後だが、sessionオブジェクトはまだ使える)
        await self.event_bus.publish(GameEvent.GAME_ENDED, session=session)
        
        return session

    async def proceed_game(self, user_id: int, user_input: str) -> Dict[str, Any]:
        """プレイヤーの入力に基づき、ゲームを1ターン進行させる"""
        session = self.sessions.get_session(user_id)
        if not session:
            # このパスは on_message の事前チェックで通常は通らないはず
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        logger.debug(f"ゲーム進行: User({user_id}), Input: '{user_input}'")

        # AIに応答を生成させる
        response_data = await self.ai_service.generate_response(session, user_input)

        # 状態更新をSessionオブジェクトに委譲
        # Sessionが世界の静的データを知らないため、ここで渡す
        world_data = self.world_data_loader.get_world(session.world_name)
        session.apply_ai_response(user_input, response_data, world_data)

        # イベント発行
        await self.event_bus.publish(GameEvent.TURN_PROCESSED, session=session, user_input=user_input, response_data=response_data)

        return response_data

    async def use_item(self, user_id: int, item_name: str) -> Dict[str, Any]:
        """アイテムを使用し、消費アイテムであれば削除してからゲームを進行させる"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        if item_name not in session.character.inventory:
            raise GameError(f"アイテム「{item_name}」を所持していません。")

        # 消費アイテムか確認して削除
        world_data = self.world_data_loader.get_world(session.world_name)
        items_data = world_data.get("items", {})
        item_data = items_data.get(item_name)
        
        if item_data and item_data.get("consumable"):
            session.character.remove_item(item_name)
            logger.info(f"User {user_id} consumed item: {item_name}")

        action_text = f"アイテム使用: {item_name}"
        return await self.proceed_game(user_id, action_text)

    async def buy_item(self, user_id: int, item_name: str) -> Dict[str, Any]:
        """ショップでアイテムを購入する"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        world_data = self.world_data_loader.get_world(session.world_name)
        shops = world_data.get("shops", {})
        
        # 現在地にショップがあるか確認
        current_shop = next((s for s in shops.values() if s.get("location_id") == session.current_location_id), None)
        if not current_shop:
            raise GameError("ここにはショップがありません。")

        # アイテムがショップにあるか確認
        shop_item = next((i for i in current_shop["items"] if i["name"] == item_name), None)
        if not shop_item:
            raise GameError(f"「{item_name}」はこのショップで取り扱っていません。")

        price = shop_item["price"]
        if session.character.gold < price:
            raise GameError(f"ゴールドが足りません。（所持金: {session.character.gold} G, 価格: {price} G）")

        # 購入処理（ゴールド減少とアイテム追加）は、AIへのアクション送信を通じて行うか、ここで直接行うか。
        # ここでは直接行い、AIには「購入した」という事実を伝えて描写させる。
        session.character.gold -= price
        session.character.add_item(item_name)
        logger.info(f"User {user_id} bought {item_name} for {price} G")

        action_text = f"ショップで「{item_name}」を {price} Gで購入した。"
        return await self.proceed_game(user_id, action_text)

    async def equip_item(self, user_id: int, item_name: str) -> Dict[str, Any]:
        """アイテムを装備する"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        if item_name not in session.character.inventory:
            raise GameError(f"アイテム「{item_name}」を所持していません。")

        world_data = self.world_data_loader.get_world(session.world_name)
        items_data = world_data.get("items", {})
        item_data = items_data.get(item_name)

        if not item_data or "equipment_type" not in item_data:
            raise GameError(f"「{item_name}」は装備できません。")

        slot = item_data["equipment_type"]
        bonuses = item_data.get("stats_bonus", {})
        
        session.character.equip(item_name, slot, bonuses)
        logger.info(f"User {user_id} equipped {item_name} to {slot}")

        action_text = f"装備変更: {item_name} を装備した。"
        return await self.proceed_game(user_id, action_text)

    async def flee_combat(self, user_id: int) -> Dict[str, Any]:
        """
        DEXに基づいて逃走判定を行う。
        """
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")
        if not session.in_combat:
            raise GameError("戦闘中ではありません。")

        character = session.character
        
        # 判定難易度(DC)の決定: 敵の中で最も高いDEX (最低10)
        max_enemy_dex = 10
        for enemy in session.current_enemies:
            enemy_dex = enemy.stats.get("DEX", 10)
            if enemy_dex > max_enemy_dex:
                max_enemy_dex = enemy_dex
        
        dc = max_enemy_dex
        
        # 判定
        roll = random.randint(1, 20)
        dex_mod = character.get_modifier("DEX")
        total = roll + dex_mod
        
        success = total >= dc
        
        action_result = {
            "type": "DICE_ROLL",
            "details": {
                "skill": "逃走 (DEX)",
                "target": dc,
                "roll": f"{roll} + {dex_mod} = {total}",
                "success": success
            }
        }

        if success:
            session.end_combat()
            narrative = f"逃走成功！\nあなたは一瞬の隙を突き、戦場から離脱することに成功した。"
            
            # 履歴に追加
            session.add_history("user", "逃走を試みる")
            session.add_history("assistant", narrative)
            
            return {
                "narrative": narrative,
                "action_result": action_result
            }
        else:
            # 失敗時はAIに状況を描写させる
            action_text = f"逃走を試みたが、失敗した (判定: {total} < 目標 {dc})。敵が立ちはだかる！"
            response_data = await self.proceed_game(user_id, action_text)
            
            # proceed_gameの結果に判定結果をマージする
            response_data["action_result"] = action_result
            return response_data

    async def get_world_list(self) -> list[str]:
        """利用可能な世界のリストを取得する"""
        return self.world_data_loader.get_world_names()
