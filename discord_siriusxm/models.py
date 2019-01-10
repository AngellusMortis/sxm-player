import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, List, Optional, Union

from discord import AudioSource, Game

from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session
from sxm.models import XMChannel, XMImage, XMLiveChannel, XMSong

from .forked import DiscordAudioPlayer

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


@dataclass
class LiveStreamInfo:
    archive_file: str
    stream_url: str
    channel: XMChannel
    stderr: BinaryIO = None

    def __init__(self, archive_file: str, stream_url: str, channel: XMChannel):
        self.archive_file = archive_file
        self.stream_url = stream_url
        self.channel = channel


@dataclass
class LiveState:
    _counter: int = 0
    _reset_counter: int = 0
    resetting: bool = False

    stream: LiveStreamInfo = None
    source: AudioSource = None
    player: DiscordAudioPlayer = None

    def reset_player(self):
        if self.source is not None:
            self.source.cleanup()
            self.source = None

        if self.player is not None:
            self.player = None

    @property
    def is_reset_allowed(self):
        if self._reset_counter < 5 and self.stream is not None:
            self._reset_counter += 1
            return True
        return False

    @property
    def is_live_missing(self):
        if self._counter < 11:
            self._counter += 1
            return False
        return True

    def reset_counters(self):
        self._counter = 0
        self._reset_counter = 0


@dataclass
class QueuedItem:
    item: Union[Song, Episode, None]
    source: AudioSource
    live: Optional[LiveStreamInfo]


class FakeClient:
    _connected: threading.Event = None

    def __init__(self):
        self._connected = threading.Event()
        self._connected.set()

    def send_audio_packet(self, data, *, encode=True) -> None:
        pass


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
