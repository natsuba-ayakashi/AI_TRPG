import datetime
from typing import List, Dict, Any, Optional

from .character import Character
# Note: The 'Enemy' model is assumed to exist for type hinting.
# You may need to create 'game/models/enemy.py' if it doesn't exist.
from .enemy import Enemy


class GameSession:
    """
    Holds the state of an active game session.
    This object lives only in memory and is not persisted to disk.
    """

    def __init__(self, user_id: int, character: Character, world_name: str):
        """
        Initializes a GameSession.

        Args:
            user_id: The Discord user ID of the player.
            character: The character object the player is using.
            world_name: The name of the world the game is set in.
        """
        self.user_id: int = user_id
        self.character: Character = character
        self.world_name: str = world_name

        # The thread_id is associated later, after the thread is created on Discord.
        self.thread_id: Optional[int] = None
        
        # The player's current location ID within the world.
        self.current_location_id: Optional[str] = None

        # The main story arc for this session.
        self.final_boss_id: Optional[str] = None
        self.quest_chain_ids: List[str] = []

        self.start_time: datetime.datetime = datetime.datetime.now()
        self.turn_count: int = 0

        # Conversation history with the AI.
        self.conversation_history: List[Dict[str, str]] = []

        # NPC state changes within this session.
        self.npc_states: Dict[str, Any] = {}

        # Combat-related state.
        self.in_combat: bool = False
        self.current_enemies: List[Enemy] = []
        self.combat_turn: str = "player"  # "player" or "enemy"
        self.combat_view_message_id: Optional[int] = None

    def add_history(self, role: str, content: str):
        """
        Adds a new entry to the conversation history.
        Removes the oldest entry if the history becomes too long.
        """
        # Limit history to a maximum of 20 entries.
        if len(self.conversation_history) >= 20:
            self.conversation_history.pop(0)
        self.conversation_history.append({"role": role, "content": content})

    def start_combat(self, enemies: List[Enemy]):
        """Starts combat mode."""
        self.in_combat = True
        self.current_enemies = enemies
        self.combat_turn = "player"  # Always start with the player's turn.

    def end_combat(self):
        """Ends combat mode."""
        self.in_combat = False
        self.current_enemies = []

    def apply_ai_response(self, user_input: str, response_data: Dict[str, Any], world_data: Dict[str, Any]):
        """
        AIからの応答を解釈し、セッションの状態を更新します。
        
        Args:
            user_input: プレイヤーの入力。
            response_data: AIからの応答データ。
            world_data: 現在の世界の静的データ（敵情報の参照などに使用）。
        """
        # ターン数をインクリメント
        self.turn_count += 1

        # 1. 会話履歴の更新
        if narrative := response_data.get("narrative"):
            self.add_history("user", user_input)
            self.add_history("assistant", narrative)

        # 2. 状態変化の適用
        if state_changes := response_data.get("state_changes"):
            previous_level = self.character.level
            # キャラクター関連の更新を委譲
            self.character.apply_state_changes(state_changes)

            # レベルアップ時のスキル習得チェック
            if self.character.level > previous_level:
                new_skills = self.character.check_new_skills(world_data)
                if new_skills:
                    state_changes["new_skills"] = new_skills

            # 場所の移動
            if new_location_id := state_changes.get("location_change"):
                self.current_location_id = new_location_id

            # 敵の攻撃処理 (システムによるダメージ計算)
            if enemy_actions := state_changes.get("enemy_actions"):
                total_damage = 0
                for action in enemy_actions:
                    enemy_id = action.get("enemy_id")
                    # インスタンスIDまたは定義IDで敵を検索
                    enemy = next((e for e in self.current_enemies if e.instance_id == enemy_id or e.enemy_id == enemy_id), None)
                    if enemy and action.get("type") == "attack":
                        # ダメージ計算: 攻撃力 - 防御力 (最低1)
                        damage = max(1, enemy.attack_power - self.character.defense)
                        self.character.take_damage(damage)
                        total_damage += damage
                
                # ログ出力用にhp_changeを更新 (負の値として加算)
                if total_damage > 0:
                    current_hp_change = state_changes.get("hp_change", 0)
                    state_changes["hp_change"] = current_hp_change - total_damage

            # NPCの状態更新
            if npc_updates := state_changes.get("npc_updates"):
                for npc_id, updates in npc_updates.items():
                    if npc_id not in self.npc_states:
                        self.npc_states[npc_id] = {}
                    self.npc_states[npc_id].update(updates)
            
            # 戦闘状態の更新
            if combat_update := state_changes.get("combat"):
                if combat_update.get("status") == "start":
                    enemy_ids = combat_update.get("enemies", [])
                    all_enemies_data = world_data.get("enemies", {})
                    enemies_to_start = []
                    for enemy_id in enemy_ids:
                        if enemy_base_data := all_enemies_data.get(enemy_id):
                            enemies_to_start.append(Enemy(enemy_base_data))
                    if enemies_to_start:
                        self.start_combat(enemies_to_start)
                elif combat_update.get("status") == "end":
                    # 戦闘終了時の報酬処理
                    total_xp = 0
                    total_gold = 0
                    collected_items = []

                    for enemy in self.current_enemies:
                        rewards = enemy.rewards
                        total_xp += rewards.get("xp", 0)
                        total_gold += rewards.get("gold", 0)
                        if items := rewards.get("items"):
                            collected_items.extend(items)

                    if total_xp > 0:
                        prev_level = self.character.level
                        self.character.add_xp(total_xp)
                        state_changes["xp_gain"] = state_changes.get("xp_gain", 0) + total_xp
                        if self.character.level > prev_level:
                            if new_skills := self.character.check_new_skills(world_data):
                                state_changes["new_skills"] = state_changes.get("new_skills", []) + new_skills

                    if total_gold > 0:
                        self.character.gold += total_gold
                        state_changes["gold_change"] = state_changes.get("gold_change", 0) + total_gold

                    if collected_items:
                        for item in collected_items:
                            self.character.add_item(item)
                        state_changes["new_items"] = state_changes.get("new_items", []) + collected_items

                    self.end_combat()