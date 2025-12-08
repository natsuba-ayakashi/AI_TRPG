import os
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

def get_env_var(key: str, default: str = None) -> str:
    """環境変数を取得します。見つからない場合はデフォルト値を返すか、例外を発生させます。"""
    value = os.getenv(key)
    if value is not None:
        return value
    if default is not None:
        return default
    raise ValueError(f"環境変数 '{key}' が設定されていません。")

# --- Bot関連 ---
BOT_TOKEN = get_env_var("DISCORD_BOT_TOKEN")

# --- チャンネルID ---
CHAR_SHEET_CHANNEL_ID = int(get_env_var("CHAR_SHEET_CHANNEL_ID", "0"))
SCENARIO_LOG_CHANNEL_ID = int(get_env_var("SCENARIO_LOG_CHANNEL_ID", "0"))
PLAY_LOG_CHANNEL_ID = int(get_env_var("PLAY_LOG_CHANNEL_ID", "0"))

# --- AI関連 ---
AI_API_KEY = get_env_var("AI_API_KEY")
AI_MODEL_NAME = get_env_var("AI_MODEL_NAME", "gpt-4-turbo") # デフォルトモデル

# --- 画像生成AI関連 (任意) ---
IMAGE_GEN_API_URL = get_env_var("IMAGE_GEN_API_URL", default=None) # 例: "http://127.0.0.1:7860/sdapi/v1/txt2img"