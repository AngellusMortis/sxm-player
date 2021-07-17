# -*- coding: utf-8 -*-

"""Console script for sxm_player."""
import os
from multiprocessing import set_start_method
from pathlib import Path
from typing import Optional, Type

import psutil
import typer
from sxm import QualitySize, RegionChoice
from sxm.cli import (
    OPTION_HOST,
    OPTION_PASSWORD,
    OPTION_PORT,
    OPTION_QUALITY,
    OPTION_REGION,
    OPTION_USERNAME,
    OPTION_VERBOSE,
)

from sxm_player import handlers
from sxm_player.command import validate_player
from sxm_player.models import PlayerState
from sxm_player.players import BasePlayer
from sxm_player.queue import EventMessage, EventTypes
from sxm_player.runner import Runner
from sxm_player.utils import ACTIVE_PROCESS_STATUSES
from sxm_player.workers import ServerWorker, StatusWorker

OPTION_CONFIG_FILE = typer.Option(
    None,
    "-c",
    "--config-file",
    exists=True,
    file_okay=True,
    dir_okay=False,
    readable=True,
    resolve_path=True,
    help="Config file to read vars from",
)
OPTION_LOG_FILE = typer.Option(
    None,
    "-l",
    "--log-file",
    exists=True,
    file_okay=True,
    resolve_path=True,
    dir_okay=False,
    readable=True,
    help="Output log file",
)
OPTION_OUTPUT_FOLDER = typer.Option(
    None,
    "-o",
    "--output-folder",
    file_okay=False,
    dir_okay=True,
    readable=True,
    writable=True,
    resolve_path=True,
    envvar="SXM_OUTPUT_FOLDER",
    help="output folder to save stream off to as it plays them",
)
OPTION_RESET_SONGS = typer.Option(
    False,
    "-R",
    "--reset-songs",
    help="Reset processed song database",
)
ARG_PLAYER_CLASS = typer.Argument(
    None, callback=validate_player, help="Optional Player Class to use"
)


def main(
    config_file: Optional[Path] = OPTION_CONFIG_FILE,
    log_file: Optional[Path] = OPTION_LOG_FILE,
    verbose: bool = OPTION_VERBOSE,
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    region: RegionChoice = OPTION_REGION,
    quality: QualitySize = OPTION_QUALITY,
    port: int = OPTION_PORT,
    host: str = OPTION_HOST,
    output_folder: Optional[Path] = OPTION_OUTPUT_FOLDER,
    reset_songs: bool = OPTION_RESET_SONGS,
    player_class: Optional[str] = ARG_PLAYER_CLASS,
):
    """Command line interface for sxm-player"""

    if verbose:
        set_start_method("spawn")

    os.system("/usr/bin/clear")  # nosec

    klass: Optional[Type[BasePlayer]] = None
    if player_class is not None:
        klass = player_class  # type: ignore

    with Runner(log_file, verbose) as runner:
        state = PlayerState()

        runner.create_worker(
            StatusWorker,
            StatusWorker.NAME,
            port=port,
            ip=host,
            sxm_status=state.sxm_running,
        )

        if klass is not None:
            worker_args = klass.get_worker_args(**locals())
            if worker_args is not None:
                state.player_name = worker_args[1]
                runner.create_worker(worker_args[0], worker_args[1], **(worker_args[2]))

        while not runner.shutdown_event.is_set():
            event_loop(**locals())

    return 0


def spawn_sxm_worker(
    runner: Runner,
    host: str,
    port: int,
    username: str,
    password: str,
    region: RegionChoice,
    quality: QualitySize,
    **kwargs,
):
    runner.create_worker(
        ServerWorker,
        ServerWorker.NAME,
        port=port,
        ip=host,
        username=username,
        password=password,
        region=region,
        quality=quality,
    )


def event_loop(runner: Runner, state: PlayerState, **kwargs):
    if not state.is_connected:
        if state.mark_attempt(runner.log):
            spawn_sxm_worker(runner, **kwargs)

    event = runner.event_queue.safe_get()

    if not event:
        return

    runner.log.debug(f"Received event: {event.msg_src}, {event.msg_type.name}")

    was_connected: Optional[bool] = None
    if event.msg_src == ServerWorker.NAME:
        was_connected = state.is_connected

    handle_event(event=event, runner=runner, state=state, **kwargs)

    if was_connected is False and state.is_connected:
        if not was_connected and state.is_connected:
            runner.log.info(
                f"SXM Client started. {len(state.channels)} channels available"
            )

            state.sxm_running = True
            handlers.sxm_status_event(runner, EventTypes.SXM_STATUS, state.sxm_running)

    check_player(runner, state)


def handle_event(event: EventMessage, **kwargs):
    runner = kwargs["runner"]
    debug = kwargs["verbose"]
    event_name = event.msg_type.name.lower()
    is_debug_event = event_name.startswith("debug")
    handler_name = f"handle_{event_name}_event"

    if hasattr(handlers, handler_name) and (not is_debug_event or debug):
        getattr(handlers, handler_name)(event, **kwargs)
    else:
        runner.log.warning(f"Unknown event received: {event.msg_src}, {event.msg_type}")


def check_player(runner: Runner, state: PlayerState):
    if state.player_name is not None:
        player = runner.workers.get(state.player_name)
        running = True

        if player is None:
            running = False
        else:
            process = psutil.Process(player.process.pid)
            if process.status() not in ACTIVE_PROCESS_STATUSES:
                running = False

        if not running:
            runner.log.info("Player has stopped, shutting down")
            runner.shutdown_event.set()
