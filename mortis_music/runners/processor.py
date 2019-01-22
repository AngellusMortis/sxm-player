import os
from typing import Dict

from sxm.models import XMMarker

from ..models import Episode, Song
from ..utils import get_air_time, get_files, splice_file
from .archiver import ARCHIVE_CHUNK
from .base import BaseRunner

__all__ = ["ProcessorRunner"]

MAX_DUPLICATE_COUNT = 3


class ProcessorRunner(BaseRunner):
    """ Runs song/show processor """

    def __init__(self, reset_songs: bool, *args, **kwargs):
        kwargs["name"] = "processor"
        kwargs["reset_songs"] = reset_songs
        super().__init__(*args, **kwargs)

        self._delay = 10
        if (
            self.state.processed_folder is not None
            and self.state.archive_folder is not None
        ):
            os.makedirs(self.state.processed_folder, exist_ok=True)
            os.makedirs(self.state.archive_folder, exist_ok=True)

    def loop(self) -> None:
        self._delay = ARCHIVE_CHUNK

        if (
            self.state.active_channel_id is None
            or self.state.live is None
            or self.state.archive_folder is None
        ):
            return None

        channel_archive = os.path.join(
            self.state.archive_folder, self.state.active_channel_id
        )
        os.makedirs(channel_archive, exist_ok=True)

        archives = {}
        archive_files = get_files(channel_archive)
        for archive_file in archive_files:
            file_parts = archive_file.split(".")
            archive_key = f"{file_parts[1]}.{file_parts[2]}"
            archives[archive_key] = os.path.join(channel_archive, archive_file)
        self._log.debug(f"found {len(archives.keys())}")

        processed_songs = self._process_cuts(archives, is_song=True)

        processed_shows = self._process_cuts(archives, is_song=False)

        self._log.info(
            f"processed: {processed_songs} songs, {processed_shows} shows"
        )

    def _path_filter(self, word: str) -> str:
        """ Filters out known words to call issues for creating
        names for folders/files """

        return (
            word.replace("Counterfeit.", "Counterfeit")
            .replace("F**ker", "Fucker")
            .replace("Trust?", "Trust")
            .replace("P.O.D.", "POD")
            .replace("//", "-")
            .strip()
        )

    def _process_cut(
        self, archives: Dict[str, str], cut: XMMarker, is_song: bool = True
    ) -> bool:
        """ Processes `archives` to splice out an
            instance of `XMMarker` if it exists """

        if (
            self.state.processed_folder is None
            or self.state.active_channel_id is None
            or self.state.db is None
        ):
            return False

        archive = None
        start = int(cut.time / 1000) + 20
        padded_duration = int(cut.duration + 20)
        end = start + padded_duration

        for archive_key, archive_file in archives.items():
            archive_start, archive_end = [
                int(i) for i in archive_key.split(".")
            ]

            if archive_start < start and archive_end > end:
                archive = archive_file
                start = start - archive_start
                end = start + padded_duration
                break

        if archive is not None:
            self._log.debug(f"found archive {archive}")

            title = None
            album_or_show = None
            artist = None
            filename = None
            folder = os.path.join(
                self.state.processed_folder, self.state.active_channel_id
            )

            air_time = get_air_time(cut)

            if is_song:
                title = self._path_filter(cut.cut.title)
                artist = self._path_filter(cut.cut.artists[0].name)

                if (
                    cut.cut.album is not None
                    and cut.cut.album.title is not None
                ):
                    album_or_show = self._path_filter(cut.cut.album.title)

                filename = f"{title}.{cut.guid}.mp3"
                folder = os.path.join(folder, "songs", artist)
            else:
                title = self._path_filter(
                    cut.episode.long_title or cut.episode.medium_title
                )

                if cut.episode.show is not None:
                    album_or_show = self._path_filter(
                        cut.episode.show.long_title
                        or cut.episode.show.medium_title
                    )

                filename = (
                    f'{title}.{air_time.strftime("%Y-%m-%d-%H.%M")}'
                    f".{cut.guid}.mp3"
                )
                folder = os.path.join(folder, "shows")

            if album_or_show is not None:
                folder = os.path.join(folder, album_or_show)

            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, filename)
            self._log.debug(f"{cut.duration}: {path}")
            path = splice_file(archive, path, start, end)  # type: ignore

            if path is not None:
                if os.path.getsize(path) < 1000:
                    self._log.error(
                        f"spliced file too small, deleting {path}: {archive}"
                    )
                    os.remove(path)
                    return False

                db_item = None

                if is_song:
                    db_item = Song(
                        guid=cut.guid,
                        title=title,
                        artist=artist,
                        album=album_or_show,
                        air_time=air_time,
                        channel=self.state.active_channel_id,
                        file_path=path,
                    )
                else:
                    db_item = Episode(
                        guid=cut.guid,
                        title=title,
                        show=album_or_show,
                        air_time=air_time,
                        channel=self.state.active_channel_id,
                        file_path=path,
                    )

                self.state.db.add(db_item)
                self.state.db.commit()
                self._log.debug(f"inserted cut {is_song}: {db_item.guid}")
                return True
        return False

    def _process_cuts(
        self, archives: Dict[str, str], is_song: bool = True
    ) -> int:
        """ Processes `archives` to splice out any
            instance of `XMMarker` if it exists """

        if self.state.live is None or self.state.db is None:
            return 0

        if is_song:
            cuts = self.state.live.song_cuts
        else:
            cuts = self.state.live.episode_markers

        processed = 0
        for cut in cuts:
            if cut.duration == 0.0:
                continue

            db_item = None
            if is_song:
                existing = (
                    self.state.db.query(Song)
                    .filter_by(
                        title=cut.cut.title, artist=cut.cut.artists[0].name
                    )
                    .all()
                )

                if len(existing) >= MAX_DUPLICATE_COUNT:
                    continue

                db_item = (
                    self.state.db.query(Song).filter_by(guid=cut.guid).first()
                )
            else:
                db_item = (
                    self.state.db.query(Episode)
                    .filter_by(guid=cut.guid)
                    .first()
                )

            if db_item is not None:
                continue

            title = None
            if is_song:
                title = cut.cut.title
            else:
                title = cut.episode.long_title or cut.episode.medium_title

            self._log.debug(
                f"processing {title}: "
                f"{cut.time}: {cut.duration}"
                f"{cut.guid}"
            )
            success = self._process_cut(archives, cut, is_song)

            if success:
                processed += 1
        return processed
