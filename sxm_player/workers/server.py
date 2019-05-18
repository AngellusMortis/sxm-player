import logging
from http.server import HTTPServer
from typing import Callable

from sxm import SXMClient, make_http_handler

from ..queue import Event, EventMessage
from ..signals import TerminateInterrupt
from .base import InterruptableWorker

__all__ = ["ServerWorker"]


class ServerWorker(InterruptableWorker):
    """ SXM Client proxy server for sxm-player to interface with """

    NAME = "sxm"

    _ip: str
    _port: int
    sxm: SXMClient

    def __init__(
        self,
        port: int,
        ip: str,
        username: str,
        password: str,
        region: str,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._port = port
        self._ip = ip

        self.sxm = SXMClient(
            username=username,
            password=password,
            region=region,
            update_handler=self._make_update_handler(),
        )

        self.sxm.authenticate()

    def _make_update_handler(self) -> Callable[[dict], None]:
        """ Returns update handler to be called by
        `SXMClient.get_playlist` when a HLS playlist updates """

        def update_handler(data: dict) -> None:
            self.push_event(
                EventMessage(self.name, Event.UPDATE_METADATA, data)
            )

        return update_handler

    def send_channel_list(self):
        channels = self.sxm.get_channels()

        self.push_event(
            EventMessage(self.name, Event.UPDATE_CHANNELS, channels)
        )

    def run(self) -> None:
        """ Runs SXM proxy server """

        self.send_channel_list()

        request_logger = logging.getLogger("sxm_player.server.request")

        httpd = HTTPServer(
            (self._ip, self._port),
            make_http_handler(
                self.sxm, request_logger, request_level=logging.DEBUG
            ),
        )
        try:
            self._log.info(
                f"{self.name} has started on http://{self._ip}:{self._port}"
            )
            httpd.serve_forever()
        except (KeyboardInterrupt, TerminateInterrupt):
            pass

        httpd.server_close()
