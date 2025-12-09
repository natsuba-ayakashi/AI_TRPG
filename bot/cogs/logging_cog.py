import discord
from discord.ext import commands
from typing import TYPE_CHECKING, Dict, Any

from bot.ui.embeds import create_action_result_embed
from game.models.session import GameSession

if TYPE_CHECKING:
    from bot.client import MyBot


class LoggingCog(commands.Cog, name="ゲームログ"):
    """ゲームの進行状況を特定のチャンネルに記録する"""

    def __init__(self, bot: "MyBot"):
        self.bot = bot
        self.play_log_channel_id = bot.PLAY_LOG_CHANNEL_ID

    @commands.Cog.listener("on_game_start")
    async def log_game_start(self, session: GameSession):
        """ゲーム開始のログを記録する"""
        channel = self.bot.get_channel(self.play_log_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        user = self.bot.get_user(session.user_id) or await self.bot.fetch_user(session.user_id)
        if not user:
            # ユーザーが取得できない場合はログをスキップ
            return

        embed = discord.Embed(
            title="▶️ ゲーム開始",
            description=f"**{session.character.name}** の冒険が始まりました。",
            color=discord.Color.green()
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar)
        embed.set_footer(text=f"ユーザーID: {session.user_id}")
        await channel.send(embed=embed)

    @commands.Cog.listener("on_game_proceed")
    async def log_game_proceed(self, session: GameSession, user_input: str, ai_response: Dict[str, Any]):
        """ゲーム進行（プレイヤーの行動とGMの応答）のログを記録する"""
        channel = self.bot.get_channel(self.play_log_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        user = self.bot.get_user(session.user_id)
        if not user:
            user = await self.bot.fetch_user(session.user_id)
        if not user:
            # ユーザーが取得できない場合はログをスキップ
            return

        embed = discord.Embed(title=f"📜 ターン進行: {session.character.name}", color=discord.Color.light_grey())
        if user:
            embed.set_author(name=user.display_name, icon_url=user.display_avatar)
        embed.add_field(name="プレイヤーの行動", value=f"```{user_input}```", inline=False)
        
        narrative = ai_response.get("narrative", "（描写なし）")
        # 長すぎる場合は省略
        if len(narrative) > 800:
            narrative = narrative[:800] + "..."
        embed.add_field(name="GMの描写", value=narrative, inline=False)

        # キャラクターの簡易ステータスを追加
        char = session.character
        embed.add_field(name="簡易ステータス", value=f"Lv: {char.level} | HP: {char.hp}/{char.max_hp} | MP: {char.mp}/{char.max_mp}", inline=True)

        # state_changesの内容をログに追加
        if state_changes := ai_response.get("state_changes"):
            changes_text = []
            if xp := state_changes.get("xp_gain"): changes_text.append(f"✨ 経験値 +{xp}")
            if hp := state_changes.get("hp_change"): changes_text.append(f"❤️ HP {hp:+}")
            if mp := state_changes.get("mp_change"): changes_text.append(f"💙 MP {mp:+}")
            if items := state_changes.get("new_items"): changes_text.append(f"획득 アイテム: {', '.join(items)}")
            if quests := state_changes.get("quest_updates"): changes_text.append(f"🗺️ クエスト更新: {', '.join(quests.keys())}")
            if changes_text:
                embed.add_field(name="状態変化", value="\n".join(changes_text), inline=False)

        embed.set_footer(text=f"ユーザーID: {session.user_id}")

        # ダイスロール結果のEmbedもあれば一緒に送信
        embeds_to_send = [embed]
        if action_result := ai_response.get("action_result"):
            if action_embed := create_action_result_embed(action_result):
                embeds_to_send.append(action_embed)

        await channel.send(embeds=embeds_to_send)

    @commands.Cog.listener("on_game_end")
    async def log_game_end(self, session: GameSession):
        """ゲーム終了のログを記録する"""
        channel = self.bot.get_channel(self.play_log_channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        user = self.bot.get_user(session.user_id) or await self.bot.fetch_user(session.user_id)
        if not user:
            # ユーザーが取得できない場合はログをスキップ
            return

        embed = discord.Embed(title="⏹️ ゲーム終了", description=f"**{session.character.name}** の冒険が終了しました。", color=discord.Color.red())
        embed.set_author(name=user.display_name, icon_url=user.display_avatar)
        embed.set_footer(text=f"ユーザーID: {session.user_id}")
        await channel.send(embed=embed)


async def setup(bot: "MyBot"):
    await bot.add_cog(LoggingCog(bot))