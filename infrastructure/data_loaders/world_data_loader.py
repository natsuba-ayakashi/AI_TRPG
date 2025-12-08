import json
from pathlib import Path
from typing import Dict, Any, Optional

class WorldDataLoader:
    """
    ゲームの世界設定など、静的なデータをファイルから読み込み、メモリ上に保持するクラス。
    """
    def __init__(self, base_path: str):
        """
        Args:
            base_path: 静的データが格納されているディレクトリのパス。
        """
        self.base_path = Path(base_path)
        self._world_data: Dict[str, Any] = {}
        self._load_all_data()

    def _load_all_data(self):
        """
        ベースパス内の全てのJSONファイルを読み込み、内部データとして保持します。
        ファイル名がデータのキーになります。
        """
        if not self.base_path.exists() or not self.base_path.is_dir():
            print(f"警告: World data path '{self.base_path}' が見つかりません。")
            return

        for file_path in self.base_path.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._world_data[file_path.stem] = data
                    print(f"世界データをロードしました: {file_path.name}")
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"エラー: 世界データ '{file_path.name}' の読み込みに失敗しました。 - {e}")

    def get(self, key: str) -> Optional[Any]:
        """
        指定されたキーに対応する世界データを取得します。
        """
        return self._world_data.get(key)