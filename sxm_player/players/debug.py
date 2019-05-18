from typing import Optional, Tuple, Type

from ..workers import BaseWorker, DebugWorker
from .base import BasePlayer


class DebugPlayer(BasePlayer):
    @staticmethod
    def get_worker_args() -> Optional[Tuple[Type[BaseWorker], str, dict]]:
        return (DebugWorker, "debug", {})
