import discord
import asyncio
from collections import defaultdict
from typing import Optional

# BGMのキーワードとファイルパスのマッピング
# 今後、ここにBGMファイルを追加していきます
BGM_MAP = {
    "town": "bgm/town.mp3",
    "battle": "bgm/battle.mp3",
    "dungeon": "bgm/dungeon.mp3",
    "sad": "bgm/sad.mp3",
    "default": "bgm/field.mp3", # デフォルトのBGM
}

currently_playing = {} # guild_id: "keyword"
volume_settings = {}   # guild_id: float (0.0 to 2.0)
guild_locks = defaultdict(asyncio.Lock) # guild_id: asyncio.Lock

async def play_bgm(vc: discord.VoiceClient, file_path: str):
    """指定された音声ファイルをループ再生する"""
    # ffmpegのオプション。-before_options -reconnect 1 はストリーミングが途切れた際に再接続を試みるためのものです。
    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }
    guild_id = vc.guild.id
    
    # ループ再生のためのラッパー関数
    def after_playing(error):
        if error:
            print(f"BGM再生中にエラーが発生しました: {error}")
            return
        # 再度同じBGMを再生する
        if vc.is_connected():
            coro = play_bgm(vc, file_path)
            fut = asyncio.run_coroutine_threadsafe(coro, vc.client.loop)
            try:
                fut.result()
            except Exception as e:
                print(f"BGMのループ再生中にエラー: {e}")

    # 既に何か再生中なら停止
    if vc.is_playing():
        vc.stop()

    # 音声ファイルからソースを作成
    source = await discord.FFmpegOpusAudio.from_probe(file_path, **ffmpeg_options)

    # 音量調整可能なソースに変換
    volume_source = discord.PCMVolumeTransformer(source, volume=volume_settings.get(guild_id, 1.0))
    
    # 再生を開始
    vc.play(volume_source, after=after_playing)

async def set_volume(guild: discord.Guild, volume: int):
    """指定されたギルドのBGM音量を設定する"""
    if not 0 <= volume <= 200:
        return False, "音量は0から200の間で設定してください。"

    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return False, "Botはボイスチャンネルに参加していません。"

    # volumeプロパティを持つソース（PCMVolumeTransformer）を探す
    if vc.source and hasattr(vc.source, 'volume'):
        new_volume = volume / 100.0
        vc.source.volume = new_volume
        volume_settings[guild.id] = new_volume
        return True, f"BGMの音量を {volume}% に設定しました。"
    else:
        return False, "音量を変更できるBGMが再生されていません。ゲームを開始するとBGMが再生されます。"

async def pause_bgm(guild: discord.Guild):
    """指定されたギルドで再生中のBGMを一時停止する"""
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return False, "Botはボイスチャンネルに参加していません。"
    
    if vc.is_playing():
        vc.pause()
        return True, "BGMを一時停止しました。"
    else:
        return False, "一時停止できるBGMが再生されていません。"

async def resume_bgm(guild: discord.Guild):
    """指定されたギルドで一時停止中のBGMを再生する"""
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return False, "Botはボイスチャンネルに参加していません。"

    if vc.is_paused():
        vc.resume()
        return True, "BGMの再生を再開しました。"
    else:
        return False, "一時停止中のBGMはありません。"

async def stop_bgm(guild: discord.Guild):
    """指定されたギルドで再生中のBGMを停止する"""
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return False, "Botはボイスチャンネルに参加していません。"

    if vc.is_playing() or vc.is_paused():
        vc.stop()
        # 再生状態をリセット
        if guild.id in currently_playing:
            del currently_playing[guild.id]
        return True, "BGMを停止しました。"
    else:
        return False, "停止するBGMがありません。"

def get_bgm_status(guild: discord.Guild) -> Optional[dict]:
    """指定されたギルドのBGM再生状況を取得する"""
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        return None

    guild_id = guild.id
    keyword = currently_playing.get(guild_id)
    volume = volume_settings.get(guild_id, 1.0)

    status = {
        "keyword": keyword,
        "file_path": BGM_MAP.get(keyword) if keyword else None,
        "volume": int(volume * 100),
        "is_playing": vc.is_playing(),
        "is_paused": vc.is_paused(),
    }
    return status

async def force_play(guild: discord.Guild, keyword: str) -> tuple[bool, str]:
    """指定されたギルドで特定のBGMを強制的に再生する"""
    if keyword not in BGM_MAP:
        return False, f"指定されたBGMキーワード「{keyword}」は存在しません。"

    async with guild_locks[guild.id]:
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return False, "Botはボイスチャンネルに参加していません。"

        file_path = BGM_MAP[keyword]
        
        # 同じ曲が再生中の場合でも、最初から再生し直す
        print(f"BGMを手動で変更します: {keyword} -> {file_path}")
        await play_bgm(vc, file_path)
        
        # 再生状態を更新
        currently_playing[guild.id] = keyword
        
        return True, f"BGMを「{keyword.capitalize()}」に変更しました。"

async def update_bgm_for_session(session, bgm_keyword: Optional[str]):
    """セッションの状態に基づいてBGMを更新する"""
    thread = client.get_channel(session.thread_id)
    if not thread: return
    guild = thread.guild
    
    # 適切なBGMファイルを選択
    keyword = bgm_keyword if bgm_keyword in BGM_MAP else "default"
    
    async with guild_locks[guild.id]:
        # 同じBGMが既に再生中なら何もしない
        if currently_playing.get(guild.id) == keyword:
            return

        file_path = BGM_MAP[keyword]

        # ボイスクライアントを取得
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            print("BGM再生エラー: ボットがボイスチャンネルに接続していません。")
            return

        print(f"BGMを変更します: {keyword} -> {file_path}")
        await play_bgm(vc, file_path)
        currently_playing[guild.id] = keyword