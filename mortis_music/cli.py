# -*- coding: utf-8 -*-

"""Console script for mortis_music."""
import os
from multiprocessing import set_start_method
from typing import Optional

import click

from . import handlers
from .models import XMState
from .queue import EventMessage
from .runner import Runner
from .utils import CustomCommandClass
from .workers import DebugWorker, ServerWorker, StatusWorker


@click.command(cls=CustomCommandClass)
# Generic Parameters
@click.option(
    "--config-file", type=click.Path(), help="Config file to read vars from"
)
@click.option(
    "-l", "--log-file", type=click.Path(), default=None, help="output log file"
)
@click.option("-d", "--debug", is_flag=True, help="enable debug logging")
# SiriusXM Parameters
@click.option(
    "-p",
    "--port",
    type=int,
    default=None,
    help="port to run SiriusXM Proxy server on",
)
@click.option(
    "-h",
    "--host",
    type=str,
    default=None,
    help="IP to bind SiriusXM Proxy server to. "
    "Must still be accessible via 127.0.0.1",
)
@click.option(
    "--username", type=str, envvar="SXM_USERNAME", help="SiriusXM Username"
)
@click.option(
    "--password", type=str, envvar="SXM_PASSWORD", help="SiriusXM Password"
)
@click.option(
    "-r",
    "--region",
    type=click.Choice(["US", "CA"]),
    default="US",
    help="Sets the SiriusXM client's region",
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
):
    """Command line interface for SiriusXM radio bot for Discord"""

    if debug:
        set_start_method("spawn")

    # context = click.get_current_context()
    os.system("/usr/bin/clear")  # nosec

    with Runner(log_file, debug) as runner:
        if debug and DebugWorker is not None:
            runner.create_worker(DebugWorker, DebugWorker.NAME)

        sxm_state = XMState()

        runner.create_worker(
            StatusWorker, StatusWorker.NAME, port=port, ip=host
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


def event_loop(runner: Runner, sxm_state: XMState, **kwargs):
    if not sxm_state.is_connected:
        if sxm_state.mark_attempt(runner.log):
            spawn_sxm_worker(runner, **kwargs)

    event = runner.event_queue.safe_get()

    if not event:
        return

    runner.log.debug(f"Received event: {event.msg_src}, {event.msg_type}")

    was_connected: Optional[bool] = None
    if event.msg_src == ServerWorker.NAME:
        was_connected = sxm_state.is_connected

    handle_event(event=event, runner=runner, sxm_state=sxm_state, **kwargs)

    if was_connected is False and sxm_state.is_connected:
        if not was_connected and sxm_state.is_connected:
            runner.log.info(
                "SiriusXM Client started. "
                f"{len(sxm_state.channels)} available"
            )

            handlers.sxm_status_event(runner, EventMessage.SXM_RUNNING_EVENT)


def handle_event(event: EventMessage, **kwargs):
    runner = kwargs["runner"]
    debug = kwargs["debug"]
    is_debug_event = event.msg_type.lower().startswith("debug")
    handler_name = f"handle_{event.msg_type.lower()}_event"

    if hasattr(handlers, handler_name) and (not is_debug_event or debug):
        getattr(handlers, handler_name)(event, **kwargs)
    else:
        runner.log.warning(
            f"Unknown event received: {event.msg_src}, {event.msg_type}"
        )
