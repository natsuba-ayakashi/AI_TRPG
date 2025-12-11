import discord
from discord import app_commands
from discord.ext import commands
import logging
from pathlib import Path
import asyncio

from core.errors import GameError, FileOperationError, CharacterNotFoundError, AIConnectionError
from infrastructure.repositories.settings_repository import SettingsRepository
from bot.ui.embeds import create_command_list_embed

# --- 型チェック用の前方参照 ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game.services.game_service import GameService
    from game.services.character_service import CharacterService
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader
    from bot.cogs.game_commands import GameCommandsCog

# --- 定数 ---
GUILD_SETTINGS_PATH = "game_data/guild_settings.json"

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
        self.settings_repo = SettingsRepository(GUILD_SETTINGS_PATH)

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
        await self._update_command_lists()

    async def _update_command_lists(self):
        """起動時に、設定されている全てのコマンドリスト用メッセージを更新する"""
        print("コマンドリストの自動更新を確認しています...")
        for guild in self.guilds:
            guild_settings = await self.settings_repo.get_guild_settings(guild.id)
            if not guild_settings:
                continue

            channel_id = guild_settings.get("command_channel_id")
            message_id = guild_settings.get("command_message_id")

            if not channel_id or not message_id:
                continue
            
            try:
                channel = self.get_channel(channel_id)
                if not channel or not isinstance(channel, discord.TextChannel):
                    print(f"サーバー '{guild.name}' のチャンネル(ID:{channel_id})が見つかりません。")
                    continue

                message = await channel.fetch_message(message_id)
                new_embed = create_command_list_embed(self)
                await message.edit(embed=new_embed)
                print(f"サーバー '{guild.name}' のコマンドリストを更新しました。")

            except discord.NotFound:
                print(f"サーバー '{guild.name}' で古いコマンドリストメッセージ(ID:{message_id})が見つかりませんでした。再投稿を試みます。")
                try:
                    # チャンネルは上で取得済みのはず
                    if channel:
                        new_embed = create_command_list_embed(self)
                        new_msg = await channel.send(embed=new_embed)
                        guild_settings["command_message_id"] = new_msg.id
                        await self.settings_repo.save_guild_settings(guild.id, guild_settings)
                        print(f"サーバー '{guild.name}' にコマンドリストを再投稿しました。")
                except (discord.Forbidden, discord.HTTPException) as e:
                    print(f"サーバー '{guild.name}' でコマンドリストの再投稿に失敗しました: {e}")
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"サーバー '{guild.name}' のコマンドリスト更新に失敗しました: {e}")


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

        # まずコマンドを処理させ、コマンドでない場合にのみゲーム進行処理を行う
        ctx = await self.get_context(message)
        if ctx.valid:
             await self.process_commands(message)
             return

        # 対応するゲームセッションをスレッドIDから取得
        session = self.game_service.sessions.get_session_by_thread_id(message.channel.id)
        if not session:
            # ゲーム中でないスレッドでの発言は何もしない
            await self.process_commands(message) # 通常のコマンドとして処理を試みる
            return

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
                user_input = message.clean_content
                async with message.channel.typing():
                    response_data = await self.game_service.proceed_game(
                        user_id=session.user_id,
                        user_input=user_input
                    )
                
                # Cogのヘルパーメソッドを呼び出して応答を処理
                await game_cog._handle_response(message.channel, response_data, session.user_id, user_input)

            except GameError as e:
                await message.channel.send(f"ゲームエラー: {e}")
            except Exception as e:
                logging.exception(f"on_messageでの予期せぬエラー (Channel: {message.channel.id})")
                await message.channel.send("予期せぬエラーが発生しました。")
        
        # 念のため、最後にコマンド処理を試みる
        await self.process_commands(message)

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