import logging
import traceback
from typing import Optional, Type
from multiprocessing import Lock

from .archiver import ArchiveRunner
from .base import BaseRunner
from .bot import BotRunner
from .hls import HLSRunner
from .processor import ProcessorRunner
from .server import ServerRunner
from ..utils import configure_root_logger

__all__ = [
    "ArchiveRunner",
    "BotRunner",
    "HLSRunner",
    "ProcessorRunner",
    "ServerRunner",
    "run",
]


def run(
    cls: Type[BaseRunner],
    state_dict: dict,
    lock: Lock,  # type: ignore
    log_level: str,
    log_file: Optional[str] = None,
    *args,
    **kwargs
) -> None:
    logger = logging.getLogger("mortis_music.runner")

    kwargs["state_dict"] = state_dict
    kwargs["lock"] = lock

    configure_root_logger(log_level, log_file)

    try:
        runner = cls(*args, **kwargs)  # type: ignore
    except Exception as e:
        logger.error("error while initializing runner:")
        logger.error(traceback.format_exc())
        raise (e)

    try:
        runner.run()
    except Exception as e:
        logger.error("error while running runner:")
        logger.error(traceback.format_exc())
        raise (e)
