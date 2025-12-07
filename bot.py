import os
import discord
from discord import app_commands
import json
import random
import asyncio
from dotenv import load_dotenv

from core.data_loader import DataLoader
from core.character_manager import Character, get_nested_attr
from core.game_manager import GameManager
from core.game_state import save_game, list_characters, delete_character, save_legacy_log, load_legacy_log
from game_features.achievements import ACHIEVEMENTS
from config import INITIAL_CHARACTER_DATA
from game_features import bgm_manager
from ui import ui_components
from ui import inventory_view
from errors import GameError, FileOperationError, CharacterNotFoundError, AIConnectionError
from game_features import game_logic

# --- 初期設定 ---
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHAR_SHEET_CHANNEL_ID = int(os.getenv("CHAR_SHEET_CHANNEL_ID", 0))
SCENARIO_LOG_CHANNEL_ID = int(os.getenv("SCENARIO_LOG_CHANNEL_ID", 0))
PLAY_LOG_CHANNEL_ID = int(os.getenv("PLAY_LOG_CHANNEL_ID", 0))

# --- データ読み込み ---
world_data_loader = DataLoader("game_data/worlds")
WORLD_SETTING_CHOICES = [app_commands.Choice(name=data['name'], value=key) for key, data in world_data_loader.get_all().items()]

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True # ボイスチャットの権限
client = discord.Client(intents=intents) # Clientの定義
tree = discord.app_commands.CommandTree(client) # CommandTreeをClientに紐付け

# ゲームセッションを管理するGameManagerのインスタンス
game_manager = GameManager()

def setup_dependencies():
    """各モジュールに必要な依存関係を設定します。"""
    # 起動時に各モジュールに必要なグローバル変数を設定
    game_logic.game_manager = game_manager
    ui_components.game_manager = game_manager
    ui_components.setup_and_start_game = game_logic.setup_and_start_game
    ui_components.create_character_embed = game_logic.create_character_embed
    game_logic.client = client
    game_logic.SCENARIO_LOG_CHANNEL_ID = SCENARIO_LOG_CHANNEL_ID
    game_logic.PLAY_LOG_CHANNEL_ID = PLAY_LOG_CHANNEL_ID
    game_logic.build_item_use_prompt = game_features.ai_handler.build_item_use_prompt
    game_logic.build_check_result_prompt = game_features.ai_handler.build_check_result_prompt
    ui_components.client = client
    ui_components.CHAR_SHEET_CHANNEL_ID = CHAR_SHEET_CHANNEL_ID
    ui_components.start_game_turn = game_logic.start_game_turn
    ui_components.build_action_result_prompt = game_features.ai_handler.build_action_result_prompt
    ui_components.handle_skill_check = game_logic.handle_skill_check
    inventory_view.game_manager = game_manager
    # game_logic.handle_item_use をインベントリViewに渡す
    inventory_view.handle_item_use = game_logic.handle_item_use
    bgm_manager.client = client

@client.event
async def on_ready():
    print(f'{client.user} としてDiscordにログインしました')
    setup_dependencies()
    print("モジュールの依存関係を設定しました。")
    # スラッシュコマンドをDiscordに同期
    await tree.sync()
    print("スラッシュコマンドを同期しました。")

@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """ボイスチャンネルの状態が変化したときに呼び出されるイベント"""
    # ボット自身の状態変化は無視
    if member.id == client.user.id:
        return

    voice_client = member.guild.voice_client
    # ボットがボイスチャンネルに接続していない場合は何もしない
    if not voice_client:
        return

    # ボットがいるチャンネルのメンバーがボット自身だけになった場合
    if len(voice_client.channel.members) == 1 and voice_client.channel.members[0] == client.user:
        # 60秒待ってから再度チェック
        await asyncio.sleep(60)
        # 再度チェックしてもボットだけの場合
        if len(voice_client.channel.members) == 1:
            print("ボイスチャンネルに誰もいなくなったため、自動的に退出します。")
            await bgm_manager.stop_bgm(member.guild)
            await voice_client.disconnect()

@tree.command(name="create", description="あなただけのオリジナルキャラクターを作成して冒険を始めます。")
@app_commands.choices(world_setting=WORLD_SETTING_CHOICES)
@app_commands.describe(custom_world_setting="世界観を自由に記述します。こちらが優先されます。")
async def create_character_command(interaction: discord.Interaction, world_setting: app_commands.Choice[str] = None, custom_world_setting: str = None):
    user_id = interaction.user.id
    async with game_manager.get_lock(user_id):
        if game_manager.has_session(user_id):
            await interaction.response.send_message("既にゲームが進行中です。新しいキャラクターで始めるには、まず `/quit` で現在のゲームを終了してください。", ephemeral=True)
            return
        
        # カスタム設定が入力されていればそれを使い、なければ選択肢を使う
        # 選択された場合はキー(fantasyなど)、カスタム入力はそのまま文字列として渡す
        ws_value = custom_world_setting or (world_setting.value if world_setting else "fantasy")
        # world_setting.valueは 'fantasy' のようなキーになる

        modal = ui_components.CharacterCreationModal(world_setting=ws_value)
        await interaction.response.send_modal(modal)

