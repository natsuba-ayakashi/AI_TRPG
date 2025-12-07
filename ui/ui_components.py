import discord
from discord.ui import View, Button

from core.game_state import load_character
from game_features.ai_handler import GM_PERSONALITIES
# これらのインポートは型ヒントのために使用し、実際の呼び出しは bot.py から渡される関数を使う
from typing import TYPE_CHECKING, Callable, Coroutine
from core.character_manager import Character
if TYPE_CHECKING:
    from core.character_manager import Character

# --- 依存関係のプレースホルダー ---
game_manager = None
client = None
CHAR_SHEET_CHANNEL_ID = 0
get_ai_response: Callable = None
build_action_result_prompt: Callable = None
setup_and_start_game: Callable = None
create_character_embed: Callable = None
start_game_turn: Callable = None
handle_skill_check: Callable = None # bot.pyから注入

class GameStartView(View):
    """ゲーム開始前の設定（GM選択など）を行うためのView"""
    def __init__(self, user_id: int, character: Character, world_setting: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.character = character
        self.world_setting = world_setting
        self.selected_gm = None

        # GM選択用のSelect Menuを作成
        gm_options = [
            discord.SelectOption(label=name.capitalize(), value=key, description=desc)
            for key, desc in GM_PERSONALITIES.items()
        ]
        gm_options.insert(0, discord.SelectOption(label="おまかせ（キャラクターの性格から自動選択）", value="random", default=True))

        self.gm_select = discord.ui.Select(placeholder="ゲームマスターの性格を選んでください", options=gm_options)
        self.gm_select.callback = self.on_gm_select
        self.add_item(self.gm_select)

    async def on_gm_select(self, interaction: discord.Interaction):
        # ユーザーが選択した値を保持
        self.selected_gm = self.gm_select.values[0]
        await interaction.response.defer() # 何も返さず、UIの状態だけ更新

    @discord.ui.button(label="この設定で冒険を始める", style=discord.ButtonStyle.success, row=1)
    async def start_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの冒険ではありません。", ephemeral=True)
            return

        await interaction.response.defer() # ボタンの応答を遅延
        # setup_and_start_game に選択されたGM情報を渡す
        await setup_and_start_game(interaction, self.character, is_new_game=True, world_setting=self.world_setting, gm_personality=self.selected_gm)
        self.stop()
        await interaction.message.edit(content="ゲームを開始します...", view=None)

class CharacterSelectView(View):
    """保存されたキャラクターからプレイするキャラクターを選択するためのView"""
    def __init__(self, user_id: int, character_names: list[str]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.selected_character_name = None

        options = [
            discord.SelectOption(label=name) for name in character_names
        ]
        self.character_select = discord.ui.Select(placeholder="冒険を再開するキャラクターを選んでください", options=options)
        self.character_select.callback = self.on_character_select
        self.add_item(self.character_select)

    async def on_character_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの選択ではありません。", ephemeral=True)
            return

        self.selected_character_name = self.character_select.values[0]
        
        # 選択されたキャラクターをロード
        character, world_setting = load_character(self.user_id, self.selected_character_name)
        if not character:
            await interaction.response.send_message("キャラクターの読み込みに失敗しました。", ephemeral=True)
            return

        await interaction.response.defer()
        await setup_and_start_game(interaction, character, is_new_game=False, world_setting=world_setting)
        self.stop()
        await interaction.message.edit(content=f"`{self.selected_character_name}` の冒険を再開します...", view=None)

class SkillCheckView(View):
    """技能判定のダイスロールを行うためのView"""
    def __init__(self, user_id: int, skill: str, difficulty: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.skill = skill
        self.difficulty = difficulty
        self.roll_button = discord.ui.Button(label=f"🎲 {skill}で判定！ (目標値: {difficulty})", style=discord.ButtonStyle.success)
        self.roll_button.callback = self.on_roll
        self.add_item(self.roll_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの判定ではありません。", ephemeral=True)
            return False
        return True

    async def on_roll(self, interaction: discord.Interaction):
        self.roll_button.disabled = True
        await interaction.message.edit(view=self)
        await handle_skill_check(interaction, self.skill, self.difficulty)

class CustomActionModal(discord.ui.Modal, title="自由行動"):
    """自由行動を入力するためのモーダル"""
    action_input = discord.ui.TextInput(
        label="あなたの行動",
        style=discord.TextStyle.long,
        placeholder="例：『辺りを見回して、何か隠されたものがないか探す』\n『衛兵に話しかけて、街の噂を聞き出す』など",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        user_id = interaction.user.id
        session = game_manager.get_session(user_id)
        if not session:
            await interaction.followup.send("エラー: ゲームセッションが見つかりません。", ephemeral=True)
            return
        character = session.character
        last_response = session.last_response
        player_action = self.action_input.value

        prompt = build_action_result_prompt(character.to_dict(), last_response['scenario'], player_action, world_setting=session.world_setting)
        result_response = get_ai_response(prompt)

        if result_response:
            update_data = result_response["update"]["choice1"]
            character.apply_update(update_data)
            
            await interaction.channel.send(f"【あなたの行動】: {player_action}\n\n{result_response['scenario']}")
            await interaction.channel.send("--- キャラクターシートが更新されました ---", embed=create_character_embed(character))
            await start_game_turn(interaction, character)
        else:
            await interaction.followup.send("申し訳ありません、AIがあなたの行動の結果を生成できませんでした。もう一度試してください。", ephemeral=True)

class CharacterCreationModal(discord.ui.Modal, title="キャラクター作成"):
    """プレイヤーが手動でキャラクターを作成するためのモーダル"""
    name = discord.ui.TextInput(label="キャラクター名", placeholder="例：アルト", required=True)
    gender = discord.ui.TextInput(label="性別", placeholder="例：男性, 女性", required=True)
    race = discord.ui.TextInput(label="種族", placeholder="例：人間, エルフ, ドワーフ", required=True)
    char_class = discord.ui.TextInput(label="クラス", placeholder="例：冒険者, 魔術師, 盗賊", required=True)
    appearance = discord.ui.TextInput(label="外見", placeholder="例：黒髪で鋭い目つきをした長身の男", required=True)
    background = discord.ui.TextInput(label="背景", style=discord.TextStyle.long, placeholder="例：辺境の村で育った孤児。失われた王家の血を引いているらしい。", required=True)
    traits_and_secrets = discord.ui.TextInput(
        label="特徴と秘密（カンマ区切り）",
        style=discord.TextStyle.long,
        placeholder="特徴：勇敢, 好奇心旺盛\n秘密：失われた王族, 古代語が読める",
        required=False
    )

    def __init__(self, world_setting: str):
        super().__init__(title="キャラクター作成")
        self.world_setting = world_setting

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = interaction.user.id

        if game_manager.has_session(user_id):
            await interaction.followup.send("既にゲームが進行中です。新しいキャラクターで始めるには、まず `/quit` で現在のゲームを終了してください。", ephemeral=True)
            return

        try:
            traits = []
            secrets = []
            for line in self.traits_and_secrets.value.split('\n'):
                if '特徴：' in line:
                    traits = [t.strip() for t in line.replace('特徴：', '').split(',')]
                elif '秘密：' in line:
                    secrets = [s.strip() for s in line.replace('秘密：', '').split(',')]

            new_char_data = {
                "name": self.name.value, "race": self.race.value, "class": self.char_class.value,
                "gender": self.gender.value, "appearance": self.appearance.value, "background": self.background.value,
                "stats": {"STR": 10, "DEX": 10, "INT": 10, "CHA": 10},
                "skills": {"交渉": 0, "探索": 0, "運動": 0},
                "san": 50, # デフォルトSAN値
                "traits": traits, "secrets": secrets,
                "equipment": {"weapon": "短剣", "armor": "旅人の服", "items": ["パン", "水袋"]},
                "history": []
            }

            character = Character(new_char_data)
            
            # GM選択を含むViewを提示
            embed = create_character_embed(character)
            view = GameStartView(user_id, character, self.world_setting)
            await interaction.followup.send("キャラクターが作成されました！\nGMの性格を選んで、冒険を始めましょう。", embed=embed, view=view, ephemeral=True)

        except Exception as e:
            print(f"キャラクター作成中にエラーが発生: {e}")
            await interaction.followup.send("キャラクターの作成に失敗しました。入力形式を確認してもう一度お試しください。", ephemeral=True)

class ChoiceView(View):
    """選択肢ボタンを管理するためのView"""
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.message = None # メッセージを後で参照するため

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの冒険ではありません。", ephemeral=True)
            return False
        return True

    async def handle_choice(self, interaction: discord.Interaction, choice_num: int):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        session = game_manager.get_session(self.user_id)
        if not session:
            await interaction.response.send_message("エラー: ゲームセッションが見つかりませんでした。", ephemeral=True)
            return
        character = session.character
        last_response = session.last_response

        update_key = f"choice{choice_num}"
        update_data = last_response["update"][update_key]
        character.apply_update(update_data)
        
        await interaction.response.send_message("--- キャラクターシートが更新されました ---", embed=create_character_embed(character))

        await start_game_turn(interaction, character)

        if client.get_channel(CHAR_SHEET_CHANNEL_ID):
            char_channel = client.get_channel(CHAR_SHEET_CHANNEL_ID)
            if char_channel:
                await char_channel.send(f"`{character.name}` のキャラクターシートが更新されました。", embed=create_character_embed(character))

    @discord.ui.button(label="自由行動...", style=discord.ButtonStyle.success, row=2)
    async def custom_action_button(self, interaction: discord.Interaction, button: Button):
        modal = CustomActionModal()
        await interaction.response.send_modal(modal) # モーダルを送信
        
        # モーダルがタイムアウトするのを待つ
        await modal.wait()
        # モーダルが閉じられた後、元のViewのタイムアウトをリセットして無効化を防ぐ
        if self.message:
            self.timeout = 300
            await self.message.edit(view=self)


class ShopView(View):
    """店のUIを管理するためのView"""
    def __init__(self, user_id: int, shop_data: dict, character: Character):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.shop_data = shop_data
        self.character = character
        self.message = None # メッセージを後で参照するため

        # 購入用セレクトメニュー
        buy_options = [
            discord.SelectOption(label=f"{item['name']} ({item['price']}G)", value=item['name'])
            for item in self.shop_data.get("items_for_sale", [])
        ]
        if buy_options:
            self.buy_select = discord.ui.Select(placeholder="商品を購入する...", options=buy_options)
            self.buy_select.callback = self.on_buy
            self.add_item(self.buy_select)

        # 売却用セレクトメニュー
        # 売却価格は定価の半額とする
        sell_options = [
            discord.SelectOption(label=f"{item} (売却: {self.get_item_price(item) // 2}G)", value=item)
            for item in self.character.equipment.get("items", [])
        ]
        if sell_options:
            self.sell_select = discord.ui.Select(placeholder="アイテムを売却する...", options=sell_options)
            self.sell_select.callback = self.on_sell
            self.add_item(self.sell_select)


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの店ではありません。", ephemeral=True)
            return False
        return True

    async def on_buy(self, interaction: discord.Interaction):
        """購入処理"""
        # 選択肢を無効化して多重実行を防ぐ
        self.buy_select.disabled = True
        if hasattr(self, 'sell_select'): self.sell_select.disabled = True
        await interaction.message.edit(view=self)

        selected_item_name = self.buy_select.values[0]
        item_to_buy = next((item for item in self.shop_data["items_for_sale"] if item["name"] == selected_item_name), None)

        if not item_to_buy:
            await interaction.response.send_message("その商品は見つかりませんでした。", ephemeral=True)
            return

        if self.character.money < item_to_buy["price"]:
            await interaction.response.send_message("所持金が足りません！", ephemeral=True)
            return

        # キャラクターデータを更新
        self.character.money -= item_to_buy["price"]
        self.character.equipment.setdefault("items", []).append(selected_item_name)

        await interaction.response.send_message(f"**{item_to_buy['name']}** を {item_to_buy['price']}G で購入しました。", ephemeral=True)
        await interaction.channel.send(f"--- {interaction.user.display_name} は {item_to_buy['name']} を手に入れた！ ---", embed=create_character_embed(self.character))
        self.stop()

    async def on_sell(self, interaction: discord.Interaction):
        """売却処理"""
        # 選択肢を無効化して多重実行を防ぐ
        self.sell_select.disabled = True
        if hasattr(self, 'buy_select'): self.buy_select.disabled = True
        await interaction.message.edit(view=self)

        selected_item_name = self.sell_select.values[0]
        inventory = self.character.equipment.get("items", [])

        if selected_item_name not in inventory:
            await interaction.response.send_message("そのアイテムは持っていません。", ephemeral=True)
            return

        # 売却価格を計算（定価の半額）
        sell_price = self.get_item_price(selected_item_name) // 2

        # キャラクターデータを更新
        self.character.money += sell_price
        inventory.remove(selected_item_name)

        await interaction.response.send_message(f"**{selected_item_name}** を {sell_price}G で売却しました。", ephemeral=True)
        await interaction.channel.send(f"--- {interaction.user.display_name} は {selected_item_name} を売却した！ ---", embed=create_character_embed(self.character))
        self.stop()

    def get_item_price(self, item_name: str) -> int:
        """商品リストからアイテムの定価を取得する。見つからなければ0を返す。"""
        item_info = next((item for item in self.shop_data.get("items_for_sale", []) if item["name"] == item_name), None)
        return item_info["price"] if item_info else 0