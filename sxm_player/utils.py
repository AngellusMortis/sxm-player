import datetime
import logging
import os
import select
import shlex
import subprocess  # nosec
from typing import List, Optional, Union

import coloredlogs
import psutil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from sxm.models import XMMarker

from .models import Episode, Song

ACTIVE_PROCESS_STATUSES = [
    psutil.STATUS_RUNNING,
    psutil.STATUS_SLEEPING,
    psutil.STATUS_DISK_SLEEP,
]


unrelated_loggers = [
    "discord.client",
    "discord.gateway",
    "discord.http",
    "plexapi",
    "urllib3.connectionpool",
    "websockets.protocol",
]

logger = logging.getLogger("sxm_player.utils")


def init_db(
    base_folder: str,
    cleanup: Optional[bool] = True,
    reset: Optional[bool] = False,
) -> Session:
    """ Initializes song database connection """

    from .models import Base

    os.makedirs(base_folder, exist_ok=True)

    song_db = os.path.join(base_folder, "songs.db")

    if reset and os.path.exists(song_db):
        os.remove(song_db)

    db_engine = create_engine(f"sqlite:///{song_db}")
    Base.metadata.create_all(db_engine)
    db_session = sessionmaker(bind=db_engine)()

    if cleanup:
        removed = 0
        for song in db_session.query(Song).all():
            if not os.path.exists(song.file_path):
                removed += 1
                db_session.delete(song)

        for show in db_session.query(Episode).all():
            if not os.path.exists(show.file_path):
                removed += 1
                db_session.delete(show)

        if removed > 0:
            logger.warn(f"deleted missing songs/shows: {removed}")
            db_session.commit()

    return db_session


def get_air_time(cut: XMMarker) -> datetime.datetime:
    """ Dates UTC datetime object for the air
    date of a `XMMarker` to the hour """

    air_time = datetime.datetime.fromtimestamp(
        int(cut.time / 1000), tz=datetime.timezone.utc
    )
    air_time = air_time.replace(minute=0, second=0, microsecond=0)

    return air_time


def get_files(folder: str) -> List[str]:
    """ Gets list of files in a folder """

    dir_list = os.listdir(folder)

    files = []
    for dir_item in dir_list:
        abs_path = os.path.join(folder, dir_item)
        if os.path.isfile(abs_path):
            files.append(dir_item)

    return files


def splice_file(
    input_file: str, output_file: str, start_time: int, end_time: int
) -> Union[str, None]:
    """ Splices a chunk off of the input file and saves it """

    ffmpeg_command = (
        'ffmpeg -y -i "{}" -acodec copy -ss {} -to {} -loglevel fatal "{}"'
    )
    args = shlex.split(
        ffmpeg_command.format(input_file, start_time, end_time, output_file)
    )

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    try:
        subprocess.run(args, check=True)  # nosec
    except subprocess.CalledProcessError as e:
        logger.error(f"failed to split file: {e}")
        return None
    else:
        logger.info(f"spliced file: {output_file}")
        return output_file


def configure_root_logger(level: str, log_file: Optional[str] = None):
    root_logger = logging.getLogger()
    if len(root_logger.handlers) == 0:
        if log_file is not None:
            fh = logging.FileHandler(log_file)
            formatter = logging.Formatter(
                "%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s"
            )
            fh.setLevel(level)
            fh.setFormatter(formatter)
            root_logger.addHandler(fh)
        coloredlogs.install(level=level, logger=root_logger)

    for logger in unrelated_loggers:
        logging.getLogger(logger).setLevel(logging.INFO)


class FFmpeg:
    command: str
    process: Optional[subprocess.Popen] = None

    _stderr_poll: Optional[select.poll] = None  # pylint: disable=E1101

    def start_ffmpeg(self) -> None:
        ffmpeg_args = shlex.split(self.command)

        self.process = subprocess.Popen(  # nosec
            ffmpeg_args, stderr=subprocess.PIPE
        )

        self._stderr_poll = select.poll()  # pylint: disable=E1101
        self._stderr_poll.register(
            self.process.stderr, select.POLLIN  # pylint: disable=E1101 # noqa
        )

    def check_process(self) -> bool:
        if self.process is None:
            return False

        process = psutil.Process(self.process.pid)
        status = process.status()

        return status in ACTIVE_PROCESS_STATUSES

    def stop_ffmpeg(self) -> None:
        if self.process is None:
            return

        self.process.kill()
        if self.process.poll() is None:
            self.process.communicate()

        self.process = None

    def read_errors(self) -> List[str]:
        if self.process is None or self._stderr_poll is None:
            return []

        lines: List[str] = []
        while self._stderr_poll.poll(0.1):
            lines.append(self.process.stderr.readline().decode("utf8"))

        return lines
