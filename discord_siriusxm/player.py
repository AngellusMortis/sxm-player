import asyncio
import logging
import os
import subprocess
import traceback
from random import SystemRandom
from typing import List, Optional, Union

from discord import (AudioSource, ClientException, Game, PCMVolumeTransformer,
                     VoiceChannel, VoiceClient)
from discord.ext.commands import Bot

from sqlalchemy import and_
from sxm.models import XMChannel

from .forked import DiscordAudioPlayer, FFmpegPCMAudio
from .models import (Episode, LiveStreamInfo, QueuedItem, SiriusXMActivity,
                     Song, XMState, LiveState)

# from discord.player import AudioPlayer as DiscordAudioPlayer

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

    _live: LiveState = None

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

        if self._voice is None or self._voice is None:
            return False

        return self._voice.is_playing()

    async def set_voice(self, channel: VoiceChannel) -> None:
        """ Sets voice channel for audio player """

        if self._voice is None:
            self._voice = await channel.connect()
            self._task = self._bot.loop.create_task(self._audio_player())
        else:
            await self._voice.move_to(channel)

    @property
    def current(self) -> Union[QueuedItem, None]:
        """ Returns current `QueuedItem` that is being played """

        if self._current is not None:
            return self._current.item
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
            self._current.source.cleanup()
            self._current = None

        self.recent = []
        self.upcoming = []

        if self._live is not None:
            self._live.reset_player()

        if reset_live:
            self._xm_state.reset_channel()

        if self._voice is not None:
            if self._voice.is_playing():
                self._voice.stop()
            if disconnect:
                if self._live is not None:
                    if self._live.stream is not None:
                        self._bot.loop.remove_reader(self._live.stream.stderr)
                    self._live = None

                if self._task is not None:
                    self._task.cancel()
                self._song_end()
                self._log.debug('Voice disconnection stacktrace:')
                self._log.debug('\n'.join(traceback.format_stack()))
                await self._voice.disconnect()
                self._voice = None

    async def kick(self, channel: VoiceChannel) -> bool:
        """ Kicks bot out of channel """

        if self._voice is None:
            return False

        if self._voice.channel.id == channel.id:
            await self.stop()
            return True
        return False

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

    async def add_live_stream(self, live_stream: LiveStreamInfo) -> None:
        """ Adds HLS live stream to playing queue """

        if os.path.exists(live_stream.archive_file):
                os.remove(live_stream.archive_file)

        source = FFmpegPCMAudio(
            live_stream.stream_url,
            before_options='-f hls',
            after_options=live_stream.archive_file,
            stderr=subprocess.PIPE
        )
        live_stream.stderr = source._process.stderr

        self._bot.loop.add_reader(
            live_stream.stderr, self._read_livestream_error)
        await self._add(None, source, live_stream)

    async def add_file(self, file_info: Union[Song, Episode]) -> None:
        """ Adds file to playing queue """

        source = FFmpegPCMAudio(
            file_info.file_path,
        )

        await self._add(file_info, source)

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

        await self.add_file(song)

    async def _add(self, file_info: Union[Song, Episode, None],
                   source: AudioSource,
                   live_stream: Optional[LiveStreamInfo] = None) -> None:
        """ Adds item to playing queue """

        if self._voice is None:
            raise ClientException('Voice client is not set')

        item = QueuedItem(file_info, source, live_stream)
        self.upcoming.append(item.item)
        await self._queue.put(item)

    def _song_end(self, error: Optional[Exception] = None) -> None:
        """ Callback for `discord.AudioPlayer`/`discord.VoiceClient` """
        self._bot.loop.call_soon_threadsafe(self._event.set)

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

                await self.add_live_stream(self._live.stream)
                self._live.resetting = False
        else:
            self._log.error(f'could not reset live stream')
            await self.stop()

    async def _audio_player(self) -> None:
        """ Bot task to manage and run the audio player """

        while True:
            self._event.clear()
            self._current = await self._queue.get()

            self.upcoming.pop(0)
            self.recent.insert(0, self._current.item)
            self.recent = self.recent[:10]

            if self._current.live is None:
                log_item = self._current.item.file_path
            else:
                log_item = self._current.live.stream_url

                if self._live is None or \
                        self._live.stream is None or \
                        self._live.stream.stream_url != \
                        self._current.live.stream_url:

                    self._live = LiveState(stream=self._current.live)
                # TODO: WIP
                # code to try to get Discord to play from output .mp3 file for
                # HLS streams at a few second delay instead of direct from
                # stream to decrease skipping/buffering
                # try:
                #     self._live.source = self._current.source
                #     self._live.player = DiscordAudioPlayer(
                #         self._live.source,
                #         FakeClient(),
                #         after=self._song_end)
                #     self._live.player.start()
                #     await asyncio.sleep(30)

                #     self._current.source = FFmpegPCMAudio(
                #         self._current.live_stream_file,
                #     )
                # except Exception as e:
                #     logger.error(f'{type(e).__name__}: {e}')

            self._current.source = PCMVolumeTransformer(
                self._current.source, volume=self._volume)
            self._log.info(f'playing {log_item}')
            self._voice.play(self._current.source, after=self._song_end)

            await self._event.wait()

            if self._playlist_channels is not None and \
                    self._queue.qsize() < 5:
                await self._add_random_playlist_song()
            self._current = None

    def _read_livestream_error(self):
        """ Bot task to read the stderr of a livestream that is playing """

        if self._live is None:
            self._log.warn('No live stream to read stderr')
            return

        if self._live.stream is not None:
            line = self._live.stream.stderr.readline().decode('utf8')
            if len(line) > 0:
                if '503' in line:
                    self._log.warn(
                        'Recieving 503 errors from SiriusXM, pausing stream')
                    self._bot.loop.create_task(self._reset_live_stream(10))
                else:
                    self._log.error(line)

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
                    # channels updates every ~50 seconds
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
                        name=self._current.item.pretty_name)

            await self._bot.change_presence(activity=activity)
