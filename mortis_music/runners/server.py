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
        request_log_level: int = logging.WARN,
        *args,
        **kwargs,
    ):
        kwargs["name"] = "server"
        super().__init__(*args, **kwargs)

        self._port = port
        self._ip = ip
        self._request_log_level = request_log_level

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
            self._log.debug(f"update data: {data}")
            if self.state.active_channel_id == data["channelId"]:
                self._log.info(
                    f"{self.state.active_channel_id}: updating channel data"
                )
                self.state.live = data

        return update_handler

    def run(self) -> None:
        """ Runs SiriusXM proxy server """

        request_logger = logging.getLogger("mortis_music.server.request")
        request_logger.setLevel(self._request_log_level)

        httpd = HTTPServer(
            (self._ip, self._port), make_http_handler(self.sxm, request_logger)
        )
        try:
            self._log.info(
                f"server runner has started on http://{self._ip}:{self._port}"
            )
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        httpd.server_close()
