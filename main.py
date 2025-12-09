import sys
import os
import logging
import asyncio

# プロジェクトのルートディレクトリをPythonのパスに追加
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot.client import MyBot
from config.settings import BOT_TOKEN, CHAR_SHEET_CHANNEL_ID, SCENARIO_LOG_CHANNEL_ID, PLAY_LOG_CHANNEL_ID, LOCAL_AI_BASE_URL, LOCAL_AI_MODEL_NAME
from game.managers.session_manager import SessionManager
from infrastructure.data_loaders.world_data_loader import WorldDataLoader
from infrastructure.repositories.file_repository import FileRepository
from infrastructure.repositories.world_repository import WorldRepository
from game.services.game_service import GameService
from game.services.character_service import CharacterService
from game.services.ai_service import AIService

async def main():
    logging.basicConfig(level=logging.INFO)

    # --- 依存関係の構築 (Composition Root) ---
    # Infrastructure Layer
    world_data_loader = WorldDataLoader("game_data/worlds")
    character_repository = FileRepository("game_data/characters")
    world_repository = WorldRepository("game_data/world_state.json")

    # Bot (Presentation Layer) のインスタンス化
    # GameServiceがBotインスタンスを必要とするため、先に生成する
    bot = MyBot(
        world_data_loader=world_data_loader,
        channel_ids={
            "CHAR_SHEET_CHANNEL_ID": CHAR_SHEET_CHANNEL_ID,
            "SCENARIO_LOG_CHANNEL_ID": SCENARIO_LOG_CHANNEL_ID,
            "PLAY_LOG_CHANNEL_ID": PLAY_LOG_CHANNEL_ID,
        }
    )

    # Game Layer
    session_manager = SessionManager()
    character_service = CharacterService(character_repository=character_repository)
    ai_service = AIService(base_url=LOCAL_AI_BASE_URL, model_name=LOCAL_AI_MODEL_NAME, world_data_loader=world_data_loader)
    game_service = GameService(
        bot=bot, # Botインスタンスを注入
        session_manager=session_manager,
        character_service=character_service,
        world_data_loader=world_data_loader,
        world_repository=world_repository,
        ai_service=ai_service
    )

    # Botに各サービスをセット
    bot.game_service = game_service
    bot.character_service = character_service

    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())