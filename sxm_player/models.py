import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Union

from pydantic import BaseModel, PrivateAttr  # pylint: disable=no-name-in-module
from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session
from sxm.models import XMChannel, XMLiveChannel

COOLDOWN_SHORT = 10
COOLDOWN_MED = 60
COOLDOWN_LONG = 600

Base = declarative_base()


class DBSong(Base):
    __tablename__ = "songs"

    guid = Column(String, primary_key=True)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    album = Column(String, nullable=True)
    air_time = Column(DateTime)
    channel = Column(String)
    file_path = Column(String)
    image_url = Column(String, nullable=True)


class Song(BaseModel):
    guid: str
    title: str
    artist: str
    album: Optional[str]
    air_time: datetime
    channel: str
    file_path: str
    image_url: Optional[str]

    class Config:
        orm_mode = True

    @property
    def air_time_smart(self):
        return self.air_time.replace(tzinfo=timezone.utc)

    @staticmethod
    def get_pretty_name(
        title: Optional[str], artist: Optional[str], bold: bool = False
    ) -> str:
        """Returns a formatted name of song"""

        if title is None:
            title = ""

        if artist is None:
            artist = ""

        mod = ""
        if bold:
            mod = "**"

        return f'{mod}"{title}"{mod} by {mod}{artist}{mod}'

    @property
    def pretty_name(self) -> str:
        """Returns a formatted name of song"""

        return Song.get_pretty_name(self.title, self.artist)

    @property
    def bold_name(self) -> str:
        """Returns a formatted name of song"""

        return Song.get_pretty_name(self.title, self.artist, True)


class DBEpisode(Base):
    __tablename__ = "episodes"

    guid = Column(String, primary_key=True)
    title = Column(String, index=True)
    show = Column(String, nullable=True, index=True)
    air_time = Column(DateTime)
    channel = Column(String)
    file_path = Column(String)
    image_url = Column(String, nullable=True)


class Episode(BaseModel):
    guid: str
    title: str
    show: str
    air_time: datetime
    channel: str
    file_path: str
    image_url: Optional[str]

    class Config:
        orm_mode = True

    @staticmethod
    def get_pretty_name(
        title: Optional[str],
        show: Optional[str],
        air_time: Optional[datetime],
        bold: bool = False,
    ) -> str:
        """Returns a formatted name of show"""

        if title is None:
            title = ""

        if show is None:
            show = ""

        mod = ""
        if bold:
            mod = "**"

        if air_time is None:
            f'{mod}"{title}"{mod} ({show})'
        return f'{mod}"{title}"{mod} ({show}) from {air_time}'

    @property
    def pretty_name(self) -> str:
        """Returns a formatted name of show"""

        return Episode.get_pretty_name(self.title, self.show, self.air_time)

    @property
    def bold_name(self) -> str:
        """Returns a formatted name of show"""

        return Episode.get_pretty_name(self.title, self.show, self.air_time, True)


