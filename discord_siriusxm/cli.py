# -*- coding: utf-8 -*-

"""Console script for discord_siriusxm."""
import logging
import signal
import sys
from multiprocessing import Manager, Pool

import click

import coloredlogs

from .archiver import run_archiver
from .bot import run_bot
from .models import XMState
from .processor import run_processor
from .server import run_server


@click.command()
@click.option('--username', type=str, prompt=True,
              help='SiriusXM Username')
@click.option('--password', type=str, prompt=True, hide_input=True,
              help='SiriusXM Password')
@click.option('--token', type=str, prompt=True,
              help='Discord bot token')
@click.option('--prefix', type=str, default='/sxm ',
              help='Discord bot command prefix')
@click.option('--description', type=str,
              default='SiriusXM radio bot for Discord',
              help='port to run SiriusXM Proxy server on')
@click.option('-p', '--port', type=int, default=9999,
              help='port to run SiriusXM Proxy server on')
@click.option('-h', '--host', type=str, default='127.0.0.1',
              help='IP to bind SiriusXM Proxy server to. '
                   'Must still be accessible via 127.0.0.1')
@click.option('-o', '--output-folder', type=click.Path(), default=None,
              help='output folder to save stream off to as it plays them')
@click.option('-r', '--reset-songs', is_flag=True,
              help='reset processed song database')
@click.option('-l', '--log-file', type=click.Path(), default=None,
              help='enable verbose logging (shows HTTP requests)')
@click.option('-v', '--verbose', is_flag=True,
              help='enable verbose logging (shows HTTP requests)')
@click.option('-vv', '--debug', is_flag=True,
              help='enable debug logging')
def main(username: str, password: str, token: str, prefix: str,
         description: str, port: int, host: str, output_folder: str,
         reset_songs: bool, verbose: bool, debug: bool, log_file: str):
    """Command line interface for SiriusXM radio bot for Discord"""

    level = 'INFO'
    request_level = logging.WARN

    if debug:
        level = 'DEBUG'
        request_level = logging.DEBUG
    elif verbose:
        request_level = logging.INFO

    if log_file is not None:
        logging.basicConfig(filename=log_file)
    coloredlogs.install(level=level)

    with Manager() as manager:
        state = manager.dict()
        XMState.init_state(state)

        process_count = 2
        if output_folder is not None:
            process_count = 4

        def init_worker():
            signal.signal(signal.SIGINT, signal.SIG_IGN)

        with Pool(processes=process_count, initializer=init_worker) as pool:
            try:
                if output_folder is not None:
                    pool.apply_async(
                        func=run_archiver,
                        args=(state, output_folder))
                    pool.apply_async(
                        func=run_processor,
                        args=(state, output_folder, reset_songs))

                pool.apply_async(
                    func=run_server,
                    args=(state, port, host, username, password, request_level)
                )
                pool.apply(
                    func=run_bot,
                    args=(prefix, description, state,
                          token, port, output_folder)
                )
                pool.close()
                pool.join()
            except KeyboardInterrupt:
                pool.terminate()
                pool.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
