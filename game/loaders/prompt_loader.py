import json
from pathlib import Path
from typing import Any, Dict

class PromptLoader:
    """プロンプト設定ファイル (JSON) を読み込み、管理するクラス。"""

    def __init__(self, file_path: Path):
        """
        指定されたパスからプロンプトファイルを読み込みます。
        Args:
            file_path: プロンプトファイルへのパス (e.g., Path("prompts/system_prompts.json"))
        """
        if not file_path.exists():
            raise FileNotFoundError(f"プロンプトファイルが見つかりません: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            self._prompts: Dict[str, Any] = json.load(f)
        
        print(f"プロンプトファイルをロードしました: {file_path}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        ドット記法を使用して、ネストされたプロンプトの値を取得します。
        例: get('game_master.response_format.header')
        """
        keys = key.split('.')
        value = self._prompts
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def get_raw(self) -> Dict[str, Any]:
        """ロードしたプロンプト全体の辞書を返します。"""
        return self._prompts
