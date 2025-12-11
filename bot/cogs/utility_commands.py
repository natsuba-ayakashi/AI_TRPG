import discord
from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING, List

from bot.ui.embeds import create_command_list_embed
from core.errors import GameError

if TYPE_CHECKING:
    from bot.client import MyBot


class UtilityCommandsCog(commands.Cog, name="ユーティリティ"):
    """Botの動作確認やヘルプなど、補助的な機能を提供するコマンド"""

    def __init__(self, bot: "MyBot"):
        self.bot = bot

    # --- Setup Command Group ---
    setup = app_commands.Group(name="setup", description="管理者向けの初期設定コマンド", default_permissions=discord.Permissions(administrator=True))

    @setup.command(name="command_channel", description="このチャンネルにコマンド一覧を常時表示します。")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_command_channel(self, interaction: discord.Interaction):
        """現在のチャンネルをコマンドリスト表示用チャンネルとして設定する。"""
        await interaction.response.defer(ephemeral=True)
        
        # まずは古いメッセージを削除しようと試みる
        try:
            guild_settings = await self.bot.settings_repo.get_guild_settings(interaction.guild.id)
            if guild_settings and guild_settings.get("command_message_id"):
                old_channel_id = guild_settings.get("command_channel_id")
                old_message_id = guild_settings.get("command_message_id")
                if old_channel_id and old_message_id:
                    channel = self.bot.get_channel(old_channel_id)
                    if channel:
                        message = await channel.fetch_message(old_message_id)
                        await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass # 古いメッセージが見つからないか、削除権限がなくても気にしない

        # 新しいコマンド一覧メッセージを投稿
        embed = create_command_list_embed(self.bot)
        msg = await interaction.channel.send(embed=embed)
        
        # 設定を保存
        guild_settings = await self.bot.settings_repo.get_guild_settings(interaction.guild.id) or {}
        guild_settings["command_channel_id"] = interaction.channel.id
        guild_settings["command_message_id"] = msg.id
        await self.bot.settings_repo.save_guild_settings(interaction.guild.id, guild_settings)
        
        await interaction.followup.send(f"✅ このチャンネル ({interaction.channel.mention}) をコマンド一覧の表示チャンネルとして設定しました。", ephemeral=True)

    @setup.command(name="log_channel", description="このチャンネルにゲームの進行ログを出力します。")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_log_channel(self, interaction: discord.Interaction):
        """現在のチャンネルをゲームログ出力用チャンネルとして設定する。"""
        await interaction.response.defer(ephemeral=True)

        guild_settings = await self.bot.settings_repo.get_guild_settings(interaction.guild.id) or {}
        guild_settings["log_channel_id"] = interaction.channel.id
        
        await self.bot.settings_repo.save_guild_settings(interaction.guild.id, guild_settings)
        
        await interaction.followup.send(f"✅ このチャンネル ({interaction.channel.mention}) をゲームログの出力チャンネルとして設定しました。", ephemeral=True)


    @app_commands.command(name="ping", description="Botの応答速度を測定します。")
    async def ping(self, interaction: discord.Interaction):
        """Botのレイテンシを表示します。"""
        latency = self.bot.latency
        await interaction.response.send_message(f"Pong! 🏓\nレイテンシ: {latency * 1000:.2f}ms", ephemeral=True)

    @app_commands.command(name="help", description="利用可能なコマンドの一覧を表示します。")
    async def help(self, interaction: discord.Interaction):
        """Botに登録されている全てのスラッシュコマンドを一覧表示します。"""
        embed = create_command_list_embed(self.bot)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="graveyard", description="この世界で散っていった者たちの記録を閲覧します。")
    async def graveyard(self, interaction: discord.Interaction):
        """世界に記録されている墓場の情報を表示する。"""
        await interaction.response.defer(ephemeral=True)

        world_state = await self.bot.game_service.world_repo.load()
        graveyard_data = world_state.get("graveyard", {})

        embed = discord.Embed(
            title="🪦 墓場 - 散りし者たちの記憶",
            description="この世界に、確かに生きた冒険者たちの記録。",
            color=discord.Color.dark_grey()
        )

        if not graveyard_data:
            embed.add_field(name="安息", value="まだ誰もこの世界で永遠の眠りについていない。")
        else:
            for char_id, data in graveyard_data.items():
                embed.add_field(name=f"**{data.get('name', '名もなき者')}**", value=f"レベル {data.get('level', '?')} で没。\n死因: {data.get('cause_of_death', '不明')}", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="search_grave", description="墓を探索し、遺品を回収します。")
    @app_commands.describe(character_name="探索する墓の主の名前")
    async def search_grave(self, interaction: discord.Interaction, character_name: str):
        """墓を探索してアイテムを回収する。"""
        await interaction.response.defer(ephemeral=True)

        try:
            looted_items = await self.bot.game_service.loot_grave(interaction.user.id, character_name)
            if looted_items:
                message = f"「{character_name}」の墓を探索し、以下のアイテムを見つけた…\n- " + "\n- ".join(looted_items)
            else:
                message = f"「{character_name}」の墓を探索したが、何も見つからなかった。"
            await interaction.followup.send(message, ephemeral=True)
        except GameError as e:
            await interaction.followup.send(str(e), ephemeral=True)

    @search_grave.autocomplete('character_name')
    async def _search_grave_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """墓場に存在するキャラクター名をオートコンプリートの候補として表示する"""
        world_state = await self.bot.game_service.world_repo.load()
        graveyard_data = world_state.get("graveyard", {})
        
        char_names = [data['name'] for data in graveyard_data.values() if 'name' in data and 'dropped_items' in data and data['dropped_items']]
        return [
            app_commands.Choice(name=name, value=name)
            for name in char_names if current.lower() in name.lower()
        ][:25]

async def setup(bot: "MyBot"):
    await bot.add_cog(UtilityCommandsCog(bot))