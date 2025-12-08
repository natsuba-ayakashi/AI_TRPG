"""
このモジュールは、プロジェクト全体で使用されるカスタム例外クラスを定義します。
"""

class GameError(Exception):
    """ゲームのロジックや操作に関するエラーの基底クラス。"""
    pass

class FileOperationError(GameError):
    """ファイルI/O操作に関連するエラー。"""
    pass

class CharacterNotFoundError(FileOperationError):
    """指定されたキャラクターがリポジトリに見つからない場合に発生するエラー。"""
    pass

class AIConnectionError(GameError):
    """AI生成APIへの接続または応答受信に関連するエラー。"""
    pass