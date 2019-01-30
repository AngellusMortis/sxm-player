import asyncio
import traceback
from typing import Union

from discord import Message, TextChannel
from discord.ext.commands import Bot, Context, command, errors
from plexapi.server import PlexServer

from ...models import Episode, Song
from ..base import BaseRunner
from .checks import is_playing, require_matching_voice, require_voice
from .converters import CountConverter, VolumeConverter
from .models import MusicCommand
from .player import AudioPlayer, RepeatSetException
from .plex import PlexCommands
from .sxm import SXMCommands
from .utils import send_message


class BotRunner(BaseRunner, PlexCommands, SXMCommands):
    """ Discord Bot to play music """

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

    async def __before_invoke(self, ctx: Context) -> None:
        if self.state.runners.get("server") is None:
            raise errors.CommandError("SiriusXM server is not running yet")

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

    # helper methods
    async def _invalid_command(self, ctx: Context, group: str = ""):
        help_command = f"{self.prefix}help {group}".strip()
        message = (
            f"`{ctx.message.content}`: invalid command. "
            f"Use `{help_command}` for a list of commands"
        )
        await send_message(ctx, message)

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
