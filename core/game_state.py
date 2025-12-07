import json
import os
import re
from core.character_manager import Character

SAVES_DIR = "saves"
LEGACY_LOGS_DIR = "legacy_logs"

def sanitize_filename(name: str) -> str:
    """ファイル名として安全な文字列に変換する"""
    return re.sub(r'[\\/*?:"<>|]', "", name)

def save_game(user_id, character: Character, world_setting: str):
    """現在のキャラクターの状態と世界設定をファイルに保存します。"""
    user_saves_dir = os.path.join(SAVES_DIR, str(user_id))
    if not os.path.exists(user_saves_dir):
        os.makedirs(user_saves_dir)
    
    char_filename = f"{sanitize_filename(character.name)}.json"
    save_path = os.path.join(user_saves_dir, char_filename)
    save_data = {
        "character": character.to_dict(),
        "world_setting": world_setting
    }

    try:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        print(f"--- ユーザー({user_id})の進行状況を `{save_path}` に保存しました ---")
        return True
    except Exception as e:
        print(f"セーブ中にエラーが発生しました: {e}")
        return False

def load_character(user_id, character_name: str):
    """指定されたキャラクターのセーブデータを読み込む"""
    char_filename = f"{sanitize_filename(character_name)}.json"
    save_path = os.path.join(SAVES_DIR, str(user_id), char_filename)
    if not os.path.exists(save_path):
        return None, None
    
    try:
        with open(save_path, "r", encoding="utf-8") as f:
            save_data = json.load(f)
            print(f"--- ユーザー({user_id})の進行状況を `{save_path}` から読み込みました ---")
            
            # 古いセーブデータ形式との互換性維持
            if "character" in save_data and "world_setting" in save_data:
                character = Character.from_dict(save_data["character"])
                world_setting = save_data["world_setting"]
            else: # 古い形式の場合
                character = Character.from_dict(save_data)
                world_setting = "一般的なファンタジー世界" # デフォルト値を設定
            return character, world_setting
    except Exception as e:
        print(f"ロード中にエラーが発生しました: {e}")
        return None, None

def list_characters(user_id: int) -> list[str]:
    """指定されたユーザーの保存済みキャラクター名のリストを返す"""
    user_saves_dir = os.path.join(SAVES_DIR, str(user_id))
    if not os.path.exists(user_saves_dir):
        return []
    
    characters = []
    for filename in os.listdir(user_saves_dir):
        if filename.endswith(".json"):
            # .json拡張子を取り除いてキャラクター名とする
            characters.append(filename[:-5])
    return characters

def delete_character(user_id: int, character_name: str) -> bool:
    """指定されたキャラクターのセーブデータを削除する"""
    char_filename = f"{sanitize_filename(character_name)}.json"
    save_path = os.path.join(SAVES_DIR, str(user_id), char_filename)
    if os.path.exists(save_path):
        os.remove(save_path)
        print(f"--- ユーザー({user_id})のキャラクター `{character_name}` を削除しました ---")
        return True
    return False

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