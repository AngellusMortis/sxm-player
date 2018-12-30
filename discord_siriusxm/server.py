import logging
import traceback
from typing import Callable

from aiohttp import web

from sxm import SiriusXMClient, make_async_http_app

from .models import XMState

__all__ = ['run_server']


class SiriusXMProxyServer:
    """ SiriusXMProxy Server for Discord bot to interface with"""

    _port = None
    _xm = None
    _state = None

    def __init__(self, state_dict: dict, port: int,
                 ip: str, username: str, password: str):
        self._port = port
        self._ip = ip
        self._state = XMState(state_dict)
        self._log = logging.getLogger('discord_siriusxm.server')

        try:
            self._xm = SiriusXMClient(
                username=username,
                password=password,
                update_handler=self._make_update_handler()
            )

            self._xm.authenticate()
            self._state.channels = self._xm.get_channels()
        except Exception as e:
            self._log.error('error occuring while creating SiriusXM client:')
            self._log.error(traceback.format_exc())
            raise(e)

    def _make_update_handler(self) -> Callable[[dict], None]:
        """ Returns update handler to be called by
        `SiriusXMClient.get_playlist` when a HLS playlist updates """

        def update_handler(data: dict) -> None:
            self._log.debug(f'update data: {data}')
            if self._state.active_channel_id == data['channelId']:
                self._log.info(
                    f'{self._state.active_channel_id}: updating channel data')
                self._state.live = data
        return update_handler

    def run(self, log_level: int = logging.WARN) -> None:
        """ Runs SiriusXM proxy server """

        app = make_async_http_app(self._xm)

        self._log.info(
            f'running SiriusXM proxy server on http://{self._ip}:{self._port}'
        )

        request_logger = logging.getLogger('discord_siriusxm.server.request')
        request_logger.setLevel(log_level)

        try:
            web.run_app(
                app,
                access_log=request_logger,
                print=None,
                host=self._ip,
                port=self._port
            )
        except Exception as e:
            self._log.error('error occuring while running server:')
            self._log.error(traceback.format_exc())
            raise(e)


def run_server(state_dict: dict, port: int, ip: str,
               username: str, password: str, log_level: int) -> None:
    """ Creates and runs SiriusXM proxy server """

    server = SiriusXMProxyServer(state_dict, port, ip, username, password)
    server.run(log_level=log_level)
