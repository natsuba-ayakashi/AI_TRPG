import json

def get_nested_attr(obj, attr_string, default=None):
    """'a.b.c' のような文字列でネストされた属性を取得する"""
    attrs = attr_string.split('.')
    for attr in attrs:
        obj = getattr(obj, attr, {}) if isinstance(obj, object) and not isinstance(obj, dict) else obj.get(attr)
        if obj is None: return default
    return obj

class Character:
    """キャラクターのデータと操作を管理するクラス"""

    def __init__(self, initial_data):
        self.name = initial_data.get("name", "名無し")
        self.race = initial_data.get("race", "不明")
        # "class"はPythonの予約語なので、属性名を "char_class" に変更
        self.char_class = initial_data.get("class", "一般人")
        self.gender = initial_data.get("gender", "不明")
        self.appearance = initial_data.get("appearance", "特徴のない容姿")
        self.background = initial_data.get("background", "不明")
        self.stats = initial_data.get("stats", {})
        self.traits = initial_data.get("traits", [])
        self.skills = initial_data.get("skills", {}) # 技能値
        self.san = initial_data.get("san", 50) # 正気度ポイント
        self.secrets = initial_data.get("secrets", [])
        self.equipment = initial_data.get("equipment", {})
        self.history = initial_data.get("history", [])
        self.money = initial_data.get("money", 0) # 所持金
        self.achievements = initial_data.get("achievements", []) # 達成した実績
        self.custom_image_url = initial_data.get("custom_image_url", None) # カスタム画像URL
        # 各GM人格との親和性スコア
        self.gm_affinity = initial_data.get("gm_affinity", {
            "standard": 1,
            "poetic": 1,
            "tactical": 1,
            "enthusiastic": 1
        })

    def apply_update(self, updates):
        """AIからの更新指示をキャラクターに適用し、GM親和性を更新する"""
        for update in updates:
            action = update["action"]
            field = update["field"]
            value = update["value"]

            # "class" を "char_class" にマッピング
            if field == "class":
                field = "char_class"

            # ネストされたフィールド（例: equipment.items）に対応
            if '.' in field:
                parts = field.split('.')
                field = parts

            # 更新内容に基づいてGM親和性スコアを更新
            if field == "stats":
                self.gm_affinity["tactical"] += 2
            elif field in ["secrets", "traits"]:
                self.gm_affinity["poetic"] += 2
            elif field == "history":
                self.gm_affinity["enthusiastic"] += 1

            # ネストされたフィールドの場合は、最初の部分で属性の存在を確認
            attr_to_check = field[0] if isinstance(field, list) else field
            if hasattr(self, attr_to_check):
                target_attribute = getattr(self, attr_to_check)
                if isinstance(target_attribute, dict) and len(parts) > 1:
                    # ネストされた辞書の更新
                    sub_dict = target_attribute
                    for part in parts[1:-1]:
                        sub_dict = sub_dict.setdefault(part, {})
                    
                    final_key = parts[-1]
                    if action == "add" and isinstance(sub_dict.get(final_key), list):
                        sub_dict[final_key].append(value)
                    elif action == "remove" and isinstance(sub_dict.get(final_key), list) and value in sub_dict[final_key]:
                        sub_dict[final_key].remove(value)
                elif isinstance(target_attribute, list):
                    if action == "add": target_attribute.append(value)
                    elif action == "remove" and value in target_attribute: target_attribute.remove(value)
                elif isinstance(target_attribute, dict):
                    if action == "update":
                        for key, change in value.items():
                            target_attribute[key] = target_attribute.get(key, 0) + change
            elif field == "money" and action == "update":
                self.money += int(value)

    def to_dict(self):
        """AIプロンプト用にキャラクターデータを辞書形式に変換する"""
        return {
            "name": self.name,
            "race": self.race,
            "class": self.char_class, # AI向けにキーを "class" に戻す
            "gender": self.gender,
            "appearance": self.appearance,
            "background": self.background,
            "stats": self.stats,
            "traits": self.traits,
            "skills": self.skills,
            "secrets": self.secrets,
            "equipment": self.equipment,
            "history": self.history,
            "money": self.money,
            "achievements": self.achievements,
            "custom_image_url": self.custom_image_url,
            "gm_affinity": self.gm_affinity # セーブデータ用に親和性スコアも辞書に含める
        }

    @classmethod
    def from_dict(cls, data):
        """辞書データからCharacterオブジェクトを生成する"""
        return cls(data)