class PlayerState(BaseModel):
    stream_url: Optional[str] = None
    stream_channel: Optional[str] = None
    processed_folder: Optional[str] = None
    db_reset: bool = False
    sxm_running: bool = False
    player_name: Optional[str] = None

    _db: Optional[Session] = PrivateAttr(None)
    _raw_channels: Optional[List[dict]] = PrivateAttr(None)
    _raw_live: Optional[dict] = PrivateAttr(None)
    _channels: Optional[List[XMChannel]] = PrivateAttr(None)
    _live: Optional[XMLiveChannel] = PrivateAttr(None)
    _failures: int = PrivateAttr(0)
    _cooldown: float = PrivateAttr(0)
    _last_failure: float = PrivateAttr(0)
    _start_time: Optional[datetime] = PrivateAttr(None)
    _time_offset: Optional[timedelta] = PrivateAttr(None)

    @property
    def stream_data(self) -> Tuple[Optional[str], Optional[str]]:
        return (self.stream_channel, self.stream_url)

    def update_stream_data(self, value: Tuple[Optional[str], Optional[str]]) -> None:
        self.stream_channel = value[0]
        self.stream_url = value[1]

    @property
    def channels(self) -> List[XMChannel]:
        """Returns list of `XMChannel`"""

        if self._channels is None:
            if self._raw_channels is None:
                return []
            self._channels = []
            for channel in self._raw_channels:
                self._channels.append(XMChannel.from_dict(channel))
        return self._channels

    def update_channels(self, value: Optional[List[dict]]) -> None:
        """
        Sets channel key in internal `_raw_channels`.
        """

        self._channels = None
        self._raw_channels = value

        if self._raw_channels is None:
            self.stream_url = None
            self.stream_channel = None

    def get_raw_channels(self) -> Optional[List[dict]]:
        return self._raw_channels

    @property
    def db(self) -> Union[Session, None]:
        if self._db is None and self.processed_folder is not None:
            from .utils import init_db

            self._db = init_db(self.processed_folder, reset=self.db_reset)
        return self._db

    @property
    def live(self) -> Union[XMLiveChannel, None]:
        """Returns current `XMLiveChannel`"""

        return self._live

    def update_live(self, value: dict) -> None:
        """Sets live key in internal `_raw_live`."""

        now = datetime.now(timezone.utc)
        self._live = None
        self._raw_live = value

        if self._raw_live is not None:
            self._live = XMLiveChannel.from_dict(self._raw_live)

            if self._live.tune_time is not None:
                self._time_offset = now - self._live.tune_time

            if self._start_time is None:
                if self._live.tune_time is None:
                    self._start_time = now
                else:
                    self._start_time = self._live.tune_time
        else:
            self._time_offset = 0
            self._start_time = None

    def get_raw_live(
        self,
    ) -> Tuple[Optional[datetime], Optional[timedelta], Optional[dict]]:
        return (self._start_time, self._time_offset, self._raw_live)

    def set_raw_live(
        self,
        live_data: Tuple[Optional[datetime], Optional[timedelta], Optional[dict]],
    ):
        self._start_time = live_data[0]
        self._time_offset = live_data[1]
        self._raw_live = live_data[2]

        if self._raw_live is not None:
            self._live = XMLiveChannel.from_dict(self._raw_live)

    @property
    def radio_time(self) -> Union[datetime, None]:
        """Returns current time for the radio"""

        if self.live is None:
            return None

        now = datetime.now(timezone.utc)
        if self._time_offset is not None:
            return now - self._time_offset
        return now

    @property
    def start_time(self) -> Optional[datetime]:
        """Returns the start time for the current SiriusXM channel"""

        if self.live is None:
            return None
        return self._start_time

    @property
    def is_connected(self) -> bool:
        is_connected = self._raw_channels is not None
        if is_connected and time.monotonic() - self._last_failure > 300:
            self._failures = 0
        return is_connected

    @property
    def can_connect(self) -> bool:
        return time.monotonic() > self._cooldown

    def mark_attempt(self, logger: logging.Logger) -> float:
        if self.can_connect:
            self.mark_failure()
            extra_seconds = self.increase_cooldown()

            logger.info(
                "Attempting to connect SXM Client (next in " f"{extra_seconds} seconds)"
            )
            return True
        return False

    def increase_cooldown(self) -> float:
        extra_seconds = 0
        if self._failures < 3:
            extra_seconds = COOLDOWN_SHORT
        elif self._failures < 5:
            extra_seconds = COOLDOWN_MED
        else:
            extra_seconds = COOLDOWN_LONG

        self._cooldown = time.monotonic() + extra_seconds

        return extra_seconds

    def mark_failure(self) -> float:
        self._failures += 1
        self._last_failure = time.monotonic()
        return self._cooldown

    def get_channel(self, name: str) -> Union[XMChannel, None]:
        """Returns channel from list of `channels` with given name"""

        name = name.lower()
        for channel in self.channels:
            if (
                channel.name.lower() == name
                or channel.id.lower() == name
                or channel.channel_number == name
            ):
                return channel
        return None
