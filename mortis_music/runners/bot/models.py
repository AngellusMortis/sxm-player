import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Union

from discord import AudioSource, FFmpegPCMAudio, Game
from discord.ext.commands import Command, CommandError, Group

from sxm.models import XMChannel, XMImage, XMLiveChannel, XMSong

from ...models import Song, Episode, XMState


@dataclass
class LiveStreamInfo:
    channel: XMChannel
    resetting: bool = False

    _counter: int = 0
    _reset_counter: int = 0

    def __init__(self, channel: XMChannel):
        self.channel = channel

    async def play(self, state: XMState) -> AudioSource:
        """ Plays FFmpeg livestream """

        self.resetting = True

        active_channel_id = state.active_channel_id
        if active_channel_id is not self.channel.id:
            state.set_channel(self.channel.id)

            start = time.time()
            now = start
            stream_url = None
            while stream_url is None and now - start < 30:
                await asyncio.sleep(0.1)
                now = time.time()
                if (now - start) > 5:
                    stream_url = state.stream_url

            if stream_url is None:
                raise CommandError("HLS stream not found")

        playback_source = FFmpegPCMAudio(
            stream_url,
            before_options="-f s16le -ar 48000 -ac 2",
            options="-loglevel fatal",
        )

        self.resetting = False

        return playback_source

    @property
    def is_reset_allowed(self):
        if self._reset_counter < 5:
            self._reset_counter += 1
            return True
        return False

    @property
    def is_live_missing(self):
        if self.resetting:
            return False

        # live channel is cached for ~50 seconds
        if self._counter < 12:
            self._counter += 1
            return False
        return True

    def reset_counters(self):
        self._counter = 0
        self._reset_counter = 0


class MusicCommand(Command):
    @property
    def cog_name(self):
        return "Music"


class MusicPlayerGroup(Group):
    @property
    def cog_name(self):
        return "Music Player"


class PlexCommand(Command):
    @property
    def cog_name(self):
        return "Plex Player"


class SXMCommand(Command):
    @property
    def cog_name(self):
        return "SiriusXM Player"


class SiriusXMActivity(Game):
    def __init__(
        self,
        start: Optional[int],
        radio_time: Optional[int],
        channel: XMChannel,
        live_channel: XMLiveChannel,
        **kwargs,
    ):

        self.timestamps = {"start": start}
        self._start = start
        self.details = "Test"

        self.assets = kwargs.pop("assets", {})
        self.party = kwargs.pop("party", {})
        self.application_id = kwargs.pop("application_id", None)
        self.url = kwargs.pop("url", None)
        self.flags = kwargs.pop("flags", 0)
        self.sync_id = kwargs.pop("sync_id", None)
        self.session_id = kwargs.pop("session_id", None)
        self._end = 0

        self.update_status(channel, live_channel, radio_time)

    def update_status(
        self,
        channel: XMChannel,
        live_channel: XMLiveChannel,
        radio_time: Optional[int],
    ) -> None:
        """ Updates activity object from current channel playing """

        self.state = "Playing music from SiriusXM"
        self.name = f"SiriusXM {channel.pretty_name}"
        self.large_image_url = None
        self.large_image_text = None

        latest_cut = live_channel.get_latest_cut(now=radio_time)
        if latest_cut is not None and isinstance(latest_cut.cut, XMSong):
            song = latest_cut.cut
            pretty_name = Song.get_pretty_name(
                song.title, song.artists[0].name
            )
            self.name = f"{pretty_name} on {self.name}"

            if song.album is not None:
                album = song.album
                if album.title is not None:
                    self.large_image_text = (
                        f"{album.title} by {song.artists[0].name}"
                    )

                for art in album.arts:
                    if isinstance(art, XMImage):
                        if art.size is not None and art.size == "MEDIUM":
                            self.large_image_url = art.url


@dataclass
class QueuedItem:
    audio_file: Union[Song, Episode, None] = None
    live: Optional[LiveStreamInfo] = None

    source: AudioSource = None
