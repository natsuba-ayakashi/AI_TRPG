from typing import TYPE_CHECKING, Dict, Any, List
import json
from openai import AsyncOpenAI

from core.errors import AIConnectionError

if TYPE_CHECKING:
    from game.models.session import GameSession
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader
    from infrastructure.data_loaders.prompt_loader import PromptLoader

class AIService:
    """
    AIモデルとの対話を担当するサービスクラス。
    ゲームマスター(GM)としての応答を生成します。
    """
    def __init__(
        self,
        base_url: str,
        model_name: str,
        world_data_loader: "WorldDataLoader",
        prompt_loader: "PromptLoader"
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama", # Ollamaの場合は必須
        )
        self.model_name = model_name
        self.world_data = world_data_loader.get_world('fantasy_world')
        self.prompts = prompt_loader

    def _build_system_prompt(self, session: "GameSession") -> str:
        """AIに与える役割や背景情報を定義するシステムプロンプトを構築する。"""
        
        # プロンプトの各部分をリストとして構築
        prompt_parts: List[str] = []

        # 1. ベースプロンプト
        prompt_parts.append(self.prompts.get('game_master.base_prompt', ''))

        # 2. 基本ルール
        headers = self.prompts.get('game_master.headers', {})
        world_rules = self.world_data.get('rules', '基本的なファンタジーTRPGのルールに従ってください。')
        prompt_parts.append(f"\n{headers.get('rules', '### 基本ルール')}\n{world_rules}")

        # 3. キャラクター情報
        char_info = f"""
{headers.get('character', '### キャラクター情報')}
名前: {session.character.name}
種族: {session.character.race}
クラス: {session.character.class_}
能力値: {session.character.stats}
技能: {session.character.skills}
背景: {session.character.background}"""
        prompt_parts.append(char_info)

        # 4. 戦闘中の情報
        if session.in_combat:
            combat_info = f"\n{headers.get('combat', '### 現在の戦闘状況')}\n"
            if session.combat_turn == "player":
                combat_info += "現在のターン: **プレイヤー**。プレイヤーの行動に対する結果を描写してください。\n"
            else:
                combat_info += "現在のターン: **敵**。敵の行動を決定し、その結果を描写してください。\n"
            combat_info += "敵:\n"
            for enemy in session.current_enemies:
                combat_info += f"- {enemy.name} (HP: {enemy.hp}/{enemy.max_hp}, ID: {enemy.instance_id})\n"
            prompt_parts.append(combat_info)

        # 5. NPCの現在の状態
        if session.npc_states:
            npc_info = f"\n{headers.get('npc', '### NPCの現在の状態')}\n"
            all_npcs = self.world_data.get('npcs', {})
            for npc_id, npc_state in session.npc_states.items():
                npc_base_info = all_npcs.get(npc_id, {})
                npc_name = npc_base_info.get('name', '不明なNPC')
                npc_info += f"- {npc_name} (ID: {npc_id}): {npc_state}\n"
            prompt_parts.append(npc_info)

        # 6. インベントリ内のアイテム情報
        if session.character.inventory:
            inventory_info = f"\n{headers.get('inventory', '### 所持アイテム情報')}\n"
            all_items = self.world_data.get('items', {})
            for item_name in session.character.inventory:
                item_data = all_items.get(item_name.lower().replace(" ", "_"), {})
                item_desc = item_data.get('description', '効果不明のアイテム。')
                inventory_info += f"- {item_name}: {item_desc}\n"
            prompt_parts.append(inventory_info)
        
        # 7. 特殊キーワード
        special_keywords = self.prompts.get('game_master.special_keywords', {})
        prompt_parts.append(f"\n{special_keywords.get('victory', '')}")
        prompt_parts.append(special_keywords.get('item_use', ''))

        # 8. 応答フォーマット
        response_format = self.prompts.get('game_master.response_format', {})
        format_body = json.dumps(response_format.get('body'), ensure_ascii=False, indent=2)
        prompt_parts.append(f"\n{response_format.get('header', '')}\n{format_body}\n{response_format.get('footer', '')}")

        return "\n".join(filter(None, prompt_parts))


    def _build_messages(self, session: "GameSession", user_input: str) -> list[dict]:
        """AIに送信するメッセージのリストを構築する。"""
        messages = []
        # 過去の対話履歴を追加
        for entry in session.conversation_history:
            messages.append({"role": entry["role"], "content": entry["content"]})
            
        # 今回のプレイヤーの行動を追加
        messages.append({"role": "user", "content": user_input})
        
        return messages

    async def generate_game_response(self, session: "GameSession", user_input: str) -> Dict[str, Any]:
        """
        プレイヤーの入力に基づき、AIからゲームの応答を生成します。
        """
        system_prompt = self._build_system_prompt(session)
        messages = self._build_messages(session, user_input)

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": system_prompt}] + messages,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            response_content = response.choices[0].message.content
            return json.loads(response_content)
        except Exception as e:
            raise AIConnectionError(f"AIからの応答生成に失敗しました: {e}") from e

    async def generate_introduction(self, session: "GameSession") -> Dict[str, Any]:
        """
        ゲーム開始時の導入シナリオをAIから生成します。
        """
        # 導入用のシステムプロンプトを構築
        prompt_parts: List[str] = []
        headers = self.prompts.get('game_master.headers', {})
        
        # 1. ベースプロンプト
        prompt_parts.append(self.prompts.get('introduction.base_prompt', ''))

        # 2. 世界設定
        world_rules = self.world_data.get('rules', '基本的なファンタジーTRPGのルールに従ってください。')
        prompt_parts.append(f"\n{headers.get('rules', '### 基本ルール')}\n{world_rules}")

        # 3. キャラクター情報
        char_info = f"""
{headers.get('character', '### キャラクター情報')}
名前: {session.character.name}
種族: {session.character.race}
クラス: {session.character.class_}
能力値: {session.character.stats}
技能: {session.character.skills}
背景: {session.character.background}"""
        prompt_parts.append(char_info)

        # 4. 応答フォーマット
        response_format = self.prompts.get('introduction.response_format', {})
        format_body = json.dumps(response_format.get('body'), ensure_ascii=False, indent=2)
        prompt_parts.append(f"\n{response_format.get('header', '')}\n{format_body}")
        
        system_prompt = "\n".join(filter(None, prompt_parts))

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": system_prompt}],
                temperature=0.8, # 少し創造性を高める
                response_format={"type": "json_object"},
            )
            response_content = response.choices[0].message.content
            # 生成された導入を最初の会話として履歴に追加
            session.conversation_history.append({"role": "assistant", "content": response_content})
            return json.loads(response_content)
        except Exception as e:
            raise AIConnectionError(f"AIからの導入シナリオ生成に失敗しました: {e}") from e