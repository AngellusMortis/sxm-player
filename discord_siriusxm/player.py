import asyncio
import logging
import traceback
from random import SystemRandom
from typing import List, Optional, Union

from discord import (AudioSource, ClientException, Game, PCMVolumeTransformer,
                     VoiceChannel, VoiceClient)
from discord.ext.commands import Bot

from sqlalchemy import and_
from sxm.models import XMChannel

from .forked import FFmpegPCMAudio
from .models import (Episode, LiveStreamInfo, QueuedItem, SiriusXMActivity,
                     Song, XMState)

__all__ = ['AudioPlayer']


class AudioPlayer:
    recent: List[Union[Episode, Song]] = None
    upcoming: List[Union[Episode, Song]] = None

    _log: logging.Logger = None
    _current: AudioSource = None
    _voice: VoiceClient = None
    _task: asyncio.Task = None
    _queue: asyncio.Queue = asyncio.Queue()
    _event: asyncio.Event = asyncio.Event()
    _bot: Bot = None
    _xm_state: XMState = None
    _volume: float = 0.25

    _live: LiveStreamInfo = None

    _playlist_channels: List[XMChannel] = None
    _random: SystemRandom = None

    def __init__(self, bot: Bot, xm_state: XMState):
        self._bot = bot
        self._xm_state = xm_state
        self._log = logging.getLogger('discord_siriusxm.player')
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

    async def stop(self, disconnect: bool = True,
                   reset_live: bool = True) -> None:
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
            self._live.stop(self._xm_state)

        if self._voice is not None:
            if self._voice.is_playing():
                self._voice.stop()
            if disconnect:
                self._song_end()
                self._live = None
                self._log.debug('Voice disconnection stacktrace:')
                self._log.debug('\n'.join(traceback.format_stack()))
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

        for x in range(5):
            await self._add_random_playlist_song()

    async def add_live_stream(self, channel: XMChannel) -> None:
        """ Adds HLS live stream to playing queue """

        await self._add(channel=channel)

    async def add_file(self, file_info: Union[Song, Episode]) -> None:
        """ Adds file to playing queue """

        await self._add(file_info=file_info)

    async def _add_random_playlist_song(self) -> None:
        channel_ids = [x.id for x in self._playlist_channels]

        songs = self._xm_state.db.query(Song.title, Song.artist)\
            .filter(Song.channel.in_(channel_ids))\
            .distinct().all()

        song = self._random.choice(songs)
        song = self._xm_state.db.query(Song)\
            .filter(and_(
                Song.channel.in_(channel_ids),
                Song.title == song[0],
                Song.artist == song[1],
            )).first()

        await self._add(file_info=song)

    async def _add(self, file_info: Union[Song, Episode, None] = None,
                   channel: Optional[XMChannel] = None) -> None:
        """ Adds item to playing queue """

        if self._voice is None:
            raise ClientException('Voice client is not set')

        live_stream = LiveStreamInfo(channel)
        item = QueuedItem(audio_file=file_info, live=live_stream)
        self.upcoming.append(item.audio_file)
        await self._queue.put(item)

    def _song_end(self, error: Optional[Exception] = None) -> None:
        """ Callback for `discord.AudioPlayer`/`discord.VoiceClient` """

        self._bot.loop.call_soon_threadsafe(self._event.set)
        if self._live is not None:
            self._live.stop(self._xm_state)

    async def _reset_live_stream(self, delay: int = 0) -> None:
        """ Stop and restart the existing HLS live stream """

        if self._live is None:
            self._log.warn('No live stream to reset')
            return

        if self._live.is_reset_allowed:
            if not self._live.resetting:
                self._live.resetting = True
                await self.stop(disconnect=False, reset_live=False)

                if delay > 0:
                    await asyncio.sleep(delay)

                await self.add_live_stream(self._live)
                self._live.resetting = False
        else:
            self._log.error(f'could not reset live stream')
            await self.stop()

    def _read_livestream(self, is_stdout: bool = True) -> Union[bytes, None]:
        """ Bot task to read the output from ffmpeg process for livestream """

        if self._live is None:
            self._log.warn('No live stream to read')
            return None

        response = None
        if self._live is not None and \
                self._live.source is not None:

            if is_stdout:
                response = self._live.source.read()
            else:
                response = self._live.process.stderr.readline()

        return response

    def _read_livestream_out(self) -> None:
        """ Bot task to read the stdout of a livestream that is playing """

        self._read_livestream()

    def _read_livestream_error(self) -> None:
        """ Bot task to read the stderr of a livestream that is playing """

        line = self._read_livestream(False)

        if line is not None:
            line = line.decode('utf8')

            if len(line) > 0:
                if '503' in line:
                    self._log.warn(
                        'Receiving 503 errors from SiriusXM, pausing stream')
                    self._bot.loop.create_task(self._reset_live_stream(10))
                else:
                    self._log.error(line)

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
                    self._current.audio_file.file_path,
                )
            else:
                log_item = self._current.live.channel.id
                self._live = self._current.live
                try:
                    self._current.source = \
                        await self._live.play(self._xm_state)
                except Exception:
                    self._log.error(
                        'Exception while trying to play HLS stream:')
                    self._log.error(traceback.format_exc())
                    try:
                        await self.stop()
                    except Exception:
                        self._log.error(traceback.format_exc())
                    continue

            self._current.source = PCMVolumeTransformer(
                self._current.source, volume=self._volume)
            self._log.info(f'playing {log_item}')
            self._voice.play(self._current.source, after=self._song_end)

            await self._event.wait()

            if self._playlist_channels is not None and \
                    self._queue.qsize() < 5:
                await self._add_random_playlist_song()
            self._current = None

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
                    self._xm_state.active_channel_id)

                if self.is_playing:
                    if self._xm_state.live is not None:
                        self._live.reset_counters()
                        activity = SiriusXMActivity(
                            start=self._xm_state.start_time,
                            radio_time=self._xm_state.radio_time,
                            channel=xm_channel,
                            live_channel=self._xm_state.live,
                        )
                    elif self._live.is_live_missing:
                        self._log.warn(
                            f'could not retrieve live stream data, resetting')
                        await self._reset_live_stream()
                elif not self._live.resetting:
                    self._log.warn(f'live stream lost, resetting')
                    await self._reset_live_stream()
            elif self.is_playing:
                if self.current is None:
                    await self.stop()
                else:
                    activity = Game(
                        name=self._current.audio_file.pretty_name)

            await self._bot.change_presence(activity=activity)
