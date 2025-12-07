import json
import google.generativeai as genai
import os

GM_PERSONALITIES = {
    "standard": "あなたは創造性豊かで、プレイヤーを楽しませるTRPGのゲームマスターです。",
    "poetic": "あなたは詩的な語り口で、世界の美しさと儚さを描写するナレーターのようなゲームマスターです。比喩や情景描写を多用してください。",
    "tactical": "あなたは戦術的で、状況を冷静に分析し、論理的な選択肢を提示するゲームマスターです。戦闘や探索では、具体的なデータやリスクを強調してください。",
    "enthusiastic": "あなたは非常に情熱的で、プレイヤーの行動を全力で応援し、物語を盛り上げるゲームマスターです。感嘆符を多用し、エネルギッシュなテキストを生成してください。"
}

# AIモデルのインスタンスは一度だけ生成して再利用する
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
ai_model = genai.GenerativeModel('gemini-pro')

def build_prompt(character, legacy_log=None, gm_personality_key="standard", world_setting="一般的なファンタジー世界"):
    """AIに渡すプロンプトを生成します。"""
    
    gm_description = GM_PERSONALITIES.get(gm_personality_key, GM_PERSONALITIES["standard"])

    legacy_section = ""
    if legacy_log:
        legacy_section = f"""
過去の英雄の伝説:
この世界では、過去に以下のような偉業を成し遂げた英雄の伝説が語り継がれています。
この伝説を、新しい物語の背景や登場人物の会話にさりげなく反映させてください。
{json.dumps(legacy_log, ensure_ascii=False, indent=2)}
"""

    world_setting_description = f"この物語は「{world_setting}」の世界観を舞台にしています。その設定に沿ったシナリオ、登場人物、アイテムを生成してください。"

    return f"""
{gm_description}
{world_setting_description}
以下のキャラクター情報と制約条件を厳密に守り、次のシナリオと選択肢、そしてキャラクターシートの更新案をJSON形式で出力してください。
{legacy_section}
現在のキャラクター情報:
{json.dumps(character, ensure_ascii=False, indent=2)}

制約条件:
- 物語にはキャラクターの `traits`（特徴）や `secrets`（秘密）を必ず反映させてください。
- プレイヤーに2〜3個の魅力的な選択肢を提示してください。
- 現在の物語の状況を要約した、簡潔で魅力的な「章のタイトル」を `chapter_title` として、`⚔️ `で始まる形式で生成してください。（例: `⚔️ 第2章：闇の森へ`）
- シナリオの情景を表現するための、**英語の短いフレーズ**（例: `A dark fantasy forest with a glowing sword`）を `image_prompt` として生成してください。
- 各選択肢を選んだ結果、キャラクターシートがどのように変化する可能性があるかを具体的に示してください。
- **ごく稀に（5%程度の確率で）**、物語に「希少なアイテムが手に入るイベント」や「隠されたボスに繋がる特殊なルート」をサプライズで登場させてください。
- その際、シナリオ描写でその希少性や特別感を強調してください。
- **同様に、ごく稀に（5%程度の確率で）**、プレイヤーが不利になるイベント（罠、敵の奇襲、アイテムの紛失など）を発生させてください。キャラクターの選択や状況に応じた自然な形で導入してください。
- **時間の経過**: `history` の項目数を時間の経過の指標とします。履歴が10増えるごとに、キャラクターが約1歳年を取ったと解釈し、その変化をシナリオに反映させてください。例えば、新しいNPCとの出会いや、恋愛イベント、結婚などを自然な形で提案してください。
- **恋愛と結婚**: プレイヤーの選択やキャラクターの性格に基づき、特定のNPCとの関係が深まることがあります。関係が十分に深まった場合、恋愛や結婚といった選択肢を提示しても構いません。
- **技能判定**: プレイヤーの行動が成功するか不確かな場合（例：崖を飛び越える、鍵を開ける、嘘をつく）、キャラクターの`skills`や`stats`を参照して成功/失敗を判定してください。技能値が高いほど成功しやすくなりますが、常に成功するとは限りません。判定結果をシナリオに反映させてください。
- **SAN値チェック**: 特に「クトゥルフ神話TRPG風」の世界観において、キャラクターが超自然的な存在に遭遇したり、恐ろしい真実を知ってしまったりした場合、`san`を減少させる更新案を生成してください。SAN値が低い（例: 20以下）場合、キャラクターの言動に影響が出る（幻覚を見る、奇妙な行動を取るなど）描写を加えてください。
- 物語が目的を達成し、英雄的な結末を迎えた場合は `"game_clear": true` を返してください。
- キャラクターが死亡したり、目的を果たせず絶望的な結末を迎えた場合は `"game_over": true` を返してください。
- 出力は必ず以下のJSON形式に従ってください。キーの名前も完全に一致させてください。

```json
{{
    "scenario": "ここに生成したシナリオを記述します。",
    "chapter_title": "⚔️ 第1章：始まりの街",
    "image_prompt": "A bustling medieval city at dusk, fantasy style",
    "choices": [
        "選択肢1の説明",
        "選択肢2の説明",
        "選択肢3の説明"
    ],
    "update": {{
        "choice1": [{{"action": "add", "field": "history", "value": "更新内容"}}],
        "choice2": [{{"action": "add", "field": "traits", "value": "更新内容"}}],
        "choice3": [{{"action": "update", "field": "stats", "value": {{"DEX": 1}}}}]
    }},
    "game_over": false,
    "game_clear": false
}}
```
"""

