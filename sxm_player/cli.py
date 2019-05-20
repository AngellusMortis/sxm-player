# -*- coding: utf-8 -*-

"""Console script for sxm_player."""
import os
from multiprocessing import set_start_method
from typing import Optional, Type

import click
import psutil

from . import handlers
from .command import ConfigCommandClass, PlayerClass
from .models import PlayerState
from .players import BasePlayer
from .queue import Event, EventMessage
from .runner import Runner
from .utils import ACTIVE_PROCESS_STATUSES
from .workers import ServerWorker, StatusWorker


@click.command(cls=ConfigCommandClass)
# Generic Parameters
@click.option(
    "-c",
    "--config-file",
    type=click.Path(),
    help="Config file to read vars from",
)
@click.option(
    "-l", "--log-file", type=click.Path(), default=None, help="output log file"
)
@click.option("-d", "--debug", is_flag=True, help="enable debug logging")
# SXM Parameters
@click.option(
    "-p",
    "--port",
    type=int,
    default=9999,
    help="port to run SXM Proxy server on",
)
@click.option(
    "-h",
    "--host",
    type=str,
    default="127.0.0.1",
    help="IP to bind SXM Proxy server to",
)
@click.option(
    "--username",
    type=str,
    envvar="SXM_USERNAME",
    help="SXM Username",
    required=True,
)
@click.option(
    "--password",
    type=str,
    envvar="SXM_PASSWORD",
    help="SXM Password",
    required=True,
)
@click.option(
    "-r",
    "--region",
    type=click.Choice(["US", "CA"]),
    default="US",
    help="Sets the SXM client's region",
)
# Archiving/Processing parameters
@click.option(
    "-o",
    "--output-folder",
    type=click.Path(),
    default=None,
    envvar="MUSIC_OUTPUT_FOLDER",
    help="output folder to save stream off to as it plays them",
)
@click.option(
    "-r", "--reset-songs", is_flag=True, help="reset processed song database"
)
# Player paramaters
@click.argument(
    "player_class", type=PlayerClass(), required=False, default=None
)
def main(
    config_file: str,
    log_file: str,
    debug: bool,
    username: str,
    password: str,
    region: str,
    port: int,
    host: str,
    output_folder: str,
    reset_songs: bool,
    player_class: Type[BasePlayer],
    **kwargs,
):
    """Command line interface for sxm-player"""

    if debug:
        set_start_method("spawn")

    os.system("/usr/bin/clear")  # nosec

    with Runner(log_file, debug) as runner:
        state = PlayerState()

        runner.create_worker(
            StatusWorker,
            StatusWorker.NAME,
            port=port,
            ip=host,
            sxm_status=state.sxm_running,
        )

        if player_class is not None:
            worker_args = player_class.get_worker_args(**locals())
            if worker_args is not None:
                state.player_name = worker_args[1]
                runner.create_worker(
                    worker_args[0], worker_args[1], **(worker_args[2])
                )

        while not runner.shutdown_event.is_set():  # type: ignore
            event_loop(**locals())

    return 0


def spawn_sxm_worker(
    runner: Runner,
    host: str,
    port: int,
    username: str,
    password: str,
    region: str,
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
            handlers.sxm_status_event(
                runner, Event.SXM_STATUS, state.sxm_running
            )

    check_player(runner, state)


def handle_event(event: EventMessage, **kwargs):
    runner = kwargs["runner"]
    debug = kwargs["debug"]
    event_name = event.msg_type.name.lower()
    is_debug_event = event_name.startswith("debug")
    handler_name = f"handle_{event_name}_event"

    if hasattr(handlers, handler_name) and (not is_debug_event or debug):
        getattr(handlers, handler_name)(event, **kwargs)
    else:
        runner.log.warning(
            f"Unknown event received: {event.msg_src}, {event.msg_type}"
        )


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
            runner.shutdown_event.set()  # type: ignore
