import asyncio
import datetime
import os
import traceback
from typing import Optional, Union

from discord import Embed, Message, TextChannel
from discord.ext.commands import Bot, Command, Context, Group, command, errors
from humanize import naturaltime
from sqlalchemy import or_
from tabulate import tabulate

from sxm.models import XMImage, XMSong
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount
from plexapi.exceptions import BadRequest, NotFound
from plexapi.audio import Track

from ...models import Episode, Song
from ...player import AudioPlayer, RepeatSetException
from ..base import BaseRunner
from .checks import is_playing, require_matching_voice, require_voice
from .converters import (
    CountConverter,
    VolumeConverter,
    XMChannelConverter,
    XMChannelListConverter,
)
from .utils import send_message

__all__ = ["BotRunner"]


class MusicCommand(Command):
    @property
    def cog_name(self):
        return "Music"


class MusicPlayerGroup(Group):
    @property
    def cog_name(self):
        return "Music Player"


class PlexComand(Command):
    @property
    def cog_name(self):
        return "Plex Player"


class SXMCommand(Command):
    @property
    def cog_name(self):
        return "SiriusXM Player"


class BotRunner(BaseRunner):
    """ Discord Bot to play SiriusXM content """

    bot: Bot
    player: AudioPlayer
    prefix: str
    token: str
    plex_library: Union[None, PlexServer] = None

    def __init__(
        self,
        prefix: str,
        description: str,
        token: str,
        plex_username: Union[str, None] = None,
        plex_password: Union[str, None] = None,
        plex_server_name: Union[str, None] = None,
        plex_library_name: Union[str, None] = None,
        *args,
        **kwargs,
    ):
        kwargs["name"] = "bot"
        super().__init__(*args, **kwargs)

        self.prefix = prefix
        self.token = token
        self.bot = Bot(
            command_prefix=self.prefix, description=description, pm_help=True
        )
        self.bot.add_cog(self)

        self.bot.cogs["SiriusXM"] = self.bot.cogs.pop("BotRunner")

        self.player = AudioPlayer(self.bot, self.state)

        if (
            plex_username is not None
            and plex_password is not None
            and plex_server_name is not None
            and plex_library_name is not None
        ):
            self.plex_library = self._get_plex_server(
                plex_username,
                plex_password,
                plex_server_name,
                plex_library_name,
            )

        if self.state.output is None:
            self.bot.remove_command("songs")
            self.bot.remove_command("song")
            self.bot.remove_command("shows")
            self.bot.remove_command("show")
            self.bot.remove_command("skip")
            self.bot.remove_command("playlist")
            self.bot.remove_command("upcoming")

        if self.plex_library is None:
            self.bot.remove_command("plex")

    def __unload(self):
        if self.player is not None:
            self.bot.loop.create_task(self.player.stop())

    # method overrides
    def run(self):
        self._log.info("bot runner has started")
        self.bot.run(self.token)

    # Discord event handlers
    async def on_ready(self) -> None:
        user = self.bot.user
        self._log.info(f"logged in as {user} (id: {user.id})")

    async def on_command_error(
        self, ctx: Context, error: errors.CommandError
    ) -> None:
        if isinstance(error, errors.BadArgument):
            message = f"`{self.prefix}{ctx.command.name}`: {error.args[0]}"
            await send_message(ctx, message)
        elif isinstance(error, errors.CommandNotFound):
            self._log.info(
                f"{ctx.message.author}: invalid command: {ctx.message.content}"
            )
            await self._invalid_command(ctx)

        elif isinstance(error, errors.MissingRequiredArgument):
            self._log.info(
                f"{ctx.message.author}: missing arg: {ctx.message.content}"
            )

            arg = str(error).split(" ")[0]
            arg = arg.replace("xm_channel", "channel_id")

            message = f"`{ctx.message.content}`: `{arg}` is missing"
            await send_message(ctx, message)
        elif not isinstance(error, errors.CheckFailure):
            self._log.error(f"{type(error)}: {error}")
            await send_message(ctx, "something went wrong ☹")

    async def on_message(self, message: Message) -> None:
        ctx = await self.bot.get_context(message)
        author = ctx.message.author

        if message.content.startswith(self.prefix.strip()):
            if isinstance(ctx.message.channel, TextChannel):
                await ctx.message.delete()

        if ctx.valid:
            self._log.info(f"{author}: {message.content}")
        elif message.content == self.prefix.strip():
            await self._invalid_command(ctx)

    async def __before_invoke(self, ctx: Context) -> None:
        if self.state.runners.get("server") is None:
            raise errors.CommandError("SiriusXM server is not running yet")

    # helper methods
    def _get_plex_server(
        self, username: str, password: str, server_name: str, library_name: str
    ):
        try:
            account = MyPlexAccount(username, password)
        except BadRequest:
            self._log.error(
                "Bad Plex username or password, Plex integration disabled"
            )
            return None

        try:
            server = account.resource(server_name).connect(ssl=True)
        except NotFound:
            self._log.error("Bad Plex server name, Plex integration disabled")
            return None

        try:
            library = server.library.section(library_name)
        except NotFound:
            self._log.error("Bad Plex library name, Plex integration disabled")
            return None

        return library

    async def _invalid_command(self, ctx: Context, group: str = ""):
        help_command = f"{self.prefix}help {group}".strip()
        message = (
            f"`{ctx.message.content}`: invalid command. "
            f"Use `{help_command}` for a list of commands"
        )
        await send_message(ctx, message)

    async def _play_archive_file(
        self, ctx: Context, guid: str = None, is_song: bool = False
    ) -> None:
        """ Quues a song/show file from SiriusXM archive to be played"""

        channel = ctx.message.channel
        author = ctx.message.author
        search_type = "shows"
        if is_song:
            search_type = "songs"

        if author.voice is None:
            await channel.send(
                f"{author.mention}, you are not in a voice channel."
            )
            return

        if guid is None:
            await channel.send(
                f"{author.mention}, please provide a {search_type} id"
            )
            return

        db_item = None
        if self.state.db is not None:
            if is_song:
                db_item = (
                    self.state.db.query(Song).filter_by(guid=guid).first()
                )
            else:
                db_item = (
                    self.state.db.query(Episode).filter_by(guid=guid).first()
                )

        if db_item is not None and not os.path.exists(db_item.file_path):
            self._log.warn(f"file does not exist: {db_item.file_path}")
            db_item = None

        if db_item is None:
            await channel.send(f"{author.mention}, invalid {search_type} id")
            return

        await self._play_file(ctx, db_item)

    async def _play_plex_file(
        self, ctx: Context, item: Track, message: bool = True
    ) -> None:
        """ Queues a file from Plex to be played """

        song = Song()
        song.title = item.title
        song.artist = item.artist().title
        song.album = item.album().title
        song.file_path = item.media[0].parts[0].file

        await self._play_file(ctx, song, message=message)

    async def _play_file(
        self, ctx: Context, item: Union[Song, Episode], message: bool = True
    ) -> None:
        """ Queues a file to be played """

        if not self.player.is_playing:
            await ctx.invoke(self.summon)

        if self.state.active_channel_id is not None:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)

        try:
            self._log.info(f"play: {item.file_path}")
            await self.player.add_file(item)
        except Exception:
            self._log.error("error while trying to add file to play queue:")
            self._log.error(traceback.format_exc())
        else:
            if message:
                await send_message(
                    ctx, f"added {item.bold_name} to now playing queue"
                )

    async def _search_archive(
        self, ctx: Context, search: str, is_song: bool
    ) -> None:
        """ Searches song/show database and responds with results """

        search_type = "shows"
        if is_song:
            search_type = "songs"

        items = None
        if is_song:
            items = (
                self.state.db.query(Song)  # type: ignore
                .filter(
                    or_(
                        Song.guid.ilike(f"{search}%"),  # type: ignore
                        Song.title.ilike(f"{search}%"),  # type: ignore
                        Song.artist.ilike(f"{search}%"),  # type: ignore
                    )
                )
                .order_by(Song.air_time.desc())[:10]  # type: ignore
            )
        else:
            items = (
                self.state.db.query(Episode)  # type: ignore
                .filter(
                    or_(
                        Episode.guid.ilike(f"{search}%"),  # type: ignore
                        Episode.title.ilike(f"{search}%"),  # type: ignore
                        Episode.show.ilike(f"{search}%"),  # type: ignore
                    )
                )
                .order_by(Episode.air_time.desc())[:10]  # type: ignore
            )
        if len(items) > 0:
            message = f"{search_type.title()} matching `{search}`:\n\n"
            for item in items:
                message += f"{item.guid}: {item.bold_name}\n"

            await send_message(ctx, message, sep="\n\n")
        else:
            await send_message(
                ctx, f"no {search_type} results found for `{search}`"
            )

    async def _sxm_now_playing(self, ctx: Context) -> None:
        """ Sends message for what is currently playing on the
        SiriusXM HLS live stream """

        xm_channel = self.state.get_channel(self.state.active_channel_id)

        if xm_channel is None or self.player.voice is None:
            return

        if self.state.live is not None:
            cut = self.state.live.get_latest_cut(now=self.state.radio_time)
            episode = self.state.live.get_latest_episode(
                now=self.state.radio_time
            )

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
                        if art.size is not None and art.size == "MEDIUM":
                            np_thumbnail = art.url

        if episode is not None:
            episode = episode.episode
            np_episode_title = episode.long_title

            if np_thumbnail is None:
                for art in episode.show.arts:
                    if (
                        art.height > 100
                        and art.height < 200
                        and art.height == art.width
                    ):
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
            name="SiriusXM", value=xm_channel.pretty_name, inline=True
        )
        if np_episode_title is not None:
            embed.add_field(name="Show", value=np_episode_title, inline=True)

        message = (
            f"currently playing **{xm_channel.pretty_name}** on "
            f"**{self.player.voice.channel.mention}**"
        )
        await send_message(ctx, message, embed=embed)

    async def _sxm_recent(self, ctx: Context, count: int) -> None:
        """ Respons with what has recently played on the
        SiriusXM HLS live stream """

        xm_channel = self.state.get_channel(self.state.active_channel_id)

        if self.state.live is None or xm_channel is None:
            return

        song_cuts = []
        now = self.state.radio_time
        latest_cut = self.state.live.get_latest_cut(now)

        for song_cut in reversed(self.state.live.song_cuts):
            if song_cut == latest_cut:
                song_cuts.append(song_cut)
                continue

            end = int(song_cut.time + song_cut.duration)
            if self.state.start_time is not None:
                if song_cut.time < now and (
                    end > self.state.start_time
                    or song_cut.time > self.state.start_time
                ):
                    song_cuts.append(song_cut)

            if len(song_cuts) >= count:
                break

        if len(song_cuts) > 0:
            message = f"Recent songs for **{xm_channel.pretty_name}**:\n\n"

            for song_cut in song_cuts:
                seconds_ago = int((now - song_cut.time) / 1000)
                time_delta = datetime.timedelta(seconds=seconds_ago)
                time_string = naturaltime(time_delta)

                pretty_name = Song.get_pretty_name(
                    song_cut.cut.title, song_cut.cut.artists[0].name, True
                )
                if song_cut == latest_cut:
                    message += f"now: {pretty_name}\n"
                else:
                    message += f"about {time_string}: {pretty_name}\n"

            await send_message(ctx, message, sep="\n\n")
        else:
            await send_message(ctx, "no recent songs played")

    @command(pass_context=True, cls=MusicCommand)
    async def playing(self, ctx: Context) -> None:
        """Responds with what the bot currently playing"""

        if not await is_playing(ctx):
            return

        if self.state.active_channel_id is not None:
            await self._sxm_now_playing(ctx)
        else:
            await send_message(
                ctx,
                (
                    f"current playing {self.player.current.bold_name} on "
                    f"**{self.player.voice.channel.mention}**"
                ),
            )

    @command(pass_context=True, cls=MusicCommand)
    async def recent(  # type: ignore
        self, ctx: Context, count: CountConverter = 3
    ) -> None:
        """Responds with the last 1-10 songs that been
        played on this channel"""

        if not await is_playing(ctx):
            return

        if self.state.active_channel_id is not None:
            await self._sxm_recent(ctx, count)
        else:
            message = f"Recent songs/shows:\n\n"

            index = 0
            for item in self.player.recent[:count]:
                if item == self.player.current:
                    message += f"now: {item.bold_name}\n"
                else:
                    message += f"{index}: {item.bold_name}\n"
                index -= 1

            await send_message(ctx, message, sep="\n\n")

    @command(pass_context=True, cls=MusicCommand)
    async def repeat(
        self, ctx: Context, do_repeat: Union[bool, None] = None
    ) -> None:
        """Sets/Unsets play queue to repeat infinitely"""

        if not await is_playing(ctx):
            return

        if do_repeat is None:
            status = "on" if self.player.repeat else "off"
            await send_message(ctx, f"repeat is currrently {status}")
        else:
            try:
                self.player.repeat = do_repeat
            except RepeatSetException as e:
                await send_message(ctx, str(e))
            else:
                status = "on" if self.player.repeat else "off"
                await send_message(ctx, f"set repeat to {status}")

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def reset(self, ctx: Context) -> None:
        """Forces bot to leave voice"""

        if not await require_voice(ctx):
            return

        await ctx.invoke(self.summon)
        await self.player.stop()

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def skip(self, ctx: Context) -> None:
        """Skips current song. Does not work for SiriusXM"""

        if not await is_playing(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if self.state.active_channel_id is not None:
            await channel.send(
                f"{author.mention}, cannot skip. " f"SiriusXM radio is playing"
            )
            return

        await self.player.skip()

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def stop(self, ctx: Context) -> None:
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """

        if not await is_playing(ctx):
            return

        await self.player.stop()
        await ctx.message.channel.send(
            f"{ctx.message.author.mention} stopped playing music"
        )

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def summon(self, ctx: Context) -> None:
        """Summons the bot to join your voice channel"""

        if not await require_voice(ctx):
            return

        summoned_channel = ctx.message.author.voice.channel
        await self.player.set_voice(summoned_channel)

    @command(pass_context=True, cls=MusicCommand)
    async def upcoming(self, ctx: Context) -> None:
        """ Displaying the songs/shows on play queue. Does not
        work for live SiriusXM radio """

        if not await is_playing(ctx):
            return

        if self.state.active_channel_id is not None:
            await send_message(ctx, "live radio playing, cannot get upcoming")
        else:
            message = f"Upcoming songs/shows:\n\n"

            index = 1
            for item in self.player.upcoming:
                if item == self.player.current:
                    message += f"next: {item.bold_name}\n"
                else:
                    message += f"{index}: {item.bold_name}\n"
                index += 1

            await send_message(ctx, message, sep="\n\n")

    @command(pass_context=True, no_pm=True, cls=MusicCommand)
    async def volume(
        self, ctx: Context, amount: VolumeConverter = None
    ) -> None:
        """Changes the volume of music
        """

        if not await require_matching_voice(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if amount is None:
            await channel.send(
                f"{author.mention}, volume is currently "
                f"{int(self.player.volume * 100)}%"
            )
        else:
            self.player.volume = amount
            await channel.send(
                f"{author.mention}, set volume to "
                f"{int(self.player.volume * 100)}%"
            )

    @command(cls=MusicPlayerGroup)
    async def plex(self, ctx: Context) -> None:
        """Command for playing local music from Plex"""
        if ctx.invoked_subcommand is None:
            await self._invalid_command(ctx, group="plex")

    @plex.command(name="album", cls=PlexComand)
    async def plex_album(
        self, ctx: Context, search: str, play_index: Union[int, None] = None
    ) -> None:
        """Plays an album from Plex library"""

        if not await require_voice(ctx) or self.plex_library is None:
            return

        items = self.plex_library.searchAlbums(title=search, maxresults=10)

        if len(items) > 1 and play_index is not None:
            try:
                items = [items[play_index]]
            except KeyError:
                send_message(
                    ctx, f"Invalid `{play_index}` for search `{search}`"
                )

        if len(items) == 1:
            await send_message(
                ctx,
                (
                    f"added the album **{items[0].title}** by "
                    f"**{items[0].artist().title}** to now "
                    f"playing queue"
                ),
            )
            for track in items[0].tracks():
                await self._play_plex_file(ctx, track, message=False)
        elif len(items) > 1:
            message = (
                f"Multiple albums match `{search}`. Use "
                f"`{self.prefix}plex album {search} #` to pick which "
                f"to play\n\n"
            )
            index = 0
            for item in items:
                message += (
                    f"{index}: **{item.title}** by {item.artist().title}\n"
                )
                index += 1

            await send_message(ctx, message, sep="\n\n")
        else:
            await send_message(ctx, f"no song results found for `{search}`")

    @plex.command(name="song", cls=PlexComand)
    async def plex_song(
        self, ctx: Context, search: str, play_index: Union[int, None] = None
    ) -> None:
        """Plays a song from Plex library"""

        if not await require_voice(ctx) or self.plex_library is None:
            return

        items = self.plex_library.searchTracks(title=search, maxresults=10)

        if len(items) > 1 and play_index is not None:
            try:
                items = [items[play_index]]
            except KeyError:
                send_message(
                    ctx, f"Invalid `{play_index}` for search `{search}`"
                )

        if len(items) == 1:
            await self._play_plex_file(ctx, items[0])
        elif len(items) > 1:
            message = (
                f"Multiple songs match `{search}`. Use "
                f"`{self.prefix}plex song {search} #` to pick which "
                f"to play\n\n"
            )
            index = 0
            for item in items:
                message += (
                    f"{index}: **{item.title}** by {item.artist().title}\n"
                )
                index += 1

            await send_message(ctx, message, sep="\n\n")
        else:
            await send_message(ctx, f"no song results found for `{search}`")

    @command(cls=MusicPlayerGroup)
    async def sxm(self, ctx: Context) -> None:
        """Command for playing music from SiriusXM"""
        if ctx.invoked_subcommand is None:
            await self._invalid_command(ctx, group="sxm")

    @sxm.command(name="channel", pass_context=True, no_pm=True, cls=SXMCommand)
    async def sxm_channel(
        self, ctx: Context, *, xm_channel: XMChannelConverter
    ) -> None:
        """Plays a specific SiriusXM channel"""

        if not await require_voice(ctx):
            return

        channel = ctx.message.channel
        author = ctx.message.author

        if self.player.is_playing:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        log_archive = ""
        if self.state.stream_folder is not None:
            log_archive = f": archiving"

        try:
            self._log.info(f"play{log_archive}: {xm_channel.id}")
            await self.player.add_live_stream(xm_channel)
        except Exception:
            self._log.error("error while trying to add channel to play queue:")
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await channel.send(
                f"{author.mention}, something went wrong starting stream"
            )
        else:
            await channel.send(
                f"{author.mention} starting playing "
                f"**{xm_channel.pretty_name}** in "
                f"**{author.voice.channel.mention}**"
            )

    @sxm.command(name="channels", pass_context=True, cls=SXMCommand)
    async def sxm_channels(self, ctx: Context) -> None:
        """Bot will PM with list of possible SiriusXM channel"""

        author = ctx.message.author

        display_channels = []
        for channel in self.state.channels:
            display_channels.append(
                [
                    channel.id,
                    channel.channel_number,
                    channel.name,
                    channel.short_description,
                ]
            )

        channel_table = tabulate(
            display_channels, headers=["ID", "#", "Name", "Description"]
        )

        self._log.debug(f"sending {len(display_channels)} for {author}")
        await author.send("SiriusXM Channels:")
        while len(channel_table) > 0:
            message = ""
            if len(channel_table) < 2000:
                message = channel_table
                channel_table = ""
            else:
                index = channel_table[:2000].rfind("\n")
                message = channel_table[:index]
                start = index + 1
                channel_table = channel_table[start:]

            await author.send(f"```{message}```")

    @sxm.command(
        name="playlist", pass_context=True, no_pm=True, cls=SXMCommand
    )
    async def sxm_playlist(
        self,
        ctx: Context,
        xm_channels: XMChannelListConverter,
        threshold: int = 40,
    ) -> None:
        """ Play a random playlist from archived songs
        for a SiriusXM channel. Can use comma seperated list of channel_ids
        to play from multiple channels (max 5 channels) """

        if not await require_voice(ctx):
            return

        if self.state.db is None:
            return

        channel_ids = [x.id for x in xm_channels]
        unique_songs = self.state.db.query(Song.title, Song.artist).filter(
            Song.channel.in_(channel_ids)  # type: ignore
        )
        unique_songs = unique_songs.distinct().all()

        if len(unique_songs) < threshold:
            await send_message(
                ctx, "not enough archived songs in provided channels"
            )
            return

        if self.player.is_playing:
            await self.player.stop(disconnect=False)
            await asyncio.sleep(0.5)
        else:
            await ctx.invoke(self.summon)

        try:
            await self.player.add_playlist(xm_channels)
        except Exception:
            self._log.error("error while trying to create playlist:")
            self._log.error(traceback.format_exc())
            await self.player.stop()
            await send_message(ctx, "something went wrong starting playlist")
        else:
            if len(xm_channels) == 1:
                await ctx.message.channel.send(
                    f"{ctx.message.author.mention} starting playing a "
                    f"playlist of random songs from "
                    f"**{xm_channels[0].pretty_name}** in "
                    f"**{ctx.message.author.voice.channel.mention}**"
                )
            else:
                channel_nums = ", ".join(
                    [f"#{x.channel_number}" for x in xm_channels]
                )
                await ctx.message.channel.send(
                    f"{ctx.message.author.mention} starting playing a "
                    f"playlist of random songs from **{channel_nums}** in "
                    f"**{ctx.message.author.voice.channel.mention}**"
                )

    @sxm.command(name="show", pass_context=True, no_pm=True, cls=SXMCommand)
    async def sxm_show(
        self, ctx: Context, show_id: Optional[str] = None
    ) -> None:
        """Adds a show to a play queue"""

        await self._play_archive_file(ctx, show_id, False)

    @sxm.command(name="shows", pass_context=True, cls=SXMCommand)
    async def sxm_shows(self, ctx: Context, search: str) -> None:
        """Searches for an archived show to play.
        Only returns the first 10 shows"""

        await self._search_archive(ctx, search, False)

    @sxm.command(name="song", pass_context=True, no_pm=True, cls=SXMCommand)
    async def sxm_song(
        self, ctx: Context, song_id: Optional[str] = None
    ) -> None:
        """Adds a song to a play queue"""

        await self._play_archive_file(ctx, song_id, True)

    @sxm.command(name="songs", pass_context=True, cls=SXMCommand)
    async def sxm_songs(self, ctx: Context, search: str) -> None:
        """Searches for an archived song to play.
        Only returns the first 10 songs"""

        await self._search_archive(ctx, search, True)
