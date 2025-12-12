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
    from game.loaders.world_data_loader import WorldDataLoader
    from game.repositories.world_repository import WorldRepository

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

        # --- 戦闘状態の事前キャプチャ ---
        was_in_combat = session.in_combat
        previous_enemy_ids = set()
        if was_in_combat:
            previous_enemy_ids = {e.id for e in session.current_enemies}
        # -----------------------------

        # ユーザー入力が「」や""で始まる場合、会話として強調する
        if user_input.startswith("「") or user_input.startswith('"') or user_input.startswith("“"):
            user_input = f"発言: {user_input}"

        # AIに応答を生成させる
        response_data = await self.ai_service.generate_response(session, user_input)

        # --- AI応答のサニタイズ (エラー回避) ---
        # new_enemies が辞書のリストになっている場合、ID文字列のリストに変換する
        if "state_changes" in response_data:
            changes = response_data["state_changes"]
            if "new_enemies" in changes and isinstance(changes["new_enemies"], list):
                sanitized_enemies = []
                for item in changes["new_enemies"]:
                    if isinstance(item, dict) and "id" in item:
                        sanitized_enemies.append(str(item["id"]))
                    elif isinstance(item, str):
                        sanitized_enemies.append(item)
                changes["new_enemies"] = sanitized_enemies
        # -------------------------------------

        # --- 移動制限のチェック (アイテム鍵など) ---
        if "state_changes" in response_data:
            changes = response_data["state_changes"]
            # AIが場所移動を提案している場合
            if new_loc_id := changes.get("current_location_id"):
                world_data = self.world_data_loader.get_world(session.world_name)
                locations = world_data.get("locations", {})
                
                if target_loc := locations.get(new_loc_id):
                    # requirements (必要条件) のチェック
                    if reqs := target_loc.get("requirements"):
                        # アイテムが必要な場合
                        if req_item := reqs.get("item"):
                            if req_item not in session.character.inventory:
                                # 条件を満たしていないため移動をキャンセル
                                logger.info(f"Access denied to {new_loc_id}. Missing item: {req_item}")
                                del changes["current_location_id"]
                                
                                # 拒否メッセージをナラティブに追加
                                denial_msg = f"\n\n(システム: 「{target_loc.get('name')}」に進むには、アイテム「{req_item}」が必要です。)"
                                if "narrative" in response_data:
                                    response_data["narrative"] += denial_msg
                                else:
                                    response_data["narrative"] = denial_msg
                            elif reqs.get("consume"):
                                # アイテムを持っていて、消費設定がある場合
                                session.character.remove_item(req_item)
                                logger.info(f"Consumed item {req_item} to enter {new_loc_id}")
                                
                                consume_msg = f"\n\n(システム: 「{req_item}」を消費して扉を開けました。)"
                                if "narrative" in response_data and isinstance(response_data["narrative"], str):
                                    response_data["narrative"] += consume_msg
                                else:
                                    response_data["narrative"] = consume_msg
                        
                        # クエスト条件のチェック
                        elif req_quest := reqs.get("quest"):
                            quest_id = req_quest.get("id")
                            req_status = req_quest.get("status")
                            # session.quests が { "quest_id": "status" } の形式であると仮定
                            current_status = getattr(session, "quests", {}).get(quest_id, "inactive")
                            
                            if current_status != req_status:
                                logger.info(f"Access denied to {new_loc_id}. Quest {quest_id} status is {current_status}, required {req_status}")
                                del changes["current_location_id"]
                                
                                denial_msg = f"\n\n(システム: この先に進むには、特定のクエストを進行させる必要があります。)"
                                response_data["narrative"] = response_data.get("narrative", "") + denial_msg
            
            # 移動が確定している場合、その場所のイベント(on_enter)をチェック
            if "current_location_id" in changes:
                self._handle_location_events(session, changes["current_location_id"], response_data)

            # --- NPC状態更新 (好感度など) ---
            if npc_updates := changes.get("npc_updates"):
                if not hasattr(session, "npc_states"):
                    session.npc_states = {}
                
                for update in npc_updates:
                    if not isinstance(update, dict):
                        logger.warning(f"Invalid NPC update format from AI: {update}")
                        continue

                    npc_id = update.get("id")
                    if npc_id:
                        if npc_id not in session.npc_states:
                            session.npc_states[npc_id] = {}
                        
                        # 更新フィールドをマージ
                        for key, value in update.items():
                            if key != "id":
                                session.npc_states[npc_id][key] = value
                        logger.info(f"Updated NPC {npc_id} state: {update}")

                        # 好感度変化によるクエスト発生チェック
                        if "disposition" in update:
                            await self._check_npc_quest_triggers(session, npc_id, update["disposition"], response_data)
        # ----------------------------------------

        # 状態更新をSessionオブジェクトに委譲
        # Sessionが世界の静的データを知らないため、ここで渡す
        world_data = self.world_data_loader.get_world(session.world_name)
        session.apply_ai_response(user_input, response_data, world_data)

        # --- 敵撃破時の報酬処理 ---
        if was_in_combat:
            current_enemy_ids = {e.id for e in session.current_enemies}
            # 以前いて、今いない敵IDを特定
            defeated_enemy_ids = previous_enemy_ids - current_enemy_ids
            
            if defeated_enemy_ids:
                await self._handle_defeated_enemies(session, defeated_enemy_ids, response_data)
        # -------------------------

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

    async def _handle_defeated_enemies(self, session: "GameSession", defeated_enemy_ids: set[str], response_data: Dict[str, Any]):
        """倒した敵の報酬を計算し、キャラクターに適用する"""
        world_data = self.world_data_loader.get_world(session.world_name)
        enemies_data = world_data.get("enemies", {})
        
        total_xp = 0
        total_gold = 0
        dropped_items = []
        
        for enemy_id in defeated_enemy_ids:
            if enemy_data := enemies_data.get(enemy_id):
                rewards = enemy_data.get("rewards", {})
                total_xp += rewards.get("xp", 0)
                total_gold += rewards.get("gold", 0)
                if items := rewards.get("items"):
                    dropped_items.extend(items)

        if total_xp > 0 or total_gold > 0 or dropped_items:
            # キャラクターに反映
            leveled_up = session.character.add_xp(total_xp)
            session.character.gold += total_gold
            for item in dropped_items:
                session.character.add_item(item)
            
            # response_data の state_changes に追記
            if "state_changes" not in response_data:
                response_data["state_changes"] = {}
            
            changes = response_data["state_changes"]
            
            changes["xp_gain"] = changes.get("xp_gain", 0) + total_xp
            changes["gold_change"] = changes.get("gold_change", 0) + total_gold
            
            if dropped_items:
                if "new_items" in changes:
                    changes["new_items"].extend(dropped_items)
                else:
                    changes["new_items"] = dropped_items

            if leveled_up:
                changes["level_up"] = session.character.level
                new_skills = session.character.check_new_skills(world_data)
                if new_skills:
                    if "new_skills" in changes:
                        changes["new_skills"].extend(new_skills)
                    else:
                        changes["new_skills"] = new_skills

            reward_text = f"\n\n(システム: 敵を倒した！ 経験値 {total_xp}、{total_gold} G を獲得。"
            if dropped_items:
                reward_text += f" アイテム: {', '.join(dropped_items)} を入手。"
            if leveled_up:
                reward_text += f" **レベルアップ！ Lv.{session.character.level} になった！**"
            reward_text += ")"
            
            if "narrative" in response_data and isinstance(response_data["narrative"], str):
                response_data["narrative"] += reward_text
            else:
                response_data["narrative"] = reward_text

    async def accept_quest(self, user_id: int, quest_id: str) -> Dict[str, Any]:
        """クエストを受注状態にする"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        world_data = self.world_data_loader.get_world(session.world_name)
        quests_data = world_data.get("quests", {})
        
        if quest_id not in quests_data:
            raise GameError(f"クエストID「{quest_id}」が見つかりません。")

        # session.quests の初期化確認
        if not hasattr(session, "quests"):
            session.quests = {}
        
        current_status = session.quests.get(quest_id, "inactive")
        if current_status != "inactive":
            raise GameError(f"このクエストは既に進行中か完了済みです (Status: {current_status})。")

        session.quests[quest_id] = "active"
        quest_title = quests_data[quest_id].get("title", quest_id)
        
        logger.info(f"User {user_id} accepted quest: {quest_id}")
        
        action_text = f"クエスト「{quest_title}」を受注した。"
        return await self.proceed_game(user_id, action_text)

    async def complete_quest(self, user_id: int, quest_id: str) -> Dict[str, Any]:
        """クエストを完了状態にする"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        world_data = self.world_data_loader.get_world(session.world_name)
        quests_data = world_data.get("quests", {})
        
        if quest_id not in quests_data:
            raise GameError(f"クエストID「{quest_id}」が見つかりません。")

        if not hasattr(session, "quests"):
            session.quests = {}

        session.quests[quest_id] = "completed"
        quest_title = quests_data[quest_id].get("title", quest_id)
        
        logger.info(f"User {user_id} completed quest: {quest_id}")

        action_text = f"クエスト「{quest_title}」を完了した！"
        return await self.proceed_game(user_id, action_text)

    def _handle_location_events(self, session: "GameSession", new_loc_id: str, response_data: Dict[str, Any]):
        """場所移動時のイベント（罠、遭遇など）を処理する"""
        if not hasattr(session, "triggered_events"):
            session.triggered_events = set()
        
        world_data = self.world_data_loader.get_world(session.world_name)
        locations = world_data.get("locations", {})
        location_data = locations.get(new_loc_id)
        
        if not location_data or "on_enter" not in location_data:
            return

        event = location_data["on_enter"]
        event_id = event.get("event_id")
        
        # 一度きりのイベントで、既に実行済みの場合はスキップ
        if event.get("once", True) and event_id in session.triggered_events:
            return

        # イベント実行記録
        if event_id:
            session.triggered_events.add(event_id)
            logger.info(f"Triggering event {event_id} at {new_loc_id}")

        # ナラティブの追加
        if narrative := event.get("narrative"):
            event_msg = f"\n\n(イベント: {narrative})"
            response_data["narrative"] = response_data.get("narrative", "") + event_msg

        # state_changes の準備
        if "state_changes" not in response_data:
            response_data["state_changes"] = {}
        changes = response_data["state_changes"]

        # イベントタイプ別の処理
        if event.get("type") == "trap":
            damage = event.get("damage", 0)
            if damage > 0:
                changes["hp_change"] = changes.get("hp_change", 0) - damage

        elif event.get("type") == "encounter":
            enemies = event.get("enemies", [])
            if enemies:
                if "new_enemies" in changes:
                    changes["new_enemies"].extend(enemies)
                else:
                    changes["new_enemies"] = enemies

    async def talk_to_npc(self, user_id: int, npc_name_or_id: str, message: str = None) -> Dict[str, Any]:
        """指定したNPCに話しかける"""
        session = self.sessions.get_session(user_id)
        if not session:
            raise SessionNotFoundError("アクティブなゲームセッションが見つかりません。")

        world_data = self.world_data_loader.get_world(session.world_name)
        locations = world_data.get("locations", {})
        current_loc = locations.get(session.current_location_id, {})
        
        # 現在地にいるNPCか確認
        npcs_here = current_loc.get("npcs", [])
        all_npcs = world_data.get("npcs", {})
        
        target_npc_id = None
        target_npc_name = ""
        
        for npc_id in npcs_here:
            npc_data = all_npcs.get(npc_id, {})
            if npc_id == npc_name_or_id or npc_data.get("name") == npc_name_or_id:
                target_npc_id = npc_id
                target_npc_name = npc_data.get("name")
                break
        
        if not target_npc_id:
            raise GameError(f"ここには「{npc_name_or_id}」というNPCはいません。")

        action_text = f"NPC「{target_npc_name}」に話しかける。"
        if message:
            action_text += f" 内容: 「{message}」"
            
        return await self.proceed_game(user_id, action_text)

    async def _check_npc_quest_triggers(self, session: "GameSession", npc_id: str, new_disposition: str, response_data: Dict[str, Any]):
        """NPCの好感度変化によるクエスト発生をチェックする"""
        world_data = self.world_data_loader.get_world(session.world_name)
        npc_data = world_data.get("npcs", {}).get(npc_id)
        
        if not npc_data or "quest_triggers" not in npc_data:
            return

        # 好感度に対応するクエストIDを取得
        quest_id = npc_data["quest_triggers"].get(new_disposition)
        if not quest_id:
            return

        # クエストデータの存在確認
        quests_data = world_data.get("quests", {})
        if quest_id not in quests_data:
            return

        # 既に受注済み・完了済みでないか確認
        if not hasattr(session, "quests"):
            session.quests = {}
        
        current_status = session.quests.get(quest_id, "inactive")
        if current_status != "inactive":
            return

        # クエストを発生させる
        session.quests[quest_id] = "active"
        quest_title = quests_data[quest_id].get("title", quest_id)
        
        logger.info(f"Quest '{quest_id}' triggered by NPC {npc_id} disposition change to {new_disposition}")

        # ナラティブに通知を追加
        trigger_msg = f"\n\n(システム: {npc_data['name']}との絆が深まり、クエスト「{quest_title}」が発生しました！)"
        if "narrative" in response_data and isinstance(response_data["narrative"], str):
            response_data["narrative"] += trigger_msg
        else:
            response_data["narrative"] = trigger_msg