@tree.command(name="start", description="新しい冒険を開始、または中断した冒険を再開します。")
@app_commands.choices(world_setting=WORLD_SETTING_CHOICES)
@app_commands.describe(custom_world_setting="世界観を自由に記述します。こちらが優先されます。")
async def start_command(interaction: discord.Interaction, world_setting: app_commands.Choice[str] = None, custom_world_setting: str = None):
    user_id = interaction.user.id
    async with game_manager.get_lock(user_id):
        if game_manager.has_session(user_id):
            await interaction.response.send_message("既にゲームが進行中です。リセットしてやり直す場合は `/reset` を入力してください。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        saved_characters = list_characters(user_id)
        if saved_characters:
            # 保存されたキャラクターが1人以上いる場合、選択肢を提示
            view = ui_components.CharacterSelectView(user_id, saved_characters)
            await interaction.followup.send("どのキャラクターで冒険を再開しますか？", view=view, ephemeral=True)
        else:
            # セーブデータがない場合、新しいキャラクターで開始
            # この部分は /create コマンドに役割を統合しても良いかもしれません
            from config import INITIAL_CHARACTER_DATA
            # カスタム設定が入力されていればそれを使い、なければ選択肢を使う
            ws_value = custom_world_setting or (world_setting.value if world_setting else "fantasy")
            character = Character(INITIAL_CHARACTER_DATA)
            view = ui_components.GameStartView(user_id, character, ws_value)
            await interaction.followup.send("新しいキャラクターで冒険を始めます。\nGMの性格を選んでください。", embed=game_logic.create_character_embed(character), view=view, ephemeral=True)

@tree.command(name="save", description="現在のゲームの進行状況を保存します。")
async def save_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    async with game_manager.get_lock(user_id):
        session = game_manager.get_session(user_id)
        if session and session.state == 'playing':
            save_game(user_id, session.character, session.world_setting)
            await interaction.response.send_message("ゲームの進行状況を保存しました。", ephemeral=True)
        else:
            await interaction.response.send_message("保存できる進行中のゲームがありません。", ephemeral=True)

@tree.command(name="quit", description="現在のゲームセッションを中断します（進行状況は保存されません）。")
async def quit_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    async with game_manager.get_lock(user_id):
        session = game_manager.get_session(user_id)
        if session:
            thread_id = session.thread_id
            game_manager.delete_session(user_id)
            await interaction.response.send_message("ゲームセッションを終了しました。お疲れ様でした！", ephemeral=True)
            
            if thread_id != 0:
                thread = client.get_channel(thread_id) or await client.fetch_channel(thread_id)
                if thread and isinstance(thread, discord.Thread):
                    await thread.send("プレイヤーがゲームを中断しました。このスレッドはアーカイブされます。")
                    await thread.edit(archived=True)
        else:
            await interaction.response.send_message("終了するゲームがありません。", ephemeral=True)

@tree.command(name="join", description="Botをあなたのいるボイスチャンネルに参加させます。")
async def join_command(interaction: discord.Interaction):
    voice_state = interaction.user.voice
    if voice_state is None:
        await interaction.response.send_message("先にボイスチャンネルに参加してください。", ephemeral=True)
        return

    voice_channel = voice_state.channel
    if interaction.guild.voice_client is not None:
        # 既に他のチャンネルにいる場合は移動
        await interaction.guild.voice_client.move_to(voice_channel)
    else:
        # どこにもいない場合は接続
        await voice_channel.connect()
    
    await interaction.response.send_message(f"`{voice_channel.name}` に参加しました。", ephemeral=True)

@tree.command(name="leave", description="Botをボイスチャンネルから退出させます。")
async def leave_command(interaction: discord.Interaction):
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("Botはボイスチャンネルに参加していません。", ephemeral=True)
        return
    await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("ボイスチャンネルから退出しました。", ephemeral=True)

@tree.command(name="volume", description="BGMの音量を調整します（0-200%）。")
@app_commands.describe(level="音量レベル (0-200)")
async def volume_command(interaction: discord.Interaction, level: app_commands.Range[int, 0, 200]):
    success, message = await bgm_manager.set_volume(interaction.guild, level)
    if success:
        await interaction.response.send_message(message, ephemeral=True)
    else:
        await interaction.response.send_message(f"エラー: {message}", ephemeral=True)

@tree.command(name="pause", description="BGMを一時停止します。")
async def pause_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return
    success, message = await bgm_manager.pause_bgm(interaction.guild)
    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="resume", description="一時停止中のBGMを再生します。")
