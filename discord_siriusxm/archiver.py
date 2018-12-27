import logging
import os
import subprocess
import time

from .models import XMState
from .utils import get_files, splice_file

ARCHIVE_CHUNK = 600
ARCHIVE_BUFFER = 5
MAX_ARCHIVE_TIME = 14400  # 4 hours

logger = logging.getLogger('discord_siriusxm.archiver')


def delete_old_archives(archive_folder, archive_base, ignored_file):
    archive_files = get_files(archive_folder)

    for archive_file in archive_files:
        abs_path = os.path.join(archive_folder, archive_file)
        if archive_file.startswith(archive_base) and \
                archive_file != ignored_file:
            logger.debug(f'deleted old archive: {abs_path}')
            os.remove(abs_path)


def process_stream_file(abs_path, channel_id, archive_folder) -> str:
    max_archive_cutoff = int(time.time()) - ARCHIVE_BUFFER
    creation_time = int(os.path.getatime(abs_path)) + ARCHIVE_BUFFER

    time_elapsed = max_archive_cutoff - creation_time
    archive_chunks = int(time_elapsed / ARCHIVE_CHUNK)
    if archive_chunks > 0:
        os.makedirs(archive_folder, exist_ok=True)
        time_elapsed = (archive_chunks * ARCHIVE_CHUNK)
        archive_cutoff = creation_time + time_elapsed

        archive_base = f'{channel_id}.{creation_time}'
        archive_filename = f'{archive_base}.{archive_cutoff}.mp3'
        archive_output = os.path.join(
            archive_folder, archive_filename)
        if os.path.exists(archive_output):
            return None

        delete_old_archives(archive_folder, archive_base, archive_filename)
        return splice_file(
            abs_path, archive_output,
            ARCHIVE_BUFFER, ARCHIVE_BUFFER + time_elapsed
        )
    return None


def run_archiver(state, output_folder):
    state = XMState(state)

    stream_folder = os.path.join(output_folder, 'streams')
    archive_folder = os.path.join(output_folder, 'archive')

    os.makedirs(stream_folder, exist_ok=True)
    os.makedirs(archive_folder, exist_ok=True)

    logger.info(f'stream archiver started: {output_folder}')
    while True:
        time.sleep(600)
        try:
            active_channel_id = state.active_channel_id

            if active_channel_id is None:
                continue

            deleted = 0
            archived = None
            stream_files = get_files(stream_folder)
            channel_archive = os.path.join(archive_folder, active_channel_id)

            for stream_file in stream_files:
                abs_path = os.path.join(stream_folder, stream_file)
                file_parts = stream_file.split('.')
                if file_parts[-1] != 'mp3' or \
                        file_parts[0] != active_channel_id:
                    os.remove(abs_path)
                    deleted += 1
                else:
                    state.processing_file = True
                    archived = process_stream_file(
                        abs_path, active_channel_id, channel_archive)
                    state.processing_file = False

            logger.info(
                f'completed processing: deleted files: {deleted}, '
                f'archived file: {archived}'
            )
        except Exception:
            logger.error(f'error occurred in archiver loop: {e}')
