import discord
from discord import ui
import random
from typing import TYPE_CHECKING, Optional

from game.models.character import Character
from bot.ui.embeds import create_character_embed
from config.settings import MAX_REROLLS_ON_CREATION
from .utility import BaseOwnedView

if TYPE_CHECKING:
    from bot.client import MyBot

def roll_for_stat():
    """能力値1つ分のダイスを振る (4d6の上位3つの和)"""
    rolls = [random.randint(1, 6) for _ in range(4)]
    return sum(sorted(rolls, reverse=True)[:3])

class CharacterCreationView(BaseOwnedView):
    """キャラクター作成の対話フローを管理するView"""

    def __init__(self, author: discord.User, bot: "MyBot"):
        super().__init__(user_id=author.id, timeout=300)
        self.author = author
        self.bot = bot
        self.character_data = {}
        self.message: discord.Message = None
        self.options = self.bot.world_data_loader.get('fantasy_world', 'creation_options')
        self.temp_character: Optional[Character] = None
        self.reroll_count = 0

    @ui.button(label="キャラクター作成を開始", style=discord.ButtonStyle.success, custom_id="start_creation")
    async def start_creation(self, interaction: discord.Interaction, button: ui.Button):
        modal = NameInputModal(title="キャラクター作成：名前", view=self)
        await interaction.response.send_modal(modal)

    async def prompt_race_selection(self):
        temp_char = Character(self.character_data)
        embed = create_character_embed(temp_char)

        race_options = [discord.SelectOption(label=race["name"], description=race["description"]) for race in self.options.get("races", [])]
        select = ui.Select(placeholder="種族を選択してください...", options=race_options)
        select.callback = self.on_race_selected
        self.clear_items(); self.add_item(select)
        await self.message.edit(content="あなたのキャラクターの「種族」を教えてください。", view=self, embed=embed)

    async def on_race_selected(self, interaction: discord.Interaction):
        self.character_data["race"] = interaction.data["values"][0]
        await interaction.response.defer(); await self.prompt_class_selection()

    async def prompt_class_selection(self):
        temp_char = Character(self.character_data)
        embed = create_character_embed(temp_char)

        class_options = [discord.SelectOption(label=cls["name"], description=cls["description"]) for cls in self.options.get("classes", [])]
        select = ui.Select(placeholder="クラスを選択してください...", options=class_options)
        select.callback = self.on_class_selected
        self.clear_items(); self.add_item(select)
        await self.message.edit(content="次に「クラス（職業）」を教えてください。", view=self, embed=embed)

    async def on_class_selected(self, interaction: discord.Interaction):
        self.character_data["class"] = interaction.data["values"][0]
        await interaction.response.defer()
        await self.prompt_profile_input()

    async def prompt_profile_input(self):
        temp_char = Character(self.character_data)
        embed = create_character_embed(temp_char)

        profile_button = ui.Button(label="プロフィールを入力", style=discord.ButtonStyle.primary)
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(ProfileInputModal(title="キャラクター作成：プロフィール", view=self))
        profile_button.callback = callback
        self.clear_items(); self.add_item(profile_button)
        await self.message.edit(content="キャラクターの「外見」や「背景設定」を入力します。", view=self, embed=embed)

    async def prompt_stats_decision(self):
        temp_char = Character(self.character_data)
        embed = create_character_embed(temp_char)

        roll_button = ui.Button(label="能力値を決める (ダイスロール)", style=discord.ButtonStyle.success)
        roll_button.callback = self.prompt_stats_roll
        
        self.clear_items()
        self.add_item(roll_button)
        
        content = "キャラクターの能力値を決定します。"
        await self.message.edit(content=content, view=self, embed=embed)

    async def _update_stats_roll_view(self, interaction: discord.Interaction):
        embed = create_character_embed(self.temp_character)

        self.clear_items()
        confirm_button = ui.Button(label="この能力値で確定する", style=discord.ButtonStyle.primary)
        confirm_button.callback = self.on_stats_confirmed
        self.add_item(confirm_button)

        remaining_rerolls = MAX_REROLLS_ON_CREATION - self.reroll_count
        reroll_disabled = remaining_rerolls <= 0

        reroll_button = ui.Button(
            label=f"リロール（残り {max(0, remaining_rerolls)} 回）",
            style=discord.ButtonStyle.secondary,
            disabled=reroll_disabled
        )
        reroll_button.callback = self.prompt_stats_roll
        self.add_item(reroll_button)

        content = "以下の能力値がランダムに割り振られました。この内容で確定しますか？"
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    async def prompt_stats_roll(self, interaction: discord.Interaction):
        self.reroll_count += 1

        rolls = [roll_for_stat() for _ in range(6)]
        stats_to_assign = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        random.shuffle(rolls)
        assigned_stats = dict(zip(stats_to_assign, rolls))

        temp_char_data = self.character_data.copy()
        temp_char_data["stats"] = assigned_stats
        self.temp_character = Character(temp_char_data)
        await self._update_stats_roll_view(interaction)

    async def on_stats_confirmed(self, interaction: discord.Interaction):
        if not self.temp_character: return
        self.character_data["stats"] = self.temp_character.stats
        await self.show_summary_and_confirm(interaction)

    async def show_summary_and_confirm(self, interaction: discord.Interaction):
        # 初期装備の付与
        race_name = self.character_data.get("race")
        class_name = self.character_data.get("class")
        starting_items = []

        # 種族の初期装備を取得
        race_data = next((r for r in self.options.get("races", []) if r["name"] == race_name), None)
        if race_data:
            starting_items.extend(race_data.get("starting_items", []))

        # クラスの初期装備を取得
        class_data = next((c for c in self.options.get("classes", []) if c["name"] == class_name), None)
        if class_data:
            starting_items.extend(class_data.get("starting_items", []))

        self.character_data["inventory"] = starting_items

        final_char = Character(self.character_data.copy())
        final_char.apply_race_bonus(self.options.get("races", []))
        
        embed = create_character_embed(final_char)
        final_view = FinalConfirmView(self.author.id, self.bot, self.character_data, self)
        
        await interaction.response.edit_message(
            content="以下の内容でキャラクターを作成しますか？", 
            embed=embed, 
            view=final_view
        )

