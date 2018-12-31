import asyncio
import logging
import os
import shlex
import subprocess
import threading
import time
import traceback
from random import SystemRandom
from typing import List, Optional, Union

from discord import (AudioSource, ClientException, Game, PCMVolumeTransformer,
                     VoiceChannel, VoiceClient)
from discord.ext.commands import Bot
from discord.opus import Encoder as OpusEncoder
from discord.player import log

from sqlalchemy import and_
from sxm.models import XMChannel

from .models import (Episode, LiveStreamInfo, QueuedItem, SiriusXMActivity,
                     Song, XMState)

# from discord.player import AudioPlayer as DiscordAudioPlayer

__all__ = ['AudioPlayer']


# TODO: try to get merged upstream
class FFmpegPCMAudio(AudioSource):
    """An audio source from FFmpeg (or AVConv).

    This launches a sub-process to a specific input file given.

    .. warning::

        You must have the ffmpeg or avconv executable in your path environment
        variable in order for this to work.

    Parameters
    ------------
    source: Union[str, BinaryIO]
        The input that ffmpeg will take and convert to PCM bytes.
        If ``pipe`` is True then this is a file-like object that is
        passed to the stdin of ffmpeg.
    executable: str
        The executable name (and path) to use. Defaults to ``ffmpeg``.
    pipe: bool
        If true, denotes that ``source`` parameter will be passed
        to the stdin of ffmpeg. Defaults to ``False``.
    stderr: Optional[BinaryIO]
        A file-like object to pass to the Popen constructor.
        Could also be an instance of ``subprocess.PIPE``.
    options: Optional[str]
        Extra command line arguments to pass to ffmpeg after the ``-i`` flag.
    before_options: Optional[str]
        Extra command line arguments to pass to ffmpeg before the ``-i`` flag.
    after_options: Optional[str]
        Extra command line arguments to pass to ffmpeg after everything else.

    Raises
    --------
    ClientException
        The subprocess failed to be created.
    """

    def __init__(self, source, *, executable='ffmpeg',
                 pipe=False, stderr=None, before_options=None,
                 options=None, after_options=None):
        stdin = None if not pipe else source

        args = [executable]

        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))

        args.append('-i')
        args.append('-' if pipe else source)
        args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'warning'))

        if isinstance(options, str):
            args.extend(shlex.split(options))

        args.append('pipe:1')

        if isinstance(after_options, str):
            args.extend(shlex.split(after_options))

        self._process = None
        try:
            self._process = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr)
            self._stdout = self._process.stdout
        except FileNotFoundError:
            raise ClientException(executable + ' was not found.') from None
        except subprocess.SubprocessError as e:
            raise ClientException('Popen failed: {0.__class__.__name__}: {0}'.format(e)) from e

    def read(self):
        ret = self._stdout.read(OpusEncoder.FRAME_SIZE)
        if len(ret) != OpusEncoder.FRAME_SIZE:
            return b''
        return ret

    def cleanup(self):
        proc = self._process
        if proc is None:
            return

        log.info('Preparing to terminate ffmpeg process %s.', proc.pid)
        proc.kill()
        if proc.poll() is None:
            log.info('ffmpeg process %s has not terminated. Waiting to terminate...', proc.pid)
            proc.communicate()
            log.info('ffmpeg process %s should have terminated with a return code of %s.', proc.pid, proc.returncode)
        else:
            log.info('ffmpeg process %s successfully terminated with return code of %s.', proc.pid, proc.returncode)

        self._process = None


