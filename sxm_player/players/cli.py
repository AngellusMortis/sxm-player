from typing import List, Optional, Tuple, Type

import click

from sxm_player.models import PlayerState
from sxm_player.players.base import BasePlayer, Option
from sxm_player.runner import Runner
from sxm_player.workers import BaseWorker, CLIPlayerWorker


class CLIPlayer(BasePlayer):
    params: List[click.Parameter] = [
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
        return CLIPlayer.params

    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:

        context = click.get_current_context()
        params = {
            "filename": context.meta["filename"],
            "stream_protocol": "udp",
            "sxm_status": state.sxm_running,
            "stream_data": (context.meta["channel_id"], state.stream_url),
            "channels": state.get_raw_channels(),
            "raw_live_data": state.get_raw_live(),
        }

        return (CLIPlayerWorker, "cli_player", params)
