import discord
import random
import asyncio

from core.character_manager import Character, get_nested_attr
from game_features.ai_handler import build_prompt, get_ai_response, generate_image_from_prompt, build_check_result_prompt
from game_features import bgm_manager
from game_features.achievements import ACHIEVEMENTS, check_all_achievements
from ui.ui_components import ChoiceView, ShopView, SkillCheckView
from core.game_state import save_legacy_log, load_legacy_log
# --- 依存関係のプレースホルダー ---
game_manager = None
client = None
SCENARIO_LOG_CHANNEL_ID = 0
build_item_use_prompt = None # bot.pyから注入
build_check_result_prompt = None # bot.pyから注入
PLAY_LOG_CHANNEL_ID = 0

def select_gm_personality(character: Character):
    """キャラクターのGM親和性スコアに基づいて、GM人格を確率的に選択する"""
    affinities = character.gm_affinity
    personalities = list(affinities.keys())
    weights = list(affinities.values())
    return random.choices(personalities, weights=weights, k=1)[0]

def create_character_embed(character: Character) -> discord.Embed:
    """キャラクターオブジェクトからEmbedを生成する"""
    char_data = character.to_dict()
    embed = discord.Embed(
        title=f"キャラクターシート: {char_data['name']}",
        description=f"**{char_data.get('appearance', '特徴のない容姿')}**\n{char_data.get('gender', '不明')} / {char_data['race']} / {char_data['class']}",
        color=discord.Color.green()
    )
    # カスタム画像が設定されていればサムネイルに設定
    if char_data.get("custom_image_url"):
        embed.set_thumbnail(url=char_data["custom_image_url"])

    money = char_data.get('money', 0)
    san_value = char_data.get('san', 'N/A')
    stats_text = " / ".join([f"{key}:{val}" for key, val in char_data['stats'].items()])
    embed.add_field(name=f"所持金: {money}G", value=f"**SAN:** {san_value} | {stats_text}", inline=False)
    
    if char_data['traits']:
        embed.add_field(name="特徴", value=", ".join(char_data['traits']), inline=True)
    
    if char_data['skills']:
        skills_text = " / ".join([f"{key}:{val:+}" for key, val in char_data['skills'].items()])
        embed.add_field(name="技能", value=skills_text, inline=True)
    if char_data['secrets']:
        embed.add_field(name="秘密", value=", ".join(char_data['secrets']), inline=True)

    # 経歴（history）の表示を動的に変更
    history_text = "冒険は始まったばかりだ..."
    field_name = "最近の出来事"
    if char_data['history']:
        history_list = char_data['history']
        history_count = len(history_list)
        field_name = f"最近の出来事 (全{history_count}件)"

        # 経歴が5件以下の場合はすべて表示し、それより多い場合は直近5件を表示する
        display_count = min(history_count, 5)
        
        history_text = "\n".join([f"- {h}" for h in history_list[-display_count:]])
    embed.add_field(name=field_name, value=history_text, inline=False)
    
    # 実績の表示
    achievements = char_data.get("achievements", [])
    if achievements:
        unlocked_count = len(achievements)
        latest_achievement_name = ACHIEVEMENTS.get(achievements[-1], {}).get("name", "不明な実績")
        achievement_text = f"最近の達成: **{latest_achievement_name}**"
        embed.add_field(name=f"実績 ({unlocked_count} / {len(ACHIEVEMENTS)})", value=achievement_text, inline=False)

    return embed

def create_scenario_embed(ai_response, gm_key, image_url=None) -> discord.Embed:
    """AIの応答からシナリオEmbedを生成する"""
    scenario_text = ai_response.get("scenario", "シナリオの生成に失敗しました。")
    embed = discord.Embed(title="新たな場面", description=scenario_text, color=discord.Color.blue())
    if image_url:
        embed.set_image(url=image_url)
    choices = ai_response.get("choices", [])
    choice_text = "\n".join([f"**{i+1}:** {choice}" for i, choice in enumerate(choices)])
    embed.add_field(name="どうしますか？", value=choice_text if choice_text else "選択肢がありません。", inline=False)
    embed.set_footer(text=f"今回のGM: {gm_key}")
    return embed

