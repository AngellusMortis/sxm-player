import logging
from typing import Callable

from aiohttp import web
from sxm import QualitySize, RegionChoice, SXMClient, make_http_handler

from ..queue import Event, EventMessage
from ..signals import TerminateInterrupt
from .base import InterruptableWorker

__all__ = ["ServerWorker"]


class ServerWorker(InterruptableWorker):
    """SXM Client proxy server for sxm-player to interface with"""

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
        region: RegionChoice,
        quality: QualitySize,
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
            quality=quality,
            update_handler=self._make_update_handler(),
        )

        self.sxm.authenticate()
        self.sxm.configuration

    def _make_update_handler(self) -> Callable[[dict], None]:
        """Returns update handler to be called by
        `SXMClient.get_playlist` when a HLS playlist updates"""

        def update_handler(data: dict) -> None:
            self.push_event(EventMessage(self.name, Event.UPDATE_METADATA, data))

        return update_handler

    def send_channel_list(self):
        channels = self.sxm.get_channels()

        self.push_event(EventMessage(self.name, Event.UPDATE_CHANNELS, channels))

    def run(self) -> None:
        """Runs SXM proxy server"""

        self.send_channel_list()

        request_logger = logging.getLogger("sxm_player.server.request")
        request_logger._info = request_logger.info  # type: ignore
        request_logger.info = request_logger.debug  # type: ignore

        app = web.Application()
        app.router.add_get("/{_:.*}", make_http_handler(self.sxm.async_client))
        try:
            self._log.info(f"{self.name} has started on http://{self._ip}:{self._port}")
            web.run_app(
                app,
                host=self._ip,
                port=self._port,
                access_log=request_logger,
                print=None,  # type: ignore
            )
        except (KeyboardInterrupt, TerminateInterrupt):
            pass