async def resume_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return
    success, message = await bgm_manager.resume_bgm(interaction.guild)
    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="stop", description="BGMの再生を停止します。")
async def stop_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return
    success, message = await bgm_manager.stop_bgm(interaction.guild)

    # BGM停止に成功した場合、ボイスチャンネルから退出する
    if success and interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        message += "\nボイスチャンネルから退出しました。"

    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="nowplaying", description="現在再生中のBGM情報を表示します。")
async def nowplaying_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    status = bgm_manager.get_bgm_status(interaction.guild)

    if not status:
        await interaction.response.send_message("Botはボイスチャンネルに参加していません。", ephemeral=True)
        return

    embed = discord.Embed(title="🎵 現在のBGM情報", color=discord.Color.blue())

    if status["is_playing"] or status["is_paused"]:
        song_name = status["keyword"].capitalize() if status["keyword"] else "不明な曲"
        state = "再生中" if status["is_playing"] else "一時停止中"
        embed.add_field(name="曲名", value=song_name, inline=False)
        embed.add_field(name="状態", value=state, inline=True)
        embed.add_field(name="音量", value=f"{status['volume']}%", inline=True)
    else:
        embed.description = "現在再生中の曲はありません。"

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="play_bgm", description="指定したBGMを再生します。")
@app_commands.choices(keyword=[
    app_commands.Choice(name=key.capitalize(), value=key) for key in bgm_manager.BGM_MAP.keys()
])
async def play_bgm_command(interaction: discord.Interaction, keyword: app_commands.Choice[str]):
    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    success, message = await bgm_manager.force_play(interaction.guild, keyword.value)
    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="start_random", description="AIが生成したランダムなキャラクターで新しい冒険を開始します。")
@app_commands.choices(world_setting=WORLD_SETTING_CHOICES)
@app_commands.describe(custom_world_setting="世界観を自由に記述します。こちらが優先されます。")
async def start_random_command(interaction: discord.Interaction, world_setting: app_commands.Choice[str] = None, custom_world_setting: str = None):
    user_id = interaction.user.id
    async with game_manager.get_lock(user_id):
        if game_manager.has_session(user_id):
            await interaction.response.send_message("既にゲームが進行中です。リセットしてやり直す場合は `/reset` を入力してください。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        # カスタム設定が入力されていればそれを使い、なければ選択肢を使う
        ws_key = custom_world_setting or (world_setting.value if world_setting else "fantasy")
        # ws_keyがYAMLのキー(fantasyなど)であれば、その名前を取得。カスタム入力ならそのまま表示。
        world_data = world_data_loader.get(ws_key)
        ws_name = world_data['name'] if world_data else ws_key
        await interaction.followup.send(f"AIが「{ws_name}」の世界の新しいキャラクターを創造しています...", ephemeral=True)

        from game_features.ai_handler import get_ai_generated_character
        random_character_data = get_ai_generated_character(world_setting_key=ws_key)

        if random_character_data is None:
            await interaction.followup.send("申し訳ありません、キャラクターの創造に失敗しました。もう一度コマンドを実行してください。", ephemeral=True)
            return

        character = Character(random_character_data)
        
        embed = game_logic.create_character_embed(character)
        view = ui_components.GameStartView(user_id, character, ws_key)
        await interaction.followup.send("キャラクターが創造されました！\nGMの性格を選んで、冒険を始めましょう。", embed=embed, view=view, ephemeral=True)

async def item_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """/use_itemコマンドのオートコンプリートリストを作成する"""
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        return []
    
    # equipment['items'] が存在するか確認
    items = get_nested_attr(session.character.equipment, 'items', [])
    if not items:
        return []

    return [
        app_commands.Choice(name=item, value=item)
        for item in items if current.lower() in item.lower()
    ]

@tree.command(name="use_item", description="インベントリのアイテムを使用します。")
@app_commands.autocomplete(item=item_autocomplete)
async def use_item_command(interaction: discord.Interaction, item: str):
    await game_logic.handle_item_use(interaction, item)

@tree.command(name="inventory", description="所持品を確認・管理します。")
async def inventory_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        await interaction.response.send_message("ゲームを開始していません。", ephemeral=True)
        return

    view = inventory_view.InventoryView(user_id)
    await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)

async def character_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """/delete_characterコマンドのオートコンプリートリストを作成する"""
    user_id = interaction.user.id
    characters = list_characters(user_id)
    return [
        app_commands.Choice(name=name, value=name)
        for name in characters if current.lower() in name.lower()
    ]

