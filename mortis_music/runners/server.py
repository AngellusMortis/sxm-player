import logging
from http.server import HTTPServer
from typing import Callable

from sxm import SiriusXMClient, make_http_handler

from .base import BaseRunner

__all__ = ["ServerRunner"]


class ServerRunner(BaseRunner):
    """ SiriusXMProxy Server for Discord bot to interface with """

    _ip: str
    _port: int
    _request_log_level: int
    sxm: SiriusXMClient

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
        kwargs["name"] = "server"
        super().__init__(*args, **kwargs)

        self._port = port
        self._ip = ip

        self.sxm = SiriusXMClient(
            username=username,
            password=password,
            region=region,
            update_handler=self._make_update_handler(),
        )

        self.sxm.authenticate()
        self.state.channels = self.sxm.get_channels()

    def _make_update_handler(self) -> Callable[[dict], None]:
        """ Returns update handler to be called by
        `SiriusXMClient.get_playlist` when a HLS playlist updates """

        def update_handler(data: dict) -> None:
            self._log.debug(f"received update data for: {data['channelId']}")
            if self.state.active_channel_id == data["channelId"]:
                self._log.info(
                    f"{self.state.active_channel_id}: updating channel data"
                )
                self.state.live = data

        return update_handler

    def run(self) -> None:
        """ Runs SiriusXM proxy server """

        request_logger = logging.getLogger("mortis_music.server.request")

        httpd = HTTPServer(
            (self._ip, self._port),
            make_http_handler(
                self.sxm, request_logger, request_level=logging.DEBUG
            ),
        )
        try:
            self._log.info(
                f"server runner has started on http://{self._ip}:{self._port}"
            )
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        httpd.server_close()
