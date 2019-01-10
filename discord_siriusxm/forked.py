import logging
import shlex
import subprocess
import threading
import time

from discord import AudioSource, ClientException
from discord.opus import Encoder as OpusEncoder
from discord.player import log


# TODO: try to get merged upstream
class FFmpegPCMAudio(AudioSource):
    """An audio source from FFmpeg (or AVConv).

    This launches a sub-process to a specific input file given.

    .. warning::

        You must have the ffmpeg or avconv executable in your path environment
        variable in order for this to work.

    Parameters
    ------------
    source: Union[str, BinaryIO]
        The input that ffmpeg will take and convert to PCM bytes.
        If ``pipe`` is True then this is a file-like object that is
        passed to the stdin of ffmpeg.
    executable: str
        The executable name (and path) to use. Defaults to ``ffmpeg``.
    pipe: bool
        If true, denotes that ``source`` parameter will be passed
        to the stdin of ffmpeg. Defaults to ``False``.
    stderr: Optional[BinaryIO]
        A file-like object to pass to the Popen constructor.
        Could also be an instance of ``subprocess.PIPE``.
    options: Optional[str]
        Extra command line arguments to pass to ffmpeg after the ``-i`` flag.
    before_options: Optional[str]
        Extra command line arguments to pass to ffmpeg before the ``-i`` flag.
    after_options: Optional[str]
        Extra command line arguments to pass to ffmpeg after everything else.

    Raises
    --------
    ClientException
        The subprocess failed to be created.
    """

    def __init__(self, source, *, executable='ffmpeg',
                 pipe=False, stderr=None, before_options=None,
                 options=None, after_options=None):
        stdin = None if not pipe else source

        args = [executable]

        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))

        args.append('-i')
        args.append('-' if pipe else source)
        args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'warning'))

        if isinstance(options, str):
            args.extend(shlex.split(options))

        args.append('pipe:1')

        if isinstance(after_options, str):
            args.extend(shlex.split(after_options))

        self._process = None
        try:
            self._process = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr)
            self._stdout = self._process.stdout
        except FileNotFoundError:
            raise ClientException(executable + ' was not found.') from None
        except subprocess.SubprocessError as e:
            raise ClientException('Popen failed: {0.__class__.__name__}: {0}'.format(e)) from e

    def read(self):
        ret = self._stdout.read(OpusEncoder.FRAME_SIZE)
        if len(ret) != OpusEncoder.FRAME_SIZE:
            return b''
        return ret

    def cleanup(self):
        proc = self._process
        if proc is None:
            return

        log.info('Preparing to terminate ffmpeg process %s.', proc.pid)
        proc.kill()
        if proc.poll() is None:
            log.info('ffmpeg process %s has not terminated. Waiting to terminate...', proc.pid)
            proc.communicate()
            log.info('ffmpeg process %s should have terminated with a return code of %s.', proc.pid, proc.returncode)
        else:
            log.info('ffmpeg process %s successfully terminated with return code of %s.', proc.pid, proc.returncode)

        self._process = None


# TODO: Remove and go back to build Discord player
class DiscordAudioPlayer(threading.Thread):
    DELAY = OpusEncoder.FRAME_LENGTH / 1000.0

    def __init__(self, source, client, *, after=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.source = source
        self.client = client
        self.after = after

        self._end = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set() # we are not paused
        self._current_error = None
        self._connected = client._connected
        self._lock = threading.Lock()

        self._log = logging.getLogger('discord_siriusxm.player')

        if after is not None and not callable(after):
            raise TypeError('Expected a callable for the "after" parameter.')

    def _do_run(self):
        self.loops = 0
        self._start = time.time()

        # getattr lookup speed ups
        play_audio = self.client.send_audio_packet

        self._log.warn('player run')
        while not self._end.is_set():
            self._log.warn('player loop')
            # are we paused?
            if not self._resumed.is_set():
                self._log.warn('player resume')
                # wait until we aren't
                self._resumed.wait()
                continue

            # are we disconnected from voice?
            if not self._connected.is_set():
                self._log.warn('player connected')
                # wait until we are connected
                self._connected.wait()
                # reset our internal data
                self.loops = 0
                self._start = time.time()

            self.loops += 1
            data = self.source.read()

            if not data:
                self._log.warn('player stop')
                self.stop()
                break

            self._log.warn('player play')
            play_audio(data, encode=not self.source.is_opus())
            next_time = self._start + self.DELAY * self.loops
            delay = max(0, self.DELAY + (next_time - time.time()))
            self._log.warn('player sleep')
            time.sleep(delay)

    def run(self):
        try:
            self._do_run()
        except Exception as exc:
            self._current_error = exc
            self.stop()
        finally:
            self.source.cleanup()
            self._call_after()

    def _call_after(self):
        if self.after is not None:
            try:
                self.after(self._current_error)
            except Exception:
                log.exception('Calling the after function failed.')

    def stop(self):
        self._end.set()
        self._resumed.set()

    def pause(self):
        self._resumed.clear()

    def resume(self):
        self.loops = 0
        self._start = time.time()
        self._resumed.set()

    def is_playing(self):
        return self._resumed.is_set() and not self._end.is_set()

    def is_paused(self):
        return not self._end.is_set() and not self._resumed.is_set()

    def _set_source(self, source):
        with self._lock:
            self.pause()
            self.source = source
            self.resume()
