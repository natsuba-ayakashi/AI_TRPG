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
        self.selected_stat = None
        self.selected_roll = None
        self.message: discord.Message = None

        # UIコンポーネントの初期化
        self.stat_select = ui.Select(placeholder="割り振る能力値を選択...", custom_id="stat_select")
        self.stat_select.callback = self.on_stat_select
        self.add_item(self.stat_select)

        self.roll_select = ui.Select(placeholder="割り振るダイス結果を選択...", custom_id="roll_select", disabled=True)
        self.roll_select.callback = self.on_roll_select
        self.add_item(self.roll_select)

        self.assign_button = ui.Button(label="割り振り", style=discord.ButtonStyle.secondary, custom_id="assign_button", disabled=True)
        self.assign_button.callback = self.on_assign
        self.add_item(self.assign_button)

        self.confirm_button = ui.Button(label="割り振りを確定", style=discord.ButtonStyle.primary, custom_id="confirm_stats", disabled=True, row=2)
        self.confirm_button.callback = self.on_confirm_assignments
        self.add_item(self.confirm_button)

        self.update_selects()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(messaging.MSG_ONLY_FOR_COMMAND_USER, ephemeral=True)
            return False
        return True

    def update_selects(self):
        """セレクトメニューの選択肢と状態を更新する"""
        # 能力値選択メニューの更新
        unassigned_stats = [s for s in self.stats_to_assign if s not in self.assignments]
        if unassigned_stats:
            self.stat_select.options = [discord.SelectOption(label=s) for s in unassigned_stats]
        else:
            self.stat_select.options = [discord.SelectOption(label="全ての能力値を割り振りました", value="all_assigned", default=True)]
        self.stat_select.disabled = not unassigned_stats

        # ダイス結果選択メニューの更新
        assigned_rolls = set(self.assignments.values())
        
        # 割り当て済みのロールをカウント
        from collections import Counter
        assigned_counts = Counter(assigned_rolls)
        
        # 未割り当てのロールをインデックス付きで管理
        unassigned_rolls_with_indices = []
        total_counts = Counter(self.rolls)
        for roll, total_count in total_counts.items():
            assigned_count = assigned_counts.get(roll, 0)
            for i in range(assigned_count, total_count):
                unassigned_rolls_with_indices.append((roll, i))

        # labelはロールの値、valueは "ロール_インデックス" 形式で一意にする
        self.roll_select.options = [discord.SelectOption(label=str(roll), value=f"{roll}_{idx}") for roll, idx in sorted(unassigned_rolls_with_indices, key=lambda x: x[0], reverse=True)]
        self.roll_select.disabled = not self.selected_stat or not unassigned_rolls_with_indices

        # ボタンの状態更新
        self.assign_button.disabled = not (self.selected_stat and self.selected_roll)
        self.confirm_button.disabled = len(self.assignments) != len(self.stats_to_assign)

    async def on_stat_select(self, interaction: discord.Interaction):
        self.selected_stat = interaction.data["values"][0]
        self.update_selects()
        await interaction.response.edit_message(content=self._get_current_content(), view=self)

    async def on_roll_select(self, interaction: discord.Interaction):
        # value (e.g., "14_0") からロールの値を取得
        self.selected_roll = int(interaction.data["values"][0].split('_')[0])
        self.update_selects()
        await interaction.response.edit_message(content=self._get_current_content(), view=self)

    async def on_assign(self, interaction: discord.Interaction):
        if self.selected_stat == "all_assigned": # ダミーオプションが選択された場合は何もしない
            await interaction.response.send_message("全ての能力値は既に割り振られています。", ephemeral=True)
            return

        self.assignments[self.selected_stat] = self.selected_roll
        self.selected_stat = None
        self.selected_roll = None
        self.update_selects()
        await interaction.response.edit_message(content=self._get_current_content(), view=self)

    async def on_confirm_assignments(self, interaction: discord.Interaction):
        self.parent_view.character_data["stats"] = self.assignments
        await interaction.response.edit_message(content="能力値を保存しました。最終確認画面を生成します...", view=None)
        await self.parent_view.show_summary_and_confirm(self.message)

    def _get_current_content(self) -> str:
        assignment_text = "\n".join([f"- **{stat}**: {val}" for stat, val in sorted(self.assignments.items())])
        current_selection_text = ""
        if self.selected_stat and self.selected_stat != "all_assigned": current_selection_text += f"\n**選択中の能力値:** {self.selected_stat}"
        if self.selected_roll is not None: current_selection_text += f"\n**選択中のダイス結果:** {self.selected_roll}"
        return (f"ダイスロールの結果を各能力値に割り振ってください。\n\n**現在の割り振り状況:**\n{assignment_text}\n{current_selection_text}")

class CharacterCreationView(ui.View):
    """キャラクター作成の対話フローを管理するView"""
    def __init__(self, author: discord.User, bot: "MyBot"):
        super().__init__(timeout=300)
        self.author = author
        self.bot = bot
        self.character_data = {}
        self.message: discord.Message = None
        self.options = self.bot.world_data_loader.get('fantasy_world', 'creation_options')

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
        await interaction.response.defer(); await self.view.prompt_stats_roll()

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
        options = [discord.SelectOption(label=name, description=f"現在値: {val}") for name, val in character.stats.items()]
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
        options = [discord.SelectOption(label=name, description=f"現在ランク: {rank}") for name, rank in character.skills.items()]
        self.skill_select = ui.Select(placeholder="強化する技能を選択...", options=options)
        self.add_item(self.skill_select)
        self.points = ui.TextInput(label="使用するポイント数", placeholder=f"最大 {character.skill_points} P", required=True)
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