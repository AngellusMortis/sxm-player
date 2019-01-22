# -*- coding: utf-8 -*-

"""Console script for discord_siriusxm."""
import logging
import os
import signal
import sys
import time
from multiprocessing import Manager, Pool

import click
import coloredlogs

from .models import XMState
from .runners import (
    ArchiveRunner,
    BotRunner,
    HLSRunner,
    ProcessorRunner,
    ServerRunner,
    run,
)


@click.command()
@click.option(
    "--username",
    type=str,
    prompt=True,
    envvar="SXM_USERNAME",
    help="SiriusXM Username",
)
@click.option(
    "--password",
    type=str,
    prompt=True,
    hide_input=True,
    envvar="SXM_PASSWORD",
    help="SiriusXM Password",
)
@click.option(
    "-r",
    "--region",
    type=click.Choice(["US", "CA"]),
    default="US",
    help="Sets the SiriusXM client's region",
)
@click.option(
    "--token",
    type=str,
    prompt=True,
    envvar="DISCORD_TOKEN",
    help="Discord bot token",
)
@click.option(
    "--prefix", type=str, default="/music ", help="Discord bot command prefix"
)
@click.option(
    "--description",
    type=str,
    default="SiriusXM radio bot for Discord",
    help="port to run SiriusXM Proxy server on",
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=9999,
    help="port to run SiriusXM Proxy server on",
)
@click.option(
    "-h",
    "--host",
    type=str,
    default="127.0.0.1",
    help="IP to bind SiriusXM Proxy server to. "
    "Must still be accessible via 127.0.0.1",
)
@click.option(
    "-o",
    "--output-folder",
    type=click.Path(),
    default=None,
    help="output folder to save stream off to as it plays them",
)
@click.option(
    "-r", "--reset-songs", is_flag=True, help="reset processed song database"
)
@click.option(
    "--plex-username",
    type=str,
    default=None,
    envvar="PLEX_USERNAME",
    help="Plex username for local server",
)
@click.option(
    "--plex-password",
    type=str,
    default=None,
    envvar="PLEX_PASSWORD",
    help="Plex password for local server",
)
@click.option(
    "--plex-server-name",
    type=str,
    default=None,
    envvar="PLEX_SERVER",
    help="Plex server name for local server",
)
@click.option(
    "--plex-library-name",
    type=str,
    default=None,
    envvar="PLEX_LIBRARY",
    help="Plex library name for local server",
)
@click.option(
    "-l",
    "--log-file",
    type=click.Path(),
    default=None,
    help="enable verbose logging (shows HTTP requests)",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="enable verbose logging (shows HTTP requests)",
)
@click.option("-vv", "--debug", is_flag=True, help="enable debug logging")
def main(
    username: str,
    password: str,
    region: str,
    token: str,
    prefix: str,
    description: str,
    port: int,
    host: str,
    output_folder: str,
    reset_songs: bool,
    verbose: bool,
    debug: bool,
    log_file: str,
    plex_username: str,
    plex_password: str,
    plex_server_name: str,
    plex_library_name: str,
):
    """Command line interface for SiriusXM radio bot for Discord"""

    level = "INFO"
    request_level = logging.WARN

    if debug:
        level = "DEBUG"
        request_level = logging.DEBUG
    elif verbose:
        request_level = logging.INFO

    if log_file is not None:
        logging.basicConfig(filename=log_file)
    coloredlogs.install(level=level)

    with Manager() as manager:
        state_dict = manager.dict()  # type: ignore
        XMState.init_state(state_dict)
        lock = manager.Lock()  # type: ignore # pylint: disable=E1101 # noqa
        state = XMState(state_dict, lock)
        logger = logging.getLogger("discord_siriusxm")

        process_count = 3
        if output_folder is not None:
            state.output = output_folder
            process_count = 5

        def init_worker():
            signal.signal(signal.SIGINT, signal.SIG_IGN)

        def is_running(name):
            try:
                os.kill(state.runners[name], 0)
                return True
            except (KeyError, TypeError, ProcessLookupError):
                state.set_runner(name, None)
                return False

        with Pool(processes=process_count, initializer=init_worker) as pool:
            try:
                base_url = f"http://{host}:{port}"
                while True:
                    delay = 0.1

                    if not is_running("server"):
                        pool.apply_async(
                            func=run,
                            args=(ServerRunner, state_dict, lock),
                            kwds={
                                "port": port,
                                "ip": host,
                                "username": username,
                                "password": password,
                                "region": region,
                                "request_log_level": request_level,
                            },
                        )
                        delay = 5

                    if not is_running("bot"):
                        pool.apply_async(
                            func=run,
                            args=(BotRunner, state_dict, lock),
                            kwds={
                                "prefix": prefix,
                                "description": description,
                                "token": token,
                                "plex_username": plex_username,
                                "plex_password": plex_password,
                                "plex_server_name": plex_server_name,
                                "plex_library_name": plex_library_name,
                            },
                        )
                        delay = 5

                    if output_folder is not None:
                        if not is_running("archiver"):
                            pool.apply_async(
                                func=run,
                                args=(ArchiveRunner, state_dict, lock),
                            )
                            delay = 5

                        if not is_running("processor"):
                            pool.apply_async(
                                func=run,
                                args=(ProcessorRunner, state_dict, lock),
                                kwds={"reset_songs": reset_songs},
                            )
                            delay = 5

                    if state.active_channel_id is not None:
                        if not is_running("hls"):
                            pool.apply_async(
                                func=run,
                                args=(HLSRunner, state_dict, lock),
                                kwds={"base_url": base_url, "port": port},
                            )
                            delay = 5

                    time.sleep(delay)

            except KeyboardInterrupt:
                logger.warn("killing runners")
                pool.close()
                pool.terminate()
                pool.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover, pylint: disable=E1120
