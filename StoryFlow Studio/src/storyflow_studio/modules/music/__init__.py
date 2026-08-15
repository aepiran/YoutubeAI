"""Background music library and rendering services."""

from .library import (
    MIXKIT_CATALOG_URL,
    MIXKIT_LICENSE_NAME,
    MIXKIT_LICENSE_URL,
    ImportResult,
    MusicLibraryError,
    MusicLibraryService,
    default_downloads_folder,
)
from .service import (
    MUSIC_CUE_COLUMNS,
    FFmpegMusicRenderer,
    MusicCue,
    MusicDNAService,
    MusicProgress,
    MusicWorkflowError,
    MusicWorkflowResult,
    MusicWorkflowService,
    format_music_timestamp,
    parse_and_validate_music_cues,
    parse_music_timestamp,
    write_music_csv,
)

__all__ = [
    "MIXKIT_CATALOG_URL",
    "MIXKIT_LICENSE_NAME",
    "MIXKIT_LICENSE_URL",
    "ImportResult",
    "MusicLibraryError",
    "MusicLibraryService",
    "default_downloads_folder",
    "MUSIC_CUE_COLUMNS",
    "FFmpegMusicRenderer",
    "MusicCue",
    "MusicDNAService",
    "MusicProgress",
    "MusicWorkflowError",
    "MusicWorkflowResult",
    "MusicWorkflowService",
    "format_music_timestamp",
    "parse_and_validate_music_cues",
    "parse_music_timestamp",
    "write_music_csv",
]
