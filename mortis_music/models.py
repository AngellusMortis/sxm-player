import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime
from multiprocessing import Lock
from typing import List, Optional, Union

from discord import AudioSource, FFmpegPCMAudio, Game
from discord.ext.commands import CommandError
from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session

from sxm.models import XMChannel, XMImage, XMLiveChannel, XMSong

Base = declarative_base()


class Song(Base):  # type: ignore
    __tablename__ = "songs"

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

        mod = ""
        if bold:
            mod = "**"

        return f'{mod}"{title}"{mod} by {mod}{artist}{mod}'

    @property
    def pretty_name(self) -> str:
        """ Returns a formatted name of song """

        return Song.get_pretty_name(self.title, self.artist)

    @property
    def bold_name(self) -> str:
        """ Returns a formatted name of song """

        return Song.get_pretty_name(self.title, self.artist, True)


class Episode(Base):  # type: ignore
    __tablename__ = "episodes"

    guid: str = Column(String, primary_key=True)
    title: str = Column(String, index=True)
    show: str = Column(String, nullable=True, index=True)
    air_time: datetime = Column(DateTime)
    channel: str = Column(String)
    file_path: str = Column(String)

    @staticmethod
    def get_pretty_name(
        title: str, show: str, air_time: datetime, bold: bool = False
    ) -> str:
        """ Returns a formatted name of show """

        mod = ""
        if bold:
            mod = "**"

        return f'{mod}"{title}"{mod} ({show}) from {air_time}'

    @property
    def pretty_name(self) -> str:
        """ Returns a formatted name of show """

        return Episode.get_pretty_name(self.title, self.show, self.air_time)

    @property
    def bold_name(self) -> str:
        """ Returns a formatted name of show """

        return Episode.get_pretty_name(
            self.title, self.show, self.air_time, True
        )


class DictState:
    """Class that uses a shared memory dictionary to populate attributes"""

    lock: Lock  # type: ignore
    _state_dict: dict

    def __init__(self, state_dict: dict, lock: Lock):  # type: ignore
        self._lock = lock  # type: ignore
        self._state_dict = state_dict

    def __getattr__(self, attr: str):
        if not attr.startswith("_") and self._state_dict is not None:
            with self._lock:
                if attr in self._state_dict:
                    return self._state_dict[attr]
        else:
            raise AttributeError(
                "--%r object has no attribute %r" % (type(self).__name__, attr)
            )

    def __setattr__(self, attr: str, value) -> None:
        if not attr.startswith("_") and self._state_dict is not None:
            with self._lock:
                if attr in self._state_dict:
                    self._state_dict[attr] = value
        super().__setattr__(attr, value)


