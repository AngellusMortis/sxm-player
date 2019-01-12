import asyncio
import datetime
import os
import traceback

from discord import Embed, Message, TextChannel
from discord.ext.commands import Bot, Command, Context, check, command, errors
from humanize import naturaltime

from sqlalchemy import or_
from sxm.models import XMImage, XMSong

from ...models import Episode, Song
from ...player import AudioPlayer
from ..base import BaseRunner
from .converters import XMChannelConverter
from .checks import require_voice
from .utils import send_message

__all__ = ['BotRunner']


class SXMCommand(Command):
    @property
    def cog_name(self):
        return 'SiriusXM'


class BotRunner(BaseRunner):
    """ Discord Bot to play SiriusXM content """

    prefix: str
    token: str
    bot: Bot = None
    player: AudioPlayer = None

    def __init__(self, prefix: str, description: str,
                 token: str, *args, **kwargs):
        super().__init__(name='bot', *args, **kwargs)

        self.prefix = prefix
        self.token = token
        self.bot = Bot(
            command_prefix=self.prefix,
            description=description,
            pm_help=True
        )
        self.bot.add_cog(self)

        self.bot.cogs['SiriusXM'] = self.bot.cogs.pop('BotRunner')

        print(self.bot.cogs.items())
        self.player = AudioPlayer(self.bot, self.state)

        if self.state.output is None:
            self.bot.remove_command('songs')
            self.bot.remove_command('song')
            self.bot.remove_command('shows')
            self.bot.remove_command('show')
            self.bot.remove_command('skip')
            self.bot.remove_command('playlist')
            self.bot.remove_command('upcoming')

    def __unload(self):
        if self.player is not None:
            self.bot.loop.create_task(self.player.stop())

    def run(self):
        self._log.info('bot runner has started')
        self.bot.run(self.token)

    async def on_ready(self) -> None:
        user = self.bot.user
        self._log.info(
            f'logged in as {user} (id: {user.id})')

    async def on_command_error(self, ctx: Context,
                               error: errors.CommandError) -> None:
        if isinstance(error, errors.BadArgument):
            message = \
                f'`{self.prefix}{ctx.command.name}`: {error.args[0]}'
            await send_message(ctx, message)
        elif isinstance(error, errors.CommandNotFound):
            self._log.info(
                f'{ctx.message.author}: invalid command: {ctx.message.content}'
            )
            message = (
                f'`{ctx.message.content}`: invalid command. '
                f'Use `{self.prefix}help` for a list of commands'
            )
            await send_message(ctx, message)
        elif isinstance(error, errors.MissingRequiredArgument):
            self._log.info(
                f'{ctx.message.author}: missing arg: {ctx.message.content}'
            )

            arg = str(error).split(' ')[0]
            if arg == 'xm_channel':
                arg = 'channel_id'

            message = (
                f'`{ctx.message.content}`: `{arg}` is missing'
            )
            await send_message(ctx, message)
        elif not isinstance(error, errors.CheckFailure):
            self._log.error(f'{type(error)}: {error}')
            await send_message(ctx, 'something went wrong ☹')

    async def on_message(self, message: Message) -> None:
        ctx = await self.bot.get_context(message)
        author = ctx.message.author

        if message.content.startswith(self.prefix.strip()):
            if isinstance(ctx.message.channel, TextChannel):
                await ctx.message.delete()

        if ctx.valid:
            self._log.info(f'{author}: {message.content}')

    async def _play_file(self, ctx: Context, guid: str = None,
                         is_song: bool = False) -> None:
        """ Queues a song/show file to be played """

        channel = ctx.message.channel
        author = ctx.message.author
        search_type = 'shows'
        if is_song:
            search_type = 'songs'

        if author.voice is None:
            await channel.send(
                f'{author.mention}, you are not in a voice channel.')
            return

        if guid is None:
            await channel.send(
                f'{author.mention}, please provide a {search_type} id'
            )
            return

        db_item = None
        if is_song:
            db_item = self.state.db.query(Song)\
                .filter_by(guid=guid).first()
        else:
            db_item = self.state.db.query(Episode)\
                .filter_by(guid=guid).first()

        if db_item is not None and not os.path.exists(db_item.file_path):
            self._log.warn(f'file does not exist: {db_item.file_path}')
            db_item = None

        if db_item is None:
            await channel.send(
                f'{author.mention}, invalid {search_type} id'
            )
            return

        if not self.player.is_playing:
            await ctx.invoke(self.summon)

        if self.state.active_channel_id is not None:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)

        try:
            self._log.info(f'play: {db_item.file_path}')
            await self.player.add_file(db_item)
        except Exception:
            self._log.error('error while trying to add file to play queue:')
            self._log.error(traceback.format_exc())
        else:
            await channel.send(
                    f'{author.mention}, added {db_item.bold_name} '
                    f'to now playing queue'
                )

    async def _search_archive(self, ctx: Context,
                              search: str, is_song: bool) -> None:
        """ Searches song/show database and responds with results """

        channel = ctx.message.channel
        author = ctx.message.author
        search_type = 'shows'
        if is_song:
            search_type = 'songs'

        if search is None:
            self._log.debug(f'{search_type}: nothing')
            await channel.send(
                f'{author.mention}, please provide a search string '
                f'to find a song'
            )
            return

        items = None
        if is_song:
            items = self.state.db.query(Song).filter(or_(
                Song.guid.ilike(f'{search}%'),
                Song.title.ilike(f'{search}%'),
                Song.artist.ilike(f'{search}%'),
            )).order_by(Song.air_time.desc())[:10]
        else:
            items = self.state.db.query(Episode).filter(or_(
                Episode.guid.ilike(f'{search}%'),
                Episode.title.ilike(f'{search}%'),
                Episode.show.ilike(f'{search}%')
            )).order_by(Episode.air_time.desc())[:10]

        if len(items) > 0:
            message = (
                f'{author.mention}\n\n'
                f'{search_type.title()} matching `{search}`:\n\n'
            )
            for item in items:
                message += f'{item.guid}: {item.bold_name}\n'

            await channel.send(message)
        else:
            await channel.send(
                f'{author.mention}, no {search_type} results '
                f'found for `{search}`'
            )

    async def _sxm_recent(self, ctx: Context, count: int) -> None:
        """ Respons with what has recently played on the
        SiriusXM HLS live stream """

        channel = ctx.message.channel
        author = ctx.message.author

        xm_channel = self.state.get_channel(
            self.state.active_channel_id)

        song_cuts = []
        now = self.state.radio_time
        latest_cut = self.state.live.get_latest_cut(now)

        for song_cut in reversed(self.state.live.song_cuts):
            if song_cut == latest_cut:
                song_cuts.append(song_cut)
                continue

            end = int(song_cut.time + song_cut.duration)
            if song_cut.time < now and \
                    (end > self.state.start_time or
                        song_cut.time > self.state.start_time):
                song_cuts.append(song_cut)

            if len(song_cuts) >= count:
                break

        if len(song_cuts) > 0:
            message = (
                f'{author.mention}\n\n'
                f'Recent songs for **{xm_channel.pretty_name}**:\n\n'
            )

            for song_cut in song_cuts:
                seconds_ago = int((now-song_cut.time)/1000)
                time_delta = datetime.timedelta(seconds=seconds_ago)
                time_string = naturaltime(time_delta)

                pretty_name = Song.get_pretty_name(
                    song_cut.cut.title,
                    song_cut.cut.artists[0].name,
                    True
                )
                if song_cut == latest_cut:
                    message += f'now: {pretty_name}\n'
                else:
                    message += f'about {time_string}: {pretty_name}\n'

            await channel.send(message)
        else:
            await channel.send(
                f'{author.mention}, no recent songs played'
            )

    async def _sxm_now_playing(self, ctx: Context) -> None:
        """ Sends message for what is currently playing on the
        SiriusXM HLS live stream """

        channel = ctx.message.channel
        author = ctx.message.author

        xm_channel = self.state.get_channel(
            self.state.active_channel_id)
        cut = self.state.live.get_latest_cut(
            now=self.state.radio_time)
        episode = self.state.live.get_latest_episode(
            now=self.state.radio_time)

        np_title = None
        np_author = None
        np_thumbnail = None
        np_album = None
        np_episode_title = None

        if cut is not None and isinstance(cut.cut, XMSong):
            song = cut.cut
            np_title = song.title
            np_author = song.artists[0].name

            if song.album is not None:
                album = song.album
                if album.title is not None:
                    np_album = album.title

                for art in album.arts:
                    if isinstance(art, XMImage):
                        if art.size is not None and art.size == 'MEDIUM':
                            np_thumbnail = art.url

        if episode is not None:
            episode = episode.episode
            np_episode_title = episode.long_title

            if np_thumbnail is None:
                for art in episode.show.arts:
                    if art.height > 100 and art.height < 200 and \
                            art.height == art.width:
                        # logo on dark is what we really want
                        if art.name == "show logo on dark":
                            np_thumbnail = art.url
                            break
                        # but it is not always there, so fallback image
                        elif art.name == "image":
                            np_thumbnail = art.url

        embed = Embed(title=np_title)
        if np_author is not None:
            embed.set_author(name=np_author)
        if np_thumbnail is not None:
            embed.set_thumbnail(url=np_thumbnail)
        if np_album is not None:
            embed.add_field(name="Album", value=np_album)
        embed.add_field(
            name="SiriusXM", value=xm_channel.pretty_name, inline=True)
        if np_episode_title is not None:
            embed.add_field(
                name="Show", value=np_episode_title, inline=True)

        await channel.send(author.mention, embed=embed)

    @command(pass_context=True, no_pm=True, cls=SXMCommand)
    @check(require_voice)
    async def channel(self, ctx: Context, *,
                      xm_channel: XMChannelConverter) -> None:
        """Plays a specific SiriusXM channel"""

        channel = ctx.message.channel
        author = ctx.message.author

        if self.player.is_playing:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        log_archive = ''
        if self.state.stream_folder is not None:
            log_archive = f': archiving'

        try:
            self._log.info(f'play{log_archive}: {xm_channel.id}')
            await self.player.add_live_stream(xm_channel)
        except Exception:
            self._log.error('error while trying to add channel to play queue:')
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await channel.send(
                f'{author.mention}, something went wrong starting stream')
        else:
            await channel.send(
                f'{author.mention} starting playing '
                f'**{xm_channel.pretty_name}** in '
                f'**{author.voice.channel.mention}**'
            )
