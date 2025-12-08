"""
このモジュールは、Botがユーザーに送信するテキストメッセージを一元管理します。
メッセージの文言変更や多言語対応を容易にすることを目的とします。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord
    from game.models.character import Character
    from game.models.session import GameSession

# --- 一般的なエラーメッセージ ---
MSG_ONLY_FOR_COMMAND_USER = "コマンドを実行した本人のみ操作できます。"
MSG_SESSION_REQUIRED = "このコマンドはアクティブなゲームセッション中にのみ使用できます。"
MSG_NO_ACTIVE_SESSION = "アクティブなゲームセッションがありません。"

# --- キャラクター関連 ---
def character_delete_confirmation(char_name: str) -> str:
    return f"本当にキャラクター「{char_name}」を削除しますか？\n**この操作は元に戻せません。**"

def character_deleted(char_name: str) -> str:
    return f"キャラクター「{char_name}」を削除しました。"

def character_delete_canceled() -> str:
    return "削除をキャンセルしました。"

def character_in_use(char_name: str) -> str:
    return f"キャラクター「{char_name}」は現在ゲームで使用中です。`/end_game` でゲームを終了してから削除してください。"

# --- ゲーム進行関連 ---
def start_game_followup(thread: "discord.Thread") -> str:
    return f"新しい冒険が始まりました！ {thread.mention} に移動してゲームを続けてください。"

def start_game_thread_message(user: "discord.User", character: "Character") -> str:
    return f"ようこそ、{user.mention}！\nキャラクター「{character.name}」の冒険がここから始まります。最初の行動を入力してください。"

def end_game_thread_message(character: "Character") -> str:
    return f"この冒険は終了しました。キャラクター「{character.name}」の最終状態は保存されました。\n\nお疲れ様でした！"

def end_game_followup(character: "Character") -> str:
    return f"ゲームを終了し、キャラクター「{character.name}」の進行状況を保存しました。"