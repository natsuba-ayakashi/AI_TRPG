import json
from typing import List, Dict, Any, Optional, Type
from abc import ABC, abstractmethod

# Forward references
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game.models.session import GameSession
    from infrastructure.data_loaders.prompt_loader import PromptLoader

# --- Base Component ---
class PromptComponent(ABC):
    """Base class for a part of a system prompt."""
    def __init__(self, session: 'GameSession', prompts: 'PromptLoader', world_data: Dict[str, Any]):
        self.session = session
        self.prompts = prompts
        self.world_data = world_data

    @abstractmethod
    def render(self) -> Optional[str]:
        """Renders the component into a string. Returns None if not applicable."""
        pass

# --- Concrete Components ---

class BasePromptComponent(PromptComponent):
    def render(self) -> Optional[str]:
        return self.prompts.get('game_master.base_prompt')

class RulesComponent(PromptComponent):
    def render(self) -> Optional[str]:
        header = self.prompts.get('game_master.headers.rules', '### 基本ルール')
        rules = self.world_data.get('rules', '基本的なファンタジーTRPGのルールに従ってください。')
        return f"{header}\n{rules}"

class CharacterComponent(PromptComponent):
    def render(self) -> Optional[str]:
        header = self.prompts.get('game_master.headers.character', '### キャラクター情報')
        char = self.session.character
        return f"""
{header}
名前: {char.name}
種族: {char.race}
クラス: {char.class_}
レベル: {char.level}
XP: {char.xp}/{char.xp_to_next_level}
所持金: {char.gold} G
能力値: {char.stats}
技能: {char.skills}
背景: {char.background}"""

class CombatComponent(PromptComponent):
    def render(self) -> Optional[str]:
        if not self.session.in_combat:
            return None
        
        header = self.prompts.get('game_master.headers.combat', '### 現在の戦闘状況')
        parts = [header]
        if self.session.combat_turn == "player":
            parts.append("現在のターン: **プレイヤー**。プレイヤーの行動に対する結果を描写してください。")
        else:
            parts.append("現在のターン: **敵**。敵の行動を決定し、その結果を描写してください。")
        
        parts.append("敵:")
        for enemy in self.session.current_enemies:
            parts.append(f"- {enemy.name} (HP: {enemy.hp}/{enemy.max_hp}, ATK: {enemy.attack_power}, ID: {enemy.instance_id})")
        
        parts.append(f"プレイヤー防御力: {self.session.character.defense}")
        parts.append("※敵が攻撃する場合、`state_changes` に `enemy_actions` リストを含めてください。例: `[{'enemy_id': '...', 'type': 'attack'}]`。ダメージはシステムが計算します。")

        return "\n".join(parts)

class NpcStateComponent(PromptComponent):
    def render(self) -> Optional[str]:
        """現在地のNPC情報を静的・動的データから構築してレンダリングする。"""
        current_location_id = self.session.current_location_id
        if not current_location_id:
            return None

        all_locations = self.world_data.get("locations", {})
        current_location_data = all_locations.get(current_location_id, {})
        npc_ids_in_location = current_location_data.get("npcs", [])

        if not npc_ids_in_location:
            return None
            
        header = self.prompts.get('game_master.headers.npc', '### 周囲のNPC情報')
        parts = [header]
        all_npcs = self.world_data.get('npcs', {})

        for npc_id in npc_ids_in_location:
            npc_data = all_npcs.get(npc_id)
            if not npc_data:
                continue
            
            npc_name = npc_data.get('name', '不明なNPC')
            personality = npc_data.get('personality', '')
            
            npc_info = f"- **{npc_name} (ID: {npc_id})**"
            if personality:
                npc_info += f"\n  - 性格/特徴: {personality}"
            
            if npc_dynamic_state := self.session.npc_states.get(npc_id):
                npc_info += f"\n  - 現在の様子: {npc_dynamic_state}"
            
            parts.append(npc_info)
        
        return "\n".join(parts)

class InventoryComponent(PromptComponent):
    def render(self) -> Optional[str]:
        if not self.session.character.inventory:
            return None

        header = self.prompts.get('game_master.headers.inventory', '### 所持アイテム情報')
        parts = [header]
        all_items = self.world_data.get('items', {})
        for item_name in self.session.character.inventory:
            item_data = all_items.get(item_name.lower().replace(" ", "_"), {})
            item_desc = item_data.get('description', '効果不明のアイテム。')
            parts.append(f"- {item_name}: {item_desc}")
        
        return "\n".join(parts)

class PuzzleComponent(PromptComponent):
    def render(self) -> Optional[str]:
        """現在地に存在する謎の情報をレンダリングする。"""
        current_location_id = self.session.current_location_id
        if not current_location_id:
            return None

        all_puzzles = self.world_data.get("puzzles", {})
        # 現在地にある謎を検索
        puzzle_data = next((p for p in all_puzzles.values() if p.get("location_id") == current_location_id), None)

        if not puzzle_data:
            return None

        header = self.prompts.get('game_master.headers.puzzle', '### 謎')
        return f"{header}\n{puzzle_data.get('description', '奇妙な仕掛けがある。')}"

class SpecialKeywordsComponent(PromptComponent):
    def render(self) -> Optional[str]:
        keywords = self.prompts.get('game_master.special_keywords', {})
        return "\n".join(keywords.values())

class ResponseFormatComponent(PromptComponent):
    def __init__(self, session: 'GameSession', prompts: 'PromptLoader', world_data: Dict[str, Any], prompt_key: str):
        super().__init__(session, prompts, world_data)
        self.prompt_key = prompt_key

    def render(self) -> Optional[str]:
        response_format = self.prompts.get(self.prompt_key, {})
        header = response_format.get('header', '')
        body = json.dumps(response_format.get('body'), ensure_ascii=False, indent=2)
        footer = response_format.get('footer', '')
        return f"\n{header}\n{body}\n{footer}"

# --- Prompt Builder ---
class PromptBuilder:
    """Builds a complete system prompt from various components."""
    def __init__(self, session: 'GameSession', prompts: 'PromptLoader', world_data: Dict[str, Any]):
        self.session = session
        self.prompts = prompts
        self.world_data = world_data
        self._components: List[PromptComponent] = []

    def add(self, component_class: Type[PromptComponent], *args, **kwargs) -> 'PromptBuilder':
        """Adds a component to the builder."""
        self._components.append(component_class(self.session, self.prompts, self.world_data, *args, **kwargs))
        return self

    def build(self) -> str:
        """Renders all components and joins them into a single string."""
        rendered_parts = [component.render() for component in self._components]
        return "\n\n".join(filter(None, rendered_parts))