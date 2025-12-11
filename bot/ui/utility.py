import discord
from discord import ui
import logging
from typing import TYPE_CHECKING, List
from functools import partial

from bot import messaging

if TYPE_CHECKING:
    from bot.client import MyBot
    from bot.cogs.game_commands import GameCommandsCog

logger = logging.getLogger(__name__)

class BaseOwnedView(ui.View):
    """作成者のみが操作できるViewの基底クラス"""
    def __init__(self, user_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(messaging.MSG_ONLY_FOR_COMMAND_USER, ephemeral=True)
            return False
        return True

class ConfirmDeleteView(BaseOwnedView):
    """キャラクター削除の最終確認を行うView"""
    def __init__(self, author_id: int, bot: "MyBot", char_name: str):
        super().__init__(user_id=author_id, timeout=60)
        self.bot = bot
        self.char_name = char_name

    @ui.button(label="はい、削除します", style=discord.ButtonStyle.danger, custom_id="confirm_delete")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            success = await self.bot.character_service.delete_character(self.user_id, self.char_name)
            if success:
                await interaction.response.edit_message(content=messaging.character_deleted(self.char_name), view=None)
            else:
                await interaction.response.edit_message(content=f"キャラクター「{self.char_name}」の削除に失敗しました。", view=None)
        except Exception as e:
            await interaction.response.edit_message(content=f"削除中にエラーが発生しました: {e}", view=None)
        self.stop()

    @ui.button(label="いいえ", style=discord.ButtonStyle.secondary, custom_id="cancel_delete")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content=messaging.character_delete_canceled(), view=None)
        self.stop()

class ActionSuggestionView(ui.View):
    """AIから提案された行動をボタンとして提示するView"""
    
    def __init__(self, actions: List[str], bot: "MyBot", timeout: int = 300):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.message: discord.Message = None
        
        for action in actions:
            button = ui.Button(label=action, style=discord.ButtonStyle.secondary)
            button.callback = partial(self.on_action_button_click, action=action)
            self.add_item(button)
            
    async def on_action_button_click(self, interaction: discord.Interaction, action: str):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        cog: "GameCommandsCog" = self.bot.get_cog("ゲーム管理")
        if cog:
            await cog._proceed_and_respond_from_interaction(interaction, action)
        else:
            logger.warning("ActionSuggestionView: GameCommandsCogが見つかりませんでした。")
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                original_content = self.message.content
                if "（時間切れです）" not in original_content:
                    await self.message.edit(content=original_content + "\n\n*（時間切れのため、選択肢は無効になりました）*", view=self)
            except discord.HTTPException as e:
                logger.warning(f"タイムアウトメッセージの編集に失敗しました (Code: {e.code}): {e.text}")
            except Exception as e:
                logger.error(f"タイムアウトメッセージの編集中に予期せぬエラーが発生しました。", exc_info=e)
        self.stop()