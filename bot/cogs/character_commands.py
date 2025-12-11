import discord
from discord.ext import commands
from discord import app_commands
from typing import TYPE_CHECKING, Optional
from collections import Counter
from game.models.character import Character
from bot.ui.embeds import create_character_embed, create_journal_embed
from bot.ui.views.character_creation import CharacterCreationView
from bot.ui.views.character_progression import CharacterSelectView, LevelUpView
from bot import messaging

if TYPE_CHECKING:
    from bot.client import MyBot


class CharacterCommandsCog(commands.Cog, name="キャラクター管理"):
    """キャラクターの作成、ステータス確認、成長に関するコマンド"""
    def __init__(self, bot: "MyBot"):
        self.bot = bot

    # --- キャラクター作成 ---
    @app_commands.command(name="character_create", description="新しいキャラクターを対話形式で作成します。")
    async def character_create(self, interaction: discord.Interaction):
        view = CharacterCreationView(interaction.user, self.bot) # Corrected import path
        await interaction.response.send_message("キャラクター作成へようこそ！下のボタンを押して作成を開始してください。", view=view, ephemeral=True)
        view.message = await interaction.original_response()

    # --- ステータス確認 ---
    @app_commands.command(name="status", description="キャラクターのステータスを表示します。")
    @app_commands.describe(ephemeral="他の人に見せない場合はTrue（デフォルト）")
    async def status(self, interaction: discord.Interaction, ephemeral: bool = True):
        character_to_display: Optional[Character] = None

        active_session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if active_session:
            character_to_display = active_session.character
        else:
            saved_chars = await self.bot.character_service.get_all_character_names(interaction.user.id) # ここで `game_service` ではなく `character_service` を使うのが正しい
            if not saved_chars:
                await interaction.response.send_message("表示できるキャラクターがいません。`/character_create` で新しいキャラクターを作成してください。", ephemeral=True)
                return
            elif len(saved_chars) == 1:
                character_to_display = await self.bot.character_service.get_character(interaction.user.id, saved_chars[0])
            else:
                view = CharacterSelectView(interaction.user.id, saved_chars, self.bot)
                await interaction.response.send_message("どのキャラクターのステータスを見ますか？", view=view, ephemeral=ephemeral)
                return

        if character_to_display:
            embed = create_character_embed(character_to_display)
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    # --- インベントリ確認 ---
    @app_commands.command(name="inventory", description="キャラクターの所持品を表示します。")
    @app_commands.describe(ephemeral="他の人に見せない場合はTrue（デフォルト）")
    async def inventory(self, interaction: discord.Interaction, ephemeral: bool = True):
        character = None
        active_session = self.bot.game_service.sessions.get_session(interaction.user.id)
        
        if active_session:
            character = active_session.character
        else:
            saved_chars = await self.bot.character_service.get_all_character_names(interaction.user.id)
            if not saved_chars:
                await interaction.response.send_message("キャラクターが見つかりません。`/character_create` で作成してください。", ephemeral=True)
                return
            elif len(saved_chars) == 1:
                character = await self.bot.character_service.get_character(interaction.user.id, saved_chars[0])
            else:
                await interaction.response.send_message("複数のキャラクターが見つかりました。インベントリを確認するには、ゲームを開始するか、キャラクターを1人に絞ってください。", ephemeral=True)
                return

        if character:
            embed = discord.Embed(title=f"🎒 {character.name} の所持品", color=discord.Color.gold())
            embed.add_field(name="所持金", value=f"{character.gold} G", inline=False)
            inventory = getattr(character, "inventory", [])
            if inventory:
                item_counts = Counter(inventory)
                embed.description = "\n".join([f"・{item} x{count}" for item, count in item_counts.items()])
            else:
                embed.description = "（何も持っていません）"
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

    # --- レベルアップ ---
    @app_commands.command(name="levelup", description="ポイントを使ってキャラクターを強化します。")
    async def levelup(self, interaction: discord.Interaction):
        lock = self.bot.game_service.sessions.get_lock(interaction.user.id)
        async with lock:
            session = self.bot.game_service.sessions.get_session(interaction.user.id)
            if not session:
                return await interaction.response.send_message(messaging.MSG_SESSION_REQUIRED, ephemeral=True)
            
            character = session.character
            if character.stat_points <= 0 and character.skill_points <= 0:
                return await interaction.response.send_message("使用できる強化ポイントがありません。", ephemeral=True)

            embed = create_character_embed(character)
            view = LevelUpView(interaction.user, character, self.bot)
            await interaction.response.send_message("キャラクターを強化します。どの項目を強化しますか？", embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()

    # --- 経験値追加（テスト用） ---
    @app_commands.command(name="add_xp", description="（テスト用）キャラクターに経験値を追加します。")
    @commands.is_owner()
    async def add_xp(self, interaction: discord.Interaction, amount: int):
        lock = self.bot.game_service.sessions.get_lock(interaction.user.id)
        async with lock:
            session = self.bot.game_service.sessions.get_session(interaction.user.id)
            if not session:
                return await interaction.response.send_message(messaging.MSG_NO_ACTIVE_SESSION, ephemeral=True)
            
            leveled_up = session.character.add_xp(amount)
            
            new_skills_msg = ""
            if leveled_up:
                world_data = self.bot.world_data_loader.get_world(session.world_name)
                new_skills = session.character.check_new_skills(world_data)
                if new_skills:
                    new_skills_msg = f"\n💡 新スキル習得: {', '.join(new_skills)}"

            await self.bot.character_service.save_character(session.character)
            message = f"{amount} の経験値を獲得しました。現在のXP: {session.character.xp}"
            if leveled_up:
                message += f"\n\n**レベルアップ！** レベルが {session.character.level} になりました！{new_skills_msg}\n`/levelup` コマンドでキャラクターを強化してください。"
            await interaction.response.send_message(message, ephemeral=True)

    # --- ジャーナル確認 ---
    @app_commands.command(name="journal", description="冒険日誌（クエスト一覧）を表示します。")
    async def journal(self, interaction: discord.Interaction):
        """現在受注しているクエストや完了したクエストの一覧を表示する"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session:
            await interaction.response.send_message(messaging.MSG_SESSION_REQUIRED, ephemeral=True)
            return

        world_data = self.bot.world_data_loader.get_world(session.world_name)
        all_quests_data = world_data.get('quests', {})
        all_enemies_data = world_data.get('enemies', {})
        embed = create_journal_embed(session, all_quests_data, all_enemies_data)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: "MyBot"):
    await bot.add_cog(CharacterCommandsCog(bot))