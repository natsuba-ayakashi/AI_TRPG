import logging
import asyncio

from bot.client import MyBot
from config.settings import BOT_TOKEN, CHAR_SHEET_CHANNEL_ID, SCENARIO_LOG_CHANNEL_ID, PLAY_LOG_CHANNEL_ID, AI_API_KEY, AI_MODEL_NAME
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

    # Bot (Presentation Layer) のインスタンス化と依存性の注入
    # Botインスタンスを先に生成する必要があるため、サービスは後から注入する
    bot = MyBot(channel_ids={
        "CHAR_SHEET_CHANNEL_ID": CHAR_SHEET_CHANNEL_ID,
        "SCENARIO_LOG_CHANNEL_ID": SCENARIO_LOG_CHANNEL_ID,
        "PLAY_LOG_CHANNEL_ID": PLAY_LOG_CHANNEL_ID,
    })

    # Game Layer
    session_manager = SessionManager()
    character_service = CharacterService(character_repository=character_repository)
    ai_service = AIService(api_key=AI_API_KEY, model_name=AI_MODEL_NAME, world_data_loader=world_data_loader)
    game_service = GameService(
        session_manager=session_manager,
        character_service=character_service,
        world_data_loader=world_data_loader,
        world_repository=world_repository,
        bot=bot, # botインスタンスを注入
        ai_service=ai_service
    )

    # Botにサービスをセット
    bot.game_service = game_service
    bot.character_service = character_service
    bot.world_data_loader = world_data_loader

    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())