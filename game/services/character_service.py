import uuid
from typing import Dict, Any, List, TYPE_CHECKING
import logging

from game.models.character import Character
from core.errors import CharacterNotFoundError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from game.repositories.file_repository import FileRepository

class CharacterService:
    """
    キャラクターに関するビジネスロジックを扱うサービスクラス。
    UI層(Cog)とデータ層(Repository)の中間に位置します。
    """
    def __init__(self, character_repository: "FileRepository"):
        """
        Args:
            character_repository: キャラクターデータの永続化を担当するリポジトリ。
        """
        self.repository = character_repository

    async def create_character(self, user_id: int, char_data: Dict[str, Any]) -> Character:
        """
        新しいキャラクターを作成し、永続化します。

        Args:
            user_id: キャラクターを所有するユーザーのID。
            char_data: キャラクター作成ビューから受け取ったデータ。

        Returns:
            作成されたCharacterオブジェクト。
        """
        # サーバー側で管理するIDを付与
        char_data['user_id'] = user_id
        if 'char_id' not in char_data:
            char_data['char_id'] = str(uuid.uuid4())

        # Characterモデルオブジェクトを生成
        character = Character(char_data)

        # Repositoryを介してデータを保存
        await self.repository.save(character.user_id, character.name, character.to_dict())
        logger.info(f"ユーザー({character.user_id})の新規キャラクター「{character.name}」を保存しました。")
        return character

    async def get_character(self, user_id: int, char_name: str) -> Character:
        """
        指定されたキャラクターを読み込み、Characterオブジェクトとして返します。
        """
        char_data = await self.repository.load(user_id, char_name)
        if not char_data:
            raise CharacterNotFoundError(f"キャラクター「{char_name}」が見つかりません。")
        
        return Character(char_data)

    async def get_all_character_names(self, user_id: int) -> List[str]:
        """
        指定されたユーザーが所有する全てのキャラクター名を取得します。
        """
        return await self.repository.list_saves(user_id)

    async def save_character(self, character: Character):
        """
        キャラクターオブジェクトの状態を永続化します。
        """
        await self.repository.save(character.user_id, character.name, character.to_dict())
        logger.info(f"ユーザー({character.user_id})のキャラクター「{character.name}」の状態を保存しました。")

    async def delete_character(self, user_id: int, char_name: str) -> bool:
        """
        指定されたキャラクターのデータを削除します。

        Returns:
            削除が成功したかどうかを示すブール値。
        """
        success = await self.repository.delete(user_id, char_name)
        if success:
            logger.info(f"ユーザー({user_id})のキャラクター「{char_name}」を削除しました。")
        return success