import os
import time
from typing import Union

from ..utils import get_files, splice_file
from .base import BaseRunner

__all__ = ['ArchiveRunner']

ARCHIVE_DROPOFF: int = 86400  # 24 hours
ARCHIVE_CHUNK = 600  # 10 minutes
ARCHIVE_BUFFER = 5


class ArchiveRunner(BaseRunner):
    def __init__(self, *args, **kwargs):
        kwargs['name'] = 'archiver'
        super().__init__(*args, **kwargs)

        self._delay = ARCHIVE_CHUNK
        os.makedirs(self.state.stream_folder, exist_ok=True)
        os.makedirs(self.state.archive_folder, exist_ok=True)

    def _delete_old_archives(self, archive_folder: str, archive_base: str,
                             current_file: str) -> int:
        """ Deletes any old versions of archive that is about to be made """

        archive_files = get_files(archive_folder)

        now: float = time.time()
        removed: int = 0
        for archive_file in archive_files:
            abs_path = os.path.join(archive_folder, archive_file)
            age: float = now - os.path.getatime(abs_path)
            if (archive_file.startswith(archive_base) and
                    archive_file != current_file) or age > ARCHIVE_DROPOFF:

                self._log.debug(f'deleted old archive: {abs_path}')
                os.remove(abs_path)
                removed += 1
        return removed

    def _process_stream_file(self, abs_path: str) -> Union[str, None]:
        """ Processes stream file by creating an archive from
        it if necessary """

        channel_id = self.state.active_channel_id
        if channel_id is None or self.state.archive_folder is None:
            return None
        channel_archive = os.path.join(self.state.archive_folder, channel_id)

        max_archive_cutoff = int(time.time()) - ARCHIVE_BUFFER
        creation_time = int(os.path.getatime(abs_path)) + ARCHIVE_BUFFER

        # not reliable enough yet
        # max_archive_cutoff = \
        #     int(self.state.radio_time / 1000) - ARCHIVE_BUFFER
        # creation_time = int(self.state.start_time / 1000) + ARCHIVE_BUFFER

        time_elapsed = max_archive_cutoff - creation_time
        archive_chunks = int(time_elapsed / ARCHIVE_CHUNK)
        if archive_chunks > 0:
            os.makedirs(channel_archive, exist_ok=True)
            time_elapsed = (archive_chunks * ARCHIVE_CHUNK)
            archive_cutoff = creation_time + time_elapsed

            archive_base = f'{channel_id}.{creation_time}'
            archive_filename = f'{archive_base}.{archive_cutoff}.mp3'
            archive_output = os.path.join(
                channel_archive, archive_filename)
            if os.path.exists(archive_output):
                return None

            self._delete_old_archives(
                channel_archive, archive_base, archive_filename)
            return splice_file(
                abs_path, archive_output,
                ARCHIVE_BUFFER, ARCHIVE_BUFFER + time_elapsed
            )
        return None

    def loop(self):
        active_channel_id = self.state.active_channel_id
        if active_channel_id is None:
            return

        deleted = 0
        archived = None
        stream_files = get_files(self.state.stream_folder)

        for stream_file in stream_files:
            abs_path = os.path.join(self.state.stream_folder, stream_file)
            file_parts = stream_file.split('.')
            if file_parts[-1] != 'mp3' or \
                    file_parts[0] != active_channel_id:
                os.remove(abs_path)
                deleted += 1
            else:
                self.state.processing_file = True
                archived = self._process_stream_file(abs_path)
                self.state.processing_file = False

        self._log.info(
            f'completed processing: deleted files: {deleted}, '
            f'archived file: {archived}'
        )
