import discord
from discord import ui
import logging
from typing import TYPE_CHECKING

from .utility import BaseOwnedView

if TYPE_CHECKING:
    from bot.client import MyBot
    from bot.cogs.game_commands import GameCommandsCog

logger = logging.getLogger(__name__)

class CombatView(BaseOwnedView):
    """戦闘中の行動選択肢を提供するView"""
    def __init__(self, author_id: int, bot: "MyBot"):
        super().__init__(user_id=author_id, timeout=None)
        self.bot = bot
        self.message: discord.Message = None

        self.attack_btn = ui.Button(label="⚔️ 攻撃", style=discord.ButtonStyle.primary, custom_id="combat_attack")
        self.attack_btn.callback = self.attack_button

        self.skill_btn = ui.Button(label="✨ スキル", style=discord.ButtonStyle.success, custom_id="combat_skill")
        self.skill_btn.callback = self.skill_button

        self.item_btn = ui.Button(label="🎒 アイテム", style=discord.ButtonStyle.secondary, custom_id="combat_item")
        self.item_btn.callback = self.item_button

        self.flee_btn = ui.Button(label="🏃 逃走", style=discord.ButtonStyle.danger, custom_id="combat_flee")
        self.flee_btn.callback = self.flee_button

        self.show_main_buttons()

    def show_main_buttons(self):
        self.clear_items()
        self.add_item(self.attack_btn)
        self.add_item(self.skill_btn)
        self.add_item(self.item_btn)
        self.add_item(self.flee_btn)

    async def attack_button(self, interaction: discord.Interaction, button: ui.Button):
        session = self.bot.game_service.sessions.get_session(self.user_id)
        if not session:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return

        if len(session.current_enemies) == 1:
            target_name = session.current_enemies[0].name
            await self._process_action(interaction, f"通常攻撃: {target_name}")
        elif len(session.current_enemies) > 1:
            await interaction.response.send_modal(TargetSelectModal(title="攻撃対象を選択", view=self))
        else:
            await interaction.response.send_message("攻撃対象の敵がいません。", ephemeral=True)

    async def skill_button(self, interaction: discord.Interaction, button: ui.Button):
        # (Implementation from original file)
        ...

    async def item_button(self, interaction: discord.Interaction, button: ui.Button):
        # (Implementation from original file)
        ...

    async def flee_button(self, interaction: discord.Interaction, button: ui.Button):
        await self._process_action(interaction, "逃走を試みる")

    async def on_skill_selected(self, interaction: discord.Interaction):
        selected_skill = interaction.data["values"][0]
        await self._process_action(interaction, f"スキル使用: {selected_skill}")

    async def on_item_selected(self, interaction: discord.Interaction):
        selected_item = interaction.data["values"][0]
        await self._process_action(interaction, f"アイテム使用: {selected_item}")

    async def on_cancel_selection(self, interaction: discord.Interaction):
        self.show_main_buttons()
        await interaction.response.edit_message(view=self)

    async def _process_action(self, interaction: discord.Interaction, action: str):
        self.disable_all_buttons()
        await interaction.response.edit_message(view=self)

        cog: "GameCommandsCog" = self.bot.get_cog("ゲーム管理")
        if cog:
            await cog._proceed_and_respond_from_interaction(interaction, action)
        else:
            logger.warning("CombatView: GameCommandsCogが見つかりませんでした。")

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True

    def enable_all_buttons(self):
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = False

class TargetSelectModal(ui.Modal):
    """戦闘時の攻撃対象を選択するためのモーダル"""
    def __init__(self, *, title: str, view: "CombatView"):
        super().__init__(title=title)
        self.view = view
        session = self.view.bot.game_service.sessions.get_session(self.view.user_id)
        
        options = [discord.SelectOption(label=f"{enemy.name} (HP: {enemy.hp}/{enemy.max_hp})", value=enemy.instance_id) for enemy in session.current_enemies]
        self.target_select = ui.Select(placeholder="攻撃する敵を選択してください...", options=options)
        self.add_item(self.target_select)

    async def on_submit(self, interaction: discord.Interaction):
        selected_target_id = self.target_select.values[0]
        await self.view._process_action(interaction, f"通常攻撃: {selected_target_id}")