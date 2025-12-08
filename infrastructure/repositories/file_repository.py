import json
import aiofiles
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.errors import FileOperationError

class FileRepository:
    """
    Handles asynchronous reading and writing of data to the file system.
    Responsible for persisting data like character sheets.
    """

    def __init__(self, base_path: str):
        """
        Args:
            base_path: The base directory path for storage.
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_user_dir(self, user_id: int) -> Path:
        """Gets the directory path for a user, creating it if it doesn't exist."""
        user_dir = self.base_path / str(user_id)
        user_dir.mkdir(exist_ok=True)
        return user_dir

    def _get_save_path(self, user_id: int, save_name: str) -> Path:
        """Gets the full path for a save file."""
        return self._get_user_dir(user_id) / f"{save_name}.json"

    async def save(self, user_id: int, save_name: str, data: Dict[str, Any]):
        """
        Asynchronously saves the given data as a JSON file.

        Args:
            user_id: The ID of the user who owns the data.
            save_name: The name of the save (e.g., character name).
            data: The data to save (in dictionary format).
        """
        file_path = self._get_save_path(user_id, save_name)
        try:
            async with aiofiles.open(file_path, mode='w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=4, ensure_ascii=False))
        except Exception as e:
            raise FileOperationError(f"Failed to save file '{file_path}'.") from e

    async def load(self, user_id: int, save_name: str) -> Optional[Dict[str, Any]]:
        """
        Asynchronously loads a JSON file and returns its data.

        Args:
            user_id: The ID of the user who owns the data.
            save_name: The name of the data to load.

        Returns:
            The loaded data, or None if the file does not exist.
        """
        file_path = self._get_save_path(user_id, save_name)
        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise FileOperationError(f"Failed to load file '{file_path}'.") from e

    async def list_saves(self, user_id: int) -> List[str]:
        """Returns a list of saved data (file names) for a given user."""
        user_dir = self._get_user_dir(user_id)
        if not user_dir.exists():
            return []
        return [p.stem for p in user_dir.glob('*.json') if p.is_file()]

    async def delete(self, user_id: int, save_name: str) -> bool:
        """Deletes a specified save file."""
        file_path = self._get_save_path(user_id, save_name)
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            return True
        return False