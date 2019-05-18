from typing import Optional, Type

from ..workers import BaseWorker, DebugWorker
from .base import BasePlayer


class DebugPlayer(BasePlayer):
    @staticmethod
    def get_worker() -> Optional[Type[BaseWorker]]:
        return DebugWorker
