import logging
import os
import subprocess
import time

from .models import XMState

ARCHIVE_CHUNK = 600
ARCHIVE_BUFFER = 5
MAX_ARCHIVE_TIME = 14400  # 4 hours

logger = logging.getLogger('discord_siriusxm.processor')


def archive_file(abs_path, archive_output, time_elapsed) -> str:
    start_time = str(ARCHIVE_BUFFER)
    end_time = str(ARCHIVE_BUFFER + time_elapsed)

    args = [
        'ffmpeg',
        '-i', abs_path, '-acodec', 'copy',
        '-ss', start_time, '-to', end_time,
        '-loglevel', 'warning',
        archive_output
    ]

    try:
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f'failed to create archive: {e}')
        return None
    else:
        logger.debug(f'created new archive: {archive_output}')
        return archive_output


def delete_old_archives(archive_folder, archive_base, ignored_file):
    dir_list = os.listdir(archive_folder)
    for dir_item in dir_list:
        abs_path = os.path.join(archive_folder, dir_item)
        if os.path.isfile(abs_path):
            if dir_item.startswith(archive_base) and dir_item != ignored_file:
                logger.debug(f'deleted old archive: {abs_path}')
                os.remove(abs_path)


def process_stream_file(abs_path, channel_id, archive_folder) -> str:
    max_archive_cutoff = int(time.time()) - ARCHIVE_BUFFER
    creation_time = int(os.path.getatime(abs_path)) + ARCHIVE_BUFFER

    time_elapsed = max_archive_cutoff - creation_time
    archive_chunks = time_elapsed / ARCHIVE_CHUNK
    if archive_chunks > 0:
        os.makedirs(archive_folder, exist_ok=True)
        archive_cutoff = creation_time + (time_elapsed * ARCHIVE_CHUNK)

        archive_base = f'{channel_id}.{creation_time}'
        archive_filename = f'{archive_base}.{archive_cutoff}.mp3'
        archive_output = os.path.join(
            archive_folder, archive_filename)
        if os.path.exists(archive_output):
            return None

        delete_old_archives(archive_folder, archive_base, archive_filename)
        return archive_file(abs_path, archive_output, time_elapsed)
    return None


def run_archiver(state, output_folder):
    state = XMState(state)

    stream_folder = os.path.join(output_folder, 'streams')
    processed_folder = os.path.join(output_folder, 'processed')
    archive_folder = os.path.join(output_folder, 'archive')

    os.makedirs(stream_folder, exist_ok=True)
    os.makedirs(processed_folder, exist_ok=True)
    os.makedirs(archive_folder, exist_ok=True)

    logger.info(f'song processor started: {output_folder}')
    while True:
        time.sleep(300)
        active_channel_id = state.active_channel_id
        dir_list = os.listdir(stream_folder)

        deleted = 0
        archived = None
        for dir_item in dir_list:
            abs_path = os.path.join(stream_folder, dir_item)
            if os.path.isfile(abs_path):
                file_parts = dir_item.split('.')
                if file_parts[-1] != 'mp3' or \
                        file_parts[0] != active_channel_id:
                    os.remove(abs_path)
                    deleted += 1
                else:
                    channel_archive = os.path.join(
                        archive_folder, active_channel_id)
                    state.processing_file = True
                    archived = process_stream_file(
                        abs_path, active_channel_id, channel_archive)
                    state.processing_file = False

        logger.info(
            f'completed processing: deleted files: {deleted}, '
            f'archived file: {archived}'
        )
