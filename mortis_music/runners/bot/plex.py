import logging
from typing import Union

from discord.ext.commands import Context, command
from plexapi.audio import Track
from plexapi.exceptions import BadRequest, NotFound
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from ...models import Episode, Song
from .checks import require_voice
from .models import MusicPlayerGroup, PlexCommand
from .utils import send_message


class PlexCommands:
    _log: logging.Logger

    prefix: str
    plex_library: Union[None, PlexServer]

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

    async def _invalid_command(self, ctx: Context, group: str = "") -> None:
        raise NotImplementedError()

    async def _play_file(
        self, ctx: Context, item: Union[Song, Episode], message: bool = True
    ) -> None:
        raise NotImplementedError()

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

    @command(cls=MusicPlayerGroup)
    async def plex(self, ctx: Context) -> None:
        """Command for playing local music from Plex"""
        if ctx.invoked_subcommand is None:
            await self._invalid_command(ctx, group="plex")

    @plex.command(name="album", cls=PlexCommand)
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

    @plex.command(name="song", cls=PlexCommand)
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
