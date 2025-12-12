from typing import TYPE_CHECKING, Dict, Any, List, Optional
import json
import logging
from openai import AsyncOpenAI

from core.errors import AIConnectionError
from game.prompts.builder import (
    PromptBuilder,
    BasePromptComponent,
    RulesComponent,
    CharacterComponent,
    CombatComponent,
    NpcStateComponent,
    InventoryComponent,
    PuzzleComponent,
    SpecialKeywordsComponent,
    ResponseFormatComponent
)

if TYPE_CHECKING:
    from game.models.session import GameSession
    from game.loaders.world_data_loader import WorldDataLoader
    from game.loaders.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)

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
        builder = PromptBuilder(session, self.prompts, self.world_data)
        
        # 行動提案の長さを制限するコンポーネントを定義
        class ActionLengthConstraintComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                return (
                    "\n[IMPORTANT UI CONSTRAINT]\n"
                    "The 'suggested_actions' list MUST contain EXACTLY 3 items.\n"
                    "The 'suggested_actions' list MUST contain very short phrases.\n"
                    "Each action string MUST be 20 characters or less (Japanese) to fit in the button UI.\n"
                    "Example: ['剣で攻撃', '逃げる', 'ポーションを使う']"
                )

        # 敵出現時のフォーマット制約を追加
        class EnemyFormatConstraintComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                return (
                    "\n[IMPORTANT JSON FORMAT CONSTRAINT]\n"
                    "When adding enemies in 'state_changes.new_enemies', use ONLY their IDs as strings.\n"
                    "DO NOT use objects/dictionaries.\n"
                    "Correct: \"new_enemies\": [\"goblin_warrior\", \"wolf\"]\n"
                    "Incorrect: \"new_enemies\": [{\"id\": \"goblin_warrior\", ...}]"
                )

        # クエスト状況をプロンプトに含めるコンポーネント
        class QuestComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                current_quests = getattr(session, "quests", {})
                if not current_quests:
                    return None
                
                lines = ["\n[QUEST STATUS]"]
                quests_data = self.world_data.get("quests", {})
                
                for q_id, status in current_quests.items():
                    if status == "inactive": continue
                    q_info = quests_data.get(q_id, {})
                    title = q_info.get("title", q_id)
                    lines.append(f"- {title} (ID: {q_id}): {status}")
                
                return "\n".join(lines)

        # 現在地のNPC情報（好感度含む）をプロンプトに含めるコンポーネント
        class CurrentLocationNpcComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                current_loc_id = getattr(session, "current_location_id", None)
                if not current_loc_id:
                    return None
                
                world_data = self.world_data_loader.get_world(session.world_name)
                location = world_data.get("locations", {}).get(current_loc_id)
                if not location or "npcs" not in location:
                    return None
                
                npc_ids = location["npcs"]
                if not npc_ids:
                    return None

                lines = ["\n[NPCs IN CURRENT LOCATION]"]
                npcs_data = world_data.get("npcs", {})
                # セッションごとのNPC状態（好感度など）
                npc_states = getattr(session, "npc_states", {})

                for npc_id in npc_ids:
                    if npc_id not in npcs_data:
                        continue
                    npc_info = npcs_data[npc_id]
                    
                    # 動的な状態があれば取得（なければデフォルト）
                    current_state = npc_states.get(npc_id, {})
                    disposition = current_state.get("disposition", npc_info.get("disposition", "neutral"))
                    
                    lines.append(f"- Name: {npc_info['name']} (ID: {npc_id})")
                    lines.append(f"  Disposition: {disposition}")
                    lines.append(f"  Personality: {npc_info.get('personality', '')}")
                    lines.append(f"  Topics: {', '.join(npc_info.get('dialogue_topics', []))}")
                
                return "\n".join(lines)

        # NPC状態更新のフォーマット制約
        class NpcUpdateFormatComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                return (
                    "\n[IMPORTANT JSON FORMAT CONSTRAINT]\n"
                    "To change NPC disposition, use 'state_changes.npc_updates'.\n"
                    "Format: \"npc_updates\": [{\"id\": \"npc_id\", \"disposition\": \"friendly\"}]"
                )

        # ダイスロールとシステム出力の禁止制約
        class SystemOutputConstraintComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                return (
                    "\n[IMPORTANT CONSTRAINTS]\n"
                    "1. DO NOT simulate dice rolls or output text like '(1d20+5=15)' in the narrative.\n"
                    "2. DO NOT include 'action_result' in your JSON response. This field is reserved for the system.\n"
                    "3. Decide outcomes based on the story and character stats, but hide the mechanics."
                )

        prompt_str = (builder
            .add(BasePromptComponent)
            .add(RulesComponent)
            .add(CharacterComponent)
            .add(CombatComponent)
            .add(NpcStateComponent)
            .add(InventoryComponent)
            .add(PuzzleComponent)
            .add(SpecialKeywordsComponent)
            .add(QuestComponent)
            .add(CurrentLocationNpcComponent)
            .add(ActionLengthConstraintComponent)
            .add(EnemyFormatConstraintComponent)
            .add(NpcUpdateFormatComponent)
            .add(SystemOutputConstraintComponent)
            .add(ResponseFormatComponent, prompt_key='game_master.response_format')
            .build()
        )
        return prompt_str

    def _build_messages(self, session: "GameSession", user_input: str) -> list[dict]:
        """AIに送信するメッセージのリストを構築する。"""
        messages = []
        # 過去の対話履歴を追加
        for entry in session.conversation_history:
            messages.append({"role": entry["role"], "content": entry["content"]})
            
        # 今回のプレイヤーの行動を追加
        messages.append({"role": "user", "content": user_input})
        
        return messages

    async def generate_response(self, session: "GameSession", user_input: str) -> Dict[str, Any]:
        """
        プレイヤーの入力に基づき、AIからゲームの応答を生成します。
        """
        system_prompt = self._build_system_prompt(session)
        messages = self._build_messages(session, user_input)

        retries = 2
        for attempt in range(retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "system", "content": system_prompt}] + messages,
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )
                response_content = response.choices[0].message.content
                return json.loads(response_content)
            except json.JSONDecodeError as e:
                logger.warning(f"AI returned invalid JSON (Attempt {attempt+1}/{retries+1}): {e}")
                # デバッグ用に生の応答内容をログに出す（長すぎる場合は切り詰める）
                logger.debug(f"Raw content: {response_content[:500]}...")
                if attempt == retries:
                    raise AIConnectionError(f"AIが不正なJSONを返しました: {e}") from e
            except Exception as e:
                raise AIConnectionError(f"AIからの応答生成に失敗しました: {e}") from e

    def _build_introduction_prompt(self, session: "GameSession") -> str:
        """導入シナリオ生成用のシステムプロンプトを構築する。"""
        builder = PromptBuilder(session, self.prompts, self.world_data)

        # 導入用のベースプロンプトを上書きするコンポーネント
        class IntroductionBaseComponent(BasePromptComponent):
            def render(self) -> Optional[str]:
                return self.prompts.get('introduction.base_prompt')

        prompt_str = (builder
            .add(IntroductionBaseComponent)
            .add(RulesComponent)
            .add(CharacterComponent)
            .add(ResponseFormatComponent, prompt_key='introduction.response_format')
            .build()
        )
        return prompt_str

    async def generate_introduction(self, session: "GameSession") -> Dict[str, Any]:
        """
        ゲーム開始時の導入シナリオをAIから生成します。
        """
        system_prompt = self._build_introduction_prompt(session)

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": system_prompt}],
                temperature=0.8, # 少し創造性を高める
                response_format={"type": "json_object"},
            )
            response_content = response.choices[0].message.content
            response_json = json.loads(response_content)
            # 生成された導入を最初の会話として履歴に追加
            # 同時に、このセッションのメインストーリー情報を保存
            session.final_boss_id = response_json.get("final_boss_id")
            session.quest_chain_ids = response_json.get("quest_chain_ids", [])

            if narrative := response_json.get("narrative"):
                session.add_history("assistant", narrative)
            return response_json
        except Exception as e:
            raise AIConnectionError(f"AIからの導入シナリオ生成に失敗しました: {e}") from e