import asyncio
import datetime
import logging
import os
import time

import discord
import humanize
from discord.ext import commands as discord_commands
from tabulate import tabulate

from sqlalchemy import or_
from sxm.models import XMImage, XMSong

from .models import BotState, Episode, Song
from .player import FFmpegPCMAudio
from .processor import init_db


class SiriusXMActivity(discord.Game):
    def __init__(self, start, radio_time, channel, live_channel, **kwargs):
        self.timestamps = {'start': start}
        self._start = start
        self.details = 'Test'

        self.assets = kwargs.pop('assets', {})
        self.party = kwargs.pop('party', {})
        self.application_id = kwargs.pop('application_id', None)
        self.url = kwargs.pop('url', None)
        self.flags = kwargs.pop('flags', 0)
        self.sync_id = kwargs.pop('sync_id', None)
        self.session_id = kwargs.pop('session_id', None)
        self._end = 0

        self.update_status(channel, live_channel, radio_time)

    def update_status(self, channel, live_channel, radio_time):
        self.state = "Playing music from SiriusXM"
        self.name = f'SiriusXM {channel.pretty_name}'
        self.large_image_url = None
        self.large_image_text = None

        latest_cut = live_channel.get_latest_cut(now=radio_time)
        if latest_cut is not None and isinstance(latest_cut.cut, XMSong):
            song = latest_cut.cut
            pretty_name = Song.get_pretty_name(
                song.title, song.artists[0].name)
            self.name = (
                f'{pretty_name} on {self.name}')

            if song.album is not None:
                album = song.album
                if album.title is not None:
                    self.large_image_text = (
                        f'{album.title} by {song.artists[0].name}')

                for art in album.arts:
                    if isinstance(art, XMImage):
                        if art.size is not None and art.size == 'MEDIUM':
                            self.large_image_url = art.url


