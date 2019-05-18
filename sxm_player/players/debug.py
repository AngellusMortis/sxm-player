from typing import Optional, Tuple, Type

from ..models import PlayerState
from ..runner import Runner
from ..workers import BaseWorker, DebugWorker
from .base import BasePlayer


class DebugPlayer(BasePlayer):
    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:
        return (DebugWorker, "debug", {})
