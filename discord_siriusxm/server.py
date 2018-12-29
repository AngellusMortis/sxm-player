import logging
import traceback

import discord
from aiohttp import web

from sxm import SiriusXMClient, make_async_http_app

from .models import XMState


class SiriusXMProxyServer:
    """ SiriusXMProxy Server for Discord bot to interface with"""

    _port = None
    _xm = None
    _state = None

    def __init__(self, state, port, username, password):
        self._port = port
        self._state = XMState(state)
        self._log = logging.getLogger('discord_siriusxm.server')

        try:
            self._xm = SiriusXMClient(
                username=username,
                password=password,
                update_handler=self._make_update_handler()
            )

            if not self._xm.authenticate():
                raise discord.DiscordException('Failed to log into SiriusXM')
            self._state.channels = self._xm.get_channels()
        except Exception as e:
            self._log.error('error occuring while creating SiriusXM client:')
            self._log.error(traceback.format_exc())
            raise(e)

    def _make_update_handler(self):
        def update_handler(data):
            self._log.debug(f'update data: {data}')
            if self._state.active_channel_id == data['channelId']:
                self._log.info(
                    f'{self._state.active_channel_id}: updating channel data')
                self._state.live = data
        return update_handler

    def run(self):
        app = make_async_http_app(self._xm)

        self._log.info(
            f'running SiriusXM proxy server on http://0.0.0.0:{self._port}'
        )
        try:
            web.run_app(
                app,
                access_log=logging.getLogger('discord_siriusxm.server.request'),
                print=None,
                port=self._port
            )
        except Exception as e:
            self._log.error('error occuring while running server:')
            self._log.error(traceback.format_exc())
            raise(e)


def run_server(state, port, username, password):
    server = SiriusXMProxyServer(state, port, username, password)
    server.run()
