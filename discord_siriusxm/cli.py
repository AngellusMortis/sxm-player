# -*- coding: utf-8 -*-

"""Console script for discord_siriusxm."""
import sys
from multiprocessing import Manager, Pool

import click

import coloredlogs

from .bot import run_bot
from .models import XMState
from .server import run_server
from .archiver import run_archiver
from .processor import run_processor


@click.command()
@click.option('--username', prompt=True,
              help='SiriusXM Username')
@click.option('--password', prompt=True, hide_input=True,
              help='SiriusXM Password')
@click.option('--token', prompt=True,
              help='Discord bot token')
@click.option('--prefix', default='/sxm ',
              help='Discord bot command prefix')
@click.option('--description', default='SiriusXM radio bot for Discord',
              help='port to run SiriusXM Proxy server on')
@click.option('-p', '--port', type=int, default=9999,
              help='port to run SiriusXM Proxy server on')
@click.option('-o', '--output-folder', type=click.Path(), default=None,
              help='output folder to save stream off to as it plays them')
@click.option('-r', '--reset-songs', is_flag=True,
              help='reset processed song database')
def main(username, password, token, prefix, description,
         port, output_folder, reset_songs):
    """Command line interface for SiriusXM radio bot for Discord"""

    coloredlogs.install(level='INFO')

    with Manager() as manager:
        state = manager.dict()
        XMState.init_state(state)

        process_count = 2
        if output_folder is not None:
            process_count = 4

        with Pool(processes=process_count) as pool:
            if output_folder is not None:
                pool.apply_async(
                    func=run_archiver, args=(state, output_folder))
                pool.apply_async(
                    func=run_processor, args=(state, output_folder, reset_songs))

            pool.apply_async(
                func=run_server, args=(state, port, username, password))
            pool.apply(
                func=run_bot,
                args=(prefix, description, state, token, port, output_folder)
            )
            pool.close()
            pool.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
