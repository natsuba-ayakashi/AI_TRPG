import discord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.models.character import Character


def create_character_embed(character: "Character") -> discord.Embed:
    """キャラクターオブジェクトからステータス表示用のEmbedを生成する"""
    
    embed = discord.Embed(
        title=f"{character.name} - Lv. {character.level}",
        description=f"{character.race} / {character.class_}",
        color=discord.Color.blue()
    )
    if character.appearance:
        embed.add_field(name="外見", value=character.appearance, inline=False)
    if character.background:
        embed.add_field(name="背景", value=character.background, inline=False)

    # HPとMP
    hp_mp_text = f"❤️ HP: {character.hp} / {character.max_hp}\n💙 MP: {character.mp} / {character.max_mp}"
    embed.add_field(name="リソース", value=hp_mp_text, inline=False)

    # 能力値
    stats_text = " / ".join([f"**{name}**: {val}" for name, val in character.stats.items()])
    embed.add_field(name="能力値", value=stats_text, inline=False)

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


def create_journal_embed(character: "Character", all_quests_data: dict) -> discord.Embed:
    """キャラクターのジャーナル（クエストログ）表示用のEmbedを生成する"""

    embed = discord.Embed(
        title=f"{character.name}の冒険日誌",
        description="これまでの冒険の記録と、現在の目的。",
        color=discord.Color.gold()
    )

    # 進行中のクエスト
    active_quests_text = ""
    for quest_id in character.active_quests:
        quest = all_quests_data.get(quest_id, {})
        active_quests_text += f"**{quest.get('title', '不明なクエスト')}**\n- {quest.get('description', '詳細不明')}\n"
    if not active_quests_text:
        active_quests_text = "現在、進行中のクエストはありません。"
    embed.add_field(name="進行中の目的", value=active_quests_text, inline=False)

    # 完了したクエスト
    completed_quests_text = ""
    for quest_id in character.completed_quests:
        quest = all_quests_data.get(quest_id, {})
        completed_quests_text += f"- {quest.get('title', '不明なクエスト')}\n"
    if completed_quests_text:
        embed.add_field(name="完了した目的", value=completed_quests_text, inline=False)

    return embed

def create_action_result_embed(action_result: dict) -> discord.Embed:
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