class FinalConfirmView(BaseOwnedView):
    """キャラクター作成の最終確認を行うView"""
    def __init__(self, author_id: int, bot: "MyBot", character_data: dict, parent_view: "CharacterCreationView"):
        super().__init__(user_id=author_id, timeout=parent_view.timeout)
        self.bot = bot
        self.character_data = character_data
        self.parent_view = parent_view

    @ui.button(label="この内容で作成", style=discord.ButtonStyle.primary)
    async def confirm_creation_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            character_obj = await self.bot.character_service.create_character(self.user_id, self.character_data)
            await interaction.response.edit_message(
                content=f"キャラクター「{character_obj.name}」を作成しました！", 
                view=None, 
                embed=None
            )
            self.parent_view.stop()
        except Exception as e:
            await interaction.response.edit_message(content=f"作成エラー: {e}", view=None, embed=None)
        self.stop()

class NameInputModal(ui.Modal):
    def __init__(self, *, title: str, view: CharacterCreationView):
        super().__init__(title=title)
        self.view = view

    char_name = ui.TextInput(label="キャラクター名", required=True, max_length=50)
    async def on_submit(self, interaction: discord.Interaction):
        self.view.character_data["name"] = self.char_name.value
        await interaction.response.defer(); await self.view.prompt_race_selection()

class ProfileInputModal(ui.Modal):
    def __init__(self, *, title: str, view: CharacterCreationView):
        super().__init__(title=title)
        self.view = view

    appearance = ui.TextInput(label="外見", style=discord.TextStyle.paragraph, required=False, max_length=500)
    background = ui.TextInput(label="背景設定", style=discord.TextStyle.paragraph, required=False, max_length=1000)
    async def on_submit(self, interaction: discord.Interaction):
        if self.appearance.value: self.view.character_data["appearance"] = self.appearance.value
        if self.background.value: self.view.character_data["background"] = self.background.value
        await interaction.response.defer()
        await self.view.prompt_stats_decision()

class StatsInputModal(ui.Modal):
    # (Implementation from original file)
    ...