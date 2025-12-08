import uuid
from typing import Dict, Any, List

class Character:
    """
    ゲーム内のキャラクターの状態とロジックを管理するデータモデルクラス。
    DiscordのUIやデータ永続化からは独立しています。
    """

    def __init__(self, data: Dict[str, Any]):
        """
        辞書データからキャラクターオブジェクトを初期化します。

        Args:
            data: キャラクターの属性を含む辞書。
        """
        # --- 基本情報 ---
        self.char_id: str = data.get('char_id', str(uuid.uuid4()))
        self.user_id: int = data.get('user_id', 0)
        self.name: str = data.get('name', '名無し')
        self.race: str = data.get('race', '不明')
        self.class_: str = data.get('class', '不明') # 'class'は予約語のためアンダースコアを付与

        # --- プロフィール ---
        self.appearance: str = data.get('appearance', '')
        self.background: str = data.get('background', '')

        # --- 能力値・技能 ---
        self.stats: Dict[str, int] = data.get('stats', {})
        self.skills: Dict[str, int] = data.get('skills', {})

        # --- 成長関連 ---
        self.level: int = data.get('level', 1)
        self.xp: int = data.get('xp', 0)
        self.stat_points: int = data.get('stat_points', 0)
        self.skill_points: int = data.get('skill_points', 0)

        # --- クエスト関連 ---
        self.active_quests: List[str] = data.get('active_quests', [])
        self.completed_quests: List[str] = data.get('completed_quests', [])

        # --- 所持品 ---
        self.inventory: List[str] = data.get('inventory', [])

        # --- HP/MP ---
        con_stat = self.stats.get("CON", 10) # CONがなければ10を基準
        int_stat = self.stats.get("INT", 10) # INTがなければ10を基準
        self.max_hp: int = data.get('max_hp', 10 + (con_stat * 2))
        self.hp: int = data.get('hp', self.max_hp)
        self.max_mp: int = data.get('max_mp', 10 + (int_stat * 2))
        self.mp: int = data.get('mp', self.max_mp)

    @property
    def xp_to_next_level(self) -> int:
        """次のレベルアップに必要な経験値の合計。"""
        # 例: Lv1->2は100, Lv2->3は200...
        return self.level * 100

    def to_dict(self) -> Dict[str, Any]:
        """
        キャラクターオブジェクトの状態を辞書形式にシリアライズします。
        ファイル保存用。
        """
        return {
            'char_id': self.char_id,
            'user_id': self.user_id,
            'name': self.name,
            'race': self.race,
            'class': self.class_,
            'appearance': self.appearance,
            'background': self.background,
            'stats': self.stats,
            'skills': self.skills,
            'level': self.level,
            'xp': self.xp,
            'stat_points': self.stat_points,
            'skill_points': self.skill_points,
            'active_quests': self.active_quests,
            'completed_quests': self.completed_quests,
            'inventory': self.inventory,
            'hp': self.hp,
            'max_hp': self.max_hp,
            'mp': self.mp,
            'max_mp': self.max_mp,
        }

    def add_xp(self, amount: int) -> bool:
        """
        経験値を追加し、レベルアップしたかどうかを判定します。

        Returns:
            レベルアップした場合は True、そうでなければ False。
        """
        self.xp += amount
        leveled_up = False
        while self.xp >= self.xp_to_next_level:
            self.xp -= self.xp_to_next_level
            self.level += 1
            self.stat_points += 1  # レベルアップで能力値ポイント+1
            self.skill_points += 5 # レベルアップで技能ポイント+5
            leveled_up = True
        return leveled_up

    def use_stat_point(self, stat_name: str) -> bool:
        """
        能力値ポイントを消費して指定された能力値を強化します。
        """
        stat_name = stat_name.upper()
        if self.stat_points > 0 and stat_name in self.stats:
            self.stat_points -= 1
            self.stats[stat_name] += 1
            return True
        return False

    def use_skill_points(self, skill_name: str, points_to_use: int) -> bool:
        """
        技能ポイントを消費して指定された技能を強化します。
        """
        if points_to_use <= 0 or self.skill_points < points_to_use:
            return False
        
        # 技能が存在しない場合は新規作成
        if skill_name not in self.skills:
            self.skills[skill_name] = 0
            
        self.skill_points -= points_to_use
        self.skills[skill_name] += points_to_use
        return True

    def apply_race_bonus(self, all_races_data: List[Dict[str, Any]]):
        """
        種族ボーナスを能力値に適用します。
        このメソッドはキャラクター作成時に一度だけ呼び出されることを想定しています。
        """
        race_data = next((race for race in all_races_data if race.get("name") == self.race), None)
        if not race_data or "stats_bonus" not in race_data:
            return

        for stat, bonus in race_data["stats_bonus"].items():
            if stat in self.stats:
                self.stats[stat] += bonus

    # --- インベントリ管理 ---

    def add_item(self, item_name: str):
        """インベントリにアイテムを追加します。"""
        if item_name not in self.inventory:
            self.inventory.append(item_name)

    def remove_item(self, item_name: str) -> bool:
        """インベントリからアイテムを削除します。"""
        if item_name in self.inventory:
            self.inventory.remove(item_name)
            return True
        return False

    # --- クエスト管理 ---

    def start_quest(self, quest_id: str):
        """新しいクエストを開始します。"""
        if quest_id not in self.active_quests and quest_id not in self.completed_quests:
            self.active_quests.append(quest_id)

    def complete_quest(self, quest_id: str):
        """クエストを完了状態にします。"""
        if quest_id in self.active_quests:
            self.active_quests.remove(quest_id)
            if quest_id not in self.completed_quests:
                self.completed_quests.append(quest_id)

    # --- HP/MP 操作 ---

    def take_damage(self, amount: int):
        """HPにダメージを受けます。HPは0未満にはなりません。"""
        self.hp = max(0, self.hp - amount)

    def heal_hp(self, amount: int):
        """HPを回復します。最大HPを超えることはありません。"""
        self.hp = min(self.max_hp, self.hp + amount)

    def spend_mp(self, amount: int) -> bool:
        """
        MPを消費します。MPが足りない場合はFalseを返します。
        
        Returns:
            MPの消費に成功した場合は True、MPが不足している場合は False。
        """
        if self.mp >= amount:
            self.mp -= amount
            return True
        return False

    def recover_mp(self, amount: int):
        """MPを回復します。最大MPを超えることはありません。"""
        self.mp = min(self.max_mp, self.mp + amount)

    @property
    def is_dead(self) -> bool:
        """キャラクターが死亡しているかどうかを返します。"""
        return self.hp <= 0