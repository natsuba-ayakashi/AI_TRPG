import json

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

            # 更新内容に基づいてGM親和性スコアを更新
            if field == "stats":
                self.gm_affinity["tactical"] += 2
            elif field in ["secrets", "traits"]:
                self.gm_affinity["poetic"] += 2
            elif field == "history":
                self.gm_affinity["enthusiastic"] += 1

            if hasattr(self, field):
                target_attribute = getattr(self, field)
                if action == "add" and isinstance(target_attribute, list):
                    target_attribute.append(value)
                elif action == "remove" and isinstance(target_attribute, list) and value in target_attribute:
                    target_attribute.remove(value)
                elif action == "update" and isinstance(target_attribute, dict):
                    for key, change in value.items():
                        if key in target_attribute:
                            target_attribute[key] += change
                        else:
                            target_attribute[key] = change

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
            "gm_affinity": self.gm_affinity # セーブデータ用に親和性スコアも辞書に含める
        }

    @classmethod
    def from_dict(cls, data):
        """辞書データからCharacterオブジェクトを生成する"""
        return cls(data)