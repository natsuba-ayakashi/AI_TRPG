import discord
from discord import app_commands
from discord.ext import commands
from typing import List, TYPE_CHECKING, Dict, Union, Optional
import logging
import random

from core.errors import GameError, CharacterNotFoundError
from bot.ui.views.utility import ConfirmDeleteView, ActionSuggestionView
from bot.ui.views.combat import CombatView
from bot.ui.views.shop import ShopView
from bot.ui.embeds import create_action_result_embed
from bot.ui.pagination import LogPaginatorView
from bot import messaging

if TYPE_CHECKING:
    from bot.client import MyBot
    from game.models.session import GameSession


class GameCommandsCog(commands.Cog, name="ゲーム管理"):
    """ゲームの開始や終了、キャラクターの削除などを管理するコマンド"""

    def __init__(self, bot: "MyBot"):
        self.bot = bot

    async def _start_combat_flow(self, channel: discord.TextChannel, session: "GameSession"):
        """戦闘開始のフローを処理する"""
        # 1. 戦闘開始メッセージ
        combat_start_embed = discord.Embed(
            title="⚔️ 戦闘開始！",
            description="敵が現れた！",
            color=discord.Color.red()
        )
        for enemy in session.current_enemies:
            combat_start_embed.add_field(name=enemy.name, value=f"HP: {enemy.hp}/{enemy.max_hp}", inline=True)
        await channel.send(embed=combat_start_embed)

        # 2. 戦闘UIの表示
        combat_view = CombatView(session.user_id, self.bot)
        
        # プレイヤーのターンであることを示すEmbed
        player_turn_embed = discord.Embed(
            title="あなたのターン",
            description="行動を選択してください。",
            color=discord.Color.blue()
        )
        player_turn_embed.add_field(name=f"{session.character.name}", value=f"HP: {session.character.hp}/{session.character.max_hp} | MP: {session.character.mp}/{session.character.max_mp}")

        message = await channel.send(embed=player_turn_embed, view=combat_view)
        session.combat_view_message_id = message.id
        combat_view.message = message

    async def _update_combat_view_for_player_turn(self, channel: discord.TextChannel, session: "GameSession"):
        """プレイヤーのターンになったら戦闘UIを更新する"""
        if not session.combat_view_message_id:
            return

        try:
            message = await channel.fetch_message(session.combat_view_message_id)

            # 新しいEmbedを作成
            player_turn_embed = discord.Embed(
                title="あなたのターン",
                description="行動を選択してください。",
                color=discord.Color.blue()
            )
            player_turn_embed.add_field(name=f"{session.character.name}", value=f"HP: {session.character.hp}/{session.character.max_hp} | MP: {session.character.mp}/{session.character.max_mp}")

            # 新しいViewを作成してUIをリセット
            new_view = CombatView(session.user_id, self.bot)
            new_view.message = message

            await message.edit(embed=player_turn_embed, view=new_view)
        except discord.NotFound:
            logging.warning(f"戦闘UIメッセージ(ID: {session.combat_view_message_id})が見つかりませんでした。")
            session.combat_view_message_id = None # IDをクリア
        except Exception as e:
            logging.exception(f"戦闘UIの更新中にエラーが発生しました: {e}")

    async def _handle_response(self, source: Union[discord.Interaction, discord.TextChannel], response_data: Dict, user_id: int, user_input: str):
        """AIからの応答を解釈し、適切なメッセージとUIを送信する共通ヘルパー"""
        # narrativeとembedsの準備
        narrative = response_data.get("narrative", "ゲームマスターは何も言わなかった...")
        action_result = response_data.get("action_result")
        
        embeds_to_send = []
        if action_result:
            if action_embed := create_action_result_embed(action_result):
                embeds_to_send.append(action_embed)

        # Viewの準備 (判定と行動提案は同時には表示しない)
        view_to_send = None
        session = self.bot.game_service.sessions.get_session(user_id)

        # 戦闘中でなければ行動提案ボタンを表示
        if not session or not session.in_combat:
            if suggested_actions := response_data.get("suggested_actions"):
                if suggested_actions:
                    view_to_send = ActionSuggestionView(suggested_actions, self.bot)
        else:
            # 戦闘中の場合、ここで敵のターン処理などを挟むことも可能
            pass

        # 応答の送信
        message = None
        if isinstance(source, discord.Interaction):
            if source.response.is_done():
                 message = await source.followup.send(narrative, embeds=embeds_to_send, view=view_to_send, wait=True)
            else:
                 await source.response.send_message(narrative, embeds=embeds_to_send, view=view_to_send)
                 message = await source.original_response()
        else: # discord.TextChannel
            message = await source.send(narrative, embeds=embeds_to_send, view=view_to_send)
        
        if view_to_send and hasattr(view_to_send, 'message'):
            view_to_send.message = message

        # 戦闘開始の処理
        if session and session.in_combat and not session.combat_view_message_id:
             channel = source.channel if isinstance(source, discord.Interaction) else source
             await self._start_combat_flow(channel, session)
             return # 戦闘開始時はここで処理を一旦終了

        # プレイヤーのターンになったらUIを更新
        if session and session.in_combat and session.combat_turn == "player":
            channel = source.channel if isinstance(source, discord.Interaction) else source
            await self._update_combat_view_for_player_turn(channel, session)
        
        # ゲームオーバー処理
        if response_data.get("game_over"):
            channel = source.channel if isinstance(source, discord.Interaction) else source
            try:
                await self.bot.game_service.end_game(user_id)
                await channel.send("キャラクターは力尽きた...。ゲームを終了し、スレッドをロックします。")
                await channel.edit(archived=True, locked=True)
            except GameError as e:
                logging.warning(f"ゲームオーバー処理中のエラー: {e}")


    async def _proceed_and_respond_from_interaction(self, interaction: discord.Interaction, action: str):
        """Interactionからゲームを進行させ、応答を処理する"""
        try:
            # アイテム使用アクションの場合は use_item を経由させる
            if action.startswith("アイテム使用: "):
                item_name = action.replace("アイテム使用: ", "").strip()
                response_data = await self.bot.game_service.use_item(interaction.user.id, item_name)
            elif action == "逃走を試みる":
                response_data = await self.bot.game_service.flee_combat(interaction.user.id)
            else:
                response_data = await self.bot.game_service.proceed_game(interaction.user.id, action)
            await self._handle_response(interaction, response_data, interaction.user.id, action)
        except GameError as e:
            if interaction.response.is_done():
                await interaction.followup.send(str(e), ephemeral=True)
            else:
                await interaction.response.send_message(str(e), ephemeral=True)
        except Exception:
            logging.exception("Interactionからのゲーム進行中に予期せぬエラーが発生しました。")
            if interaction.response.is_done():
                await interaction.followup.send("予期せぬエラーが発生しました。", ephemeral=True)
            else:
                await interaction.response.send_message("予期せぬエラーが発生しました。", ephemeral=True)

    async def _post_summary_log(self, channel: discord.TextChannel, session: "GameSession"):
        """ゲーム終了時にサマリーログを投稿する"""
        if not session.conversation_history:
            return

        user = self.bot.get_user(session.user_id) or await self.bot.fetch_user(session.user_id)
        
        header_embed = discord.Embed(
            title=f"📜 ゲームログ: {session.character.name}",
            description=(
                f"プレイヤー: {user.mention if user else '不明なユーザー'}\n"
                f"キャラクター: {session.character.name} (Lv. {session.character.level})\n"
                f"ワールド: {session.world_name}\n"
                f"プレイ日時: {session.start_time.strftime('%Y-%m-%d %H:%M')} 開始"
            ),
            color=discord.Color.dark_blue()
        )
        if user:
            header_embed.set_author(name=user.display_name, icon_url=user.display_avatar)
        
        await channel.send(embed=header_embed)

        log_content = []
        for entry in session.conversation_history:
            role = "あなた" if entry["role"] == "user" else "GM"
            log_content.append(f"**{role}**: {entry['content']}")
        
        full_log = "\n\n".join(log_content)
        
        # Discordのメッセージ長制限(2000)を考慮して分割
        chunk_size = 2000
        for i in range(0, len(full_log), chunk_size):
            chunk = full_log[i:i+chunk_size]
            if chunk.strip():
                await channel.send(chunk)

        footer_embed = discord.Embed(
            description="--- ログ終了 ---",
            color=discord.Color.dark_blue()
        )
        await channel.send(embed=footer_embed)

    # (the rest of the file is unchanged)
    # ...
    # --- /start_game コマンド ---

    @app_commands.command(name="start_game", description="キャラクターと世界を選択して新しいゲームを開始します。")
    @app_commands.describe(
        character_name="ゲームに使用するキャラクターの名前",
        world_name="冒険の舞台となる世界の名前"
    )
    async def start_game(self, interaction: discord.Interaction, character_name: str, world_name: str):
        """
        キャラクターを選択し、プライベートスレッドを作成して新しいゲームセッションを開始します。
        """
        await interaction.response.defer(ephemeral=True, thinking=True)
        thread = None # エラーハンドリングのために先に定義
        try:
            # 1. キャラクターオブジェクトを取得
            character = await self.bot.character_service.get_character(interaction.user.id, character_name)

            # 2. GameServiceを呼び出してセッションを作成し、導入ナラティブを取得
            session, introduction_narrative = await self.bot.game_service.start_game(
                user_id=interaction.user.id,
                character=character,
                world_name=world_name
            )

            # 3. Discordスレッドを作成
            thread_name = f"冒険: {interaction.user.display_name} - {character.name}"
            parent_channel = interaction.channel
            if not isinstance(parent_channel, (discord.TextChannel, discord.ForumChannel)):
                await interaction.followup.send("このコマンドはテキストチャンネルまたはフォーラムチャンネルでのみ使用できます。", ephemeral=True)
                return

            thread = await parent_channel.create_thread(name=thread_name, type=discord.ChannelType.private_thread)
            await thread.add_user(interaction.user)

            # 4. 作成したスレッドIDをセッションに紐付け
            self.bot.game_service.sessions.associate_thread_to_session(user_id=interaction.user.id, thread_id=thread.id)

            # 5. ユーザーへの応答とスレッドへの初期メッセージ送信
            await interaction.followup.send(messaging.start_game_followup(thread), ephemeral=True)

            start_message = messaging.start_game_thread_message(interaction.user, session.character)
            await thread.send(start_message)

            # 導入シナリオを送信
            await thread.send(introduction_narrative)

            # 最初の行動を促すための選択肢を提示 (UX向上のため)
            initial_actions = ["周囲を見渡す", "持ち物を確認する", "地図を見る"]
            view = ActionSuggestionView(initial_actions, self.bot)
            message = await thread.send("最初の行動を選んでください:", view=view)
            view.message = message

        except (GameError, CharacterNotFoundError) as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception:
            logging.exception("ゲーム開始中に予期せぬエラーが発生しました。")
            await interaction.followup.send("ゲームの開始中に予期せぬエラーが発生しました。", ephemeral=True)
            if thread: # スレッド作成後にエラーが発生した場合、クリーンアップを試みる
                await thread.delete()

    # --- /end_game コマンド ---
    # (変更なし)
    @app_commands.command(name="end_game", description="現在のゲームを終了し、キャラクターの状態を保存します。")
    async def end_game(self, interaction: discord.Interaction):
        lock = self.bot.game_service.sessions.get_lock(interaction.user.id)
        async with lock:
            await interaction.response.defer(ephemeral=True, thinking=True)
            session = self.bot.game_service.sessions.get_session(interaction.user.id)
            if not session:
                await interaction.followup.send(messaging.MSG_NO_ACTIVE_SESSION, ephemeral=True)
                return
            try:
                ended_session = await self.bot.game_service.end_game(interaction.user.id)

                # サマリーログを投稿
                guild_settings = await self.bot.settings_repo.get_guild_settings(interaction.guild.id)
                if guild_settings and (log_channel_id := guild_settings.get("log_channel_id")):
                    log_channel = self.bot.get_channel(log_channel_id)
                    if log_channel and isinstance(log_channel, discord.TextChannel):
                        await self._post_summary_log(log_channel, ended_session)

                # スレッドをロック
                thread = interaction.guild.get_thread(ended_session.thread_id)
                if thread:
                    await thread.send(messaging.end_game_thread_message(ended_session.character))
                    await thread.edit(archived=True, locked=True)
                await interaction.followup.send(messaging.end_game_followup(ended_session.character), ephemeral=True)
            except GameError as e:
                await interaction.followup.send(str(e), ephemeral=True)
            except Exception:
                logging.exception("ゲーム終了中に予期せぬエラーが発生しました。")
                await interaction.followup.send("ゲームの終了中に予期せぬエラーが発生しました。", ephemeral=True)

    # --- /delete_character コマンド ---
    # (変更なし)
    @app_commands.command(name="delete_character", description="作成済みのキャラクターを削除します。")
    @app_commands.describe(character_name="削除するキャラクターの名前")
    async def delete_character(self, interaction: discord.Interaction, character_name: str):
        active_session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if active_session and active_session.character.name == character_name:
            await interaction.response.send_message(messaging.character_in_use(character_name), ephemeral=True)
            return
        view = ConfirmDeleteView(interaction.user.id, self.bot, character_name)
        await interaction.response.send_message(messaging.character_delete_confirmation(character_name), view=view, ephemeral=True)

    # --- /next コマンド ---

    @app_commands.command(name="next", description="あなたの次の行動をゲームマスターに伝えます。")
    @app_commands.describe(action="実行したい行動を具体的に入力してください。")
    async def next_action(self, interaction: discord.Interaction, action: str):
        """
        プレイヤーの行動をAIに送信し、結果を受け取ってゲームを進行させます。
        このコマンドはゲームスレッド内でのみ有効です。
        """
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()

        if session.in_combat and action.strip() in ["逃げる", "逃走", "flee", "run"]:
            try:
                response_data = await self.bot.game_service.flee_combat(interaction.user.id)
                await self._handle_response(interaction, response_data, interaction.user.id, action)
            except GameError as e:
                await interaction.followup.send(str(e))
            return

        await self._proceed_and_respond_from_interaction(interaction, action)

    # --- /use コマンド ---
    @app_commands.command(name="use", description="インベントリのアイテムを使用します。")
    @app_commands.describe(item_name="使用するアイテムの名前")
    async def use_item(self, interaction: discord.Interaction, item_name: str):
        """インベントリのアイテムを使用する。"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()
        
        action_text = f"アイテム使用: {item_name}" # AIに渡すテキストを生成
        await self._proceed_and_respond_from_interaction(interaction, action_text)

    # --- /equip コマンド ---
    @app_commands.command(name="equip", description="アイテムを装備します。")
    @app_commands.describe(item_name="装備するアイテムの名前")
    async def equip_item(self, interaction: discord.Interaction, item_name: str):
        """インベントリのアイテムを装備する。"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()
        
        try:
            response_data = await self.bot.game_service.equip_item(interaction.user.id, item_name)
            await self._handle_response(interaction, response_data, interaction.user.id, f"装備: {item_name}")
        except GameError as e:
            await interaction.followup.send(str(e), ephemeral=True)

    # --- /shop コマンド ---
    @app_commands.command(name="shop", description="現在地のショップを開きます。")
    async def shop(self, interaction: discord.Interaction):
        """現在地にショップがある場合、アイテム購入画面を表示する。"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        world_data = self.bot.world_data_loader.get_world(session.world_name)
        shops = world_data.get("shops", {})
        
        # 現在地のショップを検索
        current_shop = next((s for s in shops.values() if s.get("location_id") == session.current_location_id), None)
        
        if not current_shop:
            await interaction.response.send_message("ここには店がないようだ。", ephemeral=True)
            return

        shop_name = current_shop.get("name", "ショップ")
        items = current_shop.get("items", [])
        
        view = ShopView(interaction.user.id, self.bot, shop_name, items)
        await interaction.response.send_message(f"**{shop_name}** へようこそ！\n所持金: {session.character.gold} G", view=view)

    # --- /log コマンド ---
    @app_commands.command(name="log", description="現在のゲームの会話ログを表示します。")
    async def log(self, interaction: discord.Interaction):
        """現在のゲームセッションの会話ログを表示する。"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスread内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not session.conversation_history:
            await interaction.followup.send("まだ会話の記録がありません。", ephemeral=True)
            return

        # Paginator View を使用してログを表示
        view = LogPaginatorView(interaction, session.conversation_history)
        await view.start(ephemeral=True)

    # --- /skill_check コマンド ---
    @app_commands.command(name="skill_check", description="能力値や技能を使って判定を行います。")
    @app_commands.describe(
        skill="使用する能力値（STR, DEXなど）または技能名",
        target="判定の対象（例：扉、衛兵、崖）",
        dc="目標値（GMが指定した場合など。省略可能）"
    )
    async def skill_check(self, interaction: discord.Interaction, skill: str, target: str, dc: Optional[int] = None):
        """
        指定された技能で判定を行い、その結果をAIに伝えて物語を進行させます。
        """
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()

        character = session.character

        # 目標値(DC)の決定
        if dc is None:
            # 省略された場合、キャラクターの能力値に基づいて動的に計算
            base_dc = 12 # 標準的な難易度
            modifier = character.get_modifier(skill)
            # 得意な技能ほどDCが下がり、苦手な技能ほど上がる（最低5）
            dc = max(5, base_dc - (modifier // 2))

        # 判定処理
        roll = random.randint(1, 20)
        bonus = character.get_modifier(skill)
        total = roll + bonus
        success = total >= dc

        result_embed = discord.Embed(title=f"🎲 技能判定: {skill}", color=discord.Color.green() if success else discord.Color.red())
        result_embed.add_field(name="対象", value=target, inline=False)
        result_embed.add_field(name="結果", value=f"**{'成功' if success else '失敗'}**", inline=True)
        result_embed.add_field(name="目標値(DC)", value=str(dc), inline=True)
        result_embed.add_field(name="ダイス結果", value=f"{roll} (1d20) + {bonus} (ボーナス) = **{total}**", inline=False)

        await interaction.followup.send(embed=result_embed)

        # 判定結果をAIに伝えて次の展開を生成させる
        action_text = f"技能判定「{skill}」を実行。対象は「{target}」。結果は「{'成功' if success else '失敗'}」だった。"
        # この場合、interactionは既に応答済みなので、_proceed_and_respond_from_interactionは使えない
        response_data = await self.bot.game_service.proceed_game(interaction.user.id, action_text)
        await self._handle_response(interaction.channel, response_data, interaction.user.id, action_text)

    # --- /solve コマンド ---
    @app_commands.command(name="solve", description="謎や暗号の答えを入力します。")
    @app_commands.describe(answer="あなたが導き出した答え")
    async def solve_puzzle(self, interaction: discord.Interaction, answer: str):
        """謎解きに挑戦し、答えを送信する。"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session or interaction.channel_id != session.thread_id:
            await interaction.response.send_message("このコマンドは、あなたのアクティブなゲームスレッド内でのみ使用できます。", ephemeral=True)
            return

        await interaction.response.defer()

        world_data = self.bot.world_data_loader.get_world(session.world_name)
        all_puzzles = world_data.get("puzzles", {})
        
        # 現在地の謎を特定
        current_puzzle = next((p for p in all_puzzles.values() if p.get("location_id") == session.current_location_id), None)

        if not current_puzzle:
            await interaction.followup.send("ここには解くべき謎はないようだ…。", ephemeral=True)
            return

        # 解答のチェック
        is_correct = False
        for solution in current_puzzle.get("solutions", []):
            if solution.get("type") == "keyword" and solution.get("value").lower() == answer.lower():
                is_correct = True
                break
        
        if is_correct:
            # 正解の場合
            reward = current_puzzle.get("reward", {})
            reward_narrative = reward.get("narrative", "カチリと音がして、何かが作動した。")
            
            # 状態変化を適用
            if unlocks_location := reward.get("unlocks_location"):
                session.current_location_id = unlocks_location # すぐに移動させる

            await interaction.followup.send(f"**正解！**\n{reward_narrative}")
            # 正解したことをAIに伝えて物語を進行
            action_text = f"謎「{current_puzzle.get('id')}」を「{answer}」と答えて解いた。"
            response_data = await self.bot.game_service.proceed_game(interaction.user.id, action_text)
            await self._handle_response(interaction.channel, response_data, interaction.user.id, action_text)
        else:
            # 不正解の場合
            await interaction.followup.send(f"「{answer}」…違うようだ。何も起こらない。")

    @use_item.autocomplete('item_name')
    async def _use_item_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """インベントリ内のアイテムを候補として表示する"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session:
            return []
        inventory = session.character.inventory
        return [app_commands.Choice(name=item, value=item) for item in inventory if current.lower() in item.lower()][:25]

    @equip_item.autocomplete('item_name')
    async def _equip_item_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """インベントリ内のアイテムを候補として表示する"""
        session = self.bot.game_service.sessions.get_session(interaction.user.id)
        if not session:
            return []
        # 全アイテムではなく、装備可能なものだけフィルタリングできればベストだが、簡易的に所持品全表示
        inventory = session.character.inventory
        return [app_commands.Choice(name=item, value=item) for item in inventory if current.lower() in item.lower()][:25]

async def _character_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """キャラクター名をオートコンプリートするための共通メソッド"""
    bot: "MyBot" = interaction.client
    char_names = await bot.character_service.get_all_character_names(interaction.user.id)
    return [app_commands.Choice(name=name, value=name) for name in char_names if current.lower() in name.lower()][:25]

async def _world_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """利用可能な世界名をオートコンプリートするための共通メソッド"""
    bot: "MyBot" = interaction.client
    world_names = await bot.game_service.get_world_list()
    return [app_commands.Choice(name=name, value=name) for name in world_names if current.lower() in name.lower()][:25]

async def setup(bot: "MyBot"):
    cog = GameCommandsCog(bot)
    cog.start_game.autocomplete('character_name')(_character_autocomplete)
    cog.start_game.autocomplete('world_name')(_world_autocomplete)
    cog.delete_character.autocomplete('character_name')(_character_autocomplete)
    await bot.add_cog(cog)