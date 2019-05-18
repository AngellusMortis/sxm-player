from typing import List, Optional, Tuple, Type

import click

from ..workers import BaseWorker


class BasePlayer:
    @staticmethod
    def get_options() -> List[click.Parameter]:
        return []

    @staticmethod
    def get_worker_args() -> Optional[Tuple[Type[BaseWorker], str, dict]]:
        return None
