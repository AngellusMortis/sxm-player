import logging
import traceback
from typing import Type

from .base import BaseRunner
from .bot import BotRunner
from .hls import HLSRunner
from .server import ServerRunner

__all__ = ['BotRunner', 'HLSRunner', 'ServerRunner', 'run']


def run(cls: Type[BaseRunner], state_dict: dict, *args, **kwargs) -> None:
    logger = logging.getLogger('discord_siriusxm.runner')

    try:
        runner = cls(state_dict=state_dict, *args, **kwargs)  # type: ignore
    except Exception as e:
        logger.error('error while initializing runner:')
        logger.error(traceback.format_exc())
        raise(e)

    try:
        runner.run()
    except Exception as e:
        logger.error('error while running runner:')
        logger.error(traceback.format_exc())
        raise(e)
