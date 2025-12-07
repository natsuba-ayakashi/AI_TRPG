import yaml
import os

class PromptLoader:
    """YAMLファイルからプロンプトを読み込み、管理するクラス。"""
    def __init__(self, file_path='prompts.yaml'):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"プロンプトファイルが見つかりません: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            self._prompts = yaml.safe_load(f)

    def get(self, key: str) -> str:
        """指定されたキーのプロンプトテンプレートを取得する。"""
        prompt = self._prompts.get(key)
        if prompt is None:
            raise KeyError(f"プロンプトキー '{key}' はファイル内に存在しません。")
        return prompt

# アプリケーション全体で共有するためのインスタンスを作成
prompts = PromptLoader()