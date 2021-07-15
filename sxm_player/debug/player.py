from typing import Optional, Tuple, Type

from sxm_player.models import PlayerState
from sxm_player.players.base import BasePlayer
from sxm_player.runner import Runner
from sxm_player.workers import BaseWorker, DebugWorker


class DebugPlayer(BasePlayer):
    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:
        return (DebugWorker, "debug", {})
