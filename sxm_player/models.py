import logging
import time
from datetime import datetime
from typing import List, Optional, Tuple, Union

from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.session import Session

from sxm.models import XMChannel, XMLiveChannel

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


class PlayerState:
    COOLDOWN_SHORT = 30
    COOLDOWN_MED = 300
    COOLDOWN_LONG = 3600

    stream_url: Optional[str] = None
    stream_channel: Optional[str] = None
    processed_folder: Optional[str] = None
    db_reset: bool = False
    sxm_running: bool = False
    player_name: Optional[str] = None

    _db: Optional[Session] = None
    _raw_channels: Optional[List[dict]] = None
    _raw_live: Optional[dict] = None
    _channels: Optional[List[XMChannel]] = None
    _live: Optional[XMLiveChannel] = None
    _failures: int = 0
    _cooldown: float = 0
    _start_time: Optional[float] = None
    _time_offset: Optional[float] = None

    @property
    def stream_data(self) -> Tuple[Optional[str], Optional[str]]:
        return (self.stream_channel, self.stream_url)

    @stream_data.setter
    def stream_data(self, value) -> None:
        self.stream_channel = value[0]
        self.stream_url = value[1]

    @property
    def channels(self) -> List[XMChannel]:
        """ Returns list of `XMChannel` """

        if self._channels is None:
            if self._raw_channels is None:
                return []
            self._channels = []
            for channel in self._raw_channels:
                self._channels.append(XMChannel(channel))
        return self._channels

    @channels.setter
    def channels(self, value: Optional[List[dict]]) -> None:
        """ Sets channel key in internal `_raw_channels`. """

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

            self._db = init_db(self.processed_folder, self.db_reset)
        return self._db

    @property
    def live(self) -> Union[XMLiveChannel, None]:
        """ Returns current `XMLiveChannel` """

        return self._live

    @live.setter
    def live(self, value: dict) -> None:
        """ Sets live key in internal `_raw_live`. """

        now = int(time.time() * 1000)
        self._live = None
        self._start_time = None
        self._raw_live = value

        if self._raw_live is not None:
            self._live = XMLiveChannel(self._raw_live)

            if self._live.tune_time is not None:
                self._time_offset = now - self._live.tune_time

            if self._start_time is None:
                if self._live.tune_time is None:
                    self._start_time = now
                else:
                    self._start_time = self._live.tune_time
        else:
            self._time_offset = 0

    def get_raw_live(
        self
    ) -> Tuple[Optional[float], Optional[float], Optional[dict]]:
        return (self._start_time, self._time_offset, self._raw_live)

    def set_raw_live(
        self,
        live_data: Tuple[Optional[float], Optional[float], Optional[dict]],
    ):
        self._start_time = live_data[0]
        self._time_offset = live_data[1]
        self._raw_live = live_data[2]

        if self._raw_live is not None:
            self._live = XMLiveChannel(self._raw_live)

    @property
    def radio_time(self) -> Union[int, None]:
        """ Returns current time for the radio """

        if self.live is None:
            return None
        # still working on offset:  - self.time_offset
        return int(time.time() * 1000)

    @property
    def start_time(self) -> Union[float, None]:
        """ Returns the start time for the current SiriusXM channel """

        if self.live is None:
            return None
        return self._start_time

    @property
    def is_connected(self) -> bool:
        is_connected = self._raw_channels is not None
        if is_connected:
            self._failures = 0
        return is_connected

    @property
    def can_connect(self) -> bool:
        return time.time() > self._cooldown

    def mark_attempt(self, logger: logging.Logger) -> float:
        if self.can_connect:
            self.mark_failure()
            extra_seconds = self.increase_cooldown()

            logger.info(
                "Attempting to connect SXM Client (next in "
                f"{extra_seconds} seconds)"
            )
            return True
        return False

    def increase_cooldown(self) -> float:
        extra_seconds = 0
        if self._failures < 3:
            extra_seconds = PlayerState.COOLDOWN_SHORT
        elif self._failures < 5:
            extra_seconds = PlayerState.COOLDOWN_MED
        else:
            extra_seconds = PlayerState.COOLDOWN_LONG

        self._cooldown = time.time() + extra_seconds

        return extra_seconds

    def mark_failure(self) -> float:
        self._failures += 1
        return self._cooldown

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
