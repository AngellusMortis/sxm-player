import logging
import os
import time
from dataclasses import dataclass
from multiprocessing import Lock
from typing import Optional

from ..models import XMState
from ..utils import configure_root_logger


@dataclass
class BaseRunner:
    state: XMState
    _log: logging.Logger

    name: str = "runner"

    _delay: int = 1
    _do_loop: bool = True

    def __init__(
        self,
        state_dict: dict,
        lock: Lock,  # type: ignore
        log_level: str,
        log_file: Optional[str] = None,
        name: str = "runner",
        delay: int = 1,
        reset_songs: bool = False,
    ):

        configure_root_logger(log_level, log_file)

        self._delay = delay
        self._log = logging.getLogger(f"mortis_music.{name}")

        self.name = name
        self.state = XMState(state_dict, lock, db_reset=reset_songs)
        self.state.set_runner(name, os.getpid())

    def loop(self):
        pass

    def run(self):
        self._log.info(f"{self.name} runner has started")
        while self._do_loop:
            time.sleep(self._delay)
            self.loop()
