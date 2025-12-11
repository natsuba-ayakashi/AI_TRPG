import uuid
from typing import Dict, Any, List

class Enemy:
    """
    戦闘中の個々の敵キャラクターの状態を管理するデータモデルクラス。
    """

    def __init__(self, base_data: Dict[str, Any]):
        """
        静的な敵データ（辞書）から敵オブジェクトのインスタンスを生成します。

        Args:
            base_data: world_dataから読み込まれた敵の基本データ。
        """
        # --- 基本情報 ---
        self.enemy_id: str = base_data.get('id', 'unknown_enemy')
        self.instance_id: str = str(uuid.uuid4()) # 戦闘中の個体を一意に識別するID
        self.name: str = base_data.get('name', '名無しの魔物')
        
        # --- HP ---
        base_hp = base_data.get('hp', 20)
        self.max_hp: int = base_hp
        self.hp: int = base_hp

        # --- 能力値・アビリティ ---
        self.stats: Dict[str, int] = base_data.get('stats', {})
        self.abilities: List[Dict[str, Any]] = base_data.get('abilities', [])

        # --- 戦闘中の状態 ---
        self.status_effects: List[str] = []

        # --- 報酬 ---
        self.rewards: Dict[str, Any] = base_data.get('rewards', {})

    @property
    def attack_power(self) -> int:
        """攻撃力を計算します (STR)。"""
        return self.stats.get("STR", 10)

    def take_damage(self, amount: int):
        """HPにダメージを受けます。HPは0未満にはなりません。"""
        self.hp = max(0, self.hp - amount)

    def is_defeated(self) -> bool:
        """HPが0以下になったかどうかを返します。"""
        return self.hp <= 0

    def to_dict(self) -> Dict[str, Any]:
        """敵オブジェクトの状態を辞書形式にシリアライズします。"""
        return {
            'enemy_id': self.enemy_id,
            'instance_id': self.instance_id,
            'name': self.name,
            'hp': self.hp,
            'max_hp': self.max_hp,
            'stats': self.stats,
            'abilities': self.abilities,
            'status_effects': self.status_effects,
        }