import discord
from discord import ui
import random
from typing import TYPE_CHECKING

from game.models.character import Character
from bot.ui.embeds import create_character_embed
from bot import messaging

if TYPE_CHECKING:
    from bot.client import MyBot

def roll_for_stat():
    """能力値1つ分のダイスを振る (4d6の上位3つの和)"""
    rolls = [random.randint(1, 6) for _ in range(4)]
    return sum(sorted(rolls, reverse=True)[:3])

# --- Game Control Views ---

class ConfirmDeleteView(ui.View):
    """キャラクター削除の最終確認を行うView"""
    def __init__(self, author_id: int, bot: "MyBot", char_name: str):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.bot = bot
        self.char_name = char_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(messaging.MSG_ONLY_FOR_COMMAND_USER, ephemeral=True)
            return False
        return True

    @ui.button(label="はい、削除します", style=discord.ButtonStyle.danger, custom_id="confirm_delete")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        try:
            success = await self.bot.character_service.delete_character(self.author_id, self.char_name)
            if success:
                await interaction.response.edit_message(content=messaging.character_deleted(self.char_name), view=None)
            else:
                await interaction.response.edit_message(content=f"キャラクター「{self.char_name}」の削除に失敗しました。", view=None) # これはエラーなのでそのままでも良い
        except Exception as e:
            await interaction.response.edit_message(content=f"削除中にエラーが発生しました: {e}", view=None)
        self.stop()

    @ui.button(label="いいえ", style=discord.ButtonStyle.secondary, custom_id="cancel_delete")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content=messaging.character_delete_canceled(), view=None)
        self.stop()

# --- Character Creation Views & Modals ---

