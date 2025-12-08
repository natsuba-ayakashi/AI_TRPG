from typing import TYPE_CHECKING, Dict, Any
import httpx
import json

from core.errors import AIConnectionError

if TYPE_CHECKING:
    from game.models.session import GameSession
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader

class AIService:
    """
    AIモデルとの対話を担当するサービスクラス。
    ゲームマスター(GM)としての応答を生成します。
    """
    def __init__(self, api_key: str, model_name: str, world_data_loader: "WorldDataLoader"):
        self.api_key = api_key
        self.model_name = model_name
        self.world_data = world_data_loader.get('fantasy_world') # 'fantasy_world.json' を読み込む
        self.http_client = httpx.AsyncClient(timeout=60.0)

    def _build_system_prompt(self, session: "GameSession") -> str:
        """AIに与える役割や背景情報を定義するシステムプロンプトを構築する。"""
        
        # 世界設定やルールをプロンプトに組み込む
        world_rules = self.world_data.get('rules', '基本的なファンタジーTRPGのルールに従ってください。')
        
        # 戦闘中の情報をプロンプトに追加
        combat_info = ""
        if session.in_combat:
            combat_info += "\n### 現在の戦闘状況\n"
            if session.combat_turn == "player":
                combat_info += "現在のターン: **プレイヤー**。プレイヤーの行動に対する結果を描写してください。\n"
            else: # "enemy"
                combat_info += "現在のターン: **敵**。敵の行動を決定し、その結果を描写してください。\n"
            combat_info += "敵:\n"
            for enemy in session.current_enemies:
                combat_info += f"- {enemy.name} (HP: {enemy.hp}/{enemy.max_hp}, ID: {enemy.instance_id})\n"

        # NPCの現在の状態をプロンプトに追加
        npc_info = ""
        if session.npc_states:
            npc_info += "\n### NPCの現在の状態\n"
            all_npcs = self.world_data.get('npcs', {})
            for npc_id, npc_state in session.npc_states.items():
                npc_base_info = all_npcs.get(npc_id, {})
                npc_name = npc_base_info.get('name', '不明なNPC')
                npc_info += f"- {npc_name} (ID: {npc_id}): {npc_state}\n"

        # インベントリ内のアイテム情報をプロンプトに追加
        inventory_info = ""
        if session.character.inventory:
            inventory_info += "\n### 所持アイテム情報\n"
            all_items = self.world_data.get('items', {})
            for item_name in session.character.inventory:
                # アイテムIDは小文字、表示名はそのまま、と仮定してデータを引く
                item_data = all_items.get(item_name.lower().replace(" ", "_"), {})
                item_desc = item_data.get('description', '効果不明のアイテム。')
                inventory_info += f"- {item_name}: {item_desc}\n"

        system_prompt = f"""
あなたは、テキストベースのTRPGの優れたゲームマスター(GM)です。
以下のルールとキャラクター設定に基づいて、プレイヤーの行動に対する結果を物語として描写してください。

### 基本ルール
{world_rules}

### キャラクター情報
名前: {session.character.name}
種族: {session.character.race}
クラス: {session.character.class_}
能力値: {session.character.stats}
技能: {session.character.skills}
背景: {session.character.background}
{combat_info}
{npc_info}
{inventory_info}

もしプレイヤーの行動入力が「戦闘勝利」というキーワードで始まっていたら、それは戦闘に勝利したことを意味します。その戦いで得た報酬（経験値やアイテム）を描写に含め、勝利の物語を生成してください。

もしプレイヤーの行動入力が「アイテム使用」というキーワードで始まっていたら、使用されたアイテムの効果を解釈し、HPの回復などの結果を `state_changes` に含めて応答してください。

### 応答フォーマット
あなたの応答は、必ず以下の構造を持つJSON形式でなければなりません。
{{
  "narrative": "プレイヤーに表示する物語の描写。状況、NPCのセリフ、行動の結果などを記述します。",
  "action_result": {{
    "type": "DICE_ROLL",
    "details": {{
      "skill": "交渉",
      "target": 12,
      "roll": 15,
      "success": true
    }}
  }},
  "state_changes": {{
    "xp_gain": 10,
    "new_items": ["古い鍵"],
    "hp_change": -5,
    "cause_of_death": "ゴブリンの奇襲による失血死",
    "mp_change": 10,
    "quest_updates": {{
      "main_quest_02": "active"
    }},
    "npc_updates": {{
      "npc_gardener": {{"disposition": "friendly", "has_given_key": true}}
    }},
    "combat": {{
      "status": "start",
      "enemies": [
        {{"id": "goblin_warrior", "count": 2}}
      ]
    }}
  }}
}}
キーが存在しない場合は省略してください。
"""
        return system_prompt

    def _build_messages(self, session: "GameSession", user_input: str) -> list[dict]:
        """AIに送信するメッセージのリストを構築する。"""
        messages = [{"role": "system", "content": self._build_system_prompt(session)}]
        
        # 過去の対話履歴を追加
        for entry in session.conversation_history:
            messages.append(entry)
            
        # 今回のプレイヤーの行動を追加
        messages.append({"role": "user", "content": user_input})
        
        return messages

    async def generate_game_response(self, session: "GameSession", user_input: str) -> Dict[str, Any]:
        """
        プレイヤーの入力に基づき、AIからゲームの応答を生成します。
        """
        messages = self._build_messages(session, user_input)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": messages,
            "response_format": {"type": "json_object"}
        }

        try:
            response = await self.http_client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            
            ai_response_data = response.json()
            return json.loads(ai_response_data['choices'][0]['message']['content'])
        except (httpx.HTTPStatusError, json.JSONDecodeError, KeyError) as e:
            raise AIConnectionError(f"AIからの応答生成に失敗しました: {e}") from e