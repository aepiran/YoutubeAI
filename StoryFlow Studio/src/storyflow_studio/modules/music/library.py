"""Safe user-selected imports into the local background-music library."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from ...core.media import probe_audio_duration


MIXKIT_LICENSE_NAME = "Mixkit Stock Music Free License"
MIXKIT_LICENSE_URL = "https://mixkit.co/license/#musicFree"
MIXKIT_CATALOG_URL = "https://mixkit.co/free-stock-music/"
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
LIBRARY_MANIFEST = "music_library.json"


class MusicLibraryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MusicTrackRecord:
    track_id: str
    filename: str
    title: str
    sha256: str
    size_bytes: int
    duration_seconds: float
    source: str
    source_url: str
    license: str
    license_url: str
    imported_at: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: tuple[MusicTrackRecord, ...]
    skipped: tuple[str, ...]
    manifest_path: Path


class MusicLibraryService:
    def __init__(
        self,
        duration_probe: Callable[[Path], float | None] = probe_audio_duration,
    ) -> None:
        self.duration_probe = duration_probe

    def import_files(
        self,
        sources: Iterable[str | Path],
        library_folder: str | Path,
    ) -> ImportResult:
        library = Path(library_folder).expanduser().resolve()
        if not str(library_folder).strip():
            raise MusicLibraryError("Hãy cấu hình Music Library Folder trước.")
        library.mkdir(parents=True, exist_ok=True)
        if not library.is_dir():
            raise MusicLibraryError(f"Music Library không hợp lệ: {library}")

        manifest_path = library / LIBRARY_MANIFEST
        payload = self._load_manifest(manifest_path)
        records = payload["tracks"]
        known_hashes = {
            str(item.get("sha256", ""))
            for item in records
            if isinstance(item, dict)
        }
        imported: list[MusicTrackRecord] = []
        skipped: list[str] = []
        for source_value in sources:
            source = Path(source_value).expanduser().resolve()
            if not source.is_file():
                raise MusicLibraryError(f"File nhạc không tồn tại: {source}")
            if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                raise MusicLibraryError(f"Định dạng nhạc chưa hỗ trợ: {source.name}")
            if source.stat().st_size <= 0:
                raise MusicLibraryError(f"File nhạc đang trống: {source.name}")
            digest = _sha256(source)
            if digest in known_hashes:
                skipped.append(source.name)
                continue
            duration = self.duration_probe(source)
            if duration is None or duration <= 0:
                raise MusicLibraryError(
                    f"Không đọc được audio metadata: {source.name}. "
                    "Hãy kiểm tra FFmpeg/FFprobe hoặc file nguồn."
                )
            destination = self._destination(library, source.name, digest)
            if destination.resolve() != source:
                _atomic_copy(source, destination)
            record = MusicTrackRecord(
                track_id=digest[:16],
                filename=destination.name,
                title=_title_from_filename(destination.stem),
                sha256=digest,
                size_bytes=destination.stat().st_size,
                duration_seconds=round(duration, 3),
                source="Mixkit",
                source_url=MIXKIT_CATALOG_URL,
                license=MIXKIT_LICENSE_NAME,
                license_url=MIXKIT_LICENSE_URL,
                imported_at=datetime.now(UTC).isoformat(),
            )
            records.append(asdict(record))
            known_hashes.add(digest)
            imported.append(record)

        if imported or not manifest_path.exists():
            payload["updated_at"] = datetime.now(UTC).isoformat()
            self._write_manifest(manifest_path, payload)
        return ImportResult(tuple(imported), tuple(skipped), manifest_path)

    @staticmethod
    def _load_manifest(path: Path) -> dict:
        if not path.is_file():
            return {"schema_version": 1, "updated_at": "", "tracks": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MusicLibraryError(f"Không đọc được {path.name}: {exc}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("tracks"), list)
        ):
            raise MusicLibraryError(f"{path.name} không đúng schema hỗ trợ.")
        return payload

    @staticmethod
    def _destination(library: Path, filename: str, digest: str) -> Path:
        clean_name = Path(filename).name
        destination = library / clean_name
        if not destination.exists():
            return destination
        if _sha256(destination) == digest:
            return destination
        return library / f"{destination.stem}-{digest[:8]}{destination.suffix.lower()}"

    @staticmethod
    def _write_manifest(path: Path, payload: dict) -> None:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(handle.name)
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


def default_downloads_folder() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(handle.name)
    try:
        with handle, source.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, handle, length=1024 * 1024)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _title_from_filename(value: str) -> str:
    clean = value.replace("_", " ").replace("-", " ")
    return " ".join(clean.split()).strip()