# TODO: Remove and go back to build Discord player
class DiscordAudioPlayer(threading.Thread):
    DELAY = OpusEncoder.FRAME_LENGTH / 1000.0

    def __init__(self, source, client, *, after=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.source = source
        self.client = client
        self.after = after

        self._end = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set() # we are not paused
        self._current_error = None
        self._connected = client._connected
        self._lock = threading.Lock()

        self._log = logging.getLogger('discord_siriusxm.player')

        if after is not None and not callable(after):
            raise TypeError('Expected a callable for the "after" parameter.')

    def _do_run(self):
        self.loops = 0
        self._start = time.time()

        # getattr lookup speed ups
        play_audio = self.client.send_audio_packet

        self._log.warn('player run')
        while not self._end.is_set():
            self._log.warn('player loop')
            # are we paused?
            if not self._resumed.is_set():
                self._log.warn('player resume')
                # wait until we aren't
                self._resumed.wait()
                continue

            # are we disconnected from voice?
            if not self._connected.is_set():
                self._log.warn('player connected')
                # wait until we are connected
                self._connected.wait()
                # reset our internal data
                self.loops = 0
                self._start = time.time()

            self.loops += 1
            data = self.source.read()

            if not data:
                self._log.warn('player stop')
                self.stop()
                break

            self._log.warn('player play')
            play_audio(data, encode=not self.source.is_opus())
            next_time = self._start + self.DELAY * self.loops
            delay = max(0, self.DELAY + (next_time - time.time()))
            self._log.warn('player sleep')
            time.sleep(delay)

    def run(self):
        try:
            self._do_run()
        except Exception as exc:
            self._current_error = exc
            self.stop()
        finally:
            self.source.cleanup()
            self._call_after()

    def _call_after(self):
        if self.after is not None:
            try:
                self.after(self._current_error)
            except Exception:
                log.exception('Calling the after function failed.')

    def stop(self):
        self._end.set()
        self._resumed.set()

    def pause(self):
        self._resumed.clear()

    def resume(self):
        self.loops = 0
        self._start = time.time()
        self._resumed.set()

    def is_playing(self):
        return self._resumed.is_set() and not self._end.is_set()

    def is_paused(self):
        return not self._end.is_set() and not self._resumed.is_set()

    def _set_source(self, source):
        with self._lock:
            self.pause()
            self.source = source
            self.resume()


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

    _live_counter: int = 0
    _live_reset_counter: int = 0
    _live_stream: LiveStreamInfo = None
    _live_source: AudioSource = None
    _live_player: DiscordAudioPlayer = None

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

    async def stop(self, disconnect: bool = True) -> None:
        """ Stops the `AudioPlayer` """

        self._xm_state.reset_channel()

        while not self._queue.empty():
            self._queue.get_nowait()

        if self._playlist_channels is not None:
            self._playlist_channels = None

        if self._current is not None:
            self._current.source.cleanup()
            self._current = None

        self.recent = []
        self.upcoming = []
        if self._live_source is not None:
            self._live_source.cleanup()
            self._live_source = None

        if self._live_player is not None:
            self._live_player = None

        if self._voice is not None:
            if self._voice.is_playing():
                self._voice.stop()
            if disconnect:
                self._live_counter = 0
                self._live_reset_counter = 0
                self._live_stream = None

                if self._task is not None:
                    self._task.cancel()
                self._song_end()
                self._log.error(traceback.format_exc())
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
        )
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

    async def _reset_live_stream(self) -> None:
        """ Stop and restart the existing HLS live stream """

        if self._live_reset_counter < 5 and self._live_stream is not None:
            await self.stop(disconnect=False)
            self._live_reset_counter += 1

            await self.add_live_stream(self._live_stream)
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
                self._live_stream = self._current.live
                # TODO: WIP
                # code to try to get Discord to play from output .mp3 file for
                # HLS streams at a few second delay instead of direct from
                # stream to decrease skipping/buffering
                # try:
                #     self._live_source = self._current.source
                #     self._live_player = DiscordAudioPlayer(
                #         self._live_source,
                #         FakeClient(),
                #         after=self._song_end)
                #     self._live_player.start()
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
                        self._live_counter = 0
                        self._live_reset_counter = 0
                        activity = SiriusXMActivity(
                            start=self._xm_state.start_time,
                            radio_time=self._xm_state.radio_time,
                            channel=xm_channel,
                            live_channel=self._xm_state.live,
                        )
                    elif self._live_counter < 3:
                        self._live_counter += 1
                    else:
                        self._live_counter = 0
                        self._log.warn(
                            f'could not retrieve live stream data, resetting')
                        await self._reset_live_stream()
                else:
                    self._log.error(self._live_reset_counter)
                    self._log.warn(f'live stream lost, resetting')
                    await self._reset_live_stream()
            elif self.is_playing:
                if self.current is None:
                    await self.stop()
                else:
                    activity = Game(
                        name=self._current.item.pretty_name)

            await self._bot.change_presence(activity=activity)
