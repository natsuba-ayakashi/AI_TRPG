import discord
from typing import Optional
from core.data_loader import DataLoader

# 依存関係はbot.pyから注入される
game_manager = None
handle_item_use = None
item_data_loader = DataLoader("game_data")

class InventoryView(discord.ui.View):
    """
    インタラクティブなインベントリ管理View。
    ドロップダウンでのアイテム選択、詳細表示、使用、破棄の機能を持つ。
    """
    def __init__(self, user_id: int):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.user_id = user_id
        self.selected_item: Optional[str] = None

        session = game_manager.get_session(self.user_id)
        if not session:
            self.disable_all_items()
            return

        self.character = session.character
        self.update_components()

    def update_components(self):
        """Viewのコンポーネント（ドロップダウン、ボタン）を最新の状態に更新する。"""
        self.clear_items() # 既存のコンポーネントをクリア

        # アイテム選択ドロップダウンを追加
        self.add_item(ItemSelect(self))

        is_item_selected = self.selected_item is not None
        if is_item_selected:
            all_items_data = item_data_loader.get('items') or {}
            item_data = all_items_data.get(self.selected_item, {})
            item_type = item_data.get("type")

            if item_type == "consumable":
                self.add_item(UseButton(disabled=False))
            elif item_type == "equippable":
                is_equipped = self.selected_item in self.character.equipment.get("equipped_gear", [])
                if is_equipped:
                    self.add_item(UnequipButton(disabled=False))
                else:
                    self.add_item(EquipButton(disabled=False))

        self.add_item(DropButton(disabled=not is_item_selected))

    async def update_message(self, interaction: discord.Interaction):
        """インタラクションに応じてメッセージ（EmbedとView）を更新する。"""
        self.update_components()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def create_embed(self) -> discord.Embed:
        """現在の状態に基づいてインベントリのEmbedを作成する。"""
        inventory = self.character.equipment.get("items", []) or []
        equipped_gear = self.character.equipment.get("equipped_gear", []) or []
        title = f"🎒 {self.character.name}の所持品 ({len(inventory)}個)"
        
        if not inventory:
            return discord.Embed(title=title, description="何も持っていない。", color=discord.Color.light_grey())

        embed = discord.Embed(title=title, color=discord.Color.blue())
        
        if self.selected_item:
            all_items_data = item_data_loader.get('items') or {}
            item_data = all_items_data.get(self.selected_item, {})
            item_description = item_data.get("description", "詳細不明のアイテム。")
            
            # 装備状態を表示
            equipped_status = " (装備中)" if self.selected_item in equipped_gear else ""
            embed.description = f"**{self.selected_item}**{equipped_status}\n{item_description}"
        else:
            embed.description = "下のメニューからアイテムを選択してください。"

        embed.add_field(name="所持金", value=f"{self.character.money} G", inline=False)
        if equipped_gear:
            equipped_text = "\n".join([f"・ {item}" for item in equipped_gear])
            embed.add_field(name="装備中のアイテム", value=equipped_text, inline=False)
        return embed


class ItemSelect(discord.ui.Select):
    """所持アイテムを選択するためのドロップダウンメニュー。"""
    def __init__(self, parent_view: InventoryView):
        self.parent_view = parent_view
        inventory = self.parent_view.character.equipment.get("items", [])
        
        options = [discord.SelectOption(label=item) for item in set(inventory)] if inventory else [discord.SelectOption(label="アイテムなし", value="no_item")]

        super().__init__(placeholder="アイテムを選択...", min_values=1, max_values=1, options=options, disabled=not inventory)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "no_item":
            self.parent_view.selected_item = None
        else:
            self.parent_view.selected_item = self.values[0]
        await self.parent_view.update_message(interaction)


class UseButton(discord.ui.Button):
    """選択したアイテムを使用するボタン。"""
    def __init__(self, disabled: bool):
        super().__init__(label="使う", style=discord.ButtonStyle.success, emoji="🧪", disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        view: InventoryView = self.view
        if view.selected_item:
            # handle_item_use は thinking を含むので、ここでは defer しない
            await interaction.response.send_message(f"「{view.selected_item}」を使用します...", ephemeral=True)
            # game_logicの関数を呼び出す
            await handle_item_use(interaction, view.selected_item)
            # 使用後のインベントリを再表示
            view.selected_item = None # 選択状態をリセット
            await view.update_message(interaction)

class EquipButton(discord.ui.Button):
    """選択したアイテムを装備するボタン。"""
    def __init__(self, disabled: bool):
        super().__init__(label="装備する", style=discord.ButtonStyle.primary, emoji="🛡️", disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        view: InventoryView = self.view
        item_to_equip = view.selected_item
        if item_to_equip:
            equipped_gear = view.character.equipment.setdefault("equipped_gear", [])
            if item_to_equip not in equipped_gear:
                equipped_gear.append(item_to_equip)
                await view.update_message(interaction)
                await interaction.followup.send(f"「{item_to_equip}」を装備した！", ephemeral=True)
            else:
                await interaction.response.send_message("そのアイテムは既に装備しています。", ephemeral=True)

class UnequipButton(discord.ui.Button):
    """選択したアイテムを外すボタン。"""
    def __init__(self, disabled: bool):
        super().__init__(label="外す", style=discord.ButtonStyle.secondary, emoji="✋", disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        view: InventoryView = self.view
        item_to_unequip = view.selected_item
        if item_to_unequip:
            equipped_gear = view.character.equipment.get("equipped_gear", [])
            if item_to_unequip in equipped_gear:
                equipped_gear.remove(item_to_unequip)
                await view.update_message(interaction)
                await interaction.followup.send(f"「{item_to_unequip}」を外した。", ephemeral=True)
            else:
                await interaction.response.send_message("そのアイテムは装備していません。", ephemeral=True)


class DropButton(discord.ui.Button):
    """選択したアイテムを捨てるボタン。"""
    def __init__(self, disabled: bool):
        super().__init__(label="捨てる", style=discord.ButtonStyle.danger, emoji="🗑️", disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        view: InventoryView = self.view
        item_to_drop = view.selected_item
        if item_to_drop:
            inventory = view.character.equipment.get("items", [])
            if item_to_drop in inventory:
                # 装備中であれば、まず外す
                equipped_gear = view.character.equipment.get("equipped_gear", [])
                if item_to_drop in equipped_gear:
                    equipped_gear.remove(item_to_drop)

                inventory.remove(item_to_drop)
                view.selected_item = None # 選択状態をリセット
                await view.update_message(interaction)
                await interaction.followup.send(f"「{item_to_drop}」を捨てました。", ephemeral=True)