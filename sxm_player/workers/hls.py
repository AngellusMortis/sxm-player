import os
import tempfile
import time
from typing import Optional, Tuple

from ..utils import FFmpeg
from ..queue import Event, EventMessage
from .base import SXMLoopedWorker

__all__ = ["HLSWorker"]


FFMPEG_COMMAND = "ffmpeg -loglevel warning -f hls -i {} " "-f mpegts {} "
FFMPEG_PROTOCOLS = [
    "udp",
    # "rtsp",
    # "rtmp",
    "unix",
]


class HLSWorker(SXMLoopedWorker, FFmpeg):
    NAME = "hls"

    channel_id: str
    stream_file: Optional[str] = None
    stream_url: str
    stream_protocol: str
    playback_url: str

    _start: float = 0

    def __init__(
        self,
        ip: str,
        port: int,
        channel_id: str,
        stream_folder: Optional[str],
        stream_protocol: str = "udp",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.stream_url = f"http://{ip}:{port}/{channel_id}.m3u8"
        self.channel_id = channel_id

        port = port + 1

        self.playback_url, output_options = self._get_playback_url(
            stream_protocol, ip, port, channel_id
        )

        log_message = f"playing {self.stream_url}"
        if stream_folder is not None:
            self.stream_file = os.path.join(stream_folder, f"{channel_id}.mp3")

            if os.path.exists(self.stream_file):
                os.remove(self.stream_file)

            log_message += f" ({self.stream_file})"

            output_options = f"{output_options} file:/{self.stream_file}"

        self._log.info(log_message)
        self.command = FFMPEG_COMMAND.format(self.stream_url, output_options)
        self.start_ffmpeg()

    def _get_playback_url(
        self, stream_protocol: str, ip: str, port: int, channel_id: str
    ) -> Tuple[str, str]:
        if stream_protocol not in FFMPEG_PROTOCOLS:
            self._log.warning(
                f"Unknown stream protocol: {stream_protocol}, "
                "defaulting to udp"
            )
            stream_protocol = "udp"

        output_options = ""
        if stream_protocol == "udp":
            playback_url = f"udp://{ip}:{port}"
            output_options = f"{playback_url}"
        # elif stream_protocol == "rtsp":
        #     playback_url = f"rtsp://127.0.0.1:{port}"
        #     output_options = f"-rtsp_flags listen {playback_url}"
        # elif stream_protocol == "rtmp":
        #     playback_url = f"rtmp://127.0.0.1:{port}"
        #     output_options = f"-listen 1 {playback_url}"
        else:
            socket_file = os.path.join(
                tempfile.gettempdir(), f"{channel_id}.sock"
            )
            if os.path.exists(socket_file):
                os.remove(socket_file)

            playback_url = f"unix:/{socket_file}"
            output_options = f"-listen 1 {playback_url}"

        return (playback_url, output_options)

    def setup(self):
        self._start = time.time()

        self.push_event(
            EventMessage(
                self.name,
                Event.HLS_STREAM_STARTED,
                (self.channel_id, self.playback_url),
            )
        )

    def loop(self):
        now = time.time()

        if not self._state.sxm_running:
            self._log.info(f"SXM Client is dead, stopping {self.name}")
            self.local_shutdown_event.set()
            return
        elif not self.check_process():
            self._log.info(
                f"ffmpeg process is not active, stopping {self.name}"
            )
            self.local_shutdown_event.set()
            return
        elif (
            now - self._start > 5
            and self.stream_file is not None
            and not os.path.exists(self.stream_file)
        ):
            self._log.info(f"stream file missing, stopping {self.name}")
            self.local_shutdown_event.set()
            return

        lines = self.read_errors()

        if len(lines) > 0:
            self._log.debug(f"adding {len(lines)} of stderr to shared memory")
            self.push_event(
                EventMessage(self.name, Event.HLS_STDERROR_LINES, lines)
            )

    def cleanup(self):
        self.stop_ffmpeg()

        self.push_event(EventMessage(self.name, Event.KILL_HLS_STREAM, None))
