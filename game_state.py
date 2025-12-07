import json
import os
from character_manager import Character

SAVES_DIR = "saves"
LEGACY_LOGS_DIR = "legacy_logs"

def save_game(user_id, character):
    """現在のキャラクターの状態をファイルに保存します。"""
    if not os.path.exists(SAVES_DIR):
        os.makedirs(SAVES_DIR)
    
    save_path = os.path.join(SAVES_DIR, f"{user_id}.json")
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(character.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"--- ユーザー({user_id})の進行状況を `{save_path}` に保存しました ---")
        return True
    except Exception as e:
        print(f"セーブ中にエラーが発生しました: {e}")
        return False

def load_game(user_id):
    """セーブファイルからキャラクターの状態を読み込み、Characterオブジェクトを返します。"""
    save_path = os.path.join(SAVES_DIR, f"{user_id}.json")
    if not os.path.exists(save_path):
        return None
    
    try:
        with open(save_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"--- ユーザー({user_id})の進行状況を `{save_path}` から読み込みました ---")
            return Character.from_dict(data)
    except Exception as e:
        print(f"ロード中にエラーが発生しました: {e}")
        return None

def save_legacy_log(user_id, character):
    """ユーザーのゲームクリア時のキャラクター情報をレガシーログとして保存する"""
    if not os.path.exists(LEGACY_LOGS_DIR):
        os.makedirs(LEGACY_LOGS_DIR)
    
    log_path = os.path.join(LEGACY_LOGS_DIR, f"{user_id}.json")
    character_data = character.to_dict()
    try:
        # ログに残す情報を抽出・整形
        legacy_data = {
            "hero_name": character_data.get("name"),
            "achievement": character_data.get("history", [])[-1] if character_data.get("history") else "伝説的な冒険を成し遂げた",
            "final_class": character_data.get("class")
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f, ensure_ascii=False, indent=2)
        print(f"--- ユーザー({user_id})の英雄の伝説が `{log_path}` に記録されました ---")
    except Exception as e:
        print(f"レガシーログの保存中にエラーが発生しました: {e}")

def load_legacy_log(user_id):
    """ユーザーの過去の英雄のログを読み込む"""
    log_path = os.path.join(LEGACY_LOGS_DIR, f"{user_id}.json")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            print(f"--- ユーザー({user_id})の過去の英雄の伝説 (`{log_path}`) を読み込みました ---")
            return json.load(f)
    return None