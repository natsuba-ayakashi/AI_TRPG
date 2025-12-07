import json
import google.generativeai as genai # type: ignore
import os
import logging
from core.prompt_loader import prompts
from errors import AIConnectionError
from core.data_loader import DataLoader

GM_PERSONALITIES = {
    "standard": "あなたは創造性豊かで、プレイヤーを楽しませるTRPGのゲームマスターです。",
    "poetic": "あなたは詩的な語り口で、世界の美しさと儚さを描写するナレーターのようなゲームマスターです。比喩や情景描写を多用してください。",
    "tactical": "あなたは戦術的で、状況を冷静に分析し、論理的な選択肢を提示するゲームマスターです。戦闘や探索では、具体的なデータやリスクを強調してください。",
    "enthusiastic": "あなたは非常に情熱的で、プレイヤーの行動を全力で応援し、物語を盛り上げるゲームマスターです。感嘆符を多用し、エネルギッシュなテキストを生成してください。"
}

logger = logging.getLogger(__name__)

# AIモデルのインスタンスは一度だけ生成して再利用する
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
world_data_loader = DataLoader("game_data/worlds")
item_data_loader = DataLoader("game_data")
ai_model = genai.GenerativeModel('gemini-pro')

class PromptBuilder:
    """ゲームセッションの状態に基づいて動的にプロンプトを構築するクラス。"""
    def __init__(self, session):
        self.session = session
        self.prompt_parts = []

    def build(self):
        """プロンプトの各部分を組み立てて、最終的なプロンプト文字列を返す。"""
        self._add_base()
        self._add_contextual_modules()
        self._add_constraints()
        self._add_output_format()
        return "\n".join(self.prompt_parts)

    def _add_base(self):
        """プロンプトの基本部分を追加する。"""
        base_template = prompts.get('action_result.base')
        gm_personality = GM_PERSONALITIES.get(self.session.gm_personality, GM_PERSONALITIES["standard"])
        
        # last_responseがNoneの場合でもエラーにならないように空のJSON文字列を渡す
        last_response_str = json.dumps(self.session.last_response, ensure_ascii=False, indent=2) if self.session.last_response else "{}"

        # 世界設定キーから詳細な説明を取得
        world_data = world_data_loader.get(self.session.world_setting)
        world_description = world_data['description'] if world_data else self.session.world_setting

        base_prompt = base_template.format(
            gm_personality=gm_personality,
            world_setting=world_description,
            difficulty_level=self.session.difficulty_level,
            character_sheet=json.dumps(self.session.character.to_dict(), ensure_ascii=False, indent=2),
            last_response=last_response_str,
            action_description=self.session.last_response.get("player_action", "ゲームを開始する") if self.session.last_response else "ゲームを開始する"
        )
        self.prompt_parts.append(base_prompt)

    def _add_contextual_modules(self):
        """ゲームの進行状況に応じて、動的なモジュールを追加する。"""
        # 過去の英雄ログが存在する場合
        if self.session.legacy_log:
            legacy_template = prompts.get('action_result.modules.legacy_log')
            self.prompt_parts.append(legacy_template.format(legacy_log=json.dumps(self.session.legacy_log, ensure_ascii=False, indent=2)))

        # 世界観がクトゥルフ風の場合
        if self.session.world_setting == 'cthulhu':
            self.prompt_parts.append(prompts.get('action_result.modules.cthulhu_rules'))

        # ゲームがある程度進行した場合（例: historyが5件以上）
        if len(self.session.character.history) >= 10:
            self.prompt_parts.append(prompts.get('action_result.modules.time_progression_rules'))
        
        if len(self.session.character.history) >= 15:
            self.prompt_parts.append(prompts.get('action_result.modules.romance_rules'))

        # --- アイテム効果の反映 ---
        equipped_gear = self.session.character.equipment.get("equipped_gear", []) # 装備中のアイテムリストを取得
        all_items_data = item_data_loader.get('items') # items.yaml の内容を取得
        if all_items_data:
            item_effects = []
            for item_name in equipped_gear: # 装備中のアイテムのみループ
                item_data = all_items_data.get(item_name)
                if item_data and "effect_for_ai" in item_data:
                    item_effects.append(item_data["effect_for_ai"])
            if item_effects:
                self.prompt_parts.append("# 所持アイテムによる特殊効果\n" + "\n".join(item_effects))

    def _add_constraints(self):
        """静的な制約条件を追加する。"""
        self.prompt_parts.append(prompts.get('action_result.common_constraints'))

    def _add_output_format(self):
        """出力形式の指示を追加する。"""
        self.prompt_parts.append(prompts.get('action_result.output_format'))

