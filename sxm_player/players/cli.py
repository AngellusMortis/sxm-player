from typing import List, Optional, Tuple, Type

import click

from ..models import PlayerState
from ..runner import Runner
from ..workers import BaseWorker, CLIPlayerWorker
from .base import BasePlayer, Option


class CLIPlayer(BasePlayer):
    params = [
        Option(
            "--channel-id",
            required=True,
            type=str,
            help="SXM Channel to Player",
        ),
        Option(
            "--filename",
            default="player.mp3",
            type=click.Path(dir_okay=False, writable=True, resolve_path=True),
            help="Path for output mp3 file",
        ),
    ]

    @staticmethod
    def get_params() -> List[click.Parameter]:
        return CLIPlayer.params  # type: ignore

    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:

        context = click.get_current_context()
        params = {
            "filename": context.params["filename"],
            "stream_protocol": "udp",
            "sxm_status": state.sxm_running,
            "stream_data": (context.params["channel_id"], state.stream_url),
            "channels": state.get_raw_channels(),
            "raw_live_data": state.get_raw_live(),
        }

        return (CLIPlayerWorker, "cli_player", params)
