import discord
from discord import app_commands
from discord.ext import commands
from typing import List, TYPE_CHECKING, Dict, Union
import logging

from core.errors import GameError, CharacterNotFoundError
from bot.ui.views import ConfirmDeleteView, ActionSuggestionView
from bot.ui.embeds import create_action_result_embed, create_log_embed
from bot import messaging

if TYPE_CHECKING:
    from bot.client import MyBot


class GameCommandsCog(commands.Cog, name="ゲーム管理"):
    """ゲームの開始や終了、キャラクターの削除などを管理するコマンド"""

    def __init__(self, bot: "MyBot"):
        self.bot = bot

    async def _handle_response(self, source: Union[discord.Interaction, discord.TextChannel], response_data: Dict, user_id: int, user_input: str):
        """AIからの応答を解釈し、適切なメッセージとUIを送信する共通ヘルパー"""
        # narrativeとembedsの準備
        narrative = response_data.get("narrative", "ゲームマスターは何も言わなかった...")
        action_result = response_data.get("action_result")
        
        embeds_to_send = []
        if action_result:
            if action_embed := create_action_result_embed(action_result):
                embeds_to_send.append(action_embed)

        # Viewの準備
        view = None
        if suggested_actions := response_data.get("suggested_actions"):
            if suggested_actions:
                view = ActionSuggestionView(suggested_actions, self.bot)

        # 応答の送信
        message = None
        if isinstance(source, discord.Interaction):
            if source.response.is_done():
                 message = await source.followup.send(narrative, embeds=embeds_to_send, view=view, wait=True)
            else:
                 await source.response.send_message(narrative, embeds=embeds_to_send, view=view)
                 message = await source.original_response()
        else: # discord.TextChannel
            message = await source.send(narrative, embeds=embeds_to_send, view=view)
        
        if view:
            view.message = message
        
        # --- Log to designated channel ---
        try:
            guild = source.guild if isinstance(source, discord.Interaction) else source.guild
            if guild:
                guild_settings = await self.bot.settings_repo.get_guild_settings(guild.id)
                if guild_settings and (log_channel_id := guild_settings.get("log_channel_id")):
                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        user = self.bot.get_user(user_id)
                        if user:
                            log_embed = create_log_embed(
                                user=user,
                                user_input=user_input,
                                narrative=narrative,
                                action_result=action_result
                            )
                            await log_channel.send(embed=log_embed)
        except Exception as e:
            logging.error(f"Failed to send to log channel: {e}")

        # ゲームオーバー処理
        if response_data.get("game_over"):
            channel = source.channel if isinstance(source, discord.Interaction) else source
            try:
                await self.bot.game_service.end_game(user_id)
                await channel.send("キャラクターは力尽きた...。ゲームを終了し、スレッドをロックします。")
                await channel.edit(archived=True, locked=True)
            except GameError as e:
                logging.warning(f"ゲームオーバー処理中のエラー: {e}")


    async def _proceed_and_respond_from_interaction(self, interaction: discord.Interaction, action: str):
        """Interactionからゲームを進行させ、応答を処理する"""
        try:
            response_data = await self.bot.game_service.proceed_game(interaction.user.id, action)
            await self._handle_response(interaction, response_data, interaction.user.id, action)
        except GameError as e:
            if interaction.response.is_done():
                await interaction.followup.send(str(e), ephemeral=True)
            else:
                await interaction.response.send_message(str(e), ephemeral=True)
        except Exception:
            logging.exception("Interactionからのゲーム進行中に予期せぬエラーが発生しました。")
            if interaction.response.is_done():
                await interaction.followup.send("予期せぬエラーが発生しました。", ephemeral=True)
            else:
                await interaction.response.send_message("予期せぬエラーが発生しました。", ephemeral=True)

    # (the rest of the file is unchanged)
    # ...
    # --- /start_game コマンド ---

    @app_commands.command(name="start_game", description="キャラクターを選択して新しいゲームを開始します。")
    @app_commands.describe(character_name="ゲームに使用するキャラクターの名前")
    async def start_game(self, interaction: discord.Interaction, character_name: str):
        """
        キャラクターを選択し、プライベートスレッドを作成して新しいゲームセッションを開始します。
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            thread_name = f"冒険: {interaction.user.display_name}さんのセッション"
            thread = await interaction.channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False
            )
            
            session, introduction_narrative = await self.bot.game_service.start_game(
                user_id=interaction.user.id,
                char_name=character_name,
                thread=thread
            )

            await interaction.followup.send(messaging.start_game_followup(thread), ephemeral=True)

            start_message = messaging.start_game_thread_message(interaction.user, session.character)
            await thread.send(start_message)

            # 導入シナリオと最初の選択肢を提示
            initial_actions = ["周囲を見渡す", "持ち物を確認する", "地図を見る"]
            view = ActionSuggestionView(initial_actions, self.bot)
            message = await thread.send(introduction_narrative, view=view)
            view.message = message

        except (GameError, CharacterNotFoundError) as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception:
            logging.exception("ゲーム開始中に予期せぬエラーが発生しました。")
            await interaction.followup.send("ゲームの開始中に予期せぬエラーが発生しました。", ephemeral=True)
            if 'thread' in locals() and isinstance(thread, discord.Thread):
                await thread.delete()

    # --- /end_game コマンド ---
    # (変更なし)
    @app_commands.command(name="end_game", description="現在のゲームを終了し、キャラクターの状態を保存します。")
    async def end_game(self, interaction: discord.Interaction):
        lock = self.bot.game_service.sessions.get_lock(interaction.user.id)
        async with lock:
            await interaction.response.defer(ephemeral=True, thinking=True)
            session = self.bot.game_service.get_session(interaction.user.id)
            if not session:
                await interaction.followup.send(messaging.MSG_NO_ACTIVE_SESSION, ephemeral=True)
                return
            try:
                await self.bot.game_service.end_game(interaction.user.id)
                thread = interaction.guild.get_thread(session.thread_id)
                if thread:
                    await thread.send(messaging.end_game_thread_message(session.character))
                    await thread.edit(archived=True, locked=True)
                await interaction.followup.send(messaging.end_game_followup(session.character), ephemeral=True)
            except GameError as e:
                await interaction.followup.send(str(e), ephemeral=True)
            except Exception:
                logging.exception("ゲーム終了中に予期せぬエラーが発生しました。")
                await interaction.followup.send("ゲームの終了中に予期せぬエラーが発生しました。", ephemeral=True)

    # --- /delete_character コマンド ---
    # (変更なし)
    @app_commands.command(name="delete_character", description="作成済みのキャラクターを削除します。")
    @app_commands.describe(character_name="削除するキャラクターの名前")
    async def delete_character(self, interaction: discord.Interaction, character_name: str):
        active_session = self.bot.game_service.get_session(interaction.user.id)
        if active_session and active_session.character.name == character_name:
            await interaction.response.send_message(messaging.character_in_use(character_name), ephemeral=True)
            return
        view = ConfirmDeleteView(interaction.user.id, self.bot, character_name)
        await interaction.response.send_message(messaging.character_delete_confirmation(character_name), view=view, ephemeral=True)

    # --- /next コマンド ---

    @app_commands.command(name="next", description="あなたの次の行動をゲームマスターに伝えます。")
    @app_commands.describe(action="実行したい行動を具体的に入力してください。")
    async def next_action(self, interaction: discord.Interaction, action: str):
        """
        プレイヤーの行動をAIに送信し、結果を受け取ってゲームを進行させます。
        このコマンドはゲームスレッド内でのみ有効です。
        """
        session = self.bot.game_service.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()

        if session.in_combat and action.strip() in ["逃げる", "逃走", "flee", "run"]:
            try:
                flee_narrative = await self.bot.game_service.flee_combat(interaction.user.id)
                await interaction.followup.send(flee_narrative)
            except GameError as e:
                await interaction.followup.send(str(e))
            return

        await self._proceed_and_respond_from_interaction(interaction, action)

    # --- /use コマンド ---
    @app_commands.command(name="use", description="インベントリのアイテムを使用します。")
    @app_commands.describe(item_name="使用するアイテムの名前")
    async def use_item(self, interaction: discord.Interaction, item_name: str):
        """インベントリのアイテムを使用する。"""
        session = self.bot.game_service.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()
        
        action_text = f"アイテム使用: {item_name}" # AIに渡すテキストを生成
        await self._proceed_and_respond_from_interaction(interaction, action_text)


    @use_item.autocomplete('item_name')
    async def _use_item_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """インベントリ内のアイテムを候補として表示する"""
        session = self.bot.game_service.get_session(interaction.user.id)
        if not session:
            return []
        inventory = session.character.inventory
        return [app_commands.Choice(name=item, value=item) for item in inventory if current.lower() in item.lower()][:25]

async def _character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """キャラクター名をオートコンプリートするための共通メソッド"""
    bot: "MyBot" = interaction.client
    char_names = await bot.character_service.get_all_character_names(interaction.user.id)
    return [app_commands.Choice(name=name, value=name) for name in char_names if current.lower() in name.lower()][:25]

async def setup(bot: "MyBot"):
    cog = GameCommandsCog(bot)
    cog.start_game.autocomplete('character_name')(_character_autocomplete)
    cog.delete_character.autocomplete('character_name')(_character_autocomplete)
    await bot.add_cog(cog)