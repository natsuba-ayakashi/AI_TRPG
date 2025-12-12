import discord
from discord import app_commands
from discord.ext import commands
import logging
from pathlib import Path
import os
import asyncio

from core.errors import GameError, FileOperationError, CharacterNotFoundError, AIConnectionError
from infrastructure.repositories.settings_repository import SettingsRepository
from bot.ui.embeds import create_command_list_embed
from bot import messaging
from config.settings import GUILD_SETTINGS_FILE_PATH

# --- 型チェック用の前方参照 ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from game.services.game_service import GameService
    from game.services.character_service import CharacterService
    from infrastructure.data_loaders.world_data_loader import WorldDataLoader
    from core.event_bus import EventBus
    from game.models.session import GameSession
    from bot.cogs.game_commands import GameCommandsCog

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

class MyBot(commands.Bot):
    """プロジェクトのカスタムBotクラス"""
    def __init__(
        self,
        world_data_loader: "WorldDataLoader",
        channel_ids: dict[str, int],
        game_service: "GameService",
        character_service: "CharacterService",
        event_bus: "EventBus",
    ):
        super().__init__(command_prefix="!", intents=intents, case_insensitive=True)
        # --- 依存関係の注入 (DI) ---
        # コンストラクタでサービスを受け取ることで、Botインスタンスは常に完全な状態で生成される
        self.game_service: "GameService" = game_service
        self.character_service: "CharacterService" = character_service
        self.event_bus: "EventBus" = event_bus
        self.world_data_loader: "WorldDataLoader" = world_data_loader
        self.settings_repo = SettingsRepository(GUILD_SETTINGS_FILE_PATH)

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

        # スラッシュコマンドをDiscordに同期 (開発用設定)
        # 環境変数 DEV_GUILD_ID が設定されていれば、そのサーバーに即時同期する
        dev_guild_id = os.getenv("DEV_GUILD_ID")

        if dev_guild_id and dev_guild_id.isdigit():
            guild = discord.Object(id=int(dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                print(f"スラッシュコマンドをサーバー(ID: {dev_guild_id})に同期しました。")
            except discord.Forbidden:
                logging.warning(f"開発用サーバー(ID: {dev_guild_id})への同期に失敗しました(Forbidden)。Botが参加していないか権限がありません。")
            except discord.HTTPException as e:
                logging.error(f"開発用サーバーへの同期中にエラーが発生しました: {e}")
        else:
            await self.tree.sync()
            print("スラッシュコマンドをグローバル同期しました。")

    async def on_ready(self):
        print(f'{self.user} としてDiscordにログインしました')
        
        print("--- 参加しているサーバー一覧 ---")
        for guild in self.guilds:
            print(f"サーバー名: {guild.name} | ID: {guild.id}")
        print("--------------------------------")

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

    def _is_relevant_message(self, message: discord.Message) -> bool:
        """メッセージを処理すべきかどうかの事前チェック"""
        # ボットからのメッセージは無視
        if message.author.bot:
            return False
        # DMやカテゴリ外のチャンネルは無視
        if not message.guild or not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return False
        return True

    async def _handle_game_response(self, channel: discord.abc.Messageable, response_data: dict, user_id: int, user_input: str):
        """AIからの応答を解釈し、Cogの共通ハンドラに処理を委譲する。"""
        cog: "GameCommandsCog" = self.get_cog("ゲーム管理")
        if cog:
            await cog._handle_response(channel, response_data, user_id, user_input)
        else:
            logging.warning("GameCommandsCogが見つかりません。on_messageからの応答処理をスキップします。")
            narrative = response_data.get("narrative")
            if narrative:
                await channel.send(narrative)

    async def _process_game_turn(self, message: discord.Message, session: "GameSession"):
        """ một lượt chơi game を処理し、応答を送信する"""
        lock = self.game_service.sessions.get_lock(session.user_id)
        if lock.locked():
            # 既に処理が実行中の場合は、リアクションで通知する（任意）
            await message.add_reaction("⏳")
            return

        async with lock:
            try:
                user_input = message.clean_content
                async with message.channel.typing():
                    response_data = await self.game_service.proceed_game(
                        user_id=session.user_id,
                        user_input=user_input
                    )
                
                await self._handle_game_response(message.channel, response_data, session.user_id, user_input)

            except GameError as e:
                await message.channel.send(f"ゲームエラー: {e}")
            except Exception:
                logging.exception(f"ゲーム進行中の予期せぬエラー (Channel: {message.channel.id})")
                await message.channel.send("予期せぬエラーが発生しました。")

    async def on_message(self, message: discord.Message):
        """スレッド内のメッセージをリッスンし、ゲームを進行させる"""
        if not self._is_relevant_message(message):
            return

        ctx = await self.get_context(message)
        if ctx.valid:
            return await self.process_commands(message)

        session = self.game_service.sessions.get_session_by_thread_id(message.channel.id)
        if session:
            await self._process_game_turn(message, session)

    async def _get_error_user_message(self, error: Exception) -> str:
        """
        例外オブジェクトからユーザーに表示するためのフレンドリーなエラーメッセージを生成する。
        """
        original_error = getattr(error, 'original', error)

        if isinstance(original_error, FileOperationError):
            return messaging.error_file_operation(original_error)
        if isinstance(original_error, CharacterNotFoundError):
            return messaging.error_data_not_found(original_error)
        if isinstance(original_error, AIConnectionError):
            return messaging.MSG_AI_CONNECTION_ERROR
        if isinstance(original_error, GameError):
            return messaging.error_game_error(original_error)
        if isinstance(error, app_commands.CommandOnCooldown):
            return messaging.error_command_on_cooldown(error.retry_after)
        if isinstance(error, app_commands.MissingPermissions):
            return messaging.MSG_MISSING_PERMISSIONS
        if isinstance(original_error, discord.HTTPException) and original_error.code == 50035:
            return "システムエラー: 生成されたボタン等のラベルが長すぎて表示できませんでした（Discordの80文字制限）。"
        
        # マッピングにない未知のエラー
        return messaging.MSG_UNEXPECTED_ERROR

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """スラッシュコマンドで発生したエラーのグローバルハンドラ。"""
        command_name = interaction.command.name if interaction.command else "不明なコマンド"
        
        # ログにはスタックトレース付きで詳細なエラーを出力
        logging.exception(f"スラッシュコマンド '{command_name}' の実行中にエラーが発生しました。")

        # ユーザー向けのメッセージを生成
        user_message = await self._get_error_user_message(error)

        # ユーザーに応答
        try:
            if interaction.response.is_done():
                await interaction.followup.send(user_message, ephemeral=True)
            else:
                await interaction.response.send_message(user_message, ephemeral=True)
        except discord.HTTPException as e:
            logging.error(f"エラーメッセージの送信に失敗しました: {e}")

    async def on_error(self, event_method: str, *args, **kwargs):
        """
        on_app_command_error やコマンドハンドラで捕捉されなかった、
        他のイベントハンドラ (on_message, on_readyなど) で発生したエラーを処理する。
        """
        logging.exception(f"イベント '{event_method}' の処理中に未捕捉の例外が発生しました。")
        # ここで開発者に通知する処理（例：DMを送信する）などを追加することもできる。