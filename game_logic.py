import discord
import random
import asyncio

from character_manager import Character
from ai_handler import build_prompt, get_ai_response, generate_image_from_prompt
from ui_components import ChoiceView
from game_state import save_legacy_log, load_legacy_log
# --- グローバル変数/関数のプレースホルダー ---
game_sessions = {}
client = None
SCENARIO_LOG_CHANNEL_ID = 0

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
    san_value = char_data.get('san', 'N/A')
    stats_text = f"**SAN:** {san_value} | " + " / ".join([f"{key}:{val}" for key, val in char_data['stats'].items()])
    embed.add_field(name="能力値", value=stats_text, inline=False)
    
    if char_data['traits']:
        embed.add_field(name="特徴", value=", ".join(char_data['traits']), inline=True)
    
    if char_data['skills']:
        skills_text = " / ".join([f"{key}:{val:+}" for key, val in char_data['skills'].items()])
        embed.add_field(name="技能", value=skills_text, inline=True)
    if char_data['secrets']:
        embed.add_field(name="秘密", value=", ".join(char_data['secrets']), inline=True)

    history_text = "冒険は始まったばかりだ..."
    if char_data['history']:
        history_text = "\n".join([f"- {h}" for h in char_data['history'][-3:]])
    embed.add_field(name="最近の出来事", value=history_text, inline=False)
    
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

async def setup_and_start_game(interaction, character: Character, is_new_game: bool, world_setting: str):
    """スレッドを作成し、新しいゲームセッションを開始する共通関数"""
    user_id = interaction.user.id
    thread_name_prefix = "⚔️"
    thread_name = f"{thread_name_prefix} {character.name}の冒険"
    if not is_new_game:
        thread_name += " (再開)"

    thread = await interaction.channel.create_thread(name=thread_name, auto_archive_duration=1440)
    await interaction.followup.send(f"{character.name}の冒険が始まります！ {thread.mention} で物語が進行します。", ephemeral=True)

    legacy_log = load_legacy_log(user_id)
    game_sessions[user_id] = {'character': character, 'state': 'playing', 'legacy_log': legacy_log, 'world_setting': world_setting}

    await thread.send(f"ようこそ、{interaction.user.mention} さん！ここがあなたの冒険の舞台です。", embed=create_character_embed(character))
    if legacy_log:
        await thread.send(f"過去の英雄「{legacy_log.get('hero_name')}」の伝説が、この世界に息づいています...")
    
    interaction.channel = thread
    await start_game_turn(interaction, character)

async def start_game_turn(message, character: Character):
    """ゲームの1ターンを実行し、結果をDiscordに送信する"""
    user_id = message.author.id
    
    gm_key = select_gm_personality(character)
    await message.channel.send(f"--- 今回のGM: {gm_key} ---")
    
    legacy_log = game_sessions[user_id].get('legacy_log')
    world_setting = game_sessions[user_id].get("world_setting")

    prompt = build_prompt(character.to_dict(), legacy_log=legacy_log, gm_personality_key=gm_key, world_setting=world_setting)
    thinking_message = await message.channel.send("--- AIが物語を紡いでいます... 📜 ---")
    ai_response = get_ai_response(prompt)

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

    if ai_response.get("game_clear") or ai_response.get("game_over"):
        is_clear = ai_response.get("game_clear", False)
        end_message = "--- 見事、物語を完結させました！ ---" if is_clear else "--- 物語は終わりを告げた ---"
        final_embed = discord.Embed(title="物語の結末", description=ai_response.get("scenario"), color=discord.Color.gold())
        final_embed.set_footer(text=end_message)
        await message.channel.send(embed=final_embed)

        user_id = message.author.id
        character = game_sessions[user_id]['character']
        if is_clear:
            save_legacy_log(user_id, character)

        if SCENARIO_LOG_CHANNEL_ID and client.get_channel(SCENARIO_LOG_CHANNEL_ID):
            log_channel = client.get_channel(SCENARIO_LOG_CHANNEL_ID)
            await log_channel.send(f"`{character.name}` の冒険が結末を迎えました。", embed=final_embed)
        del game_sessions[user_id] # ゲームセッションを終了
        return

    game_sessions[user_id]['last_response'] = ai_response
    
    view = ChoiceView(user_id=user_id)
    for i, choice_text in enumerate(ai_response.get("choices", [])):
        async def button_callback(interaction: discord.Interaction, choice_num=i+1):
            await view.handle_choice(interaction, choice_num)
        button = discord.ui.Button(label=f"{i+1}: {choice_text[:75]}", style=discord.ButtonStyle.primary)
        button.callback = button_callback
        view.add_item(button)

    channel = message.channel if isinstance(message, discord.Message) else message.channel
    scenario_message = await channel.send(embed=create_scenario_embed(ai_response, gm_key), view=view)

    image_prompt = ai_response.get("image_prompt")
    if image_prompt:
        image_url = await asyncio.to_thread(generate_image_from_prompt, image_prompt)
        if image_url:
            new_embed = create_scenario_embed(ai_response, gm_key, image_url)
            await scenario_message.edit(embed=new_embed)