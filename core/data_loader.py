import os
import yaml
from typing import Dict, Any

class DataLoader:
    """
    指定されたディレクトリから再帰的にYAMLファイルを読み込み、
    ファイル名をキーとする辞書としてデータを保持するクラス。
    """
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.data: Dict[str, Any] = {}
        self._load_all()

    def _load_all(self):
        """ベースパス以下のすべてのYAMLファイルを読み込む。"""
        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.endswith(('.yaml', '.yml')):
                    file_path = os.path.join(root, file)
                    key_name = os.path.splitext(file)[0] # 拡張子を除いたファイル名をキーとする
                    with open(file_path, 'r', encoding='utf-8') as f:
                        self.data[key_name] = yaml.safe_load(f)

    def get(self, key: str) -> Dict[str, Any]:
        """キーに一致するデータを取得する。"""
        return self.data.get(key)

    def get_all(self) -> Dict[str, Any]:
        """ロードしたすべてのデータを取得する。"""
        return self.data