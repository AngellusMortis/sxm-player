import asyncio
import datetime
import logging
import os
import tempfile
import traceback
from dataclasses import dataclass
from typing import Optional

from discord import Embed, Message
from discord.ext.commands import Bot, Context, command
from humanize import naturaltime
from tabulate import tabulate

from sqlalchemy import or_
from sxm.models import XMImage, XMSong

from .models import Episode, LiveStreamInfo, Song, XMState
from .player import AudioPlayer

__all__ = ['run_bot']


@dataclass
class BotState:
    """Class to store the state for Discord bot"""
    xm_state: XMState = None
    player: AudioPlayer = None
    _bot: Bot = None

    def __init__(self, state_dict: dict, bot: Bot):
        self._bot = bot
        self.xm_state = XMState(state_dict)
        self.player = AudioPlayer(bot, self.xm_state)


class SiriusXMBotCog:
    """Discord bot cog for SiriusXM radio bot
    """

    _bot: Bot = None
    _state: BotState = None
    _log: logging.Logger = None
    _proxy_base: str = None

    def __init__(self, bot: Bot, state_dict: dict, port: int):

        self._bot = bot
        self._state = BotState(state_dict, bot)
        self._log = logging.getLogger('discord_siriusxm.bot')
        self._proxy_base = f'http://127.0.0.1:{port}'

    def __unload(self):
        if self._state.player is not None:
            self._bot.loop.create_task(self._state.player.stop())

    @command(pass_context=True)
    async def channels(self, ctx: Context) -> None:
        """Bot will PM with list of possible SiriusXM channel"""

        author = ctx.message.author

        display_channels = []
        for channel in self._state.xm_state.channels:
            display_channels.append([
                channel.id,
                channel.channel_number,
                channel.name,
                channel.short_description,
            ])

        channel_table = tabulate(display_channels, headers=[
                "ID", "#", "Name", "Description"])

        self._log.debug(
            f'sending {len(display_channels)} for {author}')
        await author.send("SiriusXM Channels:")
        while len(channel_table) > 0:
            message = ""
            if len(channel_table) < 2000:
                message = channel_table
                channel_table = ""
            else:
                index = channel_table[:2000].rfind('\n')
                message = channel_table[:index]
                channel_table = channel_table[index+1:]

            await author.send(f"```{message}```")

    @command(pass_context=True, no_pm=True)
    async def summon(self, ctx: Context) -> None:
        """Summons the bot to join your voice channel"""

        author = ctx.message.author
        if author.voice is None:
            await ctx.message.channel.send(
                f'{author.mention}, you not in a voice channel.')
            return False

        summoned_channel = author.voice.channel
        await self._state.player.set_voice(summoned_channel)

    @command(pass_context=True, no_pm=True)
    async def volume(self, ctx: Context,
                     amount: Optional[float] = None) -> None:
        """Changes the volume of the music that is being played. 1.0 = 100%
        """

        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.player.is_playing:
            self._log.debug('volume: nothing is playing')
            await channel.send(
                f'{author.mention}, cannot get/set the volume. '
                f'Nothing is playing'
            )
        elif amount is None:
            await channel.send(
                f'{author.mention}, volume is currently '
                f'{self._state.player.volume}'
            )
        else:
            self._state.player.volume = amount
            await channel.send(
                f'{author.mention}, set volume to {self._state.player.volume}')

    @command(pass_context=True, no_pm=True)
    async def stop(self, ctx: Context) -> None:
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """

        channel = ctx.message.channel
        author = ctx.message.author

        if self._state.player.is_playing:
            await self._state.player.stop()

            self._log.debug('stop: stopped')
            await channel.send(f'{author.mention} stopped playing music')
        else:
            self._log.debug('stop: nothing')
            await channel.send(
                f'{author.mention}, cannot stop music. Nothing is playing')

    @command(pass_context=True, no_pm=True)
    async def kick(self, ctx: Context) -> None:
        """Kicks bot from current voice channel. If playing music, this will stop it
        """

        channel = ctx.message.channel
        author = ctx.message.author

        if author.voice is None:
            self._log.debug('kick: no room')
            await channel.send(
                f'{author.mention}, nothing to kick. '
                f'You are not in a voice channel'
            )
        else:
            success = await self._state.player.kick(author.voice.channel)
            if not success:
                await channel.send(
                    f'{author.mention}, cannot kick. '
                    f'Are you sure I am in the same voice channel as you?'
                )

    @command(pass_context=True, no_pm=True)
    async def channel(self, ctx: Context, *,
                      channel_id: Optional[str] = None) -> None:
        """Plays a specific SiriusXM channel"""

        channel = ctx.message.channel
        author = ctx.message.author

        if author.voice is None:
            self._log.debug('play: no channel')
            await channel.send(
                f'{author.mention}, you are not in a voice channel.')
            return

        if channel_id is None:
            self._log.debug('play: missing')
            await channel.send(f'{author.mention}, missing channel id.')
            return

        xm_channel = self._state.xm_state.get_channel(channel_id)
        xm_url = f'{self._proxy_base}/{xm_channel.id}.m3u8'
        if xm_channel is None:
            self._log.debug('play: invalid')
            await channel.send(f'{author.mention}, `{channel_id}` is invalid')
            return

        if self._state.player.is_playing:
            await self._state.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        stream_file = None
        log_archive = ''
        if self._state.xm_state.stream_folder is not None:
            log_archive = f': archiving'
            stream_file = os.path.join(
                self._state.xm_state.stream_folder, f'{xm_channel.id}.mp3')
        else:
            stream_file = os.path.join(tempfile.gettempdir(), f'{xm_channel.id}.mp3')

        live_stream = LiveStreamInfo(stream_file, xm_url, xm_channel)
        try:
            self._log.info(f'play{log_archive}: {xm_channel.id}')
            await self._state.player.add_live_stream(live_stream)
        except Exception:
            self._log.error('error while trying to add channel to play queue:')
            self._log.error(traceback.format_exc())
            await self._state.player.stop()
            await channel.send(
                f'{author.mention}, something went wrong starting stream')
        else:
            self._state.xm_state.set_channel(xm_channel.id)
            await channel.send(
                f'{author.mention} starting playing '
                f'**{xm_channel.pretty_name}** in '
                f'**{author.voice.channel.mention}**'
            )

    async def _sxm_now_playing(self, ctx: Context) -> None:
        """ Sends message for what is currently playing on the
        SiriusXM HLS live stream """

        channel = ctx.message.channel
        author = ctx.message.author

        xm_channel = self._state.xm_state.get_channel(
            self._state.xm_state.active_channel_id)
        cut = self._state.xm_state.live.get_latest_cut(
            now=self._state.xm_state.radio_time)
        episode = self._state.xm_state.live.get_latest_episode(
            now=self._state.xm_state.radio_time)

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

    @command(pass_context=True, no_pm=True)
    async def playing(self, ctx: Context) -> None:
        """Responds with what the bot currently playing"""

        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.player.is_playing:
            self._log.debug('np: nothing')
            await channel.send(f'{author.mention}, nothing is playing')
            return

        if self._state.xm_state.active_channel_id is not None:
            await self._sxm_now_playing(ctx)
        else:
            await channel.send(
                f'{author.mention}, current playing is '
                f'{self._state.player.current.bold_name}'
            )

    async def _sxm_recent(self, ctx: Context, count: int) -> None:
        """ Respons with what has recently played on the
        SiriusXM HLS live stream """

        channel = ctx.message.channel
        author = ctx.message.author

        xm_channel = self._state.xm_state.get_channel(
            self._state.xm_state.active_channel_id)

        song_cuts = []
        now = self._state.xm_state.radio_time
        latest_cut = self._state.xm_state.live.get_latest_cut(now)

        for song_cut in reversed(self._state.xm_state.live.song_cuts):
            if song_cut == latest_cut:
                song_cuts.append(song_cut)
                continue

            end = int(song_cut.time + song_cut.duration)
            if song_cut.time < now and \
                    (end > self._state.xm_state.start_time or
                        song_cut.time > self._state.xm_state.start_time):
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

    @command(pass_context=True, no_pm=True)
    async def recent(self, ctx: Context, count: Optional[int] = 3) -> None:
        """Responds with the last 1-10 songs that been
        played on this channel"""

        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.player.is_playing:
            self._log.debug('recent: nothing')
            await channel.send(f'{author.mention}, nothing is playing')
            return

        if count > 10 or count < 1:
            self._log.debug('recent: invalid count')
            await channel.send(
                f'{author.mention}, invalid count, must be between 1 and 10, '
                f'exclusive'
            )
            return

        if self._state.xm_state.active_channel_id is not None:
            await self._sxm_recent(ctx, count)
        else:
            message = (
                f'{author.mention}\n\n'
                f'Recent songs/shows:\n\n'
            )

            index = 0
            for item in self._state.player.recent[:count]:
                if item == self._state.player.current:
                    message += f'now: {item.bold_name}\n'
                else:
                    message += f'{index}: {item.bold_name}\n'
                index -= 1

            await channel.send(message)

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
            items = self._state.xm_state.db.query(Song).filter(or_(
                Song.guid.ilike(f'{search}%'),
                Song.title.ilike(f'{search}%'),
                Song.artist.ilike(f'{search}%'),
            )).order_by(Song.air_time.desc())[:10]
        else:
            items = self._state.xm_state.db.query(Episode).filter(or_(
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

    @command(pass_context=True, no_pm=True)
    async def songs(self, ctx: Context, search: Optional[str] = None) -> None:
        """Searches for an archived song to play.
        Only returns the first 10 songs"""

        await self._search_archive(ctx, search, True)

    @command(pass_context=True, no_pm=True)
    async def shows(self, ctx: Context, search: Optional[str] = None) -> None:
        """Searches for an archived show to play.
        Only returns the first 10 shows"""

        await self._search_archive(ctx, search, False)

    @command(pass_context=True, no_pm=True)
    async def song(self, ctx: Context, song_id: Optional[str] = None) -> None:
        """Adds a song to a play queue"""

        await self._play_file(ctx, song_id, True)

    @command(pass_context=True, no_pm=True)
    async def show(self, ctx: Context, show_id: Optional[str] = None) -> None:
        """Adds a show to a play queue"""

        await self._play_file(ctx, show_id, False)

    async def _play_file(self, ctx: Context, guid: str = None,
                         is_song: bool = False) -> None:
        """ Queues a song/show file to be played """

        channel = ctx.message.channel
        author = ctx.message.author
        search_type = 'shows'
        if is_song:
            search_type = 'songs'

        if author.voice is None:
            self._log.debug('play: no channel')
            await channel.send(
                f'{author.mention}, you are not in a voice channel.')
            return

        if guid is None:
            self._log.debug(f'{search_type}: nothing')
            await channel.send(
                f'{author.mention}, please provide a {search_type} id'
            )
            return

        db_item = None
        if is_song:
            db_item = self._state.xm_state.db.query(Song)\
                .filter_by(guid=guid).first()
        else:
            db_item = self._state.xm_state.db.query(Episode)\
                .filter_by(guid=guid).first()

        if db_item is not None and not os.path.exists(db_item.file_path):
            self._log.warn(f'file does not exist: {db_item.file_path}')
            db_item = None

        if db_item is None:
            await channel.send(
                f'{author.mention}, invalid {search_type} id'
            )
            return

        if not self._state.player.is_playing:
            await ctx.invoke(self.summon)

        if self._state.xm_state.active_channel_id is not None:
            await self._state.player.stop(disconnect=False)
            await asyncio.sleep(0.5)

        try:
            self._log.info(f'play: {db_item.file_path}')
            await self._state.player.add_file(db_item)
        except Exception:
            self._log.error('error while trying to add file to play queue:')
            self._log.error(traceback.format_exc())
        else:
            await channel.send(
                    f'{author.mention}, added {db_item.bold_name} '
                    f'to now playing queue'
                )

    @command(pass_context=True, no_pm=True)
    async def skip(self, ctx: Context) -> None:
        """Skips current song (only for ad-hoc, not SiriusXM radio)"""

        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.player.is_playing:
            await channel.send(
                f'{author.mention}, cannot skip. '
                f'Nothing is playing'
            )
            return

        if self._state.xm_state.active_channel_id is not None:
            await channel.send(
                f'{author.mention}, cannot skip. '
                f'SiriusXM radio is playing'
            )
            return

        await self._state.player.skip()

    @command(pass_context=True, no_pm=True)
    async def playlist(self, ctx: Context,
                       channel_id: str = None, threshold: int = 40) -> None:
        """ Play a random playlist from archived songs
        for a SiriusXM channel. Can use comma seperated list of channel_ids
        to play from multiple channels (max 5 channels) """

        channel = ctx.message.channel
        author = ctx.message.author

        if author.voice is None:
            self._log.debug('playlist: no channel')
            await channel.send(
                f'{author.mention}, you are not in a voice channel.')
            return

        if channel_id is None:
            self._log.debug('playlist: missing')
            await channel.send(f'{author.mention}, missing channel id.')
            return

        channel_ids = channel_id.split(',')
        xm_channels = []
        for channel_id in channel_ids:
            xm_channel = self._state.xm_state.get_channel(channel_id)
            if xm_channel is None:
                self._log.debug('playlist: invalid')
                await channel.send(
                    f'{author.mention}, `{channel_id}` is invalid')
                return
            xm_channels.append(xm_channel)

        if len(xm_channels) > 5:
            self._log.debug('playlist: too many')
            await channel.send(f'{author.mention}, too many channel IDs')
            return

        channel_ids = [x.id for x in xm_channels]
        unique_songs = self._state.xm_state.db\
            .query(Song.title, Song.artist)\
            .filter(Song.channel.in_(channel_ids))\
            .distinct().all()

        if len(unique_songs) < threshold:
            self._log.debug('playlist: threshold')
            await channel.send(
                f'{author.mention}, `{channel_id}` does not have '
                f'enough archived songs'
            )
            return

        if self._state.player.is_playing:
            await self._state.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        try:
            await self._state.player.add_playlist(xm_channels)
        except Exception:
            self._log.error('error while trying to create playlist:')
            self._log.error(traceback.format_exc())
            await self._state.player.stop()
            await channel.send(
                f'{author.mention}, something went wrong starting playlist')
        else:
            if len(xm_channels) == 1:
                await channel.send(
                    f'{author.mention} starting playing a playlist of random '
                    f'songs from **{xm_channel.pretty_name}** in '
                    f'**{author.voice.channel.mention}**'
                )
            else:
                channel_nums = ', '.join(
                    [f'#{x.channel_number}' for x in xm_channels])
                await channel.send(
                    f'{author.mention} starting playing a playlist of random '
                    f'songs from **{channel_nums}** in '
                    f'**{author.voice.channel.mention}**'
                )

    @command(pass_context=True, no_pm=True)
    async def upcoming(self, ctx: Context) -> None:
        """ Displaying the songs/shows on play queue. Does not
        work for live SiriusXM radio """

        channel = ctx.message.channel
        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.player.is_playing:
            self._log.debug('upcoming: nothing')
            await channel.send(f'{author.mention}, nothing is playing')
            return

        if self._state.xm_state.active_channel_id is not None:
            await channel.send(
                f'{author.mention}, live radio playing, cannot get upcoming')
        else:
            message = (
                f'{author.mention}\n\n'
                f'Upcoming songs/shows:\n\n'
            )

            index = 1
            for item in self._state.player.upcoming:
                if item == self._state.player.current:
                    message += f'next: {item.bold_name}\n'
                else:
                    message += f'{index}: {item.bold_name}\n'
                index += 1

            await channel.send(message)


def run_bot(prefix: str, description: str, state_dict: dict,
            token: str, port: int) -> None:
    """ Runs SiriusXM Discord bot """

    bot = Bot(
        command_prefix=prefix,
        description=description,
        pm_help=True
    )
    bot.add_cog(SiriusXMBotCog(bot, state_dict, port))

    if state_dict['output'] is None:
        bot.remove_command('songs')
        bot.remove_command('song')
        bot.remove_command('shows')
        bot.remove_command('show')
        bot.remove_command('skip')
        bot.remove_command('playlist')
        bot.remove_command('upcoming')

    logger = logging.getLogger('discord_siriusxm.bot')

    @bot.event
    async def on_ready() -> None:
        logger.info(f'logged in as {bot.user} (id: {bot.user.id})')

    @bot.event
    async def on_message(message: Message) -> None:
        ctx = await bot.get_context(message)
        author = ctx.message.author
        can_error = False

        if message.content.startswith(prefix.strip()):
            can_error = True
            await ctx.message.delete()

        if ctx.valid:
            logger.info(f'{author}: {message.content}')
            await bot.invoke(ctx)
        elif can_error:
            logger.info(
                f'{author}: invalid command: {message.content}')
            await ctx.message.channel.send(
                f'{author.mention}, invalid command. Use `{prefix}help` '
                'for a list of commands'
            )

    bot.run(token)
