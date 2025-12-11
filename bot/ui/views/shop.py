import discord
from discord import ui
from typing import TYPE_CHECKING, List, Dict

from .utility import BaseOwnedView

if TYPE_CHECKING:
    from bot.client import MyBot
    from bot.cogs.game_commands import GameCommandsCog

class ShopView(BaseOwnedView):
    """ショップでアイテムを購入するためのView"""
    def __init__(self, user_id: int, bot: "MyBot", shop_name: str, items: List[Dict]):
        super().__init__(user_id=user_id, timeout=180)
        self.bot = bot
        self.shop_name = shop_name
        
        options = []
        for item in items:
            options.append(discord.SelectOption(
                label=f"{item['name']} ({item['price']} G)",
                value=item['name'],
                description=f"価格: {item['price']} G"
            ))
            
        self.select = ui.Select(placeholder="購入するアイテムを選択...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        item_name = self.select.values[0]
        # 処理に時間がかかる場合があるためdefer
        await interaction.response.defer()
        
        try:
            # GameServiceで購入処理を実行
            response_data = await self.bot.game_service.buy_item(self.user_id, item_name)
            
            # GameCommandsCogの共通ハンドラを使って結果を表示
            cog: "GameCommandsCog" = self.bot.get_cog("ゲーム管理")
            if cog:
                # ショップUIは使い終わったので無効化するか、メッセージを更新する
                # ここでは新しいメッセージとして結果を表示する
                await cog._handle_response(interaction, response_data, self.user_id, f"購入: {item_name}")
            else:
                await interaction.followup.send(f"「{item_name}」を購入しました。")
                
        except Exception as e:
            await interaction.followup.send(f"購入エラー: {e}", ephemeral=True)