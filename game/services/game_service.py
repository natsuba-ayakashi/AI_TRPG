from typing import TYPE_CHECKING, Optional, Dict, Any
import discord
import random
import json

from core.errors import GameError
from game.models.session import GameSession
from game.models.enemy import Enemy

if TYPE_CHECKING:
    from game.managers.session_manager import SessionManager
    from game.services.character_service import CharacterService
    from game.services.ai_service import AIService
    from infrastructure.repositories.world_repository import WorldRepository
    from bot.client import MyBot
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader

class GameService:
    """
    ゲームの主要なビジネスロジック（セッション管理、ゲーム進行など）を扱うサービスクラス。
    プレゼンテーション層（Cogs）と他のゲームコンポーネントとの間のファサードとして機能します。
    """
    def __init__(
        self,
        session_manager: "SessionManager",
        character_service: "CharacterService",
        world_data_loader: "WorldDataLoader",
        world_repository: "WorldRepository",
        bot: "MyBot",
        ai_service: "AIService",
    ):
        """
        Args:
            session_manager: アクティブなゲームセッションを管理するマネージャー。
            character_service: キャラクター関連のロジックを扱うサービス。
            world_data_loader: 静的なゲームデータ（世界設定など）を読み込むローダー。
            world_repository: 世界の状態を永続化するリポジトリ。
            bot: MyBotインスタンス。イベントディスパッチに使用。
        """
        self.sessions = session_manager
        self.characters = character_service
        self.bot = bot
        self.world_repo = world_repository
        self.worlds = world_data_loader
        self.ai = ai_service

    def get_session(self, user_id: int) -> Optional[GameSession]:
        """
        指定されたユーザーのアクティブなゲームセッションを取得します。
        SessionManagerへの単純なプロキシメソッドです。

        Args:
            user_id: ユーザーのDiscord ID。

        Returns:
            存在すればGameSessionオブジェクト、なければNone。
        """
        return self.sessions.get_session(user_id)

    async def start_game(
        self, user_id: int, char_name: str, thread: discord.Thread
    ) -> GameSession:
        """
        新しいゲームセッションを開始します。

        Args:
            user_id: ゲームを開始するユーザーのID。
            char_name: 使用するキャラクターの名前。
            thread: ゲームをプレイするスレッド。

        Returns:
            新しく作成されたGameSessionオブジェクト。

        Raises:
            GameError: ユーザーが既に別のアクティブセッションを持っている場合。
        """
        if self.sessions.has_session(user_id):
            raise GameError("既にアクティブなゲームセッションがあります。新しいゲームを始める前に、現在のアクティブなゲームを終了してください。")

        # CharacterServiceを使用してキャラクターをロード
        character = await self.characters.get_character(user_id, char_name)

        # WorldRepositoryから現在の世界のNPC状態をロード
        world_state = await self.world_repo.load()

        # SessionManagerを使用して新しいセッションを作成
        session = self.sessions.create_session(user_id, character, thread.id, world_state.get("npc_states", {}))
        
        # ゲーム開始イベントを発行
        self.bot.dispatch("game_start", session)
        print(f"ユーザー({user_id})がキャラクター「{char_name}」でゲームを開始しました。")
        return session

    async def end_game(self, user_id: int):
        """
        アクティブなゲームセッションを終了します。
        キャラクターの最終状態を保存し、セッションをクリーンアップします。
        """
        session = self.get_session(user_id)
        if not session:
            raise GameError("終了するアクティブなゲームセッションがありません。")

        # セッション中のNPCの状態を、現在の世界のNPC状態として保存する
        current_world_state = await self.world_repo.load()
        current_world_state["npc_states"] = session.npc_states
        await self.world_repo.save(current_world_state)
        print(f"世界のNPCの状態を更新しました。")

        # CharacterServiceを使用してキャラクターの最終状態を保存
        await self.characters.save_character(user_id, session.character)

        # ゲーム終了イベントを発行
        self.bot.dispatch("game_end", session)

        # SessionManagerを使用してセッションを削除
        self.sessions.delete_session(user_id)
        print(f"ユーザー({user_id})のゲームセッションを終了し、キャラクターデータを保存しました。")

    async def flee_combat(self, user_id: int) -> str:
        """戦闘からの逃走を試みます。"""
        session = self.get_session(user_id)
        if not session or not session.in_combat:
            raise GameError("戦闘中でなければ逃げることはできません。")

        # DEXに基づいた単純な逃走成功判定
        dex_stat = session.character.stats.get("DEX", 10)
        # 50%を基本成功率とし、DEXに応じて補正
        success_chance = 50 + (dex_stat - 10) * 5
        is_success = random.randint(1, 100) <= success_chance

        if is_success:
            self._end_combat(session)
            # 逃走成功の描写をAIに生成させる
            user_input = "プレイヤーは戦闘から逃走することに成功した。その後の状況を描写してください。"
            ai_response = await self.ai.generate_game_response(session, user_input)
            narrative = ai_response.get("narrative", "あなたはなんとか敵から逃げ切った...")
            self.bot.dispatch("game_proceed", session, "逃走成功", ai_response)
            return narrative
        else:
            # 逃走失敗。敵のターンに移行する。
            session.switch_combat_turn()
            enemy_response = await self.ai.generate_game_response(session, "プレイヤーは逃走に失敗した。敵のターンです。")
            self._apply_state_changes(session, enemy_response.get("state_changes", {}))
            session.switch_combat_turn() # プレイヤーのターンに戻す
            narrative = "あなたは逃げようとしたが、敵に阻まれてしまった！\n\n" + enemy_response.get("narrative", "")
            self.bot.dispatch("game_proceed", session, "逃走失敗", enemy_response)
            return narrative

    async def proceed_game(self, user_id: int, user_input: str) -> Dict[str, Any]:
        """
        プレイヤーの行動を受け取り、AIの応答を生成してゲームを1ターン進行させます。
        """
        session = self.get_session(user_id)
        if not session:
            raise GameError(f"アクティブなゲームセッションが見つかりません。")

        # AI Serviceを呼び出して応答を生成
        ai_response = await self.ai.generate_game_response(session, user_input)

        # --- AIの応答を解釈し、ゲームの状態を更新 ---
        session.last_response = ai_response

        # 対話履歴を更新
        session.conversation_history.append({"role": "user", "content": user_input})
        session.conversation_history.append({"role": "assistant", "content": json.dumps(ai_response, ensure_ascii=False)})

        # 時間を経過させる
        session.advance_time(self.worlds)

        # キャラクターの状態を更新 (経験値など)
        self._apply_state_changes(session, ai_response.get("state_changes", {}))

        # 勝利が確定した場合、特別なプロンプトでAIに最終描写を依頼する
        if session.victory_prompt:
            victory_response = await self.ai.generate_game_response(session, session.victory_prompt)
            ai_response["narrative"] += "\n\n" + victory_response.get("narrative", "敵をすべて倒した！")
            session.victory_prompt = None # 使用済みなのでクリア
            self.bot.dispatch("game_proceed", session, user_input, ai_response)
            return ai_response

        # 戦闘中であれば、ターンを切り替えて敵の行動を処理
        if session.in_combat:
            session.switch_combat_turn()
            # 敵のターンを処理
            enemy_response = await self.ai.generate_game_response(session, "敵のターン")
            self._apply_state_changes(session, enemy_response.get("state_changes", {}))
            
            # プレイヤーのターンに戻す
            session.switch_combat_turn()
            
            # プレイヤーの死亡判定
            if session.character.is_dead:
                # ゲームオーバー処理を呼び出し、特別な物語を返す
                game_over_narrative = await self._handle_game_over(session)
                ai_response["narrative"] += "\n\n" + enemy_response.get("narrative", "") + "\n\n" + game_over_narrative
                # ゲーム進行イベントを発行して終了
                ai_response["game_over"] = True
                self.bot.dispatch("game_proceed", session, user_input, ai_response)
                return ai_response

            # プレイヤーの行動結果と敵の行動結果を結合して返す
            # ここでは単純に物語を結合するが、より洗練された方法も考えられる
            ai_response["narrative"] += "\n\n" + enemy_response.get("narrative", "")

        # ゲーム進行イベントを発行
        self.bot.dispatch("game_proceed", session, user_input, ai_response)

        return ai_response

    async def _handle_game_over(self, session: GameSession) -> str:
        """プレイヤー死亡時のゲームオーバー処理を行う。"""
        char_name = session.character.name
        user_id = session.user_id

        # AIに最後の物語と死因を生成させる
        final_response = await self.ai.generate_game_response(session, "プレイヤーは力尽きた。その最後の瞬間を英雄譚の終わりのように描写し、state_changesにcause_of_deathを記述してください。")
        final_narrative = final_response.get("narrative", f"「{char_name}」の冒険は、ここで終わりを告げた...")
        cause_of_death = final_response.get("state_changes", {}).get("cause_of_death", "戦闘による死亡")

        # 世界の状態に「墓」としてキャラクターの記録を追加
        world_state = await self.world_repo.load()
        graveyard = world_state.get("graveyard", {})
        graveyard[session.character.char_id] = {
            "name": char_name,
            "level": session.character.level,
            "cause_of_death": cause_of_death,
            "dropped_items": session.character.inventory
        }
        await self.world_repo.save(world_state)

        # ゲーム終了イベントを発行
        self.bot.dispatch("game_end", session)

        # SessionManagerからセッションを削除
        self.sessions.delete_session(user_id)
        print(f"ユーザー({user_id})のキャラクター「{char_name}」が死亡し、ゲームオーバーとなりました。")

        return final_narrative

    async def use_item(self, user_id: int, item_name: str) -> Dict[str, Any]:
        """
        インベントリのアイテムを使用します。

        Returns:
            AIによって生成されたアイテム使用の結果。
        """
        session = self.get_session(user_id)
        if not session:
            raise GameError("アクティブなゲームセッションがありません。")

        # プレイヤーがアイテムを所持しているか確認
        if not item_name in session.character.inventory:
            raise GameError(f"アイテム「{item_name}」を所持していません。")

        # アイテムを消費
        session.character.remove_item(item_name)

        # AIにアイテム使用の効果を生成させる
        item_use_prompt = f"アイテム使用: 「{item_name}」。このアイテムの効果を解釈し、結果を描写してください。"
        ai_response = await self.ai.generate_game_response(session, item_use_prompt)

        # 状態変化を適用
        self._apply_state_changes(session, ai_response.get("state_changes", {}))

        self.bot.dispatch("game_proceed", session, f"アイテム使用: {item_name}", ai_response)
        return ai_response

    async def loot_grave(self, user_id: int, dead_char_name: str) -> List[str]:
        """
        指定された墓を探索し、ドロップされたアイテムを回収します。

        Returns:
            回収したアイテムのリスト。
        """
        session = self.get_session(user_id)
        if not session:
            raise GameError("アイテムを回収するには、アクティブなゲームセッションを開始している必要があります。")

        world_state = await self.world_repo.load()
        graveyard = world_state.get("graveyard", {})

        target_grave_id = None
        for char_id, data in graveyard.items():
            if data.get("name") == dead_char_name:
                target_grave_id = char_id
                break

        if not target_grave_id or not graveyard[target_grave_id].get("dropped_items"):
            return [] # 墓が見つからないか、アイテムがない

        looted_items = graveyard[target_grave_id].pop("dropped_items", [])
        for item in looted_items:
            session.character.add_item(item)

        await self.world_repo.save(world_state) # アイテムがなくなった状態を保存
        return looted_items

    def _apply_state_changes(self, session: GameSession, state_changes: Dict[str, Any]):
        """AIの応答に基づいてキャラクターの状態を更新する"""
        character = session.character

        if xp_gain := state_changes.get("xp_gain"):
            if isinstance(xp_gain, int) and xp_gain > 0:
                character.add_xp(xp_gain)

        if hp_change := state_changes.get("hp_change"):
            if isinstance(hp_change, int):
                if hp_change < 0:
                    character.take_damage(abs(hp_change))
                else:
                    character.heal_hp(hp_change)

        if mp_change := state_changes.get("mp_change"):
            if isinstance(mp_change, int):
                if mp_change < 0:
                    character.spend_mp(abs(mp_change))
                else:
                    character.recover_mp(mp_change)

        if new_items := state_changes.get("new_items"):
            if isinstance(new_items, list):
                for item in new_items:
                    character.add_item(item)

        if quest_updates := state_changes.get("quest_updates"):
            if isinstance(quest_updates, dict):
                for quest_id, status in quest_updates.items():
                    if status == "active":
                        character.start_quest(quest_id)
                    elif status == "completed":
                        character.complete_quest(quest_id)

        if npc_updates := state_changes.get("npc_updates"):
            if isinstance(npc_updates, dict):
                for npc_id, updates in npc_updates.items():
                    if npc_id not in session.npc_states:
                        session.npc_states[npc_id] = {}
                    session.npc_states[npc_id].update(updates)

        if enemy_damage_list := state_changes.get("enemy_damage"):
            if isinstance(enemy_damage_list, list):
                for damage_info in enemy_damage_list:
                    target_id = damage_info.get("instance_id")
                    damage = damage_info.get("damage")
                    if target_id and isinstance(damage, int) and damage > 0:
                        target_enemy = next((e for e in session.current_enemies if e.instance_id == target_id), None)
                        if target_enemy:
                            target_enemy.take_damage(damage)
                            print(f"敵「{target_enemy.name}」({target_id}) に {damage} のダメージを与えた。残りHP: {target_enemy.hp}")

                defeated_enemies_this_turn = [e for e in session.current_enemies if e.is_defeated()]

                # 倒された敵を戦闘リストから削除
                session.current_enemies = [e for e in session.current_enemies if not e.is_defeated()]
                
                # プレイヤーの攻撃によって全ての敵が倒されたかチェック
                if not session.current_enemies:
                    # このターンに倒した敵も含めて報酬を計算
                    all_defeated_enemies = defeated_enemies_this_turn # 将来的に複数ターンにまたがる場合、これまでの敵も含む必要がある
                    xp_reward, items_reward = self._calculate_rewards(all_defeated_enemies)
                    
                    # 戦闘を終了させ、報酬をキャラクターに適用
                    self._end_combat(session, all_defeated_enemies)
                    
                    # AIに勝利の報告と報酬の内容を伝えて、描写を生成させる
                    session.victory_prompt = f"戦闘勝利。報酬として経験値{xp_reward}とアイテム{', '.join(items_reward) if items_reward else 'なし'}を獲得した。この勝利の瞬間を描写してください。"

        if combat_updates := state_changes.get("combat"):
            if isinstance(combat_updates, dict):
                status = combat_updates.get("status")
                if status == "start":
                    self._start_combat(session, combat_updates.get("enemies", []))
                elif status == "end":
                    self._end_combat(session)

    def _start_combat(self, session: GameSession, enemies_to_spawn: List[Dict[str, Any]]):
        """戦闘を開始する"""
        if session.in_combat:
            return # 既に戦闘中

        session.in_combat = True
        session.combat_turn = "player" # 戦闘開始時は必ずプレイヤーのターン
        session.current_enemies.clear()
        all_enemies_data = self.worlds.get('enemies') # fantasy_world.jsonなどから敵の基本データを取得
        if not all_enemies_data:
            return

        for enemy_info in enemies_to_spawn:
            enemy_id = enemy_info.get("id")
            count = enemy_info.get("count", 1)
            base_data = all_enemies_data.get(enemy_id)
            if base_data:
                for _ in range(count):
                    session.current_enemies.append(Enemy(base_data))
        print(f"戦闘開始: {', '.join([e.name for e in session.current_enemies])}")

    def _calculate_rewards(self, defeated_enemies: List[Enemy]) -> (int, List[str]):
        """倒された敵のリストから合計報酬を計算する"""
        total_xp = 0
        total_items = []
        for enemy in defeated_enemies:
            total_xp += enemy.rewards.get("xp", 0)
            total_items.extend(enemy.rewards.get("items", []))
        return total_xp, total_items

    def _end_combat(self, session: GameSession, all_defeated_enemies: List[Enemy]):
        """戦闘を終了する"""
        session.in_combat = False

        # 報酬を計算してキャラクターに適用
        xp_reward, items_reward = self._calculate_rewards(all_defeated_enemies)
        session.character.add_xp(xp_reward)
        for item in items_reward:
            session.character.add_item(item)

        session.current_enemies.clear()
        print("戦闘終了")