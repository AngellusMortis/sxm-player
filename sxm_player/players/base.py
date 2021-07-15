import inspect
from typing import List, Optional, Tuple, Type

import click

from sxm_player.models import PlayerState
from sxm_player.runner import Runner
from sxm_player.workers import BaseWorker


class BasePlayer:
    @staticmethod
    def get_params() -> List[click.Parameter]:
        return []

    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:
        return None


class Option(click.Option):
    def __init__(self, *params_decls, **kwargs):
        if "help" in kwargs:
            kwargs["help"] = inspect.cleandoc(kwargs["help"])

        super().__init__(params_decls, **kwargs)