@tree.command(name="delete_character", description="保存されているキャラクターを削除します。")
@app_commands.autocomplete(character_name=character_autocomplete)
async def delete_character_command(interaction: discord.Interaction, character_name: str):
    delete_character(interaction.user.id, character_name)
    await interaction.response.send_message(f"キャラクター「{character_name}」のデータを削除しました。", ephemeral=True)

@tree.command(name="achievements", description="現在のキャラクターの実績達成状況を表示します。")
async def achievements_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        await interaction.response.send_message("実績を表示するゲームセッションがありません。", ephemeral=True)
        return

    character = session.character
    unlocked_ids = set(character.achievements)

    embed = discord.Embed(
        title=f"{character.name}の実績",
        description=f"達成率: {len(unlocked_ids)} / {len(ACHIEVEMENTS)}",
        color=discord.Color.dark_gold()
    )

    for achievement_id, details in ACHIEVEMENTS.items():
        if achievement_id in unlocked_ids:
            embed.add_field(name=f"🏆 {details['name']}", value=details['description'], inline=False)
        elif not details.get("hidden", False):
            embed.add_field(name=f"🔒 {details['name']}", value=details['description'], inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="set_image", description="キャラクターのカスタム画像を設定します。")
@app_commands.describe(image="キャラクターとして設定する画像ファイル")
async def set_image_command(interaction: discord.Interaction, image: discord.Attachment):
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        await interaction.response.send_message("画像を登録するゲームセッションがありません。", ephemeral=True)
        return

    # 画像が実際に画像ファイルか簡易チェック
    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.response.send_message("画像ファイル（PNG, JPGなど）をアップロードしてください。", ephemeral=True)
        return

    session.character.custom_image_url = image.url
    await interaction.response.send_message("キャラクター画像を設定しました！", embed=game_logic.create_character_embed(session.character), ephemeral=True)

@tree.command(name="set_difficulty", description="ゲームの難易度を手動で設定します（自動調整が無効になります）。")
@app_commands.describe(level="難易度レベル (1-10)")
async def set_difficulty_command(interaction: discord.Interaction, level: app_commands.Range[int, 1, 10]):
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        await interaction.response.send_message("難易度を設定するゲームセッションがありません。", ephemeral=True)
        return

    session.difficulty_level = level
    session.is_difficulty_manual = True
    await interaction.response.send_message(f"ゲームの難易度をレベル **{level}** に設定しました。\n今後の難易度は自動調整されません。", ephemeral=True)

@tree.command(name="reset_difficulty", description="ゲームの難易度を進行度に応じた自動調整に戻します。")
async def reset_difficulty_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        await interaction.response.send_message("難易度をリセットするゲームセッションがありません。", ephemeral=True)
        return

    session.is_difficulty_manual = False
    # 次のターンから自動計算が再開される
    await interaction.response.send_message("ゲームの難易度を自動調整に戻しました。", ephemeral=True)

# --- グローバルエラーハンドラ ---
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """
    スラッシュコマンドの実行中に発生したエラーをここで一元的に処理します。
    """
    # エラーの根本原因を取得
    original_error = getattr(error, 'original', error)
    
    # 開発者向けのログ出力
    logging.exception(f"コマンド '{interaction.command.name}' の実行中にエラーが発生しました: {original_error}")

    # カスタム例外に応じたユーザーへのメッセージ
    user_message = "予期せぬエラーが発生しました。しばらくしてからもう一度お試しください。" # デフォルトメッセージ

    if isinstance(original_error, FileOperationError):
        user_message = f"ファイルの処理中にエラーが発生しました。\n詳細: {original_error}"
    elif isinstance(original_error, CharacterNotFoundError):
        user_message = f"指定されたデータが見つかりませんでした。\n詳細: {original_error}"
    elif isinstance(original_error, AIConnectionError):
        user_message = f"AIとの通信に失敗しました。時間をおいて再度試してください。\n詳細: {original_error}"
    elif isinstance(original_error, GameError):
        # その他のゲーム関連エラー
        user_message = f"エラーが発生しました: {original_error}"
    elif isinstance(error, app_commands.CommandOnCooldown):
        user_message = f"コマンドはクールダウン中です。{error.retry_after:.2f}秒後にもう一度試してください。"
    elif isinstance(error, app_commands.MissingPermissions):
        user_message = "コマンドの実行に必要な権限がありません。"

    # ephemeral=True をつけて、エラーメッセージが本人にしか見えないようにする
    if interaction.response.is_done():
        await interaction.followup.send(user_message, ephemeral=True)
    else:
        await interaction.response.send_message(user_message, ephemeral=True)


client.run(BOT_TOKEN)