class StatsAllocationView(ui.View):
    """能力値の割り振りを管理するView"""
    def __init__(self, author: discord.User, rolls: list, parent_view, bot: "MyBot"):
        super().__init__(timeout=300)
        self.author = author
        self.bot = bot
        self.rolls = rolls
        self.parent_view = parent_view
        self.stats_to_assign = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        self.assignments = {}
        self.message: discord.Message = None

        for stat in self.stats_to_assign:
            select = ui.Select(placeholder=f"{stat}に割り振る値を選択", options=[discord.SelectOption(label=str(roll)) for roll in self.rolls], custom_id=f"stat_select_{stat}")
            select.callback = self.on_stat_select
            self.add_item(select)
        
        self.confirm_button = ui.Button(label="割り振りを確定", style=discord.ButtonStyle.primary, custom_id="confirm_stats", disabled=True)
        self.confirm_button.callback = self.on_confirm
        self.add_item(self.confirm_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(messaging.MSG_ONLY_FOR_COMMAND_USER, ephemeral=True)
            return False
        return True

    async def on_stat_select(self, interaction: discord.Interaction):
        stat_name = interaction.data['custom_id'].split('_')[-1]
        selected_value = int(interaction.data['values'][0])

        for key, value in self.assignments.items():
            if value == selected_value and key != stat_name:
                self.assignments[key] = None
                break
        self.assignments[stat_name] = selected_value

        assigned_values = {v for v in self.assignments.values() if v is not None}
        remaining_rolls = [r for r in self.rolls if r not in assigned_values]

        for item in self.children:
            if isinstance(item, ui.Select):
                current_stat = item.custom_id.split('_')[-1]
                current_assignment = self.assignments.get(current_stat)
                new_options = [discord.SelectOption(label=str(r)) for r in remaining_rolls]
                if current_assignment is not None and current_assignment not in remaining_rolls:
                    new_options.insert(0, discord.SelectOption(label=str(current_assignment)))
                item.options = new_options

        all_assigned = len(self.assignments) == len(self.stats_to_assign) and all(v is not None for v in self.assignments.values())
        self.confirm_button.disabled = not all_assigned

        assignment_text = "\n".join([f"- **{stat}**: {val if val is not None else '未割り当て'}" for stat, val in sorted(self.assignments.items())])
        await interaction.response.edit_message(content=f"ダイスロールの結果を各能力値に割り振ってください。\n\n**現在の割り振り状況:**\n{assignment_text}", view=self)

    async def on_confirm(self, interaction: discord.Interaction):
        assigned_values = [v for v in self.assignments.values() if v is not None]
        if len(assigned_values) != len(self.rolls) or len(set(assigned_values)) != len(self.rolls):
            await interaction.response.send_message("エラー: 全ての能力値にユニークなダイス結果を割り振ってください。", ephemeral=True)
            return

        self.parent_view.character_data["stats"] = self.assignments
        await interaction.response.edit_message(content="能力値を保存しました。最終確認画面を生成します...", view=None)
        await self.parent_view.show_summary_and_confirm(self.message)

class CharacterCreationView(ui.View):
    """キャラクター作成の対話フローを管理するView"""
    def __init__(self, author: discord.User, bot: "MyBot"):
        super().__init__(timeout=300)
        self.author = author
        self.bot = bot
        self.character_data = {}
        self.message: discord.Message = None
        self.options = self.bot.world_data_loader.get_creation_options()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("キャラクターを作成中の人のみ操作できます。", ephemeral=True) # 少し特殊なメッセージなので維持
            return False
        return True

    @ui.button(label="キャラクター作成を開始", style=discord.ButtonStyle.success, custom_id="start_creation")
    async def start_creation(self, interaction: discord.Interaction, button: ui.Button):
        modal = NameInputModal(title="キャラクター作成：名前", view=self)
        await interaction.response.send_modal(modal)

    async def prompt_race_selection(self):
        race_options = [discord.SelectOption(label=race["name"], description=race["description"]) for race in self.options.get("races", [])]
        select = ui.Select(placeholder="種族を選択してください...", options=race_options)
        select.callback = self.on_race_selected
        self.clear_items(); self.add_item(select)
        await self.message.edit(content="あなたのキャラクターの「種族」を教えてください。", view=self)

    async def on_race_selected(self, interaction: discord.Interaction):
        self.character_data["race"] = interaction.data["values"][0]
        await interaction.response.defer(); await self.prompt_class_selection()

    async def prompt_class_selection(self):
        class_options = [discord.SelectOption(label=cls["name"], description=cls["description"]) for cls in self.options.get("classes", [])]
        select = ui.Select(placeholder="クラスを選択してください...", options=class_options)
        select.callback = self.on_class_selected
        self.clear_items(); self.add_item(select)
        await self.message.edit(content="次に「クラス（職業）」を教えてください。", view=self)

    async def on_class_selected(self, interaction: discord.Interaction):
        self.character_data["class"] = interaction.data["values"][0]
        await interaction.response.defer(); await self.prompt_profile_input()

    async def prompt_profile_input(self):
        profile_button = ui.Button(label="プロフィールを入力", style=discord.ButtonStyle.primary)
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(ProfileInputModal(title="キャラクター作成：プロフィール", view=self))
        profile_button.callback = callback
        self.clear_items(); self.add_item(profile_button)
        await self.message.edit(content="キャラクターの「外見」や「背景設定」を入力します。", view=self)

    async def prompt_stats_roll(self):
        roll_button = ui.Button(label="能力値を決める (ダイスロール)", style=discord.ButtonStyle.success)
        async def callback(interaction: discord.Interaction):
            rolls = sorted([roll_for_stat() for _ in range(6)], reverse=True)
            content = f"ダイスロールの結果: **{' '.join(map(str, rolls))}**\n\n値を各能力値に割り振ってください。"
            allocation_view = StatsAllocationView(self.author, rolls, self, self.bot)
            await interaction.response.edit_message(content=content, view=allocation_view)
            allocation_view.message = await interaction.original_response()
        roll_button.callback = callback
        self.clear_items(); self.add_item(roll_button)
        await self.message.edit(content="キャラクターの能力値を決定します。", view=self)

    async def show_summary_and_confirm(self, message_to_edit: discord.Message):
        # Apply race bonus and update the internal state
        final_char = Character(self.character_data.copy())
        final_char.apply_race_bonus(self.options.get("races", []))
        self.character_data = final_char.to_dict() # Update view's data with final stats
        
        embed = create_character_embed(final_char)
        final_view = ui.View(timeout=self.timeout)
        confirm_button = ui.Button(label="この内容で作成", style=discord.ButtonStyle.primary)
        async def callback(interaction: discord.Interaction): await self.on_confirm(interaction)
        confirm_button.callback = callback
        final_view.add_item(confirm_button)
        
        if message_to_edit:
            await message_to_edit.edit(content="以下の内容でキャラクターを作成しますか？", embed=embed, view=final_view)

    async def on_confirm(self, interaction: discord.Interaction):
        try:
            # Use the already finalized character_data
            character_obj = await self.bot.character_service.create_character(self.author.id, self.character_data)
            await interaction.response.edit_message(content=f"キャラクター「{character_obj.name}」を作成しました！", view=None, embed=None)

            # # 画像生成機能が有効な場合、キャラクターの立ち絵を生成する
            # if self.bot.game_service.images.is_enabled():
            #     prompt = f"full body portrait of a fantasy character, {character_obj.race}, {character_obj.class_}, {character_obj.appearance}"
            #     try:
            #         image_data = await self.bot.game_service.images.generate_image_from_text(prompt)
            #         if image_data:
            #             file = discord.File(image_data, filename=f"{character_obj.name}_portrait.png")
            #             char_sheet_channel_id = self.bot.CHAR_SHEET_CHANNEL_ID
            #             channel = self.bot.get_channel(char_sheet_channel_id)
            #             
            #             embed = create_character_embed(character_obj)
            #             
            #             if channel and isinstance(channel, discord.TextChannel):
            #                 await channel.send(f"新しい冒険者「{character_obj.name}」が誕生しました。", embed=embed, file=file)
            #                 await interaction.followup.send(f"キャラクターシートと立ち絵を {channel.mention} に投稿しました。", ephemeral=True)
            #             else:
            #                 await interaction.followup.send("キャラクターシート投稿チャンネルが見つかりませんでした。", ephemeral=True)
            #     except Exception as img_e:
            #         await interaction.followup.send(f"立ち絵の生成中にエラーが発生しました: {img_e}", ephemeral=True)
        except Exception as e:
            await interaction.response.edit_message(content=f"作成エラー: {e}", view=None, embed=None)
        self.stop()

class NameInputModal(ui.Modal):
    char_name = ui.TextInput(label="キャラクター名", required=True, max_length=50)
    async def on_submit(self, interaction: discord.Interaction):
        view: CharacterCreationView = self.view
        view.character_data["name"] = self.char_name.value
        await interaction.response.defer(); await view.prompt_race_selection()

class ProfileInputModal(ui.Modal):
    appearance = ui.TextInput(label="外見", style=discord.TextStyle.paragraph, required=False, max_length=500)
    background = ui.TextInput(label="背景設定", style=discord.TextStyle.paragraph, required=False, max_length=1000)
    async def on_submit(self, interaction: discord.Interaction):
        view: CharacterCreationView = self.view
        if self.appearance.value: view.character_data["appearance"] = self.appearance.value
        if self.background.value: view.character_data["background"] = self.background.value
        await interaction.response.defer(); await view.prompt_stats_roll()

# --- Character Progression Views & Modals ---

class CharacterSelectView(ui.View):
    """保存されたキャラクターを選択するためのView"""
    def __init__(self, author_id: int, char_list: list[str], bot: "MyBot"):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.bot = bot
        
        options = [discord.SelectOption(label=name) for name in char_list]
        self.select_menu = ui.Select(placeholder="ステータスを見たいキャラクターを選択...", options=options)
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(messaging.MSG_ONLY_FOR_COMMAND_USER, ephemeral=True)
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        char_name = interaction.data["values"][0]
        try:
            character = await self.bot.character_service.get_character(self.author_id, char_name)
            embed = create_character_embed(character)
            await interaction.response.edit_message(content=f"「{char_name}」のステータスです。", embed=embed, view=None)
        except Exception as e:
            await interaction.response.edit_message(content=f"エラー: `{e}`", view=None)

class LevelUpView(ui.View):
    """レベルアップ時の強化選択肢を提供するView"""
    def __init__(self, author: discord.User, character: Character, bot: "MyBot"):
        super().__init__(timeout=300)
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(messaging.MSG_ONLY_FOR_COMMAND_USER, ephemeral=True)
            return False
        return True

    async def on_stat_increase(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StatIncreaseModal(self.character, self))

    async def on_skill_increase(self, interaction: discord.Interaction):
        if not self.character.skills:
            await interaction.response.send_message("強化できる技能を習得していません。", ephemeral=True)
            return
        await interaction.response.send_modal(SkillIncreaseModal(self.character, self))

    async def update_view(self):
        self.stat_button.disabled = (self.character.stat_points <= 0)
        self.skill_button.disabled = (self.character.skill_points <= 0)
        if self.stat_button.disabled and self.skill_button.disabled: self.stop()
        embed = create_character_embed(self.character)
        if self.message: await self.message.edit(embed=embed, view=self)

class StatIncreaseModal(ui.Modal):
    """能力値を強化するためのモーダル"""
    def __init__(self, character: Character, parent_view: LevelUpView):
        super().__init__(title="能力値強化")
        self.character = character
        self.parent_view = parent_view
        options = [discord.SelectOption(label=name, description=f"現在値: {val}") for name, val in self.character.stats.items()]
        self.stat_select = ui.Select(placeholder="強化する能力値を選択...", options=options)
        self.add_item(self.stat_select)

    async def on_submit(self, interaction: discord.Interaction):
        stat_to_increase = self.stat_select.values[0]
        if self.character.use_stat_point(stat_to_increase):
            await self.parent_view.bot.character_service.save_character(interaction.user.id, self.character)
            await interaction.response.defer(); await self.parent_view.update_view()
        else:
            await interaction.response.send_message(f"エラー: 能力値 `{stat_to_increase}` の強化に失敗しました。", ephemeral=True)

class SkillIncreaseModal(ui.Modal):
    """技能を強化するためのモーダル"""
    def __init__(self, character: Character, parent_view: LevelUpView):
        super().__init__(title="技能強化")
        self.character = character
        self.parent_view = parent_view
        options = [discord.SelectOption(label=name, description=f"現在ランク: {rank}") for name, rank in self.character.skills.items()]
        self.skill_select = ui.Select(placeholder="強化する技能を選択...", options=options)
        self.add_item(self.skill_select)
        self.points = ui.TextInput(label="使用するポイント数", placeholder=f"最大 {self.character.skill_points} P", required=True)
        self.add_item(self.points)

    async def on_submit(self, interaction: discord.Interaction):
        skill_to_increase = self.skill_select.values[0]
        try:
            points_to_use = int(self.points.value)
            if self.character.use_skill_points(skill_to_increase, points_to_use):
                await self.parent_view.bot.character_service.save_character(interaction.user.id, self.character)
                await interaction.response.defer(); await self.parent_view.update_view()
            else:
                await interaction.response.send_message(f"エラー: 技能 `{skill_to_increase}` の強化に失敗しました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("エラー: ポイント数には数値を入力してください。", ephemeral=True)