import os
import tempfile
import time

from discord import AudioSource
from discord.opus import Encoder as OpusEncoder

from sxm.models import XMChannel

from ..forked import FFmpegPCMAudio
from .base import BaseRunner

__all__ = ['HLSRunner']


DELAY = OpusEncoder.FRAME_LENGTH / 1000.0


class HLSRunner(BaseRunner):
    channel: XMChannel
    source: AudioSource
    stream_url: str = None

    _loops: int = 0
    _start: int = 0

    def __init__(self, base_url: str, *args, **kwargs):
        super().__init__(name='hls', *args, **kwargs)

        self.channel = self.state.get_channel(self.state.active_channel_id)
        self.stream_url = f'{base_url}/{self.channel.id}.m3u8'

        socket_file = os.path.join(tempfile.gettempdir(), f'{self.channel.id}.sock')
        if os.path.exists(socket_file):
            os.remove(socket_file)

        options = f'unix:/{socket_file}'
        self.state.stream_url = options
        options = f'-af adelay=3000|3000 -listen 1 {options}'

        log_message = f'playing {self.stream_url}'
        if self.state.stream_folder is not None:
            stream_file = os.path.join(
                self.state.stream_folder, f'{self.channel.id}.mp3')

            if os.path.exists(stream_file):
                os.remove(stream_file)

            options = f'{options} file:/{stream_file}'
            log_message += f' ({stream_file})'

        options = f'{options} -f s16le -ar 48000 -ac 2'
        self._log.info(log_message)
        self.source = FFmpegPCMAudio(
            self.stream_url,
            before_options='-loglevel fatal -f hls',
            options=options,
            # stderr=subprocess.PIPE
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

    def loop(self):
        self._loops += 1
        data = self.source.read()

        if not data or self.state.active_channel_id is None or \
                self.state.active_channel_id != self.channel.id:
            self._do_loop = False
        next_time = self._start + DELAY * self._loops
        self._delay = max(0, DELAY + (next_time - time.time()))
