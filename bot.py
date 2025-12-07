import os
import discord
from discord import app_commands
import json
import random
import asyncio
from dotenv import load_dotenv

from character_manager import Character
from ai_handler import get_ai_generated_character
from game_state import save_game, load_game, save_legacy_log, load_legacy_log
from config import INITIAL_CHARACTER_DATA
import ui_components
import game_logic

# --- 初期設定 ---
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHAR_SHEET_CHANNEL_ID = int(os.getenv("CHAR_SHEET_CHANNEL_ID", 0))
SCENARIO_LOG_CHANNEL_ID = int(os.getenv("SCENARIO_LOG_CHANNEL_ID", 0))

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents) # Clientの定義
tree = discord.app_commands.CommandTree(client) # CommandTreeをClientに紐付け

# 複数プレイヤーのゲームセッションを管理する辞書
game_sessions = {}

@tree.command(name="create", description="あなただけのオリジナルキャラクターを作成して冒険を始めます。")
@app_commands.choices(world_setting=WORLD_SETTING_CHOICES)
async def create_character_command(interaction: discord.Interaction, world_setting: app_commands.Choice[str] = None):
    user_id = interaction.user.id
    if user_id in game_sessions:
        await interaction.response.send_message("既にゲームが進行中です。新しいキャラクターで始めるには、まず `/quit` で現在のゲームを終了してください。", ephemeral=True)
        return
    
    ws_value = world_setting.value if world_setting else "一般的なファンタジー世界"
    modal = ui_components.CharacterCreationModal(world_setting=ws_value)
    await interaction.response.send_modal(modal)

@client.event
async def on_ready():
    print(f'{client.user} としてDiscordにログインしました')
    # スラッシュコマンドをDiscordに同期
    await tree.sync()
    print("スラッシュコマンドを同期しました。")

WORLD_SETTING_CHOICES = [
    app_commands.Choice(name="一般的なファンタジー世界", value="一般的なファンタジー世界"),
    app_commands.Choice(name="クトゥルフ神話TRPG風", value="クトゥルフ神話TRPG風の現代"),
    app_commands.Choice(name="ソードワールド風", value="ソードワールド風の剣と魔法の世界"),
    app_commands.Choice(name="サイバーパンク", value="ネオン輝く巨大都市を舞台にしたサイバーパンク"),
    app_commands.Choice(name="スチームパンク", value="蒸気機関と歯車が支配するスチームパンク世界"),
]

@tree.command(name="start", description="新しい冒険を開始、または中断した冒険を再開します。")
@app_commands.choices(world_setting=WORLD_SETTING_CHOICES)
async def start_command(interaction: discord.Interaction, world_setting: app_commands.Choice[str] = None):
    user_id = interaction.user.id
    if user_id in game_sessions:
        await interaction.response.send_message("既にゲームが進行中です。リセットしてやり直す場合は `/reset` を入力してください。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    saved_character = load_game(user_id)
    if saved_character:
        game_sessions[user_id] = {
            'character': saved_character,
            'state': 'confirming_new_game',
            'legacy_log': load_legacy_log(user_id)
            # world_settingは保存されたものを使うので、ここでは設定しない
        }
        await interaction.followup.send("セーブデータが見つかりました。このチャンネルで続きから始めますか？ (`yes` / `no` と発言してください)", ephemeral=True)
    else:
        character = Character(INITIAL_CHARACTER_DATA)
        await game_logic.setup_and_start_game(interaction, character, is_new_game=True, world_setting=world_setting.value if world_setting else "一般的なファンタジー世界")

@tree.command(name="save", description="現在のゲームの進行状況を保存します。")
async def save_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in game_sessions and game_sessions[user_id]['state'] == 'playing':
        if save_game(user_id, game_sessions[user_id]['character']):
            await interaction.response.send_message("ゲームの進行状況を保存しました。", ephemeral=True)
        else:
            await interaction.response.send_message("エラーにより保存に失敗しました。", ephemeral=True)
    else:
        await interaction.response.send_message("保存できるゲームがありません。", ephemeral=True)

@tree.command(name="quit", description="現在のゲームセッションを中断します（進行状況は保存されません）。")
async def quit_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in game_sessions:
        del game_sessions[user_id]
        await interaction.response.send_message("ゲームセッションを終了しました。お疲れ様でした！")
    else:
        await interaction.response.send_message("終了するゲームがありません。", ephemeral=True)


@tree.command(name="start_random", description="AIが生成したランダムなキャラクターで新しい冒険を開始します。")
@app_commands.choices(world_setting=WORLD_SETTING_CHOICES)
async def start_random_command(interaction: discord.Interaction, world_setting: app_commands.Choice[str] = None):
    user_id = interaction.user.id
    if user_id in game_sessions:
        await interaction.response.send_message("既にゲームが進行中です。リセットしてやり直す場合は `/reset` を入力してください。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True) # 本人にだけ「考え中」と表示
    await interaction.followup.send(f"AIが「{world_setting.name}」の世界の新しいキャラクターを創造しています...", ephemeral=True) # 処理中であることを伝える

    # AIにキャラクターを生成させる
    ws_value = world_setting.value if world_setting else "一般的なファンタジー世界"
    random_character_data = get_ai_generated_character(ws_value)

    if random_character_data is None:
        await interaction.followup.send("申し訳ありません、キャラクターの創造に失敗しました。もう一度コマンドを実行してください。", ephemeral=True)
        return

    character = Character(random_character_data)
    await game_logic.setup_and_start_game(interaction, character, is_new_game=True, world_setting=ws_value)

@client.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author == client.user:
        return

    user_id = message.author.id

    # ゲームが進行中のプレイヤーからのメッセージを処理
    if user_id in game_sessions:
        try:
            # `!start`後の確認応答のみを処理する
            if game_sessions[user_id].get('state') == 'confirming_new_game':
                character = game_sessions[user_id]['character']
                if message.content.lower() in ['yes', 'y']:
                    game_sessions[user_id]['state'] = 'playing'
                    # 保存された世界観を使う
                    world_setting = game_sessions[user_id].get('world_setting', '一般的なファンタジー世界')
                    await game_logic.setup_and_start_game(message, character, is_new_game=False, world_setting=world_setting)

                elif message.content.lower() in ['no', 'n']:
                    # レガシーログは引き継ぐ
                    legacy_log = game_sessions[user_id].get('legacy_log')
                    # 新しい世界観を使う
                    world_setting = game_sessions[user_id].get('world_setting', '一般的なファンタジー世界')
                    new_character = Character(INITIAL_CHARACTER_DATA)
                    game_sessions[user_id] = {'character': new_character, 'state': 'playing', 'legacy_log': legacy_log}
                    await game_logic.setup_and_start_game(message, new_character, is_new_game=True, world_setting=world_setting)
                else:
                    await message.channel.send("`yes` または `no` でお答えください。")

        except (ValueError, KeyError):
            # 数字以外の入力や予期せぬエラーは無視（あるいはヘルプメッセージを出す）
            pass

# 起動時に各モジュールに必要なグローバル変数を設定
game_logic.game_sessions = game_sessions
ui_components.game_sessions = game_sessions
ui_components.setup_and_start_game = game_logic.setup_and_start_game
ui_components.create_character_embed = game_logic.create_character_embed
game_logic.client = client
game_logic.SCENARIO_LOG_CHANNEL_ID = SCENARIO_LOG_CHANNEL_ID
ui_components.client = client
ui_components.CHAR_SHEET_CHANNEL_ID = CHAR_SHEET_CHANNEL_ID

client.run(BOT_TOKEN)