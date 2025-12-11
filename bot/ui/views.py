import discord
import logging
from discord import ui
import random
from typing import TYPE_CHECKING, List, Optional
from functools import partial

from game.models.character import Character
from bot.ui.embeds import create_character_embed
from bot import messaging

if TYPE_CHECKING:
    from bot.client import MyBot
    from bot.cogs.game_commands import GameCommandsCog

def roll_for_stat():
    """能力値1つ分のダイスを振る (4d6の上位3つの和)"""
    rolls = [random.randint(1, 6) for _ in range(4)]
    return sum(sorted(rolls, reverse=True)[:3])

logger = logging.getLogger(__name__)

# --- Game Control Views ---

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
                await interaction.response.edit_message(content=f"キャラクター「{self.char_name}」の削除に失敗しました。", view=None) # これはエラーなのでそのままでも良い
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
        
        # 提案されたアクションごとにボタンを作成
        for action in actions:
            button = ui.Button(label=action, style=discord.ButtonStyle.secondary)
            # partialを使って、コールバックにactionテキストを直接渡す
            button.callback = partial(self.on_action_button_click, action=action)
            self.add_item(button)
            
    async def on_action_button_click(self, interaction: discord.Interaction, action: str):
        """アクションボタンがクリックされたときの共通処理"""
        
        # 2回以上押せないように、また他の選択肢も押せないように即座に無効化
        for item in self.children:
            item.disabled = True
        # viewを更新してボタンを無効化
        await interaction.response.edit_message(view=self)

        # Cogを取得して、ゲームを進行させるヘルパーを呼び出す
        cog: "GameCommandsCog" = self.bot.get_cog("ゲーム管理")
        if cog:
            # このメソッドが新しいメッセージをfollowupで送信する
            await cog._proceed_and_respond_from_interaction(interaction, action)
        else:
            logger.warning("ActionSuggestionView: GameCommandsCogが見つかりませんでした。")
        
        self.stop()

    async def on_timeout(self):
        """Viewがタイムアウトしたときの処理"""
        for item in self.children:
            item.disabled = True
        
        if self.message:
            try:
                # メッセージにタイムアウトした旨を追記する
                original_content = self.message.content
                if "（時間切れです）" not in original_content:
                    await self.message.edit(content=original_content + "\n\n*（時間切れのため、選択肢は無効になりました）*", view=self)
            except discord.HTTPException as e:
                # スレッドがアーカイブされている場合(50083)など、編集に失敗することがある
                # その場合はログに記録するだけで、クラッシュはさせない
                logger.warning(f"タイムアウトメッセージの編集に失敗しました (Code: {e.code}): {e.text}")
            except Exception as e:
                logger.error(f"タイムアウトメッセージの編集中に予期せぬエラーが発生しました。", exc_info=e)
        self.stop()


# --- Character Creation Views & Modals ---

