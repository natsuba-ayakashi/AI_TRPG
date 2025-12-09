import httpx
import base64
from io import BytesIO
from typing import Optional

from core.errors import AIConnectionError

class ImageGenerationService:
    """
    画像生成AIモデルとの通信を担当するサービスクラス。
    """
    def __init__(self, api_url: Optional[str]):
        self.api_url = api_url
        self.http_client = httpx.AsyncClient(timeout=120.0)

    def is_enabled(self) -> bool:
        """画像生成機能が有効かどうかを返します。"""
        return self.api_url is not None

    async def generate_image_from_text(self, text_prompt: str) -> Optional[BytesIO]:
        """
        テキストプロンプトから画像を生成し、画像のバイナリデータを返します。
        """
        if not self.is_enabled():
            return None

        # プロンプトを調整（品質向上のための定型句を追加）
        full_prompt = f"masterpiece, best quality, highres, {text_prompt}"
        negative_prompt = "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry"

        payload = {
            "prompt": full_prompt,
            "negative_prompt": negative_prompt,
            "steps": 25,
            "sampler_index": "DPM++ 2M Karras",
            "width": 1024,
            "height": 768,
        }

        try:
            response = await self.http_client.post(self.api_url, json=payload)
            response.raise_for_status()
            
            r = response.json()
            image_data = base64.b64decode(r['images'][0])
            
            return BytesIO(image_data)

        except (httpx.HTTPStatusError, KeyError, IndexError) as e:
            print(f"画像生成エラー: {e}")
            raise AIConnectionError(f"画像生成AIとの通信に失敗しました。") from e