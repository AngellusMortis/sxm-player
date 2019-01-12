import logging
from typing import Callable

from aiohttp import web

from sxm import SiriusXMClient, make_async_http_app

from .base import BaseRunner

__all__ = ['ServerRunner']


class ServerRunner(BaseRunner):
    """ SiriusXMProxy Server for Discord bot to interface with """

    _ip: str = None
    _port: int = None
    _request_log_level: int = logging.WARN
    sxm: SiriusXMClient = None

    def __init__(self, port: int, ip: str,
                 username: str, password: str,
                 region: str, request_log_level: int = logging.WARN,
                 *args, **kwargs):
        super().__init__(name='server', *args, **kwargs)

        self._port = port
        self._ip = ip
        self._request_log_level = request_log_level

        self.sxm = SiriusXMClient(
            username=username,
            password=password,
            region=region,
            update_handler=self._make_update_handler()
        )

        self.sxm.authenticate()
        self.state.channels = self.sxm.get_channels()

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

    def run(self) -> None:
        """ Runs SiriusXM proxy server """

        app = make_async_http_app(self.sxm)

        self._log.info(
            f'server runner has start on http://{self._ip}:{self._port}'
        )

        request_logger = logging.getLogger('discord_siriusxm.server.request')
        request_logger.setLevel(self._request_log_level)

        web.run_app(
            app,
            access_log=request_logger,
            print=None,
            host=self._ip,
            port=self._port
        )
