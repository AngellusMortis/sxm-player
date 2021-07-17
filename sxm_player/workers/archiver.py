import os
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Dict, Optional, Tuple, Union

from sxm_player.queue import EventMessage, EventTypes
from sxm_player.utils import create_fs_datetime, get_files, splice_file
from sxm_player.workers.base import HLSLoopedWorker

__all__ = ["ArchiveWorker"]

ARCHIVE_DROPOFF = timedelta(hours=24)
ARCHIVE_CHUNK = timedelta(minutes=10)
ARCHIVE_BUFFER = timedelta(seconds=5)


class ArchiveWorker(HLSLoopedWorker):
    NAME = "archiver"

    stream_folder: str
    archive_folder: str
    last_size: Dict[str, int] = {}

    _delay: float = ARCHIVE_CHUNK.total_seconds()

    def __init__(self, stream_folder: str, archive_folder: str, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # run in 11 minutes (ARCHIVE_CHUNK + 1 minute) to ensure a
        # full 10 minutes of audio exists
        self._last_loop = monotonic() + 60

        self.stream_folder = stream_folder
        self.archive_folder = archive_folder

        os.makedirs(self.stream_folder, exist_ok=True)
        os.makedirs(self.archive_folder, exist_ok=True)

    def loop(self) -> None:
        if self._state.stream_channel is None or self.stream_folder is None:
            self.local_shutdown_event.set()
            return

        deleted = 0
        archived = None
        stream_files = get_files(self.stream_folder)

        for stream_file in stream_files:
            abs_path = os.path.join(self.stream_folder, stream_file)
            archived, removed = self._process_file(abs_path)
            deleted += removed

        self._log.info(
            f"archived: deleted files: {deleted}, " f"archived file: {archived}"
        )

    def _process_file(self, abs_path) -> Tuple[Optional[str], int]:
        archived = None
        deleted = 0

        if not self._validate_name(abs_path):
            deleted += 1
        elif self._validate_size(abs_path):
            archived, removed = self._process_stream_file(abs_path)
            deleted += removed

        return (archived, deleted)

    def _validate_name(self, stream_file) -> bool:
        stream_file = os.path.basename(stream_file)
        file_parts = stream_file.split(".")
        if file_parts[-1] != "mp3" or file_parts[0] != self._state.stream_channel:
            os.remove(stream_file)
            return False
        return True

    def _validate_size(self, stream_file) -> bool:
        if not self._check_size(stream_file):
            self._log.error("archive not increasing, resetting channel")
            self.push_event(EventMessage(self.name, EventTypes.KILL_HLS_STREAM, None))
            return False
        return True

    def _check_size(self, abs_path: str) -> bool:
        current = os.path.getsize(abs_path)
        if (
            self.last_size.get(abs_path) is not None
            and self.last_size[abs_path] == current
        ):
            return False

        self.last_size[abs_path] = current
        return True

    def _delete_old_archives(
        self, archive_folder: str, archive_base: str, current_file: str
    ) -> int:
        """Deletes any old versions of archive that is about to be made"""

        archive_files = get_files(archive_folder)

        now = datetime.now(timezone.utc)
        removed: int = 0
        for archive_file in archive_files:
            abs_path = os.path.join(archive_folder, archive_file)
            access_time = datetime.fromtimestamp(os.path.getatime(abs_path)).replace(
                tzinfo=timezone.utc
            )

            age = now - access_time
            if (
                archive_file.startswith(archive_base) and archive_file != current_file
            ) or age > ARCHIVE_DROPOFF:

                self._log.debug(f"deleted old archive: {abs_path}")
                os.remove(abs_path)
                removed += 1
        return removed

    def _process_stream_file(self, abs_path: str) -> Tuple[Union[str, None], int]:
        """Processes stream file by creating an archive from
        it if necessary"""

        channel_id = self._state.stream_channel
        if channel_id is None or self.archive_folder is None:
            return (None, 0)
        channel_archive = os.path.join(self.archive_folder, channel_id)

        now = self._state.radio_time or datetime.now(timezone.utc)
        start_time = self._state.start_time or datetime.fromtimestamp(
            os.path.getatime(abs_path)
        ).replace(tzinfo=timezone.utc)

        max_archive_cutoff = now - ARCHIVE_BUFFER
        creation_time = start_time + ARCHIVE_BUFFER

        time_elapsed = max_archive_cutoff - creation_time
        archive_chunks = int(time_elapsed / ARCHIVE_CHUNK)
        if archive_chunks > 0:
            os.makedirs(channel_archive, exist_ok=True)
            time_elapsed = archive_chunks * ARCHIVE_CHUNK
            archive_cutoff = creation_time + time_elapsed

            archive_base = f"{channel_id}.{create_fs_datetime(creation_time)}"
            archive_filename = (
                f"{archive_base}.{create_fs_datetime(archive_cutoff)}.mp3"
            )
            archive_output = os.path.join(channel_archive, archive_filename)
            if os.path.exists(archive_output):
                return (None, 0)

            removed = self._delete_old_archives(
                channel_archive, archive_base, archive_filename
            )
            return (
                splice_file(
                    abs_path,
                    archive_output,
                    int(ARCHIVE_BUFFER.total_seconds()),
                    int((ARCHIVE_BUFFER + time_elapsed).total_seconds()),
                ),
                removed,
            )
        return (None, 0)
