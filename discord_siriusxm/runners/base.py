import logging
import time
from dataclasses import dataclass

from ..models import XMState


@dataclass
class BaseRunner:
    state: XMState
    _log: logging.Logger

    name: str = 'runner'

    _delay: int = 1
    _do_loop: bool = True

    def __init__(self, state_dict: dict, name: str = 'runner', delay: int = 1):
        self._delay = delay
        self.name = name

        self.state = XMState(state_dict)
        self._log = logging.getLogger(f'discord_siriusxm.{name}')

    def loop(self):
        pass

    def run(self):
        self._log.info(f'{self.name} runner has started')
        while self._do_loop:
            time.sleep(self._delay)
            self.loop()