def build_action_result_prompt(session):
    """
    ゲームセッション情報に基づいて、AIへの行動結果生成プロンプトを構築する。
    game_logic.py から呼び出されることを想定しています。
    """
    builder = PromptBuilder(session)
    return builder.build()

def get_ai_response(prompt):
    """Geminiモデルを呼び出し、応答をJSONとして解析して返します。"""
    try:
        logger.debug(f"AIへのプロンプト:\n{prompt}")
        response = ai_model.generate_content(prompt)
        # AIの返答からJSON部分を抽出してパースする
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(json_text)
    except Exception as e:
        logger.error(f"AI応答の解析中にエラーが発生しました: {e}", exc_info=True)
        logger.error(f"受信テキスト: {getattr(response, 'text', 'N/A')}")
        raise AIConnectionError("AIからの応答形式が正しくありません。")

def generate_image_from_prompt(prompt: str) -> str | None:
    """画像生成AIを呼び出し、生成された画像のURLを返します。"""
    # この機能を利用するには、Google Cloudプロジェクトの設定と認証が必要です。
    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel

        project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
        if not project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT_IDが.envファイルに設定されていません。画像生成をスキップします。")
            return None

        vertexai.init(project=project_id, location="us-central1")

        model = ImageGenerationModel.from_pretrained("imagegeneration@005")

        logger.info(f"画像生成プロンプト: {prompt}")
        # ネガティブプロンプトで低品質な画像を避ける
        negative_prompt = "text, watermark, blurry, low quality, ugly"

        # 画像を生成
        images = model.generate_images(
            prompt=f"cinematic photo, epic fantasy art, {prompt}",
            number_of_images=1,
            negative_prompt=negative_prompt,
            aspect_ratio="16:9" # DiscordのEmbedで見やすい比率
        )

        # 生成された画像はGCSに自動で保存されるため、その公開URLを取得する
        # 注意: この方法はGCSバケットが公開設定になっている必要があります。
        # より安全な方法は署名付きURLを発行することです。
        image = images[0]
        # GCS URI (gs://...) を公開HTTP URL (https://storage.googleapis.com/...) に変換
        gcs_uri = image._image_bytes._gcs_uri
        public_url = gcs_uri.replace("gs://", "https://storage.googleapis.com/")
        return public_url

    except (ImportError, Exception) as e:
        logger.error(f"画像生成中にエラーが発生しました: {e}", exc_info=True)
        return None

def get_ai_generated_character(world_setting_key: str = "fantasy"):
    """AIにキャラクターを生成させるためのプロンプトを生成します。"""
    try:
        # 世界設定キーから詳細な説明を取得。見つからなければキー自体を説明として使う。
        world_data = world_data_loader.get(world_setting_key)
        world_description = world_data['description'] if world_data else world_setting_key

        base = prompts.get('character_generation.base').format(world_setting=world_description)
        constraints = prompts.get('character_generation.constraints')
        output_format = prompts.get('character_generation.output_format')
        prompt = "\n".join([base, constraints, "出力は必ず以下のJSON形式に従ってください。", output_format])
        
        response = ai_model.generate_content(prompt)
        # AIの返答からJSON部分を抽出してパースする
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(json_text)
    except Exception as e:
        logger.error(f"AIキャラクター生成中にエラーが発生しました: {e}", exc_info=True)
        logger.error(f"受信テキスト: {getattr(response, 'text', 'N/A')}")
        raise AIConnectionError("AIによるキャラクター生成に失敗しました。")