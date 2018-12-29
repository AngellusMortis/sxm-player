import threading
import time
from typing import List

import discord

from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sxm.models import XMChannel, XMImage, XMLiveChannel, XMSong


Base = declarative_base()


class DictState:
    """Class that uses a shared memory dictionary to populate attributes"""
    _state_dict = None

    def __init__(self, state_dict):
        self._state_dict = state_dict

    def __getattr__(self, attr):
        if self._state_dict is not None and attr in self._state_dict:
            return self._state_dict[attr]
        else:
            raise AttributeError("--%r object has no attribute %r" % (
                type(self).__name__, attr))

    def __setattr__(self, attr, value):
        if self._state_dict is not None and attr in self._state_dict:
            self._state_dict[attr] = value
        super().__setattr__(attr, value)


class LiveStreamInfo:
    archive_file: str = None
    stream_url: str = None
    channel: XMChannel = None

    def __init__(self, archive_file, stream_url, channel):
        self.archive_file = archive_file
        self.stream_url = stream_url
        self.channel = channel


class QueuedItem:
    item = None
    source: discord.AudioSource = None
    live: LiveStreamInfo = None

    def __init__(self, item, source, live=None):
        self.item = item
        self.source = source
        self.live = live


class FakeClient:
    _connected = None

    def __init__(self):
        self._connected = threading.Event()
        self._connected.set()

    def send_audio_packet(self, data, *, encode=True):
        pass


class SiriusXMActivity(discord.Game):
    def __init__(self, start, radio_time, channel, live_channel, **kwargs):
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

    def update_status(self, channel, live_channel, radio_time):
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
    _channels = None
    _live_update_time = None
    _live = None

    @staticmethod
    def init_state(state):
        state['active_channel_id'] = None
        state['channels'] = []
        state['start_time'] = None
        state['live'] = None
        state['processing_file'] = False
        state['live_update_time'] = None
        state['time_offset'] = None

    @property
    def channels(self) -> List[XMChannel]:
        if self._channels is None:
            self._channels = []
            for channel in self._state_dict['channels']:
                if isinstance(channel, XMChannel):
                    self._channels.append(channel)
                else:
                    self._channels.append(XMChannel(channel))
        return self._channels

    @channels.setter
    def channels(self, value):
        self._channels = None
        self._state_dict['channels'] = value

    @property
    def live(self) -> XMLiveChannel:
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
    def live(self, value):
        self._live = None
        self._state_dict['start_time'] = None
        self._state_dict['live'] = value
        if value is not None:
            self._state_dict['live_update_time'] = time.time()

    @property
    def radio_time(self):
        if self.live is None:
            return None
        # still working on offset:  - self.time_offset
        return int(time.time() * 1000)

    @property
    def start_time(self):
        if self.live is None:
            return None
        return self._state_dict['start_time']

    def get_channel(self, name):
        name = name.lower()
        for channel in self.channels:
            if channel.name.lower() == name or \
                    channel.id.lower() == name or \
                    channel.channel_number == name:
                return channel
        return None

    def set_channel(self, channel_id):
        self.active_channel_id = channel_id
        self.live = None

    def reset_channel(self):
        self.active_channel_id = None
        self.live = None


class Song(Base):
    __tablename__ = 'songs'

    guid = Column(String, primary_key=True)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    album = Column(String, nullable=True)
    air_time = Column(DateTime)
    channel = Column(String)
    file_path = Column(String)

    @staticmethod
    def get_pretty_name(title, artist, bold=False):
        mod = ''
        if bold:
            mod = '**'

        return f'{mod}"{title}"{mod} by {mod}{artist}{mod}'

    @property
    def pretty_name(self):
        return Song.get_pretty_name(self.title, self.artist)

    @property
    def bold_name(self):
        return Song.get_pretty_name(self.title, self.artist, True)


class Episode(Base):
    __tablename__ = 'episodes'

    guid = Column(String, primary_key=True)
    title = Column(String, index=True)
    show = Column(String, nullable=True, index=True)
    air_time = Column(DateTime)
    channel = Column(String)
    file_path = Column(String)

    @property
    def pretty_name(self):
        return f'"{self.title}" ({self.show}) from {self.air_time}'

    @property
    def bold_name(self):
        return f'**"{self.title}"** ({self.show}) from {self.air_time}'
