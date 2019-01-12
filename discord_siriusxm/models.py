import asyncio
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Union

from discord import AudioSource, Game
from discord.ext.commands import Bot
from discord.opus import Encoder as OpusEncoder

from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session
from sxm.models import XMChannel, XMImage, XMLiveChannel, XMSong

from .forked import FFmpegPCMAudio

Base = declarative_base()


class Song(Base):
    __tablename__ = 'songs'

    guid: str = Column(String, primary_key=True)
    title: str = Column(String, index=True)
    artist: str = Column(String, index=True)
    album: str = Column(String, nullable=True)
    air_time: datetime = Column(DateTime)
    channel: str = Column(String)
    file_path: str = Column(String)

    @staticmethod
    def get_pretty_name(title: str, artist: str, bold: bool = False) -> str:
        """ Returns a formatted name of song """

        mod = ''
        if bold:
            mod = '**'

        return f'{mod}"{title}"{mod} by {mod}{artist}{mod}'

    @property
    def pretty_name(self) -> str:
        """ Returns a formatted name of song """

        return Song.get_pretty_name(self.title, self.artist)

    @property
    def bold_name(self) -> str:
        """ Returns a formatted name of song """

        return Song.get_pretty_name(self.title, self.artist, True)


class Episode(Base):
    __tablename__ = 'episodes'

    guid: str = Column(String, primary_key=True)
    title: str = Column(String, index=True)
    show: str = Column(String, nullable=True, index=True)
    air_time: datetime = Column(DateTime)
    channel: str = Column(String)
    file_path: str = Column(String)

    @staticmethod
    def get_pretty_name(title: str, show: str, air_time: str,
                        bold: bool = False) -> str:
        """ Returns a formatted name of show """

        mod = ''
        if bold:
            mod = '**'

        return f'{mod}"{title}"{mod} ({show}) from {air_time}'

    @property
    def pretty_name(self) -> str:
        """ Returns a formatted name of show """

        return Episode.get_pretty_name(self.title, self.show, self.air_time)

    @property
    def bold_name(self) -> str:
        """ Returns a formatted name of show """

        return Episode.get_pretty_name(
            self.title, self.show, self.air_time, True)


class DictState:
    """Class that uses a shared memory dictionary to populate attributes"""
    _state_dict: dict = None

    def __init__(self, state_dict: dict):
        self._state_dict = state_dict

    def __getattr__(self, attr: str):
        if self._state_dict is not None and attr in self._state_dict:
            return self._state_dict[attr]
        else:
            raise AttributeError("--%r object has no attribute %r" % (
                type(self).__name__, attr))

    def __setattr__(self, attr: str, value) -> None:
        if self._state_dict is not None and attr in self._state_dict:
            self._state_dict[attr] = value
        super().__setattr__(attr, value)


class FakePlayer(threading.Thread):
    """ Striped down Discord Audio Player to play HLS """
    DELAY = OpusEncoder.FRAME_LENGTH / 1000.0

    def __init__(self, source):
        threading.Thread.__init__(self)
        self.daemon = True
        self.source = source

        self._end = threading.Event()

    def _do_run(self):
        self.loops = 0
        self._start = time.time()

        while not self._end.is_set():
            self.loops += 1
            data = self.source.read()

            if not data:
                self.stop()
                break
            next_time = self._start + self.DELAY * self.loops
            delay = max(0, self.DELAY + (next_time - time.time()))
            time.sleep(delay)

    def run(self):
        try:
            self._do_run()
        except Exception as exc:
            self._current_error = exc
            self.stop()
        finally:
            self.source.cleanup()

    def stop(self):
        self._end.set()


@dataclass
class QueuedItem:
    audio_file: Union[Song, Episode] = None
    channel: XMChannel = None

    source: AudioSource = None


class SiriusXMActivity(Game):
    def __init__(self, start: int, radio_time: int,
                 channel: XMChannel, live_channel: XMLiveChannel, **kwargs):

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

    def update_status(self, channel: XMChannel,
                      live_channel: XMLiveChannel, radio_time: int) -> None:
        """ Updates activity object from current channel playing """

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


