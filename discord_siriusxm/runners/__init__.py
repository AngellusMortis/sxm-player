import logging
import traceback

from .base import BaseRunner
from .bot import BotRunner
from .server import ServerRunner

__all__ = ['BotRunner', 'ServerRunner', 'run']


def run(cls: BaseRunner, state_dict: dict, *args, **kwargs) -> None:
    logger = logging.getLogger('discord_siriusxm.runner')

    try:
        runner = cls(state_dict=state_dict, *args, **kwargs)
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
