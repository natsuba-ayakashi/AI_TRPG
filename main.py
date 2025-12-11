import sys
import os
import logging
import asyncio
from pathlib import Path
from typing import Dict

# プロジェクトのルートディレクトリをPythonのパスに追加
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot.client import MyBot
from config.settings import BOT_TOKEN, CHAR_SHEET_CHANNEL_ID, SCENARIO_LOG_CHANNEL_ID, PLAY_LOG_CHANNEL_ID, LOCAL_AI_BASE_URL, LOCAL_AI_MODEL_NAME
from game.managers.session_manager import SessionManager
from infrastructure.data_loaders.world_data_loader import WorldDataLoader
from infrastructure.data_loaders.prompt_loader import PromptLoader
from infrastructure.repositories.file_repository import FileRepository
from infrastructure.repositories.world_repository import WorldRepository
from game.services.game_service import GameService
from game.services.character_service import CharacterService
from game.services.ai_service import AIService

logger = logging.getLogger(__name__)

def setup_logging():
    """アプリケーションのロギングを設定する"""
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)

    # ルートロガーにハンドラを追加
    root_logger = logging.getLogger()
    # ログレベルをINFOに設定。デバッグ時はDEBUGに変更すると良い。
    root_logger.setLevel(logging.INFO)
    # 既存のハンドラをクリアしてから追加（重複防止）
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)
    logger.info("ロギングを設定しました。")

def build_dependencies() -> MyBot:
    """
    アプリケーションの依存関係を構築し、設定済みのBotインスタンスを返す。
    """
    logger.info("依存関係の構築を開始します...")

    # --- Infrastructure Layer ---
    world_data_loader = WorldDataLoader("game_data/worlds")
    prompt_loader_path = Path(project_root) / "prompts" / "system_prompts.json"
    if not prompt_loader_path.exists():
        logger.error(f"PromptLoader のパスが見つかりません: {prompt_loader_path}")
        raise FileNotFoundError(f"Prompt file not found at {prompt_loader_path}")
    prompt_loader = PromptLoader(prompt_loader_path)
    character_repository = FileRepository("game_data/characters")
    world_repository = WorldRepository("game_data/world_state.json")
    logger.info("Infrastructure Layer のインスタンス化完了。")

    # --- Bot Instance ---
    channel_ids: Dict[str, int] = {
        "CHAR_SHEET_CHANNEL_ID": CHAR_SHEET_CHANNEL_ID,
        "SCENARIO_LOG_CHANNEL_ID": SCENARIO_LOG_CHANNEL_ID,
        "PLAY_LOG_CHANNEL_ID": PLAY_LOG_CHANNEL_ID,
    }
    bot = MyBot(
        world_data_loader=world_data_loader,
        channel_ids=channel_ids
    )
    logger.info("MyBot のインスタンス化完了。")

    # --- Game Layer (Services) ---
    session_manager = SessionManager()
    character_service = CharacterService(character_repository=character_repository)
    ai_service = AIService(
        base_url=LOCAL_AI_BASE_URL,
        model_name=LOCAL_AI_MODEL_NAME,
        world_data_loader=world_data_loader,
        prompt_loader=prompt_loader
    )
    game_service = GameService(
        bot=bot,
        session_manager=session_manager,
        character_service=character_service,
        world_data_loader=world_data_loader,
        world_repository=world_repository,
        ai_service=ai_service
    )
    logger.info("Game Layer のインスタンス化完了。")

    # --- Inject services into Bot ---
    bot.game_service = game_service
    bot.character_service = character_service
    logger.info("Botにサービスを注入しました。")

    logger.info("依存関係の構築が完了しました。")
    return bot

async def main():
    """アプリケーションのメインエントリーポイント"""
    setup_logging()

    if not BOT_TOKEN:
        logger.critical("BOT_TOKENが設定されていません。.envファイルを確認してください。")
        return

    bot = build_dependencies()

    logger.info(f"Botを起動します... (Token: '{BOT_TOKEN[:5]}...')")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("ボットを手動で停止しました。")
    except Exception as e:
        # main()内で捕捉されなかったすべての例外をここで捕捉してログに出力
        logging.getLogger(__name__).critical("アプリケーションの実行中に致命的なエラーが発生しました。", exc_info=True)