def get_ai_response(prompt):
    """Geminiモデルを呼び出し、応答をJSONとして解析して返します。"""
    try:
        response = ai_model.generate_content(prompt)
        # AIの返答からJSON部分を抽出してパースする
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(json_text)
    except Exception as e:
        print(f"--- AI応答の解析中にエラーが発生しました ---")
        print(f"エラー: {e}")
        print(f"受信テキスト: {getattr(response, 'text', 'N/A')}")
        return None # エラー発生時はNoneを返す

def generate_image_from_prompt(prompt: str) -> str | None:
    """画像生成AIを呼び出し、生成された画像のURLを返します。"""
    # この機能を利用するには、Google Cloudプロジェクトの設定と認証が必要です。
    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel

        project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
        if not project_id:
            print("--- エラー: GOOGLE_CLOUD_PROJECT_IDが.envファイルに設定されていません。 ---")
            return None

        vertexai.init(project=project_id, location="us-central1")

        model = ImageGenerationModel.from_pretrained("imagegeneration@005")

        print(f"画像生成プロンプト: {prompt}")
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
        print(f"画像生成中にエラーが発生しました: {e}")
        return None

def build_character_generation_prompt():
    """AIにキャラクターを生成させるためのプロンプトを生成します。"""
    return f"""
あなたは経験豊富なTRPGのゲームマスターです。
これから始まる冒険のための、ユニークで魅力的なキャラクターを1人作成してください。
ファンタジー世界を舞台にしたソロTRPGの主人公です。

以下の制約条件を厳密に守り、キャラクターシートをJSON形式で出力してください。

制約条件:
- 名前、種族、クラス、性別、背景、能力値、技能、特徴、秘密、装備、**そして外見**を創造してください。
- 技能(skills)は、「交渉」「探索」「運動」など、キャラクターのクラスや背景に合ったものを3つほど、-1から+3の範囲で設定してください。
- 性別(gender)は、「男性」「女性」、あるいは他の適切なものを設定してください。
- 外見(appearance)は、キャラクターの容姿を簡潔に描写してください。（例: 「黒髪で鋭い目つきをした長身の男」）
- 能力値(stats)は STR, DEX, INT, CHA の4つで、それぞれ8〜15の範囲の整数にしてください。
- 特徴(traits)と秘密(secrets)は、キャラクターの性格や物語のフックとなるような、簡潔なフレーズを1〜2個設定してください。
- 出力は必ず以下のJSON形式に従ってください。キーの名前も完全に一致させてください。

```json
{{
    "name": "キャラクターの名前",
    "race": "キャラクターの種族（例: エルフ, ドワーフ, 人間）",
    "class": "キャラクターのクラス（例: 魔術師, 盗賊, 聖騎士）",
    "gender": "男性",
    "appearance": "キャラクターの外見描写",
    "background": "キャラクターの背景（例: 没落した貴族, 元傭兵）",
    "stats": {{"STR": 10, "DEX": 12, "INT": 14, "CHA": 8}},
    "san": 50,
    "skills": {{"交渉": 2, "歴史": 1, "隠密": 0}},
    "traits": ["特徴1", "特徴2"],
    "secrets": ["秘密1"],
    "equipment": {{"weapon": "武器の名前", "armor": "防具の名前", "items": ["アイテム1", "アイテム2"]}},
    "history": []
}}
```
"""

def get_ai_generated_character():
    """AIにキャラクターを生成させ、そのデータを辞書として返します。"""
    try:
        prompt = build_character_generation_prompt()
        response = ai_model.generate_content(prompt)
        # AIの返答からJSON部分を抽出してパースする
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(json_text)
    except Exception as e:
        print(f"--- AIキャラクター生成中にエラーが発生しました ---")
        print(f"エラー: {e}")
        print(f"受信テキスト: {getattr(response, 'text', 'N/A')}")
        return None