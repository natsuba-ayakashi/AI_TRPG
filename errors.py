"""
このプロジェクトで使用するカスタム例外クラスを定義します。
"""

class GameError(Exception):
    """ゲームのロジックや操作に関するベースとなる例外クラス。"""
    pass

class FileOperationError(GameError):
    """ファイルの読み書きに関するエラー。"""
    pass

class CharacterNotFoundError(FileOperationError):
    """指定されたキャラクターが見つからないエラー。"""
    pass

class AIConnectionError(GameError):
    """AI生成APIへの接続やレスポンスに関するエラー。"""
    pass