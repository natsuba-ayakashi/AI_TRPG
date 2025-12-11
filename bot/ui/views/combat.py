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
        session = self.bot.game_service.sessions.get_session(self.user_id)
        if not session:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return

        character = session.character
        world_data = self.bot.world_data_loader.get_world(session.world_name)
        
        # クラス定義からスキル情報を取得して、パッシブスキルを除外
        classes = world_data.get("creation_options", {}).get("classes", [])
        class_data = next((c for c in classes if c["name"] == character.class_), None)
        
        usable_skills = []
        if class_data:
            skill_defs = {s["name"]: s for s in class_data.get("skills", [])}
            for skill_name in character.skills:
                s_def = skill_defs.get(skill_name)
                if not s_def or s_def.get("type") != "passive":
                    usable_skills.append(skill_name)
        else:
            usable_skills = list(character.skills.keys())

        if not usable_skills:
            await interaction.response.send_message("使用できるスキルがありません。", ephemeral=True)
            return

        self.clear_items()
        options = [discord.SelectOption(label=skill) for skill in usable_skills[:25]]
        skill_select = ui.Select(placeholder="使用するスキルを選択...", options=options)
        skill_select.callback = self.on_skill_selected
        self.add_item(skill_select)

        cancel_btn = ui.Button(label="戻る", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self.on_cancel_selection
        self.add_item(cancel_btn)

        await interaction.response.edit_message(view=self)

    async def item_button(self, interaction: discord.Interaction, button: ui.Button):
        session = self.bot.game_service.sessions.get_session(self.user_id)
        if not session:
            await interaction.response.send_message("セッションが見つかりません。", ephemeral=True)
            return

        character = session.character
        world_data = self.bot.world_data_loader.get_world(session.world_name)
        all_items = world_data.get("items", {})

        # インベントリから消費アイテムのみを抽出
        usable_items = []
        for item_name in character.inventory:
            item_data = all_items.get(item_name)
            if item_data and item_data.get("consumable"):
                usable_items.append(item_name)
        
        unique_usable_items = sorted(list(set(usable_items)))

        if not unique_usable_items:
            await interaction.response.send_message("使用できるアイテム（消費アイテム）を持っていません。", ephemeral=True)
            return

        self.clear_items()
        options = [discord.SelectOption(label=item) for item in unique_usable_items[:25]]
        item_select = ui.Select(placeholder="使用するアイテムを選択...", options=options)
        item_select.callback = self.on_item_selected
        self.add_item(item_select)

        cancel_btn = ui.Button(label="戻る", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self.on_cancel_selection
        self.add_item(cancel_btn)

        await interaction.response.edit_message(view=self)

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