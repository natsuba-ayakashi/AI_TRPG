import discord
from discord import app_commands
from discord.ext import commands
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from game.models.character import Character
    from bot.client import MyBot


def create_character_embed(character: "Character") -> discord.Embed:
    """キャラクターオブジェクトからステータス表示用のEmbedを生成する"""
    
    STAT_DETAILS = {
        "STR": {"name": "筋力", "desc": "物理的な力強さ。近接攻撃の威力や、物を持ち上げる力に影響します。"},
        "DEX": {"name": "器用さ", "desc": "身のこなしや手先の器用さ。回避能力、隠密行動、弓などの遠距離攻撃に影響します。"},
        "CON": {"name": "耐久力", "desc": "体力や忍耐力。HPの最大値や、毒・病気への抵抗力に影響します。"},
        "INT": {"name": "知力", "desc": "知識や論理的思考力。魔法の威力や、世界の謎を解き明かす力に影響します。"},
        "WIS": {"name": "判断力", "desc": "直感や洞察力、意志の強さ。危険の察知や、精神的な抵抗力に影響します。"},
        "CHA": {"name": "魅力", "desc": "カリスマ性や交渉力。NPCとの会話や、リーダーシップに影響します。"},
    }

    description_parts = []
    if character.race != '不明':
        description_parts.append(character.race)
    if character.class_ != '不明':
        description_parts.append(character.class_)
    description = " / ".join(description_parts) or "作成中..."

    embed = discord.Embed(
        title=f"{character.name} - Lv. {character.level}",
        description=description,
        color=discord.Color.blue()
    )
    if character.appearance:
        embed.add_field(name="外見", value=character.appearance, inline=False)
    if character.background:
        embed.add_field(name="背景", value=character.background, inline=False)

    # HPとMP
    hp_mp_text = f"❤️ HP: {character.hp} / {character.max_hp}\n💙 MP: {character.mp} / {character.max_mp}\n💰 所持金: {character.gold} G"
    embed.add_field(name="リソース", value=hp_mp_text, inline=False)

    # 装備
    if character.equipment:
        equip_text_parts = []
        for slot, item in character.equipment.items():
            bonus_text = ", ".join([f"{k}+{v}" for k, v in item['bonuses'].items()])
            equip_text_parts.append(f"**{slot.capitalize()}**: {item['name']} ({bonus_text})")
        embed.add_field(name="装備", value="\n".join(equip_text_parts), inline=False)
    else:
        embed.add_field(name="装備", value="なし", inline=False)

    # 能力値
    if character.stats:
        stats_text_parts = []
        for name, val in character.stats.items():
            details = STAT_DETAILS.get(name, {"name": "?", "desc": "詳細不明"})
            stats_text_parts.append(f"**{name} ({details['name']})**: {val}\n*└ {details['desc']}*")
        stats_text = "\n".join(stats_text_parts)
        embed.add_field(name="能力値", value=stats_text, inline=False)
    else:
        embed.add_field(name="能力値", value="未設定", inline=False)

    # 技能
    if character.skills:
        skills_text = "\n".join([f"- {name}: {rank}" for name, rank in character.skills.items()])
        embed.add_field(name="技能", value=skills_text, inline=True)

    # ポイント
    points_text = (
        f"経験値: {character.xp} / {character.xp_to_next_level}\n"
        f"能力値ポイント: {character.stat_points}\n"
        f"技能ポイント: {character.skill_points}"
    )
    embed.add_field(name="ポイント", value=points_text, inline=True)

    embed.set_footer(text=f"キャラクターID: {character.char_id}")

    return embed

def create_command_list_embed(bot: "MyBot") -> discord.Embed:
    """Botに登録されているすべてのスラッシュコマンドのEmbedを生成する。"""
    embed = discord.Embed(
        title="コマンド一覧",
        description="このBotで利用できるスラッシュコマンドの一覧です。",
        color=discord.Color.green()
    )

    # Cogsごとにコマンドをグループ化
    cogs_to_display = {name: cog for name, cog in bot.cogs.items() if name not in ["ゲーム管理"]} # "ゲーム管理" Cogを除外
    
    for cog_name, cog in cogs_to_display.items():
        # Cogに属するスラッシュコマンドのみを抽出
        commands_in_cog = [
            cmd for cmd in cog.get_app_commands() if isinstance(cmd, app_commands.Command)
        ]
        if not commands_in_cog:
            continue

        command_list = [f"`/{cmd.name}`: {cmd.description}" for cmd in commands_in_cog]
        embed.add_field(name=cog_name, value="\n".join(command_list), inline=False)
    
    embed.set_footer(text="このメッセージはBot起動時に自動更新されます。")
    return embed


