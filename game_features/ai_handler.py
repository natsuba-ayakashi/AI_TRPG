import json
import google.generativeai as genai # type: ignore
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

def build_prompt(character, legacy_log=None, gm_personality_key="standard", world_setting="一般的なファンタジー世界", difficulty_level=1):
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

    difficulty_description = f"現在のゲーム難易度はレベル {difficulty_level} です。この難易度に応じて、登場する敵の強さ、技能判定の目標値、得られる報酬などを調整してください。レベルが高いほど、より挑戦的な内容にしてください。"

    return f"""
{gm_description}
{world_setting_description}
{difficulty_description}
以下のキャラクター情報と制約条件を厳密に守り、次のシナリオと選択肢、そしてキャラクターシートの更新案をJSON形式で出力してください。
{legacy_section}
現在のキャラクター情報:
{json.dumps(character, ensure_ascii=False, indent=2)}

制約条件:
- 物語にはキャラクターの `traits`（特徴）や `secrets`（秘密）を必ず反映させてください。
- プレイヤーに2〜3個の魅力的な選択肢を提示してください。
- 現在の物語の状況を要約した、簡潔で魅力的な「章のタイトル」を `chapter_title` として、`⚔️ `で始まる形式で生成してください。（例: `⚔️ 第2章：闇の森へ`）
- **経歴の記録**: 各選択肢を選んだ結果、キャラクターの `history` に追加するイベントが発生した場合、`"action": "add", "field": "history"` を使って、その出来事を要約した簡潔な文章（例: `古い遺跡で魔法の剣を手に入れた`）を `value` として追加してください。
- シナリオの情景を表現するための、**英語の短いフレーズ**（例: `A dark fantasy forest with a glowing sword`）を `image_prompt` として生成してください。
- 各選択肢を選んだ結果、キャラクターシートがどのように変化する可能性があるかを具体的に示してください。
- **BGMの提案**: シナリオの雰囲気に合わせて、以下のキーワードから最も適切なものを `"bgm_keyword"` として指定してください: `town`, `battle`, `dungeon`, `sad`, `default`。
- **サプライズイベント（低確率）**: 以下のイベントを、それぞれ5%程度の低い確率で、現在の難易度レベルに関わらず発生させてください。
  - **格上の敵**: 現在の実力では歯が立たないような、非常に強力な敵との遭遇。必ずしも倒す必要はなく、「逃げる」「隠れる」といった選択肢も重要になります。
  - **幸運な発見**: 希少なアイテムの入手、隠された場所の発見、重要なNPCとの出会いなど、プレイヤーに大きな利益をもたらすイベント。
- その際、シナリオ描写でその希少性や特別感を強調してください。
- **時間の経過**: `history` の項目数を時間の経過の指標とします。履歴が10増えるごとに、キャラクターが約1歳年を取ったと解釈し、その変化をシナリオに反映させてください。例えば、新しいNPCとの出会いや、恋愛イベント、結婚などを自然な形で提案してください。
- **恋愛と結婚**: プレイヤーの選択やキャラクターの性格に基づき、特定のNPCとの関係が深まることがあります。関係が十分に深まった場合、恋愛や結婚といった選択肢を提示しても構いません。
- **技能判定の要求**: プレイヤーの行動が成功するか不確かな場合（例：崖を飛び越える、鍵を開ける、嘘をつく）、`"skill_check": {"skill": "判定する技能名", "difficulty": 目標値}` をJSONに含めてください。目標値は、現在の難易度レベルを考慮して設定してください（例: `8 + difficulty_level`）。この時、`choices`は`null`にしてください。
- **店の登場**: 街や村のシナリオでは、武器屋、道具屋、宿屋などの「店」が登場することがあります。店が登場した場合、`"shop": {"name": "店の名前", "items_for_sale": [{"name": "商品名", "price": 価格}]}` の形式で、3〜5個の商品リストをJSONに含めてください。
- **売買の処理**: プレイヤーがアイテムを購入する選択肢を選んだ場合、`"action": "update", "field": "money", "value": -価格` と `"action": "add", "field": "equipment.items", "value": "商品名"` の両方を`update`に含めてください。売却の場合はその逆です。
- **SAN値チェック**: 特に「クトゥルフ神話TRPG風」の世界観において、キャラクターが超自然的な存在に遭遇したり、恐ろしい真実を知ってしまったりした場合、`san`を減少させる更新案を生成してください。SAN値が低い（例: 20以下）場合、キャラクターの言動に影響が出る（幻覚を見る、奇妙な行動を取るなど）描写を加えてください。
- 物語が目的を達成し、英雄的な結末を迎えた場合は `"game_clear": true` を返してください。
- キャラクターが死亡したり、目的を果たせず絶望的な結末を迎えた場合は `"game_over": true` を返してください。
- 出力は必ず以下のJSON形式に従ってください。キーの名前も完全に一致させてください。

```json
{{
    "scenario": "ここに生成したシナリオを記述します。",
    "chapter_title": "⚔️ 第1章：始まりの街",
    "bgm_keyword": "town",
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
    "skill_check": {{
        "skill": "運動",
        "difficulty": 12
    }},
    "shop": {{
        "name": "店の名前",
        "items_for_sale": [
            {{"name": "ポーション", "price": 50}}
        ]
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

def build_character_generation_prompt(world_setting: str = "一般的なファンタジー世界"):
    """AIにキャラクターを生成させるためのプロンプトを生成します。"""
    world_setting_description = f"この物語は「{world_setting}」の世界観を舞台にしています。その設定に合ったキャラクターを生成してください。"

    return f"""
あなたは経験豊富なTRPGのゲームマスターです。
これから始まる冒険のための、ユニークで魅力的なキャラクターを1人作成してください。
{world_setting_description}

以下の制約条件を厳密に守り、キャラクターシートをJSON形式で出力してください。

制約条件:
- 名前、種族、クラス、性別、背景、能力値、技能、特徴、秘密、装備、**そして外見**を創造してください。
- 技能(skills)は、「交渉」「探索」「運動」など、キャラクターのクラスや背景に合ったものを3つほど、-1から+3の範囲で設定してください。
- 性別(gender)は、「男性」「女性」、あるいは他の適切なものを設定してください。
- 外見(appearance)は、キャラクターの容姿を簡潔に描写してください。（例: 「黒髪で鋭い目つきをした長身の男」）
- 能力値(stats)は STR, DEX, INT, CHA の4つで、それぞれ8〜15の範囲の整数にしてください。
- 特徴(traits)と秘密(secrets)は、キャラクターの性格や物語のフックとなるような、簡潔なフレーズを1〜2個設定してください。
- 出力は必ず以下のJSON形式に従ってください。キーの名前も完全に一致させてください。
- **所持金(money)** は、50から200の範囲でランダムな初期値を設定してください。

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
    "history": [],
    "money": 100
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