# -*- coding: utf-8 -*-

"""Console script for discord_siriusxm."""
import logging
import sys
from multiprocessing import Pool, Manager

import click

from .bot import run_bot
from .server import run_server
from .models import XMState


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
def main(username, password, token, prefix, description, port):
    """Command line interface for SiriusXM radio bot for Discord"""

    logging.basicConfig(level=logging.INFO)

    with Manager() as manager:
        state = manager.dict()
        XMState.init_state(state)

        with Pool(processes=2) as pool:
            pool.apply_async(func=run_server, args=(state, port, username, password))
            pool.apply(func=run_bot, args=(prefix, description, state, token, port))
            pool.close()
            pool.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
