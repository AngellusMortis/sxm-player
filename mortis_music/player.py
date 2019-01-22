import asyncio
import logging
import traceback
from random import SystemRandom
from typing import List, Optional, Union

from discord import (
    AudioSource,
    ClientException,
    FFmpegPCMAudio,
    Game,
    PCMVolumeTransformer,
    VoiceChannel,
    VoiceClient,
)
from discord.ext.commands import Bot
from sqlalchemy import and_

from sxm.models import XMChannel

from .models import (
    Episode,
    LiveStreamInfo,
    QueuedItem,
    SiriusXMActivity,
    Song,
    XMState,
)

__all__ = ["AudioPlayer"]


class RepeatSetException(Exception):
    pass


class AudioPlayer:
    recent: List[Union[Episode, Song]]
    upcoming: List[Union[Episode, Song]]

    _log: logging.Logger
    _random: SystemRandom
    _xm_state: XMState
    _bot: Bot = None
    _current: Optional[AudioSource] = None
    _event: asyncio.Event = asyncio.Event()
    _live: Optional[LiveStreamInfo] = None
    _playlist_channels: Optional[List[XMChannel]] = None
    _queue: asyncio.Queue = asyncio.Queue()
    _task: Optional[asyncio.Task] = None
    _voice: Optional[VoiceClient] = None
    _volume: float = 0.25
    _do_repeat: bool = False

    def __init__(self, bot: Bot, xm_state: XMState):
        self._bot = bot
        self._xm_state = xm_state
        self._log = logging.getLogger("mortis_music.player")
        self._random = SystemRandom()

        self.recent = []
        self.upcoming = []

        self._bot.loop.create_task(self._update())

    @property
    def is_playing(self) -> bool:
        """ Returns if `AudioPlayer` is playing audio """

        if self._voice is None or self._current is None:
            return False

        return self._voice.is_playing()

    @property
    def repeat(self) -> bool:
        return self._do_repeat

    @repeat.setter
    def repeat(self, value: bool):
        if self._playlist_channels is not None:
            raise RepeatSetException(
                "Cannot set repeat while playing a SiriusXM Archive playlist"
            )
        if self._live is not None:
            raise RepeatSetException(
                "Cannot set repeat while playing a SiriusXM live channel"
            )

        self._do_repeat = value

    @property
    def voice(self) -> Union[VoiceClient, None]:
        """ Gets the voice client for audio player """
        return self._voice

    async def set_voice(self, channel: VoiceChannel) -> None:
        """ Sets voice channel for audio player """

        if self._voice is None:
            self._voice = await channel.connect()
            self._task = self._bot.loop.create_task(self._audio_player())
        else:
            await self._voice.move_to(channel)

    @property
    def current(self) -> Union[QueuedItem, None]:
        """ Returns current `Song` or `Episode` that is being played """

        if self._current is not None:
            return self._current.audio_file
        return None

    @property
    def volume(self) -> float:
        """ Gets current volume level """

        return self._volume

    @volume.setter
    def volume(self, volume: float) -> None:
        """ Sets current volume level """

        if volume < 0.0:
            volume = 0.0
        elif volume > 1.0:
            volume = 1.0

        self._volume = volume
        if self._current is not None:
            self._current.source.volume = self._volume

    async def stop(
        self, disconnect: bool = True, reset_live: bool = True
    ) -> None:
        """ Stops the `AudioPlayer` """

        while not self._queue.empty():
            self._queue.get_nowait()

        if self._playlist_channels is not None:
            self._playlist_channels = None

        if self._current is not None:
            if self._current.source is not None:
                self._current.source.cleanup()
            self._current = None

        self.recent = []
        self.upcoming = []

        if reset_live and self._live is not None:
            self._xm_state.reset_channel()
            self._live = None

        self._song_end()

        if self._voice is not None:
            if self._voice.is_playing():
                self._voice.stop()
            if disconnect:
                self._log.debug("Voice disconnection stacktrace:")
                self._log.debug("".join(traceback.format_stack()))
                await self._voice.disconnect()
                self._voice = None
                if self._task is not None:
                    self._task.cancel()

    async def skip(self) -> bool:
        """ Skips current `QueueItem` """

        if self._voice is not None:
            if self._queue.qsize() < 1:
                await self.stop()
            else:
                self._voice.stop()
            return True
        return False

    async def add_playlist(self, xm_channels: List[XMChannel]) -> None:
        """ Creates a playlist of random songs from an channel """

        self._playlist_channels = xm_channels

        for _ in range(5):
            await self._add_random_playlist_song()

    async def add_live_stream(self, channel: XMChannel) -> None:
        """ Adds HLS live stream to playing queue """

        await self._add(channel=channel)

    async def add_file(self, file_info: Union[Song, Episode]) -> None:
        """ Adds file to playing queue """

        await self._add(file_info=file_info)

    async def _add_random_playlist_song(self) -> None:
        if self._playlist_channels is None or self._xm_state.db is None:
            return

        channel_ids = [x.id for x in self._playlist_channels]

        songs = self._xm_state.db.query(Song.title, Song.artist).filter(
            Song.channel.in_(channel_ids)  # type: ignore
        )
        songs = songs.distinct().all()

        song = self._random.choice(songs)
        song = (
            self._xm_state.db.query(Song)
            .filter(
                and_(
                    Song.channel.in_(channel_ids),  # type: ignore
                    Song.title == song[0],
                    Song.artist == song[1],
                )
            )
            .first()
        )

        await self._add(file_info=song)

    async def _add(
        self,
        file_info: Union[Song, Episode, None] = None,
        channel: Optional[XMChannel] = None,
    ) -> None:
        """ Adds item to playing queue """

        if self._voice is None:
            raise ClientException("Voice client is not set")

        live_stream = None
        if channel is not None:
            live_stream = LiveStreamInfo(channel)

        item = QueuedItem(audio_file=file_info, live=live_stream)
        self.upcoming.append(item.audio_file)  # type: ignore

        await self._queue.put(item)

    def _song_end(self, error: Optional[Exception] = None) -> None:
        """ Callback for `discord.AudioPlayer`/`discord.VoiceClient` """

        self._bot.loop.call_soon_threadsafe(self._event.set)

    async def _reset_live_stream(self, delay: int = 0) -> None:
        """ Stop and restart the existing HLS live stream """

        if self._live is None:
            self._log.warn("No live stream to reset")
            return

        if self._live.is_reset_allowed:
            if not self._live.resetting:
                self._live.resetting = True
                self._xm_state.reset_channel()
                await self.stop(disconnect=False, reset_live=False)

                if delay > 0:
                    await asyncio.sleep(delay)

                await self.add_live_stream(self._live.channel)
                self._live.resetting = False
        else:
            self._log.error(f"could not reset live stream")
            await self.stop()

    async def _audio_player(self) -> None:
        """ Bot task to manage and run the audio player """

        while True:
            self._event.clear()
            self._current = await self._queue.get()

            if len(self.upcoming) > 0:
                self.upcoming.pop(0)

            if self._current.audio_file is not None:
                self.recent.insert(0, self._current.audio_file)
                self.recent = self.recent[:10]

                log_item = self._current.audio_file.file_path
                self._current.source = FFmpegPCMAudio(
                    self._current.audio_file.file_path
                )
            # preserve counters in current live info
            elif self._current.live is not None:
                self._live = self._current.live

            if self._current.live is not None:
                log_item = self._current.live.channel.id
                try:
                    self._log.warn("playing live stream")
                    self._current.source = await self._live.play(  # type: ignore  # noqa
                        self._xm_state
                    )
                except Exception:
                    self._log.error(
                        "Exception while trying to play HLS stream:"
                    )
                    self._log.error(traceback.format_exc())
                    try:
                        await self.stop()
                    except Exception:
                        self._log.error(traceback.format_exc())
                    continue

            self._current.source = PCMVolumeTransformer(
                self._current.source, volume=self._volume
            )
            self._log.info(f"playing {log_item}")

            if self._voice is not None:
                self._voice.play(self._current.source, after=self._song_end)

            await self._event.wait()

            if self._playlist_channels is not None and self._queue.qsize() < 5:
                await self._add_random_playlist_song()
            elif (
                self._do_repeat
                and self._playlist_channels is None
                and self._current.live is None
            ):
                try:
                    await self._add(file_info=self._current.audio_file)
                except Exception:
                    self._log.error(
                        "Exception while re-add song to queue for repeat:"
                    )
                    self._log.error(traceback.format_exc())

            self._current = None

    async def _read_errors(self):
        lines = self._xm_state.pop_hls_errors()

        if lines is not None:
            for line in lines:
                if "503" in line:
                    self._log.warn(
                        "Receiving 503 errors from SiriusXM, pausing stream"
                    )
                    await self._reset_live_stream(10)
                else:
                    self._log.warn(line)

    async def _update(self) -> None:
        """ Bot task update the state of the audio player """

        await self._bot.wait_until_ready()

        sleep_time = 10
        while not self._bot.is_closed():
            await asyncio.sleep(sleep_time)
            sleep_time = 5

            activity = None
            if self._xm_state.active_channel_id is not None:
                xm_channel = self._xm_state.get_channel(
                    self._xm_state.active_channel_id
                )

                if self.is_playing and self._live is not None:
                    if self._xm_state.live is not None:
                        self._live.reset_counters()
                        activity = SiriusXMActivity(
                            start=self._xm_state.start_time,
                            radio_time=self._xm_state.radio_time,
                            channel=xm_channel,
                            live_channel=self._xm_state.live,
                        )

                        await self._read_errors()
                    elif self._live.is_live_missing:
                        self._log.warn(
                            f"could not retrieve live stream data, resetting"
                        )
                        await self._reset_live_stream()
                elif self._live is not None and not self._live.resetting:
                    self._log.warn(f"live stream lost, resetting")
                    await self._reset_live_stream()
            elif self.is_playing:
                if self.current is None:
                    await self.stop()
                else:
                    activity = Game(name=self._current.audio_file.pretty_name)

            await self._bot.change_presence(activity=activity)
