import asyncio
import threading
import time
from dataclasses import dataclass
from typing import List

import discord
from discord.ext import commands as discord_commands
from discord.player import AudioPlayer as DiscordAudioPlayer

from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sxm.models import XMChannel, XMLiveChannel

from .player import FFmpegPCMAudio

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


class QueuedItem:
    item = None
    source: discord.AudioSource = None
    live_stream_file: str = None

    def __init__(self, item, source, live_stream_file=None):
        self.item = item
        self.source = source
        self.live_stream_file = live_stream_file


class FakeClient:
    _connected = None

    def __init__(self):
        self._connected = threading.Event()
        self._connected.set()

    def send_audio_packet(self, data, *, encode=True):
        pass


class AudioPlayer:
    _current: discord.AudioSource = None
    _voice: discord.VoiceClient = None
    _task = None
    _queue: asyncio.Queue = asyncio.Queue()
    _event: asyncio.Event = asyncio.Event()
    _bot: discord_commands.Bot = None

    _live_source: discord.AudioSource = None
    _live_player: DiscordAudioPlayer = None

    recent = None

    _volume: float = 0.5

    def __init__(self, bot):
        self._bot = bot
        self.recent = []

    @property
    def is_playing(self):
        if self._voice is None or self._voice is None:
            return False

        return self._voice.is_playing()

    async def set_voice(self, channel):
        if self._voice is None:
            self._voice = await channel.connect()
            self._task = self._bot.loop.create_task(self._audio_player())
        else:
            await self._voice.move_to(channel)

    @property
    def volume(self):
        return self._volume

    @property
    def current(self):
        if self._current is not None:
            return self._current.item
        return None

    @volume.setter
    def volume(self, volume) -> bool:
        if volume < 0.0:
            volume = 0.0
        elif volume > 1.0:
            volume = 1.0

        self._volume = volume
        if self._current is not None:
            self._current.volume = self._volume

    async def stop(self, disconnect=True):
        if self._current is not None:
            self._current.source.cleanup()
            self._current = None

        self.recent = []
        if self._live_source is not None:
            self._live_source.cleanup()
            self._live_source = None

        if self._live_player is not None:
            self._live_player = None

        if self._voice is not None:
            if self._voice.is_playing():
                self._voice.stop()
            if disconnect:
                if self._task is not None:
                    self._task.cancel()
                self._song_end()
                await self._voice.disconnect()
                self._voice = None

    async def kick(self, channel) -> bool:
        if self._voice is None:
            return False

        if self._voice.channel.id == channel.id:
            await self.stop()
            return True
        return False

    async def skip(self) -> bool:
        if self._voice is not None:
            if self._queue.qsize() < 1:
                await self.stop()
            else:
                self._voice.stop()
            return True
        return False

    async def add(self, db_item, source, live_stream_file=False):
        if self._voice is None:
            raise discord.DiscordException('Voice client is not set')

        item = QueuedItem(db_item, source, live_stream_file)
        await self._queue.put(item)

    def _song_end(self, error=None):
        self._bot.loop.call_soon_threadsafe(self._event.set)

    async def _audio_player(self):
        import logging
        logger = logging.getLogger('test')

        while True:
            self._event.clear()
            self._current = await self._queue.get()

            self.recent.insert(0, self._current.item)
            self.recent = self.recent[:10]

            if self._current.live_stream_file is not None:
                try:
                    self._live_source = self._current.source
                    self._live_player = DiscordAudioPlayer(
                        self._live_source, FakeClient(), after=self._song_end)
                    self._live_player.start()
                    await asyncio.sleep(10)

                    self._current.source = FFmpegPCMAudio(
                        self._current.live_stream_file,
                    )
                except Exception as e:
                    logger.error(f'{type(e).__name__}: {e}')

            self._current.source = discord.PCMVolumeTransformer(
                self._current.source, volume=self._volume)
            self._voice.play(self._current.source, after=self._song_end)

            await self._event.wait()
            self._current = None


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


@dataclass
class BotState:
    """Class to store the state for Discord bot"""
    xm_state: XMState = None
    player: AudioPlayer = None
    _bot: discord_commands.Bot = None

    def __init__(self, state_dict, bot):
        self._bot = bot
        self.xm_state = XMState(state_dict)
        self.player = AudioPlayer(bot)


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
