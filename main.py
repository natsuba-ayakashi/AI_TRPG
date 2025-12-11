import sys
import logging
import asyncio
from typing import Dict

# プロジェクトのルートディレクトリをPythonのパスに追加するため、最初にPROJECT_ROOTをインポートします。
# このインポートが成功するためには、スクリプト実行時にプロジェクトルートが
# Pythonの検索パスに含まれている必要があります (例: `python main.py`)。
from config.settings import PROJECT_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.client import MyBot
from config.settings import (
    BOT_TOKEN, CHAR_SHEET_CHANNEL_ID, SCENARIO_LOG_CHANNEL_ID, PLAY_LOG_CHANNEL_ID,
    LOCAL_AI_BASE_URL, LOCAL_AI_MODEL_NAME, GAME_LOG_FILE_PATH,
    WORLDS_DATA_PATH, SYSTEM_PROMPTS_FILE_PATH, CHARACTERS_DATA_PATH, WORLD_STATE_FILE_PATH,
)
from game.managers.session_manager import SessionManager
from infrastructure.data_loaders.world_data_loader import WorldDataLoader
from infrastructure.data_loaders.prompt_loader import PromptLoader
from infrastructure.repositories.file_repository import FileRepository
from infrastructure.repositories.world_repository import WorldRepository
from core.event_bus import EventBus
from game.services.game_service import GameService
from game.services.character_service import CharacterService
from game.services.ai_service import AIService
from game.services.logging_service import LoggingService

logger = logging.getLogger(__name__)

def setup_logging():
    """アプリケーションのロギングを設定する"""
    # Python 3.8+ では force=True を使うことで、既存のハンドラを置き換えられます
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout,
        force=True,
    )
    logger.info("ロギングを設定しました。")

def build_dependencies() -> MyBot:
    """
    アプリケーションの依存関係を構築し、設定済みのBotインスタンスを返す。
    依存関係の注入(DI)はここで行う。
    """
    logger.info("依存関係の構築を開始します...")

    # 0. コアコンポーネントとしてEventBusを生成
    event_bus = EventBus()

    # 1. 依存関係のない、または外部依存のみのコンポーネントを構築 (Infrastructure)
    logger.info("Infrastructure Layer を構築中...")
    world_data_loader = WorldDataLoader(WORLDS_DATA_PATH)
    if not SYSTEM_PROMPTS_FILE_PATH.exists():
        logger.error(f"PromptLoader のパスが見つかりません: {SYSTEM_PROMPTS_FILE_PATH}")
        raise FileNotFoundError(f"Prompt file not found at {SYSTEM_PROMPTS_FILE_PATH}")
    prompt_loader = PromptLoader(SYSTEM_PROMPTS_FILE_PATH)
    character_repository = FileRepository(CHARACTERS_DATA_PATH)
    world_repository = WorldRepository(WORLD_STATE_FILE_PATH)

    # 2. Infrastructureに依存するコンポーネントを構築 (Services)
    logger.info("Game Layer を構築中...")
    session_manager = SessionManager()
    character_service = CharacterService(character_repository=character_repository)
    ai_service = AIService(
        base_url=LOCAL_AI_BASE_URL,
        model_name=LOCAL_AI_MODEL_NAME,
        world_data_loader=world_data_loader,
        prompt_loader=prompt_loader
    )
    # GameServiceはBotの代わりにEventBusに依存
    game_service = GameService(
        session_manager=session_manager,
        character_service=character_service,
        world_data_loader=world_data_loader,
        world_repository=world_repository,
        ai_service=ai_service,
        event_bus=event_bus
    )

    # LoggingServiceをインスタンス化し、EventBusを注入
    # このサービスは他のサービスに依存せず、イベントを購読するだけなので、ここで生成する
    _ = LoggingService(event_bus=event_bus, log_file_path=GAME_LOG_FILE_PATH)

    # 3. Servicesに依存するコンポーネントを構築 (Bot)
    logger.info("Bot を構築中...")
    channel_ids: Dict[str, int] = {
        "CHAR_SHEET_CHANNEL_ID": CHAR_SHEET_CHANNEL_ID,
        "SCENARIO_LOG_CHANNEL_ID": SCENARIO_LOG_CHANNEL_ID,
        "PLAY_LOG_CHANNEL_ID": PLAY_LOG_CHANNEL_ID,
    }
    bot = MyBot(
        world_data_loader=world_data_loader,
        channel_ids=channel_ids,
        game_service=game_service,
        character_service=character_service,
        event_bus=event_bus
    )

    # 4. 循環依存はEventBusによって解決されたため、セッターインジェクションは不要
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
        logger.info("ボットを手動で停止しました。")
    except Exception as e:
        # main()内で捕捉されなかったすべての例外をここで捕捉してログに出力
        logger.critical("アプリケーションの実行中に致命的なエラーが発生しました。", exc_info=True)