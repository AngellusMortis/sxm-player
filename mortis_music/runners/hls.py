import logging
import os
import select
import subprocess
import tempfile
import time
from typing import List

import psutil

from sxm.models import XMChannel

from .base import BaseRunner

__all__ = ["HLSRunner"]


# ripped Discord's FFmpegPCMAudio class to remove Discord dependency
# from this section of code
# https://github.com/Rapptz/discord.py/blob/rewrite/discord/player.py
SAMPLING_RATE = 48000
FRAME_LENGTH = 20
SAMPLE_SIZE = 4  # (bit_rate / 8) * CHANNELS (bit_rate == 16)
SAMPLES_PER_FRAME = int(SAMPLING_RATE / 1000 * FRAME_LENGTH)
FRAME_SIZE = SAMPLES_PER_FRAME * SAMPLE_SIZE
DELAY = FRAME_LENGTH / 1000.0


class HLSAudio:
    def __init__(self, source, url, *, stream_file="", stderr=None):

        self._log = logging.getLogger("mortis_music.ffmpeg")

        args = [
            "ffmpeg",
            "-loglevel",
            "warning",
            "-f",
            "hls",
            "-i",
            source,
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-af",
            "adelay=3000|3000",
            "-listen",
            "1",
            url,
            stream_file,
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "pipe:1",
        ]

        self._process = None
        self._process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=stderr
        )
        self._stdout = self._process.stdout

        self._log.info(
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

        self._log.info("Preparing to terminate ffmpeg process %s.", proc.pid)
        proc.kill()
        if proc.poll() is None:
            self._log.info(
                f"ffmpeg process {proc.pid} has not terminated. Waiting "
                f"to terminate..."
            )
            proc.communicate()
            self._log.info(
                f"ffmpeg process {proc.pid} should have terminated with a "
                f"return code of {proc.returncode}."
            )
        else:
            self._log.info(
                f"ffmpeg process {proc.pid} successfully terminated with "
                f"return code of {proc.returncode}."
            )

        self._process = None


class HLSRunner(BaseRunner):
    channel: XMChannel
    source: HLSAudio
    stderr_poll: select.poll  # pylint: disable=E1101
    stream_url: str
    use_udp: bool = False

    _loops: int = 0
    _start: float = 0

    def __init__(self, base_url: str, port: int, *args, **kwargs):
        kwargs["name"] = "hls"
        super().__init__(*args, **kwargs)

        self.channel = self.state.get_channel(self.state.active_channel_id)
        if self.channel is not None:
            self.stream_url = f"{base_url}/{self.channel.id}.m3u8"

            if self.use_udp:
                playback_url = f"udp://127.0.0.1:{port}"
            else:
                socket_file = os.path.join(
                    tempfile.gettempdir(), f"{self.channel.id}.sock"
                )
                if os.path.exists(socket_file):
                    os.remove(socket_file)

                playback_url = f"unix:/{socket_file}"

            stream_file = ""

            log_message = f"playing {self.stream_url}"
            if self.state.stream_folder is not None:
                stream_file = os.path.join(
                    self.state.stream_folder, f"{self.channel.id}.mp3"
                )

                if os.path.exists(stream_file):
                    os.remove(stream_file)

                log_message += f" ({stream_file})"
                stream_file = f"file:/{stream_file}"

        self.state.stream_url = playback_url
        self._log.info(log_message)
        self.source = HLSAudio(
            source=self.stream_url,
            url=playback_url,
            stream_file=stream_file,
            stderr=subprocess.PIPE,
        )

        self.stderr_poll = select.poll()  # pylint: disable=E1101
        self.stderr_poll.register(
            self.source._process.stderr,
            select.POLLIN,  # pylint: disable=E1101 # noqa
        )

    def __unload__(self):
        self.stop()

    def stop(self):
        self.state.active_channel_id = None
        self.state.stream_socket = None
        if self.source is not None:
            self.source.cleanup()
            self.source = None

    def run(self) -> None:
        self._loops = 0
        self._start = time.time()

        try:
            super().run()
        except Exception:
            pass
        finally:
            self.stop()
        self._log.debug("hls runner stopped")
        exit(0)

    def loop(self):
        self._loops += 1

        lines: List[str] = []
        while self.stderr_poll.poll(0.1):
            lines.append(self.source._process.stderr.readline().decode("utf8"))

        if len(lines) > 0:
            self._log.debug(f"adding {len(lines)} of stderr to shared memory")
            self.state.push_hls_errors(lines)

        self.source.read()

        process = psutil.Process(self.source._process.pid)

        if self.state.active_channel_id is None:
            self._log.debug("active_channel_id is None, stopping hls runner")
            self._do_loop = False
        elif self.state.active_channel_id != self.channel.id:
            self._log.debug(
                "active_channel_id has changed, stopping hls runner"
            )
            self._do_loop = False
        elif process.status() not in (
            psutil.STATUS_RUNNING,
            psutil.STATUS_SLEEPING,
        ):
            self._log.debug("ffmpeg process is dead, stopping hls runner")
            self._do_loop = False
        next_time = self._start + DELAY * self._loops
        self._delay = max(0, DELAY + (next_time - time.time()))