async def setup_and_start_game(interaction, character: Character, is_new_game: bool, world_setting: str, gm_personality: str = None):
    """スレッドを作成し、新しいゲームセッションを開始する共通関数"""
    user_id = interaction.user.id
    thread_name_prefix = "⚔️"
    thread_name = f"{thread_name_prefix} {character.name}の冒険"
    if not is_new_game:
        thread_name += " (再開)"

    thread = await interaction.channel.create_thread(name=thread_name, auto_archive_duration=1440)
    await interaction.followup.send(f"{character.name}の冒険が始まります！ {thread.mention} で物語が進行します。", ephemeral=True)

    legacy_log = load_legacy_log(user_id)
    session = game_manager.create_session(user_id, character, world_setting, thread.id, legacy_log)
    if gm_personality and gm_personality != "random":
        session.gm_personality = gm_personality

    await thread.send(f"ようこそ、{interaction.user.mention} さん！ここがあなたの冒険の舞台です。", embed=create_character_embed(character))
    if legacy_log:
        await thread.send(f"過去の英雄「{legacy_log.get('hero_name')}」の伝説が、この世界に息づいています...")
    
    interaction.channel = thread
    await start_game_turn(interaction, character)

async def handle_item_use(interaction: discord.Interaction, item_name: str):
    """アイテム使用コマンドのロジックを処理する"""
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session or not session.last_response:
        await interaction.response.send_message("アイテムを使用できる状況ではありません。", ephemeral=True)
        return

    character = session.character
    # equipment['items'] が存在するか確認
    inventory = get_nested_attr(character.equipment, 'items', [])
    if item_name not in inventory:
        await interaction.response.send_message(f"あなたは「{item_name}」を持っていません。", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    prompt = build_item_use_prompt(
        character.to_dict(),
        session.last_response['scenario'],
        item_name,
        session.world_setting
    )
    
    thinking_message = await interaction.channel.send(f"あなたは「{item_name}」を使った...！")
    ai_response = get_ai_response(prompt)

    if ai_response and ai_response.get("scenario"):
        await thinking_message.edit(content=f"【アイテム使用】: {item_name}\n\n{ai_response['scenario']}")
        # アイテム使用によるキャラクター更新はAIのレスポンスに含まれる想定
        # 次のターンに進む前に、選択肢と更新データをセッションに保存
        session.last_response = ai_response
        await start_game_turn(interaction, character, from_item_use=True)
    else:
        await thinking_message.edit(content="しかし、何も起こらなかった...")
        await interaction.followup.send("申し訳ありません、AIが応答しませんでした。もう一度お試しください。", ephemeral=True)

async def handle_skill_check(interaction: discord.Interaction, skill: str, difficulty: int):
    """技能判定のダイスロールと結果処理を行う"""
    await interaction.response.defer()
    user_id = interaction.user.id
    session = game_manager.get_session(user_id)
    if not session:
        await interaction.followup.send("エラー: ゲームセッションが見つかりません。", ephemeral=True)
        return

    character = session.character
    modifier = character.skills.get(skill, 0)
    
    # 2D6ロール
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    dice_roll = dice1 + dice2
    total = dice_roll + modifier
    success = total >= difficulty

    result_text = "成功" if success else "失敗"
    roll_embed = discord.Embed(
        title=f"【{skill}】技能判定",
        description=f"ダイスロール: {dice_roll} ( {dice1} + {dice2} )\n技能値: {modifier:+}\n**合計: {total}** (目標値: {difficulty})",
        color=discord.Color.green() if success else discord.Color.red()
    )
    roll_embed.set_footer(text=f"結果: {result_text}")
    await interaction.channel.send(embed=roll_embed)

    roll_result = {
        "dice_roll": dice_roll, "modifier": modifier, "total": total, "success": success
    }

    # AIに結果を渡して次のシナリオを生成させる
    prompt = build_check_result_prompt(character.to_dict(), session.last_response['scenario'], {"skill": skill, "difficulty": difficulty}, roll_result, session.world_setting)
    
    # start_game_turnに処理を移譲
    await start_game_turn(interaction, character, from_skill_check=True, external_prompt=prompt)

async def check_and_notify_achievements(channel: discord.TextChannel, character: Character, session):
    """実績の達成をチェックし、アンロックされていれば通知する"""
    newly_unlocked = check_all_achievements(character, session)
    for achievement_id in newly_unlocked:
        character.achievements.append(achievement_id)
        details = ACHIEVEMENTS[achievement_id]
        
        embed = discord.Embed(
            title="🏆 実績解除！",
            description=f"**{details['name']}**\n{details['description']}",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://emojipedia-us.s3.amazonaws.com/source/skype/289/trophy_1f3c6.png")
        await channel.send(embed=embed)

async def post_play_log(embed: discord.Embed, user: discord.User):
    """プレイログを指定されたチャンネルに投稿する"""
    if not PLAY_LOG_CHANNEL_ID:
        return

    log_channel = client.get_channel(PLAY_LOG_CHANNEL_ID)
    if not log_channel:
        print(f"エラー: プレイログチャンネル(ID: {PLAY_LOG_CHANNEL_ID})が見つかりません。")
        return

    # Embedのフッターにプレイヤー情報を追加
    embed.set_footer(text=f"プレイヤー: {user.display_name}", icon_url=user.display_avatar.url)
    await log_channel.send(embed=embed)

async def start_game_turn(message, character: Character, from_item_use: bool = False, from_skill_check: bool = False, external_prompt: str = None):
    """ゲームの1ターンを実行し、結果をDiscordに送信する"""
    user_id = message.author.id
    session = game_manager.get_session(user_id)
    if not session:
        await message.channel.send("エラー: ゲームセッションが見つかりませんでした。")
        return
    
    # 進行度に応じて難易度レベルを更新 (手動設定されていない場合のみ)
    if not session.is_difficulty_manual:
        session.difficulty_level = 1 + (len(character.history) // 5)

    gm_key = session.gm_personality or select_gm_personality(character)

    if from_item_use:
        # アイテム使用からの呼び出しの場合、AI応答は既に取得済み
        ai_response = session.last_response
    elif from_skill_check:
        # 技能判定結果からの呼び出しの場合、新しいプロンプトでAI応答を取得
        prompt = external_prompt
        thinking_message = await message.channel.send("--- GMが判定結果を物語に反映させています... 📜 ---")
        ai_response = get_ai_response(prompt)
    else:
        # 通常のターン進行
        await message.channel.send(f"--- 今回のGM: {gm_key} ---")
        prompt = build_prompt(character.to_dict(), legacy_log=session.legacy_log, gm_personality_key=gm_key, world_setting=session.world_setting, difficulty_level=session.difficulty_level)
        thinking_message = await message.channel.send("--- AIが物語を紡いでいます... 📜 ---")
        ai_response = get_ai_response(prompt)

    # thinking_messageが定義されている場合のみ操作
    if 'thinking_message' in locals() and thinking_message:
        if ai_response is None:
            await thinking_message.edit(content="申し訳ありません、AIが応答に失敗しました。少し時間をおいて、もう一度選択肢を選び直してください。")
            return

        new_chapter_title = ai_response.get("chapter_title")
        thread = message.channel
        if new_chapter_title and isinstance(thread, discord.Thread) and thread.name != new_chapter_title:
            try:
                await thinking_message.edit(content=f"--- 物語は新たな章へ: **{new_chapter_title}** ---")
                await thread.edit(name=new_chapter_title)
            except discord.HTTPException as e:
                print(f"スレッド名の変更中にエラーが発生しました: {e}")
        else:
            await thinking_message.delete()
    elif ai_response is None:
        # thinking_message がない場合（アイテム使用時など）でAIの応答がない場合
        await message.channel.send("申し訳ありません、AIが応答に失敗しました。")
        return

    if ai_response.get("game_clear") or ai_response.get("game_over"):
        is_clear = ai_response.get("game_clear", False)
        end_message = "--- 見事、物語を完結させました！ ---" if is_clear else "--- 物語は終わりを告げた ---"
        final_embed = discord.Embed(title="物語の結末", description=ai_response.get("scenario"), color=discord.Color.gold())
        final_embed.set_footer(text=end_message)
        await message.channel.send(embed=final_embed) # thinking_messageがないので直接送信

        if is_clear and "game_clear" not in character.achievements:
            character.achievements.append("game_clear")
            # TODO: ゲームクリア実績の通知

        user_id = message.author.id
        if is_clear:
            save_legacy_log(user_id, character)

        if SCENARIO_LOG_CHANNEL_ID and client.get_channel(SCENARIO_LOG_CHANNEL_ID):
            log_channel = client.get_channel(SCENARIO_LOG_CHANNEL_ID)
            await log_channel.send(f"`{character.name}` の冒険が結末を迎えました。", embed=final_embed)
        
        # ゲーム終了時にBGMを停止し、VCから退出
        guild = message.channel.guild
        if guild and guild.voice_client:
            await bgm_manager.stop_bgm(guild)
            await guild.voice_client.disconnect()

        game_manager.delete_session(user_id) # ゲームセッションを終了

        if isinstance(message.channel, discord.Thread):
            await message.channel.send("この冒険は終わりを告げました。まもなくこのスレッドはアーカイブされます。")
            await message.channel.edit(archived=True)
        return

    session.last_response = ai_response

    # 技能判定が要求されているかチェック
    skill_check_data = ai_response.get("skill_check")
    if skill_check_data:
        skill = skill_check_data["skill"]
        difficulty = skill_check_data["difficulty"]
        check_view = SkillCheckView(user_id, skill, difficulty)
        await message.channel.send(ai_response["scenario"], view=check_view)
        return # 判定ボタンが押されるのを待つ
    
    view = ChoiceView(user_id=user_id)
    for i, choice_text in enumerate(ai_response.get("choices", [])):
        async def button_callback(interaction: discord.Interaction, choice_num=i+1):
            await view.handle_choice(interaction, choice_num)
        button = discord.ui.Button(label=f"{i+1}: {choice_text[:75]}", style=discord.ButtonStyle.primary)
        button.callback = button_callback
        view.add_item(button)

    # 店が登場した場合、売買用のViewを追加する
    shop_data = ai_response.get("shop")
    if shop_data and shop_data.get("items_for_sale"):
        shop_embed = discord.Embed(title=f"ようこそ、{shop_data.get('name', '店')}へ！", description="ご用件は？", color=discord.Color.gold())
        shop_view = ShopView(user_id=user_id, shop_data=shop_data, character=session.character)
        shop_message = await channel.send(embed=shop_embed, view=shop_view)
        shop_view.message = shop_message

    # まず画像なしのEmbedを作成して送信
    channel = message.channel if isinstance(message, discord.Message) else message.channel
    final_embed = create_scenario_embed(ai_response, gm_key)
    scenario_message = await channel.send(embed=final_embed, view=view) # ChoiceViewを持つメッセージ
    view.message = scenario_message

    # 画像生成を非同期で実行
    image_prompt = ai_response.get("image_prompt")
    if image_prompt:
        image_url = await asyncio.to_thread(generate_image_from_prompt, image_prompt)
        if image_url:
            # 画像が見つかったらEmbedを更新してメッセージを編集
            final_embed = create_scenario_embed(ai_response, gm_key, image_url)
            await scenario_message.edit(embed=final_embed)
    
    # 最終的なEmbedをログとして投稿
    await post_play_log(embed=final_embed, user=message.author)

    # ターン終了時に実績をチェック
    await check_and_notify_achievements(channel, character, session)

    # BGMを更新
    if ai_response:
        await bgm_manager.update_bgm_for_session(session, ai_response.get("bgm_keyword"))