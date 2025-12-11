import os
from dotenv import load_dotenv
from pathlib import Path

# .envファイルから環境変数を読み込む
load_dotenv()

# --- プロジェクトパス設定 ---
# このファイル (settings.py) の親ディレクトリ (config) のさらに親がプロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- データパス設定 ---
GAME_DATA_DIR = PROJECT_ROOT / "game_data"
WORLDS_DATA_PATH = GAME_DATA_DIR / "worlds"
CHARACTERS_DATA_PATH = GAME_DATA_DIR / "characters"
WORLD_STATE_FILE_PATH = GAME_DATA_DIR / "world_state.json"
GUILD_SETTINGS_FILE_PATH = GAME_DATA_DIR / "guild_settings.json"
GAME_LOG_FILE_PATH = GAME_DATA_DIR / "logs" / "game_events.log"

PROMPTS_DIR = PROJECT_ROOT / "prompts"
SYSTEM_PROMPTS_FILE_PATH = PROMPTS_DIR / "system_prompts.json"

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

# --- AI関連 (Ollamaを使用) ---
LOCAL_AI_BASE_URL = get_env_var("AI_API_KEY", "http://127.0.0.1:11434/v1/") # OllamaのデフォルトURL
LOCAL_AI_MODEL_NAME = get_env_var("AI_MODEL_NAME", "deepseek-r1:latest") # Ollamaで利用するモデル名

# --- 画像生成AI関連 (任意) ---
# IMAGE_GEN_API_URL = get_env_var("IMAGE_GEN_API_URL", default=None) # 例: "http://127.0.0.1:7860/sdapi/v1/txt2img"

# --- ゲームバランス設定 ---
MAX_REROLLS_ON_CREATION = int(get_env_var("MAX_REROLLS_ON_CREATION", "3"))