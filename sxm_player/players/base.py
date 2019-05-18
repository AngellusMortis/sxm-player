from typing import List, Optional, Type

import click

from ..workers import BaseWorker


class BasePlayer:
    @staticmethod
    def get_options() -> List[click.Parameter]:
        return []

    @staticmethod
    def get_worker() -> Optional[Type[BaseWorker]]:
        return None
