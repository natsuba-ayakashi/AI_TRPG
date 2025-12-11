import discord
from typing import List, Dict

class LogPaginatorView(discord.ui.View):
    """
    会話ログをページネーションで表示するためのView。
    """
    def __init__(self, interaction: discord.Interaction, history: List[Dict[str, str]], entries_per_page: int = 5):
        super().__init__(timeout=180.0)
        self.original_interaction = interaction
        self.history = history
        self.entries_per_page = entries_per_page
        self.current_page = 0
        # 履歴が空でも1ページとして扱う
        self.total_pages = max(1, (len(self.history) + self.entries_per_page - 1) // self.entries_per_page)
        self.message: discord.Message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("コマンドを実行した本人のみ操作できます。", ephemeral=True)
            return False
        return True

    def _create_embed(self) -> discord.Embed:
        """現在のページに基づいてEmbedを生成する。"""
        start_index = self.current_page * self.entries_per_page
        end_index = start_index + self.entries_per_page
        page_history = self.history[start_index:end_index]

        log_content = []
        for entry in page_history:
            role = "あなた" if entry["role"] == "user" else "GM"
            content = entry['content']
            # 1エントリが長すぎるとEmbedのdescription上限を超える可能性があるため、適度に丸める
            if len(content) > 700:
                content = content[:700] + "..."
            log_content.append(f"**{role}**: {content}")
        
        description = "\n\n".join(log_content) if log_content else "このページに表示するログはありません。"

        embed = discord.Embed(
            title=f"📜 会話ログ (ページ {self.current_page + 1}/{self.total_pages})",
            description=description,
            color=discord.Color.blurple()
        )
        return embed

    def _update_buttons(self):
        """ボタンの状態（有効/無効）を更新する。"""
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    @discord.ui.button(label="◀️ 前へ", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._create_embed(), view=self)

    @discord.ui.button(label="▶️ 次へ", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._create_embed(), view=self)

    async def start(self, ephemeral: bool = True):
        """最初のページを送信してページネーションを開始する。"""
        self._update_buttons()
        embed = self._create_embed()
        await self.original_interaction.followup.send(embed=embed, view=self, ephemeral=ephemeral)