class XMState(DictState):
    """Class to store state SiriusXM Radio player for Discord Bot"""
    _channels: List[XMChannel] = None
    _live_update_time: int = None
    _live: XMLiveChannel = None
    _archive_folder: str = None
    _processed_folder: str = None
    _stream_folder: str = None

    _db: Session = None
    _db_reset: bool = False

    def __init__(self, state_dict: dict, db_reset: bool = False):
        self._state_dict = state_dict
        self._db_reset = False

    @staticmethod
    def init_state(state_dict: dict) -> None:
        """ Initializes a dictionary that will be used
        for a `XMState` object """

        state_dict['active_channel_id'] = None
        state_dict['stream_file'] = None
        state_dict['channels'] = []
        state_dict['start_time'] = None
        state_dict['live'] = None
        state_dict['processing_file'] = False
        state_dict['live_update_time'] = None
        state_dict['time_offset'] = None
        state_dict['output'] = None

    @property
    def channels(self) -> List[XMChannel]:
        """ Returns list of `XMChannel` """

        if self._channels is None:
            self._channels = []
            for channel in self._state_dict['channels']:
                self._channels.append(XMChannel(channel))
        return self._channels

    @channels.setter
    def channels(self, value: dict) -> None:
        """ Sets channel key in internal `state_dict`. """

        self._channels = None
        self._state_dict['channels'] = value

    @property
    def live(self) -> Union[XMLiveChannel, None]:
        """ Returns current `XMLiveChannel` """

        last_update = self._state_dict['live_update_time']
        now = int(time.time() * 1000)
        if self._live is None or \
                self._live_update_time != last_update:
            if self._state_dict['live'] is not None:
                self._live_update_time = last_update
                self._live = XMLiveChannel(self._state_dict['live'])

            if self._live.tune_time is not None:
                self._state_dict['time_offset'] = now - self._live.tune_time
            else:
                self._state_dict['time_offset'] = 0

        if self._state_dict['start_time'] is None:
            if self._live.tune_time is None:
                self._state_dict['start_time'] = now
            else:
                self._state_dict['start_time'] = self._live.tune_time
        return self._live

    @live.setter
    def live(self, value: dict) -> None:
        """ Sets live key in internal `state_dict`. """

        self._live = None
        self._state_dict['start_time'] = None
        self._state_dict['live'] = value
        if value is not None:
            self._state_dict['live_update_time'] = time.time()

    @property
    def radio_time(self) -> Union[int, None]:
        """ Returns current time for the radio """

        if self.live is None:
            return None
        # still working on offset:  - self.time_offset
        return int(time.time() * 1000)

    @property
    def start_time(self) -> Union[int, None]:
        """ Returns the start time for the current SiriusXM channel """

        if self.live is None:
            return None
        return self._state_dict['start_time']

    def get_channel(self, name: str) -> Union[XMChannel, None]:
        """ Returns channel from list of `channels` with given name """

        name = name.lower()
        for channel in self.channels:
            if channel.name.lower() == name or \
                    channel.id.lower() == name or \
                    channel.channel_number == name:
                return channel
        return None

    def set_channel(self, channel_id: str) -> None:
        """ Sets active SiriusXM channel """

        self.active_channel_id = channel_id
        self.live = None

    def reset_channel(self) -> None:
        """ Removes active SiriusXM channel """

        self.active_channel_id = None
        self.live = None

    @property
    def archive_folder(self) -> Union[str, None]:
        """ Returns path to archive folder """

        if self._archive_folder is None:
            if self.output is not None:
                self._archive_folder = os.path.join(self.output, 'archive')
        return self._archive_folder

    @property
    def processed_folder(self) -> Union[str, None]:
        """ Returns path to processed folder """

        if self._processed_folder is None:
            if self.output is not None:
                self._processed_folder = os.path.join(self.output, 'processed')
        return self._processed_folder

    @property
    def stream_folder(self) -> Union[str, None]:
        """ Returns path to stream folder """

        if self._stream_folder is None:
            if self.output is not None:
                self._stream_folder = os.path.join(self.output, 'streams')
        return self._stream_folder

    @property
    def db(self) -> Union[Session, None]:
        if self._db is None and self.output is not None:
            from .utils import init_db

            self._db = init_db(self.processed_folder, self._db_reset)
        return self._db

@dataclass
class LiveStreamInfo:
    channel: XMChannel
    resetting: bool = False

    process: subprocess.Popen = None
    source: AudioSource = None

    _counter: int = 0
    _reset_counter: int = 0
    _stream_player: FakePlayer = None

    def __init__(self, channel: XMChannel):
        self.channel = channel

    async def play(self, state: XMState) -> AudioSource:
        """ Plays FFmpeg livestream """

        self.resetting = True

        state.set_channel(self.channel)

        start = time.time()
        now = start
        can_start = False
        while not can_start and now - start < 30:
            await asyncio.sleep(0.1)
            now = time.time()
            if os.path.exists(self.archive_file):
                if os.path.getsize(self.archive_file) > 10000:
                    can_start = True

        if not can_start:
            raise Exception('HLS archive file is not growing in size')

        playback_source = FFmpegPCMAudio(
            self.archive_file,
            log_level='fatal',
        )

        self.resetting = False

        return playback_source

    # async def play(self, stdout_callback: Callable,
    #                stderr_callback: Callable) -> AudioSource:
    #     """ Plays FFmpeg livestream """

    #     self.stop()

    #     self.resetting = True
    #     if os.path.exists(self.archive_file):
    #         os.remove(self.archive_file)

    #     self.source = FFmpegPCMAudio(
    #         self.stream_url,
    #         before_options='-f hls',
    #         after_options=self.archive_file,
    #         stderr=subprocess.PIPE
    #     )
    #     self.process = self.source._process

    #     loop = asyncio.get_event_loop()
    #     loop.add_reader(self.process.stdout, stdout_callback)
    #     loop.add_reader(self.process.stderr, stderr_callback)

    #     start = time.time()
    #     now = start
    #     can_start = False
    #     while not can_start and now - start < 30:
    #         await asyncio.sleep(0.1)
    #         now = time.time()
    #         if os.path.exists(self.archive_file):
    #             if os.path.getsize(self.archive_file) > 10000:
    #                 can_start = True

    #     if not can_start:
    #         raise Exception('HLS archive file is not growing in size')

    #     playback_source = FFmpegPCMAudio(
    #         self.archive_file,
    #         log_level='fatal',
    #     )

    #     self.resetting = False

    #     return playback_source

    # def stop(self, bot: Bot = None) -> None:
    #     """ Stops FFmpeg livestream """

    #     if self.source is not None:
    #         try:
    #             if bot is None:
    #                 loop = asyncio.get_event_loop()
    #             else:
    #                 loop = bot.loop
    #             loop.remove_reader(self.process.stdout)
    #             loop.remove_reader(self.process.stderr)
    #         except ValueError:
    #             pass

    #         try:
    #             self.source.cleanup()
    #         except OSError:
    #             pass
    #         self.source = None
    #         self.process = None

    def stop(self, state: XMState) -> None:
        """ Stops FFmpeg livestream """

        state.reset_channel()

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

        if self._counter < 11:
            self._counter += 1
            return False
        return True

    def reset_counters(self):
        self._counter = 0
        self._reset_counter = 0
