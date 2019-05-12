import logging
import os
import select
import subprocess  # nosec
import tempfile
import time
import shlex
from typing import List, Optional, Tuple

import psutil

from .base import SXMLoopedWorker
from ..queue import EventMessage

__all__ = ["HLSWorker"]


ACTIVE_STATUS = [
    psutil.STATUS_RUNNING,
    psutil.STATUS_SLEEPING,
    psutil.STATUS_DISK_SLEEP,
]
SAMPLING_RATE = 48000
FRAME_LENGTH = 20
SAMPLE_SIZE = 4  # (bit_rate / 8) * CHANNELS (bit_rate == 16)
SAMPLES_PER_FRAME = int(SAMPLING_RATE / 1000 * FRAME_LENGTH)
FRAME_SIZE = SAMPLES_PER_FRAME * SAMPLE_SIZE
DELAY = FRAME_LENGTH / 1000.0

FFMPEG_COMMAND = (
    "ffmpeg -loglevel warning "
    "-f hls -i {} "
    "-f s16le -ar 48000 -ac 2 -af adelay=3000|3000 {} "
    "-f s16le -ar 48000 -ac 2 pipe:1"
)
FFMPEG_PROTOCOLS = [
    "udp",
    # "rtsp",
    # "rtmp",
    "unix",
]


class HLSAudio:
    def __init__(self, source, output_options, *, stderr=None):

        self._log = logging.getLogger("mortis_music.ffmpeg")

        args = shlex.split(FFMPEG_COMMAND.format(source, output_options))

        self._process = None
        self._process = subprocess.Popen(  # nosec
            args, stdout=subprocess.PIPE, stderr=stderr
        )
        self._stdout = self._process.stdout

        self._log.debug(
            f"ffmpeg processed started with pid {self._process.pid}"
        )

    def __del__(self):
        self.cleanup()

    def read(self):
        ret = self._stdout.read(FRAME_SIZE)
        if len(ret) != FRAME_SIZE:
            return b""
        return ret

    def cleanup(self):
        proc = self._process
        if proc is None:
            return

        self._log.debug("Preparing to terminate ffmpeg process %s.", proc.pid)
        proc.kill()
        if proc.poll() is None:
            self._log.debug(
                f"ffmpeg process {proc.pid} has not terminated. Waiting "
                f"to terminate..."
            )
            proc.communicate()
            self._log.debug(
                f"ffmpeg process {proc.pid} should have terminated with a "
                f"return code of {proc.returncode}."
            )
        else:
            self._log.debug(
                f"ffmpeg process {proc.pid} successfully terminated with "
                f"return code of {proc.returncode}."
            )

        self._process = None


class HLSWorker(SXMLoopedWorker):
    NAME = "hls"

    channel_id: str
    source: HLSAudio
    stderr_poll: select.poll  # pylint: disable=E1101
    stream_file: Optional[str] = None
    stream_url: str
    stream_protocol: str
    playback_url: str

    _loops: int = 0
    _start: float = 0

    def __init__(
        self,
        base_url: str,
        port: int,
        channel_id: str,
        stream_folder: Optional[str],
        stream_protocol: str = "udp",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._sxm_running = True
        port = port + 1

        self.stream_url = f"{base_url}/{channel_id}.m3u8"
        self.channel_id = channel_id

        self.playback_url, output_options = self._get_playback_url(
            stream_protocol, port, channel_id
        )

        log_message = f"playing {self.stream_url}"
        if stream_folder is not None:
            self.stream_file = os.path.join(stream_folder, f"{channel_id}.mp3")

            if os.path.exists(self.stream_file):
                os.remove(self.stream_file)

            log_message += f" ({self.stream_file})"

            output_options = f"{output_options} file:/{self.stream_file}"

        self._log.info(log_message)
        self.source = HLSAudio(
            source=self.stream_url,
            output_options=output_options,
            stderr=subprocess.PIPE,
        )

        self.stderr_poll = select.poll()  # pylint: disable=E1101
        self.stderr_poll.register(
            self.source._process.stderr,
            select.POLLIN,  # pylint: disable=E1101 # noqa
        )

    def __unload__(self):
        self.stop()

    def _get_playback_url(
        self, stream_protocol, port, channel_id
    ) -> Tuple[str, str]:
        if stream_protocol not in FFMPEG_PROTOCOLS:
            self._log.warning(
                f"Unknown stream protocol: {stream_protocol}, "
                "defaulting to udp"
            )
            stream_protocol = "udp"

        output_options = ""
        if stream_protocol == "udp":
            playback_url = f"udp://127.0.0.1:{port}"
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

    def stop(self):
        self.push_event(
            EventMessage(self.name, EventMessage.KILL_HLS_STREAM, None)
        )

        if self.source is not None:
            self.source.cleanup()
            self.source = None

    def run(self) -> None:
        self._loops = 0
        self._start = time.time()

        self.push_event(
            EventMessage(
                self.name,
                EventMessage.HLS_STREAM_STARTED,
                (self.channel_id, self.playback_url),
            )
        )

        try:
            super().run()
        except Exception as e:
            self._log.warning(f"Exception occurred in {self.name}: {e}")
        finally:
            self.stop()
        self._log.debug(f"{self.name} stopped")
        exit(0)

    def loop(self):
        self._loops += 1

        process = psutil.Process(self.source._process.pid)
        status = process.status()

        if not self._sxm_running:
            self._log.info(f"SiriusXM Client is dead, stopping {self.name}")
            self.local_shutdown_event.set()
            return
        elif status not in ACTIVE_STATUS:
            self._log.info(f"ffmpeg process is {status}, stopping {self.name}")
            self.local_shutdown_event.set()
            return
        elif (
            self._loops > 10
            and self.stream_file is not None
            and not os.path.exists(self.stream_file)
        ):
            self._log.info(f"stream file missing, stopping {self.name}")
            self.local_shutdown_event.set()
            return

        lines: List[str] = []
        while self.stderr_poll.poll(0.1):
            lines.append(self.source._process.stderr.readline().decode("utf8"))

        if len(lines) > 0:
            self._log.debug(f"adding {len(lines)} of stderr to shared memory")
            self.push_event(
                EventMessage(self.name, EventMessage.HLS_STDERROR_LINES, lines)
            )

        self.source.read()

        next_time = self._start + DELAY * self._loops
        self._delay = max(0, DELAY + (next_time - time.time()))