class CharacterCreationView(BaseOwnedView):
    """キャラクター作成の対話フローを管理するView"""
    MAX_REROLLS = 3 # リロール回数の上限

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
        await interaction.response.defer()
        await self.prompt_profile_input()

    async def prompt_profile_input(self):
        profile_button = ui.Button(label="プロフィールを入力", style=discord.ButtonStyle.primary)
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(ProfileInputModal(title="キャラクター作成：プロフィール", view=self))
        profile_button.callback = callback
        self.clear_items(); self.add_item(profile_button)
        await self.message.edit(content="キャラクターの「外見」や「背景設定」を入力します。", view=self, embed=None)

    async def prompt_stats_decision(self):
        """能力値決定のステップに進むためのボタンを表示する"""
        roll_button = ui.Button(label="能力値を決める (ダイスロール)", style=discord.ButtonStyle.success)
        roll_button.callback = self.prompt_stats_roll
        self.clear_items()
        self.add_item(roll_button)
        await self.message.edit(content="キャラクターの能力値を決定します。", view=self, embed=None)

    async def prompt_stats_roll(self, interaction: discord.Interaction):
        """
        能力値をランダムに決定し、ユーザーに提示する。
        このメソッドは必ずボタンクリックのインタラクションから呼び出される。
        """
        # リロール回数を1増やす
        self.reroll_count += 1
        
        # 1. ダイスロール
        rolls = [roll_for_stat() for _ in range(6)]
        
        # 2. ランダム割り当て
        stats_to_assign = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        random.shuffle(rolls)
        assigned_stats = dict(zip(stats_to_assign, rolls))

        # 3. 仮のキャラクターオブジェクトを作成してインスタンス変数に保存
        temp_char_data = self.character_data.copy()
        temp_char_data["stats"] = assigned_stats
        
        self.temp_character = Character(temp_char_data)
        self.temp_character.apply_race_bonus(self.options.get("races", []))
        
        embed = create_character_embed(self.temp_character)
        
        # 4. Viewのボタンを更新
        self.clear_items()
        confirm_button = ui.Button(label="この能力値で確定する", style=discord.ButtonStyle.primary, custom_id="confirm_stats")
        confirm_button.callback = self.on_stats_confirmed
        self.add_item(confirm_button)

        remaining_rerolls = self.MAX_REROLLS - self.reroll_count
        reroll_disabled = remaining_rerolls < 0

        reroll_button = ui.Button(
            label=f"リロール（残り {remaining_rerolls if not reroll_disabled else 0} 回）", 
            style=discord.ButtonStyle.secondary, 
            custom_id="reroll_stats",
            disabled=reroll_disabled
        )
        reroll_button.callback = self.prompt_stats_roll # 自分自身を再度呼び出す
        self.add_item(reroll_button)
        
        # 5. メッセージをインタラクション応答として編集
        content = "以下の能力値がランダムに割り振られました。この内容で確定しますか？"
        await interaction.response.edit_message(content=content, embed=embed, view=self)

    async def on_stats_confirmed(self, interaction: discord.Interaction):
        """能力値の確定ボタンが押されたときの処理"""
        if not self.temp_character: return # 万が一のため
        self.character_data["stats"] = self.temp_character.stats
        await self.show_summary_and_confirm(interaction)

    async def show_summary_and_confirm(self, interaction: discord.Interaction):
        # 確定したキャラクターデータから最終的なCharacterオブジェクトを作成
        final_char = Character(self.character_data.copy())
        
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

# --- Character Progression Views & Modals ---

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
    """能力値を強化するためのView（セレクトメニュー）"""
    def __init__(self, character: Character, parent_view: LevelUpView):
        super().__init__(timeout=60)
        self.character = character
        self.parent_view = parent_view
        
        options = [discord.SelectOption(label=name, description=f"現在値: {val}") for name, val in character.stats.items()]
        self.select = ui.Select(placeholder="強化する能力値を選択...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        stat_to_increase = self.select.values[0]
        if self.character.use_stat_point(stat_to_increase):
            await self.parent_view.bot.character_service.save_character(interaction.user.id, self.character)
            await self.parent_view.update_view()
            await interaction.response.edit_message(content=f"能力値 `{stat_to_increase}` を強化しました。", view=None)
        else:
            await interaction.response.send_message(f"エラー: 能力値 `{stat_to_increase}` の強化に失敗しました。", ephemeral=True)

class SkillSelectView(ui.View):
    """技能強化のための技能選択View"""
    def __init__(self, character: Character, parent_view: LevelUpView):
        super().__init__(timeout=60)
        self.character = character
        self.parent_view = parent_view
        
        options = [discord.SelectOption(label=name, description=f"現在ランク: {rank}") for name, rank in character.skills.items()]
        self.select = ui.Select(placeholder="強化する技能を選択...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        skill_name = self.select.values[0]
        await interaction.response.send_modal(SkillPointsModal(self.character, self.parent_view, skill_name))

class SkillPointsModal(ui.Modal):
    """技能強化のためのポイント入力モーダル"""
    def __init__(self, character: Character, parent_view: LevelUpView, skill_name: str):
        super().__init__(title=f"技能強化: {skill_name}")
        self.character = character
        self.parent_view = parent_view
        self.skill_name = skill_name
        
        self.points = ui.TextInput(label="使用するポイント数", placeholder=f"最大 {character.skill_points} P", required=True)
        self.add_item(self.points)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            points_to_use = int(self.points.value)
            if self.character.use_skill_points(self.skill_name, points_to_use):
                await self.parent_view.bot.character_service.save_character(interaction.user.id, self.character)
                await interaction.response.defer(); await self.parent_view.update_view()
            else:
                await interaction.response.send_message(f"エラー: 技能 `{self.skill_name}` の強化に失敗しました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("エラー: ポイント数には数値を入力してください。", ephemeral=True)