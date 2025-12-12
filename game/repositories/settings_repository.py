import json
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional
import logging

from core.errors import FileOperationError

logger = logging.getLogger(__name__)

class SettingsRepository:
    """
    Handles reading and writing of guild-specific settings to a JSON file.
    """

    def __init__(self, settings_path: str):
        """
        Args:
            settings_path: The path to the JSON file for storing settings.
        """
        self.settings_file = Path(settings_path)
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        # To ensure the file exists, touch it if it doesn't.
        if not self.settings_file.is_file():
            self.settings_file.touch()
            self.settings_file.write_text('{}')

    async def _load_all_settings(self) -> Dict[str, Any]:
        """Loads all settings from the JSON file."""
        try:
            async with aiofiles.open(self.settings_file, mode='r', encoding='utf-8') as f:
                content = await f.read()
                # If file is empty, return empty dict
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Settings file '{self.settings_file}' contains invalid JSON. Starting fresh.")
            return {}
        except FileNotFoundError:
            logger.info(f"Settings file '{self.settings_file}' not found. A new one will be created.")
            return {}
        except Exception as e:
            raise FileOperationError(f"Failed to load settings file '{self.settings_file}'.") from e

    async def _save_all_settings(self, all_settings: Dict[str, Any]):
        """Saves all settings to the JSON file."""
        try:
            async with aiofiles.open(self.settings_file, mode='w', encoding='utf-8') as f:
                await f.write(json.dumps(all_settings, indent=4, ensure_ascii=False))
        except Exception as e:
            raise FileOperationError(f"Failed to save settings file '{self.settings_file}'.") from e

    async def get_guild_settings(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves settings for a specific guild.
        
        Args:
            guild_id: The ID of the guild.
            
        Returns:
            A dictionary with the guild's settings, or None.
        """
        all_settings = await self._load_all_settings()
        return all_settings.get(str(guild_id))

    async def save_guild_settings(self, guild_id: int, settings: Dict[str, Any]):
        """
        Saves settings for a specific guild.
        
        Args:
            guild_id: The ID of the guild.
            settings: The settings dictionary to save for the guild.
        """
        all_settings = await self._load_all_settings()
        all_settings[str(guild_id)] = settings
        await self._save_all_settings(all_settings)
