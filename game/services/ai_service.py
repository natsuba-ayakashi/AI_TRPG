from typing import TYPE_CHECKING, Dict, Any, List, Optional
import json
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
        builder = PromptBuilder(session, self.prompts, self.world_data)
        
        prompt_str = (builder
            .add(BasePromptComponent)
            .add(RulesComponent)
            .add(CharacterComponent)
            .add(CombatComponent)
            .add(NpcStateComponent)
            .add(InventoryComponent)
            .add(PuzzleComponent)
            .add(SpecialKeywordsComponent)
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