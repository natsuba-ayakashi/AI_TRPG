import discord
from discord import ui
from typing import TYPE_CHECKING

from game.models.character import Character
from bot.ui.embeds import create_character_embed
from .utility import BaseOwnedView

if TYPE_CHECKING:
    from bot.client import MyBot


class CharacterSelectView(BaseOwnedView):
    """保存されたキャラクターを選択するためのView"""
    def __init__(self, author_id: int, char_list: list[str], bot: "MyBot"):
        super().__init__(user_id=author_id, timeout=180)
        self.bot = bot
        
        options = [discord.SelectOption(label=name) for name in char_list]
        self.select_menu = ui.Select(placeholder="ステータスを見たいキャラクターを選択...", options=options)
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def on_select(self, interaction: discord.Interaction):
        char_name = interaction.data["values"][0]
        try:
            character = await self.bot.character_service.get_character(self.user_id, char_name)
            embed = create_character_embed(character)
            await interaction.response.edit_message(content=f"「{char_name}」のステータスです。", embed=embed, view=None)
        except Exception as e:
            await interaction.response.edit_message(content=f"エラー: `{e}`", view=None)

class LevelUpView(BaseOwnedView):
    """レベルアップ時の強化選択肢を提供するView"""
    def __init__(self, author: discord.User, character: Character, bot: "MyBot"):
        super().__init__(user_id=author.id, timeout=300)
        self.author = author
        self.character = character
        self.bot = bot
        self.message: discord.Message = None

        self.stat_button = ui.Button(label=f"能力値強化 ({self.character.stat_points} P)", style=discord.ButtonStyle.success, disabled=(self.character.stat_points <= 0))
        self.stat_button.callback = self.on_stat_increase
        self.add_item(self.stat_button)

        self.skill_button = ui.Button(label=f"技能強化 ({self.character.skill_points} P)", style=discord.ButtonStyle.primary, disabled=(self.character.skill_points <= 0))
        self.skill_button.callback = self.on_skill_increase
        self.add_item(self.skill_button)

    async def on_stat_increase(self, interaction: discord.Interaction):
        view = StatIncreaseView(self.character, self)
        await interaction.response.send_message("強化する能力値を選択してください：", view=view, ephemeral=True)

    async def on_skill_increase(self, interaction: discord.Interaction):
        if not self.character.skills:
            await interaction.response.send_message("強化できる技能を習得していません。", ephemeral=True)
            return
        view = SkillSelectView(self.character, self)
        await interaction.response.send_message("強化する技能を選択してください：", view=view, ephemeral=True)

    async def update_view(self):
        self.stat_button.disabled = (self.character.stat_points <= 0)
        self.skill_button.disabled = (self.character.skill_points <= 0)
        if self.stat_button.disabled and self.skill_button.disabled: self.stop()
        embed = create_character_embed(self.character)
        if self.message: await self.message.edit(embed=embed, view=self)

class StatIncreaseView(ui.View):
    """能力値強化のための選択肢を提供するView"""
    def __init__(self, character: Character, parent_view: LevelUpView):
        super().__init__(timeout=180)
        self.character = character
        self.parent_view = parent_view

        options = [discord.SelectOption(label=stat.upper()) for stat in self.character.stats.keys()]
        self.select_menu = ui.Select(placeholder="強化する能力値を選択...", options=options)
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def on_select(self, interaction: discord.Interaction):
        stat_to_increase = interaction.data["values"][0]
        if self.character.use_stat_point(stat_to_increase):
            await interaction.response.send_message(f"{stat_to_increase} を 1 強化しました。", ephemeral=True)
            await self.parent_view.update_view()
        else:
            await interaction.response.send_message("ポイントが足りません。", ephemeral=True)

class SkillSelectView(ui.View):
    """強化する技能を選択するためのView"""
    def __init__(self, character: Character, parent_view: LevelUpView):
        super().__init__(timeout=180)
        self.character = character
        self.parent_view = parent_view

        options = [discord.SelectOption(label=skill) for skill in self.character.skills.keys()]
        self.select_menu = ui.Select(placeholder="強化する技能を選択...", options=options)
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def on_select(self, interaction: discord.Interaction):
        skill_to_increase = interaction.data["values"][0]
        modal = SkillPointsModal(title=f"「{skill_to_increase}」の強化", character=self.character, skill_name=skill_to_increase, parent_view=self.parent_view)
        await interaction.response.send_modal(modal)

class SkillPointsModal(ui.Modal):
    """技能強化に使用するポイント数を入力するモーダル"""
    def __init__(self, *, title: str, character: Character, skill_name: str, parent_view: LevelUpView):
        super().__init__(title=title)
        self.character = character
        self.skill_name = skill_name
        self.parent_view = parent_view

        self.points_input = ui.TextInput(label=f"使用するポイント数 (最大: {self.character.skill_points})", placeholder="1", required=True)
        self.add_item(self.points_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            points_to_use = int(self.points_input.value)
            if self.character.use_skill_points(self.skill_name, points_to_use):
                await interaction.response.send_message(f"技能「{self.skill_name}」を {points_to_use} ポイント強化しました。", ephemeral=True)
                await self.parent_view.update_view()
            else:
                await interaction.response.send_message("ポイントが不足しているか、入力が不正です。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("エラー: ポイント数には数値を入力してください。", ephemeral=True)