from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.character_manager import Character
    from core.game_manager import GameSession

# --- 実績の達成条件を定義する関数 ---

def check_first_step(character: "Character", session: Optional["GameSession"]) -> bool:
    """最初の1歩を踏み出したか"""
    return len(character.history) >= 1

def check_moneybags(character: "Character", session: Optional["GameSession"]) -> bool:
    """所持金が1000Gを超えたか"""
    return character.money >= 1000

def check_collector(character: "Character", session: Optional["GameSession"]) -> bool:
    """アイテムを10種類以上集めたか"""
    return len(set(character.equipment.get("items", []))) >= 10

def check_game_clear(character: "Character", session: Optional["GameSession"]) -> bool:
    """ゲームをクリアしたか"""
    # このチェックは game_logic 側で is_clear フラグを見て行う
    return False

# --- 実績の定義 ---
# 各キーは実績のユニークID
ACHIEVEMENTS = {
    "first_step": {
        "name": "最初の一歩",
        "description": "最初の冒険を始める。",
        "condition": check_first_step,
        "hidden": False,
    },
    "moneybags": {
        "name": "小さな富豪",
        "description": "所持金が1000Gを超える。",
        "condition": check_moneybags,
        "hidden": False,
    },
    "collector": {
        "name": "コレクター",
        "description": "10種類以上の異なるアイテムを所持する。",
        "condition": check_collector,
        "hidden": True, # 隠し実績
    },
    "game_clear": {
        "name": "英雄の誕生",
        "description": "物語を英雄的な結末に導く。",
        "condition": check_game_clear, # 特殊な条件
        "hidden": False,
    }
}

def check_all_achievements(character: "Character", session: "GameSession") -> list[str]:
    """キャラクターの状態をチェックし、新たにアンロックされた実績のIDリストを返す。"""
    unlocked_ids = []
    for achievement_id, details in ACHIEVEMENTS.items():
        # まだアンロックしておらず、条件を満たしているか
        if achievement_id not in character.achievements and details["condition"](character, session):
            unlocked_ids.append(achievement_id)
    return unlocked_ids