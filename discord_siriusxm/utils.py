import logging
import os
import subprocess

from pydub import AudioSegment
from pydub.silence import split_on_silence

TRIM_VARIANCE = 0.05

logger = logging.getLogger('discord_siriusxm.utils')


def get_files(folder):
    dir_list = os.listdir(folder)

    files = []
    for dir_item in dir_list:
        abs_path = os.path.join(folder, dir_item)
        if os.path.isfile(abs_path):
            files.append(dir_item)

    return files


def splice_file(input_file, output_file, start_time, end_time) -> str:
    args = [
        'ffmpeg', '-y',
        '-i', input_file, '-acodec', 'copy',
        '-ss', str(start_time), '-to', str(end_time),
        '-loglevel', 'warning',
        output_file
    ]

    try:
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f'failed to create archive: {e}')
        return None
    else:
        logger.info(f'spliced file: {output_file}')
        return output_file


def attempt_trim(song, song_path, expected_length):
    for min_silence in range(500, 0, -100):
        for silence_thresh in range(-14, -30, -2):
            logger.warn(
                f'attempting to trim file: {song_path} '
                f'{silence_thresh} {min_silence}'
            )

            song_chunks = split_on_silence(
                song,
                min_silence_len=min_silence,
                silence_thresh=silence_thresh
            )

            logger.warn(f'chunks: {len(song_chunks)}')
            for chunk in song_chunks:
                length = float(len(chunk) / 1000)
                precent_expected = (length / expected_length)
                if precent_expected > (1.0 - TRIM_VARIANCE):
                    if precent_expected < (1.0 + TRIM_VARIANCE):
                        return chunk
                    logger.warn(
                        f'file to large: {length}/{expected_length} ({precent_expected})'
                    )
                else:
                    logger.warn(
                        f'file to small: {length}/{expected_length} ({precent_expected})'
                    )
    return None


def trim_song(song_path, expected_length):
    song = AudioSegment.from_file(song_path)

    song_chunk = attempt_trim(song, song_path, expected_length)

    if song_chunk is not None:
        logger.warn(f'trim file successfully: {song_path}')

        # os.path.remove(song_path)

        song_path = song_path.replace('.untrimmed', '')
        song_chunk.export(song_path, bitrate='256k', format="mp3")
    else:
        logger.warn(f'could not trim file: {song_path}')

    return song_path