def create_journal_embed(session: "GameSession", all_quests_data: dict, all_enemies_data: dict) -> discord.Embed:
    """キャラクターのジャーナル（クエストログ）表示用のEmbedを生成する"""
    character = session.character

    embed = discord.Embed(
        title=f"{character.name}の冒険日誌",
        description="これまでの冒険の記録と、現在の目的。",
        color=discord.Color.gold()
    )

    # 最終目標の表示
    if session.final_boss_id:
        final_boss_data = all_enemies_data.get(session.final_boss_id, {})
        final_boss_name = final_boss_data.get("name", "未知の脅威")
        embed.add_field(name="最終目標", value=f"**{final_boss_name} の討伐**", inline=False)

    # メインクエストの進捗
    if session.quest_chain_ids:
        main_quest_text = []
        for i, quest_id in enumerate(session.quest_chain_ids):
            quest_data = all_quests_data.get(quest_id, {})
            quest_title = quest_data.get("title", "不明なクエスト")
            
            status_icon = "✅" if quest_id in character.completed_quests else \
                          "▶️" if quest_id in character.active_quests else \
                          "◽"
            
            main_quest_text.append(f"{status_icon} {i+1}. {quest_title}")
        
        if main_quest_text:
            embed.add_field(name="メインクエスト", value="\n".join(main_quest_text), inline=False)

    # 完了したクエスト
    completed_quests_text = ""
    for quest_id in character.completed_quests:
        if quest_id not in session.quest_chain_ids: # メインクエスト以外
            quest = all_quests_data.get(quest_id, {})
            completed_quests_text += f"- {quest.get('title', '不明なクエスト')}\n"
    if completed_quests_text:
        embed.add_field(name="完了した目的（その他）", value=completed_quests_text, inline=False)

    return embed

def create_action_result_embed(action_result: dict) -> Optional[discord.Embed]:
    """AIの応答に含まれるaction_resultからEmbedを生成する"""
    
    details = action_result.get("details", {})
    type = action_result.get("type")

    if type == "DICE_ROLL":
        skill = details.get("skill", "不明な技能")
        target = details.get("target", "?")
        roll = details.get("roll", "?")
        success = details.get("success", False)

        title = f"🎲 ダイスロール: {skill}"
        color = discord.Color.green() if success else discord.Color.red()
        result_text = "成功" if success else "失敗"

        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="結果", value=f"**{result_text}**", inline=True)
        embed.add_field(name="目標値", value=str(target), inline=True)
        embed.add_field(name="出目", value=str(roll), inline=True)
        return embed

    return None # 未知のタイプの場合は何も返さない

def create_log_embed(user: discord.User, user_input: str, narrative: str, action_result: Optional[dict]) -> discord.Embed:
    """ゲームの進行状況を記録するためのログ用Embedを生成する"""
    embed = discord.Embed(
        title="ゲームログ",
        description=narrative,
        color=discord.Color.dark_grey(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=user.display_name, icon_url=user.avatar.url if user.avatar else None)
    embed.add_field(name="プレイヤーの行動", value=f"```{user_input}```", inline=False)
    
    if action_result and action_result.get("type") == "DICE_ROLL":
        details = action_result.get("details", {})
        skill = details.get("skill", "不明")
        target = details.get("target", "?")
        roll = details.get("roll", "?")
        success = details.get("success", False)
        result_text = "成功" if success else "失敗"
        
        dice_summary = f"技能: {skill} | 目標値: {target} | 出目: {roll} | 結果: **{result_text}**"
        embed.add_field(name="🎲 ダイスロール結果", value=dice_summary, inline=False)

    return embed