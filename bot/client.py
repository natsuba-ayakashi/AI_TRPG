import discord
from discord import app_commands
from discord.ext import commands
import logging
from pathlib import Path
import asyncio

from core.errors import GameError, FileOperationError, CharacterNotFoundError, AIConnectionError

# --- 型チェック用の前方参照 ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game.services.game_service import GameService
    from game.services.character_service import CharacterService
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

class MyBot(commands.Bot):
    """プロジェクトのカスタムBotクラス"""
    def __init__(
        self,
        world_data_loader: "WorldDataLoader",
        channel_ids: dict[str, int],
    ):
        super().__init__(command_prefix="!", intents=intents, case_insensitive=True)
        # 依存性注入によって後から設定されるプロパティ
        self.game_service: "GameService" = None
        self.character_service: "CharacterService" = None
        self.world_data_loader: "WorldDataLoader" = world_data_loader

        # 設定値
        self.CHAR_SHEET_CHANNEL_ID = channel_ids.get("CHAR_SHEET_CHANNEL_ID", 0)
        self.SCENARIO_LOG_CHANNEL_ID = channel_ids.get("SCENARIO_LOG_CHANNEL_ID", 0)
        self.PLAY_LOG_CHANNEL_ID = channel_ids.get("PLAY_LOG_CHANNEL_ID", 0)

    async def setup_hook(self):
        """Bot起動時にCogsをロードし、コマンドを同期する"""
        # cogsディレクトリ内のCogを全て読み込む
        cogs_path = Path(__file__).parent / "cogs"
        if cogs_path.exists() and cogs_path.is_dir():
            for file in cogs_path.glob("*.py"):
                if file.stem == "__init__":
                    continue
                cog_name = f"bot.cogs.{file.stem}"
                try:
                    await self.load_extension(cog_name)
                    print(f"Cogをロードしました: {cog_name}")
                except commands.ExtensionError as e:
                    logging.exception(f"Cog '{cog_name}' のロードに失敗しました。", exc_info=e)

        # スラッシュコマンドをDiscordに同期
        await self.tree.sync()
        print("スラッシュコマンドを同期しました。")

    async def on_ready(self):
        print(f'{self.user} としてDiscordにログインしました')

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ボイスチャンネルのメンバーがBotのみになったら自動退出する"""
        if member.id == self.user.id:
            return

        voice_client = member.guild.voice_client
        if not voice_client:
            return

        if len(voice_client.channel.members) == 1 and voice_client.channel.members[0] == self.user:
            await asyncio.sleep(60)
            if len(voice_client.channel.members) == 1:
                print("ボイスチャンネルに誰もいなくなったため、自動的に退出します。")
                # BGMマネージャーがある場合はここで停止処理を呼ぶ
                # await bgm_manager.stop_bgm(member.guild)
                await voice_client.disconnect()

    async def on_message(self, message: discord.Message):
        """スレッド内のメッセージをリッスンし、ゲームを進行させる"""
        # --- メッセージを処理すべきかどうかの事前チェック ---
        if message.author.bot:
            return
        if not message.guild or isinstance(message.channel, discord.DMChannel):
            return
        if message.content.startswith(self.command_prefix):
            # コマンドとして処理されるべきメッセージは無視
            # process_commandsを呼ぶと二重処理になる可能性があるため、プレフィックスで判定
            return
            
        # game_serviceが初期化されるまで待つ
        if not self.game_service:
            return
            
        # 対応するゲームセッションをスレッドIDから取得
        session = self.game_service.sessions.get_session_by_thread_id(message.channel.id)
        if not session:
            return # ゲームが行われていないスレッドでの発言は無視

        # --- ゲーム進行処理 ---
        # プレイヤーの行動であるとみなし、ゲームを進行させる
        # ロックを取得して、多重実行を防ぐ
        lock = self.game_service.sessions.get_lock(session.user_id)
        async with lock:
            try:
                # Cogを取得
                game_cog: "GameCommandsCog" = self.get_cog("ゲーム管理")
                if not game_cog:
                    logging.warning("GameCommandsCogが見つかりません。on_messageからの応答処理をスキップします。")
                    return

                # 処理中であることをユーザーに示す
                async with message.channel.typing():
                    response_data = await self.game_service.proceed_game(
                        user_id=session.user_id,
                        user_input=message.clean_content
                    )
                
                # Cogのヘルパーメソッドを呼び出して応答を処理
                await game_cog._handle_response(message.channel, response_data, session.user_id)

            except GameError as e:
                await message.channel.send(f"ゲームエラー: {e}")
            except Exception as e:
                logging.exception(f"on_messageでの予期せぬエラー (Channel: {message.channel.id})")
                await message.channel.send("予期せぬエラーが発生しました。")

    async def on_error(self, event_method: str, *args, **kwargs):
        """グローバルエラーハンドラ"""
        if event_method == 'on_app_command_error':
            interaction: discord.Interaction = args[0]
            error: app_commands.AppCommandError = args[1]
            original_error = getattr(error, 'original', error)
            logging.exception(f"コマンド '{interaction.command.name if interaction.command else 'N/A'}' でエラー: {original_error}")

            error_map = {
                FileOperationError: f"ファイルの処理中にエラーが発生しました。\n詳細: {original_error}",
                CharacterNotFoundError: f"指定されたデータが見つかりませんでした。\n詳細: {original_error}",
                AIConnectionError: "AIとの通信に失敗しました。時間をおいて再度試してください。(APIの利用制限に達したか、サーバーが混み合っている可能性があります)",
                GameError: f"エラーが発生しました: {original_error}",
                app_commands.CommandOnCooldown: f"コマンドはクールダウン中です。{error.retry_after:.2f}秒後にもう一度試してください。",
                app_commands.MissingPermissions: "コマンドの実行に必要な権限がありません。"
            }
            user_message = next((msg for err_type, msg in error_map.items() if isinstance(original_error, err_type)), "予期せぬエラーが発生しました。")

            if interaction.response.is_done():
                await interaction.followup.send(user_message, ephemeral=True)
            else:
                await interaction.response.send_message(user_message, ephemeral=True)
        else:
            logging.exception(f"未処理のイベントエラー: {event_method}")