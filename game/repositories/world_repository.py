import json
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional

from core.errors import FileOperationError

class WorldRepository:
    """
    世界の状態（NPCの状態など）を単一のファイルで永続化するリポジトリ。
    """

    def __init__(self, file_path: str):
        """
        Args:
            file_path: 世界の状態を保存するJSONファイルのパス。
        """
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    async def save(self, data: Dict[str, Any]):
        """世界の状態データをJSONファイルとして非同期に保存します。"""
        try:
            async with aiofiles.open(self.file_path, mode='w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=4, ensure_ascii=False))
        except Exception as e:
            raise FileOperationError(f"世界の状態ファイル '{self.file_path}' の保存に失敗しました。") from e

    async def load(self) -> Dict[str, Any]:
        """世界の状態データをJSONファイルから非同期に読み込みます。"""
        if not self.file_path.exists():
            return {"npc_states": {}, "graveyard": {}} # ファイルが存在しない場合は空のデータを返す

        try:
            async with aiofiles.open(self.file_path, mode='r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                # 過去のデータとの互換性のため、キーが存在しない場合はデフォルト値を設定
                data.setdefault("npc_states", {})
                data.setdefault("graveyard", {})
                return data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # ファイルが空の場合や不正な形式の場合も空データを返す
            print(f"警告: 世界の状態ファイル '{self.file_path}' の読み込みに失敗したか、ファイルが空です。 - {e}")
            return {"npc_states": {}, "graveyard": {}}