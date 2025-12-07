import discord
from discord.ui import View, Button

# これらのインポートは型ヒントのために使用し、実際の呼び出しは bot.py から渡される関数を使う
from typing import TYPE_CHECKING, Callable, Coroutine
from character_manager import Character
if TYPE_CHECKING:
    from character_manager import Character

# --- グローバル変数/関数のプレースホルダー ---
# これらは bot.py から実行時に設定される
game_sessions = {}
client = None
CHAR_SHEET_CHANNEL_ID = 0
get_ai_response: Callable = None
build_action_result_prompt: Callable = None
setup_and_start_game: Callable = None
create_character_embed: Callable = None
start_game_turn: Callable = None

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
        character = game_sessions[user_id]['character']
        last_response = game_sessions[user_id]['last_response']
        player_action = self.action_input.value

        prompt = build_action_result_prompt(character.to_dict(), last_response['scenario'], player_action, world_setting=game_sessions[user_id].get("world_setting"))
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

        if user_id in game_sessions:
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
            # bot.pyから注入されたsetup_and_start_gameを呼び出す
            await setup_and_start_game(interaction, character, is_new_game=True, world_setting=self.world_setting)

        except Exception as e:
            print(f"キャラクター作成中にエラーが発生: {e}")
            await interaction.followup.send("キャラクターの作成に失敗しました。入力形式を確認してもう一度お試しください。", ephemeral=True)

class ChoiceView(View):
    """選択肢ボタンを管理するためのView"""
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたの冒険ではありません。", ephemeral=True)
            return False
        return True

    async def handle_choice(self, interaction: discord.Interaction, choice_num: int):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        character = game_sessions[self.user_id]['character']
        last_response = game_sessions[self.user_id]['last_response']

        update_key = f"choice{choice_num}"
        update_data = last_response["update"][update_key]
        character.apply_update(update_data)
        
        await interaction.response.send_message("--- キャラクターシートが更新されました ---", embed=game_logic.create_character_embed(character))

        await start_game_turn(interaction, character)

        if client.get_channel(CHAR_SHEET_CHANNEL_ID):
            char_channel = client.get_channel(CHAR_SHEET_CHANNEL_ID)
            if char_channel:
                await char_channel.send(f"`{character.name}` のキャラクターシートが更新されました。", embed=create_character_embed(character))

    @discord.ui.button(label="自由行動...", style=discord.ButtonStyle.success, row=2)
    async def custom_action_button(self, interaction: discord.Interaction, button: Button):
        modal = CustomActionModal()
        await interaction.response.send_modal(modal)