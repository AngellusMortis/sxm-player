import asyncio
import logging

import discord
from discord.ext import commands as discord_commands
from sxm.models import XMImage, XMSong
from tabulate import tabulate

from .models import BotState


class SiriusXMActivity(discord.Game):
    def __init__(self, start, channel, live_channel, **kwargs):
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

        self.update_status(channel, live_channel)

    def update_status(self, channel, live_channel):
        self.state = "Playing music from SiriusXM"
        self.name = f'SiriusXM {channel.pretty_name}'
        self.large_image_url = None
        self.large_image_text = None

        latest_cut = live_channel.get_latest_cut()
        if latest_cut is not None and isinstance(latest_cut.cut, XMSong):
            song = latest_cut.cut
            self.name = (
                f'"{song.title}" by {song.artists[0].name} on {self.name}')

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

    def __init__(self, bot, state, port):
        self._bot = bot
        self._state = BotState(state)
        self._log = logging.getLogger('discord_siriusxm.bot')
        self._proxy_base = f'http://127.0.0.1:{port}'

        self._bot.loop.create_task(self.status_update())

    def __unload(self):
        pass

    async def status_update(self):
        await self._bot.wait_until_ready()

        while not self._bot.is_closed():
            activity = None
            if self._state.is_playing and \
                    self._state.xm_state.live is not None:
                channel = self._state.xm_state.get_channel(
                    self._state.xm_state.active_channel_id)

                activity = SiriusXMActivity(
                    start=self._state.xm_state.start_time,
                    channel=channel,
                    live_channel=self._state.xm_state.live,
                )

            await self._bot.change_presence(activity=activity)
            await asyncio.sleep(1)

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
        if self._state.voice is None:
            self._log.debug(
                f'connecting to new voice channel: {summoned_channel.id}')
            self._state.voice = await summoned_channel.connect()
        else:
            self._log.debug(
                f'moving to voice channel: {summoned_channel.id}')
            await self._state.voice.move_to(summoned_channel)

        return True

    @discord_commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx, amount: float = None):
        """Changes the volume of the music that is being played. 1.0 = 100%
        """
        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.is_playing:
            self._log.debug('volume: nothing is playing')
            await channel.send(
                f'{author.mention}, cannot get/set the volume. '
                f'Nothing is playing'
            )
        elif amount is None:
            self._log.debug(
                f'volume: {self._state.source.volume}')
            await channel.send(
                f'{author.mention}, volume is currently '
                f'{self._state.source.volume}'
            )
        elif amount < 0.0 or amount > 1.0:
            self._log.debug(
                f'volume: invalid amount')
            await channel.send(
                f'{author.mention}, invalid volume amount. Must be between '
                f'0.0 and 1.0 (1.0 = 100% max volume)'
            )
        else:
            self._log.debug(
                f'volume: set {amount}')
            self._state.source.volume = amount
            await channel.send(
                f'{author.mention}, set volume to {amount}')

    @discord_commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        channel = ctx.message.channel
        author = ctx.message.author

        if self._state.is_playing:
            self._state.source.cleanup()
            await self._state.voice.disconnect()
            self._state.source = None
            self._state.voice = None
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

        if self._state.voice is None:
            self._log.debug('kick: nothing')
            await channel.send(
                f'{author.mention}, cannot kick. Not in a voice channel')
        elif author.voice is None or \
                self._state.voice.channel.id != author.voice.channel.id:
            self._log.debug('kick: invalid room')
            await channel.send(
                f'{author.mention}, cannot kick. Not in your voice channel')
        elif self._state.is_playing:
            await ctx.invoke(self.stop)
        else:
            self._log.debug(f'kick: {self._state.voice.channel.id}')
            await self._state.voice.disconnect()
            self._state.voice = None

    @discord_commands.command(pass_context=True, no_pm=True)
    async def play(self, ctx, *, channel_id: str = None):
        """Plays a specific SiriusXM channel"""
        channel = ctx.message.channel
        author = ctx.message.author

        if channel_id is None:
            self._log.debug('play: missing')
            await channel.send(f'{author.mention}, missing channel id.')
            return

        xm_channel = self._state.xm_state.get_channel(channel_id)
        if xm_channel is None:
            self._log.debug('play: invalid')
            await channel.send(f'{author.mention}, `{channel_id}` is invalid')
            return

        xm_url = f'{self._proxy_base}/{xm_channel.id}.m3u8'
        if not self._state.is_playing:
            await ctx.invoke(self.summon)
        if self._state.source is not None:
            self._state.xm_state.reset_channel()
            self._state.voice.stop()
            self._state.source.cleanup()
            self._state.source = None
            await asyncio.sleep(0.5)

        try:
            self._state.source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(xm_url, before_options='-f hls'),
                volume=0.5
            )
            self._state.voice.play(self._state.source)
        except Exception as e:
            await self._state.voice.disconnect()
            await channel.send(
                f'{author.mention}, something went wrong starting stream')
            self._log.error(f'{type(e).__name__}: {e}')
        else:
            self._state.xm_state.set_channel(xm_channel.id)
            self._log.debug(
                f'play: {xm_channel.pretty_name}: {author.voice.channel.id}')
            await channel.send(
                f'{author.mention} starting playing '
                f'**{xm_channel.pretty_name}** in '
                f'**{author.voice.channel.mention}**'
            )

    @discord_commands.command(pass_context=True, no_pm=True)
    async def np(self, ctx):
        """Responds with what the bot currently playing"""
        channel = ctx.message.channel
        author = ctx.message.author

        if not self._state.is_playing:
            self._log.debug('np: nothing')
            await channel.send(f'{author.mention}, nothing is playing')
            return

        xm_channel = self._state.xm_state.get_channel(
            self._state.xm_state.active_channel_id)
        cut = self._state.xm_state.live.get_latest_cut()
        episode = self._state.xm_state.live.get_latest_episode()

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
            embed.add_field(name="Show", value=np_episode_title, inline=True)

        await channel.send(author.mention, embed=embed)


def run_bot(prefix, description, state, token, port):
    bot = discord_commands.Bot(
        command_prefix=prefix,
        description=description,
        pm_help=True
    )
    bot.add_cog(SiriusXMBotCog(bot, state, port))
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