class XMState(DictState):
    """Class to store state SiriusXM Radio player for Discord Bot"""

    _channels: Optional[List[XMChannel]] = None
    _live_update_time: Optional[int] = None
    _live: Optional[XMLiveChannel] = None
    _archive_folder: Optional[str] = None
    _processed_folder: Optional[str] = None
    _stream_folder: Optional[str] = None

    _db: Session = None
    _db_reset: bool = False

    def __init__(
        self,
        state_dict: dict,
        lock: Lock,
        db_reset: bool = False,  # type: ignore
    ):
        super().__init__(state_dict, lock)

        self._db_reset = False

    @staticmethod
    def init_state(state_dict: dict) -> None:
        """ Initializes a dictionary that will be used
        for a `XMState` object """

        state_dict["active_channel_id"] = None
        state_dict["stream_url"] = None
        state_dict["channels"] = []
        state_dict["start_time"] = None
        state_dict["live"] = None
        state_dict["processing_file"] = False
        state_dict["live_update_time"] = None
        state_dict["time_offset"] = None
        state_dict["output"] = None
        state_dict["hls_errors"] = None
        state_dict["runners"] = {}

    @property
    def channels(self) -> List[XMChannel]:
        """ Returns list of `XMChannel` """

        with self._lock:
            if self._channels is None:
                self._channels = []
                for channel in self._state_dict["channels"]:
                    self._channels.append(XMChannel(channel))
            return self._channels

    @channels.setter
    def channels(self, value: dict) -> None:
        """ Sets channel key in internal `state_dict`. """

        with self._lock:
            self._channels = None
            self._state_dict["channels"] = value

    @property
    def live(self) -> Union[XMLiveChannel, None]:
        """ Returns current `XMLiveChannel` """

        with self._lock:
            last_update = self._state_dict["live_update_time"]
            now = int(time.time() * 1000)
            if self._live is None or self._live_update_time != last_update:
                if self._state_dict["live"] is not None:
                    self._live_update_time = last_update
                    self._live = XMLiveChannel(self._state_dict["live"])

                    if self._live.tune_time is not None:
                        self._state_dict["time_offset"] = (
                            now - self._live.tune_time
                        )

                    if self._state_dict["start_time"] is None:
                        if self._live.tune_time is None:
                            self._state_dict["start_time"] = now
                        else:
                            self._state_dict[
                                "start_time"
                            ] = self._live.tune_time
                else:
                    self._state_dict["time_offset"] = 0
            return self._live

    @live.setter
    def live(self, value: dict) -> None:
        """ Sets live key in internal `state_dict`. """

        with self._lock:
            self._live = None
            self._state_dict["start_time"] = None
            self._state_dict["live"] = value
            if value is not None:
                self._state_dict["live_update_time"] = time.time()

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
        return self._state_dict["start_time"]

    @property
    def archive_folder(self) -> Union[str, None]:
        """ Returns path to archive folder """

        if self._archive_folder is None:
            if self.output is not None:
                self._archive_folder = os.path.join(self.output, "archive")
        return self._archive_folder

    @property
    def processed_folder(self) -> Union[str, None]:
        """ Returns path to processed folder """

        if self._processed_folder is None:
            if self.output is not None:
                self._processed_folder = os.path.join(self.output, "processed")
        return self._processed_folder

    @property
    def stream_folder(self) -> Union[str, None]:
        """ Returns path to stream folder """

        if self._stream_folder is None:
            if self.output is not None:
                self._stream_folder = os.path.join(self.output, "streams")
        return self._stream_folder

    @property
    def db(self) -> Union[Session, None]:
        if self._db is None and self.processed_folder is not None:
            from .utils import init_db

            self._db = init_db(self.processed_folder, self._db_reset)
        return self._db

    def get_channel(self, name: str) -> Union[XMChannel, None]:
        """ Returns channel from list of `channels` with given name """

        name = name.lower()
        for channel in self.channels:
            if (
                channel.name.lower() == name
                or channel.id.lower() == name
                or channel.channel_number == name
            ):
                return channel
        return None

    def set_channel(self, channel_id: str) -> None:
        """ Sets active SiriusXM channel """

        self.active_channel_id = channel_id
        self.live = None

    def reset_channel(self) -> None:
        """ Removes active SiriusXM channel """

        self.active_channel_id = None  # type: ignore
        self.live = None

    def pop_hls_errors(self) -> Union[List[str], None]:
        errors = None
        with self._lock:
            if self._state_dict["hls_errors"] is not None:
                errors = self._state_dict["hls_errors"]
                self._state_dict["hls_errors"] = None
        return errors

    def push_hls_errors(self, errors) -> None:
        with self._lock:
            if self._state_dict["hls_errors"] is not None:
                errors = self._state_dict["hls_errors"] + errors
            self.state.hls_errors = errors

    def set_runner(self, name, pid):
        with self._lock:
            runners = self._state_dict["runners"]
            runners[name] = pid
            self._state_dict["runners"] = runners


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

        if state.active_channel_id is not self.channel.id:
            state.set_channel(self.channel.id)

            start = time.time()
            now = start
            can_start = False
            while not can_start and now - start < 30:
                await asyncio.sleep(0.1)
                now = time.time()
                if state.stream_url is not None and (now - start) > 5:
                    can_start = True

            if not can_start:
                raise CommandError("HLS stream not found")

        playback_source = FFmpegPCMAudio(
            state.stream_url,
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


@dataclass
class QueuedItem:
    audio_file: Union[Song, Episode, None] = None
    live: Optional[LiveStreamInfo] = None

    source: AudioSource = None