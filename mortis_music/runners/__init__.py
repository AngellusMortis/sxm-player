import logging
import traceback
from typing import Type
from multiprocessing import Lock

from .archiver import ArchiveRunner
from .base import BaseRunner
from .bot import BotRunner
from .hls import HLSRunner
from .processor import ProcessorRunner
from .server import ServerRunner

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
    *args,
    **kwargs
) -> None:
    logger = logging.getLogger("mortis_music.runner")

    kwargs["state_dict"] = state_dict
    kwargs["lock"] = lock

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