class SiriusXMBotCog:
    """Discord bot cog for SiriusXM radio bot
    """

    _xm = None
    _bot = None
    _state = None
    _output_folder = None

    def __init__(self, bot, state, port, output_folder):
        self._bot = bot
        self._state = BotState(state, bot)
        self._log = logging.getLogger('discord_siriusxm.bot')
        self._proxy_base = f'http://127.0.0.1:{port}'
        self._output_folder = output_folder

        if self._output_folder is not None:
            self._output_folder = os.path.join(self._output_folder, 'streams')

        self._bot.loop.create_task(self.status_update())

    def __unload(self):
        if self._state.player is not None:
            self._bot.loop.create_task(self._state.player.stop())
        self._state.xm_state.reset_channel()

    async def status_update(self):
        await self._bot.wait_until_ready()

        sleep_time = 10
        while not self._bot.is_closed():
            await asyncio.sleep(sleep_time)
            sleep_time = 5

            activity = None
            if self._state.player.is_playing:
                if self._state.xm_state.active_channel_id is not None:
                    xm_channel = self._state.xm_state.get_channel(
                        self._state.xm_state.active_channel_id)

                    if self._state.xm_state.live is not None:
                        self._log.debug('status update: SiriusXM')
                        activity = SiriusXMActivity(
                            start=self._state.xm_state.start_time,
                            radio_time=self._state.xm_state.radio_time,
                            channel=xm_channel,
                            live_channel=self._state.xm_state.live,
                        )
                elif self._state.player.current is not None:
                    self._log.debug(
                        f'status update: {self._state.player.current}')
                    activity = discord.Game(
                        name=self._state.player.current.pretty_name)

            await self._bot.change_presence(activity=activity)

    @discord_commands.command(pass_context=True)
    async def channels(self, ctx):
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

    @discord_commands.command(pass_context=True, no_pm=True)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel"""
        author = ctx.message.author
        if author.voice is None:
            await ctx.message.channel.send(
                f'{author.mention}, you not in a voice channel.')
            return False

        summoned_channel = author.voice.channel
        await self._state.player.set_voice(summoned_channel)

    @discord_commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx, amount: float = None):
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

    @discord_commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        channel = ctx.message.channel
        author = ctx.message.author

        if self._state.player.is_playing:
            await self._state.player.stop()
            self._state.xm_state.reset_channel()

            self._log.debug('stop: stopped')
            await channel.send(f'{author.mention} stopped playing music')
        else:
            self._log.debug('stop: nothing')
            await channel.send(
                f'{author.mention}, cannot stop music. Nothing is playing')

    @discord_commands.command(pass_context=True, no_pm=True)
    async def kick(self, ctx):
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

    @discord_commands.command(pass_context=True, no_pm=True)
    async def channel(self, ctx, *, channel_id: str = None):
        """Plays a specific SiriusXM channel"""
        channel = ctx.message.channel
        author = ctx.message.author

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
        if self._output_folder is not None:
            log_archive = f': archiving'
            stream_file = os.path.join(
                self._output_folder, f'{xm_channel.id}.mp3')

            if os.path.exists(stream_file):
                os.remove(stream_file)

        try:
            self._log.info(f'play{log_archive}: {xm_channel.id}')
            source = FFmpegPCMAudio(
                xm_url,
                before_options='-f hls',
                after_options=stream_file,
            )
            stream_file = None
            await self._state.player.add(None, source, stream_file)
        except Exception as e:
            self._log.error(f'{type(e).__name__}: {e}')
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

    async def _sxm_now_playing(self, ctx):
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

        embed = discord.Embed(title=np_title)
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

    @discord_commands.command(pass_context=True, no_pm=True)
    async def playing(self, ctx):
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

    async def _sxm_recent(self, ctx, count):
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
                time_string = humanize.naturaltime(time_delta)

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

    @discord_commands.command(pass_context=True, no_pm=True)
    async def recent(self, ctx, count: int = 3):
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
                f'{author.mention}, invalid count, must be between 1 and 1, '
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

    def _get_db(self):
        return init_db(os.path.join(self._output_folder, '..', 'processed'))

    async def _search_archive(self, ctx, search, is_song):
        channel = ctx.message.channel
        author = ctx.message.author
        db = self._get_db()
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
            items = db.query(Song).filter(or_(
                Song.guid.ilike(f'{search}%'),
                Song.title.ilike(f'{search}%'),
                Song.artist.ilike(f'{search}%'),
            )).order_by(Song.air_time.desc())[:10]
        else:
            items = db.query(Episode).filter(or_(
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

    @discord_commands.command(pass_context=True, no_pm=True)
    async def songs(self, ctx, search: str = None):
        """Searches for an archived song to play.
        Only returns the first 10 songs"""

        await self._search_archive(ctx, search, True)

    @discord_commands.command(pass_context=True, no_pm=True)
    async def shows(self, ctx, search: str = None):
        """Searches for an archived show to play.
        Only returns the first 10 shows"""

        await self._search_archive(ctx, search, False)

    @discord_commands.command(pass_context=True, no_pm=True)
    async def song(self, ctx, song_id: str = None):
        """Adds a song to a play queue"""

        await self._play_file(ctx, song_id, True)

    @discord_commands.command(pass_context=True, no_pm=True)
    async def show(self, ctx, show_id: str = None):
        """Adds a show to a play queue"""

        await self._play_file(ctx, show_id, False)

    async def _play_file(self, ctx, guid, is_song):
        channel = ctx.message.channel
        author = ctx.message.author
        db = self._get_db()
        search_type = 'shows'
        if is_song:
            search_type = 'songs'

        if guid is None:
            self._log.debug(f'{search_type}: nothing')
            await channel.send(
                f'{author.mention}, please provide a {search_type} id'
            )
            return

        if not self._state.player.is_playing:
            await ctx.invoke(self.summon)

        if self._state.xm_state.active_channel_id is not None:
            self._state.xm_state.reset_channel()
            await self._state.player.stop(disconnect=False)
            await asyncio.sleep(0.5)

        db_item = None
        if is_song:
            db_item = db.query(Song).filter_by(guid=guid).first()
        else:
            db_item = db.query(Episode).filter_by(guid=guid).first()

        if db_item is not None and not os.path.exists(db_item.file_path):
            self._log.warn(f'file does not exist: {db_item.file_path}')
            db_item = None

        if db_item is None:
            await channel.send(
                f'{author.mention}, invalid {search_type} id'
            )

        try:
            self._log.info(f'play: {db_item.file_path}')
            source = FFmpegPCMAudio(
                db_item.file_path,
            )
            await self._state.player.add(db_item, source)
        except Exception as e:
            self._log.error(f'{type(e).__name__}: {e}')
        else:
            await channel.send(
                    f'{author.mention}, added {db_item.bold_name} '
                    f'to now playing queue'
                )

    @discord_commands.command(pass_context=True, no_pm=True)
    async def skip(self, ctx):
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


def run_bot(prefix, description, state, token, port, output_folder):
    bot = discord_commands.Bot(
        command_prefix=prefix,
        description=description,
        pm_help=True
    )
    bot.add_cog(SiriusXMBotCog(bot, state, port, output_folder))

    if output_folder is None:
        bot.remove_command('songs')
        # bot.remove_command('song')
        bot.remove_command('shows')
        # bot.remove_command('show')

    logger = logging.getLogger('discord_siriusxm.bot')

    @bot.event
    async def on_ready():
        logger.info(f'logged in as {bot.user} (id: {bot.user.id})')

    @bot.event
    async def on_message(message):
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
