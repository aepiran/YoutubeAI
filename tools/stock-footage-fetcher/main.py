"""Search, visually rank and download Pexels footage for every Beat."""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Iterable

import requests
import torch
from PIL import Image


ROOT_DIR = Path(__file__).resolve().parent
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
DEFAULT_MODEL = "google/siglip2-base-patch16-224"
DEFAULT_MODEL_CACHE = (
    ROOT_DIR.parent
    / "footage-video-builder"
    / ".cache"
    / "huggingface"
    / "hub"
)
MAX_PER_PAGE = 80
MAX_PAGE_LIMIT = 50
SUPPORTED_QUALITY = ("hd", "uhd", "sd")


def load_env_file(path: Path = ROOT_DIR / ".env") -> None:
    """Load simple KEY=VALUE entries without overriding system variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value


def normalized_keywords(value: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"[,;\n|]+", value or "")
        if item.strip()
    ]


def search_query(row: dict[str, str]) -> str:
    """Build a concise Pexels query; long cinematic prompts reduce recall."""
    keywords = normalized_keywords(row.get("tu_khoa", ""))
    if keywords:
        return keywords[0]
    visual = str(row.get("hinh_can_tim", "")).strip()
    return " ".join(visual.split()[:10])


def positive_prompt(row: dict[str, str]) -> str:
    parts = [
        str(row.get("hinh_can_tim", "")).strip(),
        str(row.get("y_chinh", "")).strip(),
        ", ".join(normalized_keywords(row.get("tu_khoa", ""))[:4]),
    ]
    return ". ".join(part for part in parts if part)


def best_video_file(video: dict) -> dict | None:
    files = [
        item
        for item in video.get("video_files", [])
        if item.get("link") and item.get("quality") in SUPPORTED_QUALITY
    ]
    landscape = [
        item
        for item in files
        if int(item.get("width") or 0) >= int(item.get("height") or 0)
    ]
    usable = landscape or files
    if not usable:
        return None
    return max(
        usable,
        key=lambda item: (
            min(int(item.get("width") or 0), 3840)
            * min(int(item.get("height") or 0), 2160),
            int(item.get("width") or 0),
        ),
    )


def technical_bonus(video: dict, min_duration: float) -> float:
    """Small tie-breaker; semantic image relevance remains dominant."""
    duration = float(video.get("duration") or 0.0)
    video_file = best_video_file(video)
    if video_file is None or duration < min_duration:
        return -1.0
    width = int(video_file.get("width") or 0)
    height = int(video_file.get("height") or 0)
    resolution_bonus = min(0.025, (width * height) / (1920 * 1080) * 0.012)
    duration_bonus = min(0.015, max(0.0, duration - min_duration) * 0.002)
    return resolution_bonus + duration_bonus


class VisualScorer:
    """Score actual Pexels preview pixels against positive/negative prompts."""

    def __init__(
        self,
        model_name: str,
        session: requests.Session,
        cache_dir: Path,
    ) -> None:
        self.session = session
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Đang tải model thị giác {model_name} trên {self.device}...")
        if "siglip2" in model_name.lower():
            from transformers import SiglipModel as VisionModel
            from transformers import SiglipProcessor as VisionProcessor
        else:
            from transformers import CLIPModel as VisionModel
            from transformers import CLIPProcessor as VisionProcessor
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.processor = VisionProcessor.from_pretrained(
            model_name,
            cache_dir=str(cache_dir),
            use_fast=False,
        )
        self.model = VisionModel.from_pretrained(
            model_name,
            cache_dir=str(cache_dir),
        ).to(self.device)
        self.model.eval()
        self.inference_lock = Lock()

    @staticmethod
    def _normalize(features: torch.Tensor) -> torch.Tensor:
        return features / features.norm(p=2, dim=-1, keepdim=True).clamp(
            min=1e-12
        )

    def _text_features(self, prompts: list[str]) -> torch.Tensor:
        is_siglip = "siglip" in type(self.model).__name__.lower()
        values = self.processor(
            text=prompts,
            return_tensors="pt",
            padding="max_length" if is_siglip else True,
            truncation=True,
            max_length=64 if is_siglip else 77,
        )
        values = {key: value.to(self.device) for key, value in values.items()}
        with torch.inference_mode():
            return self._normalize(self.model.get_text_features(**values))

    def _load_preview(self, video: dict) -> Image.Image | None:
        url = video.get("image")
        if not url:
            pictures = video.get("video_pictures", [])
            url = pictures[0].get("picture") if pictures else None
        if not url:
            return None
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content)).convert("RGB")
        except (requests.RequestException, OSError, ValueError):
            return None

    def score_videos(
        self,
        videos: list[dict],
        positive: str,
        avoid: str,
        min_duration: float,
    ) -> list[tuple[dict, float]]:
        valid_videos = []
        images = []
        bonuses = []
        for video in videos:
            bonus = technical_bonus(video, min_duration)
            if bonus < 0:
                continue
            image = self._load_preview(video)
            if image is None:
                continue
            valid_videos.append(video)
            images.append(image)
            bonuses.append(bonus)
        if not images:
            return []

        with self.inference_lock:
            values = self.processor(
                images=images, return_tensors="pt"
            )
            values = {
                key: value.to(self.device) for key, value in values.items()
            }
            prompts = [positive]
            if avoid.strip():
                prompts.append(avoid.strip())
            with torch.inference_mode():
                image_features = self._normalize(
                    self.model.get_image_features(**values)
                )
                text_features = self._text_features(prompts)
                similarities = image_features @ text_features.T

        rows = []
        for index, video in enumerate(valid_videos):
            positive_score = float(similarities[index, 0].item())
            avoid_score = (
                max(0.0, float(similarities[index, 1].item()))
                if len(prompts) > 1
                else 0.0
            )
            score = positive_score - 0.35 * avoid_score + bonuses[index]
            rows.append((video, score))
        return rows


def search_best_video(
    *,
    row: dict[str, str],
    api_key: str,
    scorer,
    session: requests.Session,
    max_pages: int,
    per_page: int,
    min_score: float,
    min_duration: float,
) -> tuple[dict | None, float, int]:
    """Search pages in order and stop once a page yields a good candidate."""
    query = search_query(row)
    positive = positive_prompt(row)
    avoid = str(row.get("tranh", "")).strip()
    seen_ids: set[int] = set()
    best_video = None
    best_score = -math.inf
    pages_searched = 0

    for page in range(1, max_pages + 1):
        print(
            f"  Trang {page}/{max_pages}: tìm '{query}' "
            f"({per_page} kết quả/trang)"
        )
        # avoid using undefined printf; print for debugging (redact key)
        print(f"API key: {api_key[:4]}...{api_key[-4:]}")
        response = session.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "orientation": "landscape",
                "size": "large",
                "page": page,
                "per_page": per_page,
            },
            timeout=30,
        )
        if response.status_code == 429:
            raise RuntimeError(
                "Pexels API đã hết hạn mức request. Hãy chờ reset hoặc "
                "giảm --max-pages."
            )
        if response.status_code == 401:
            raise RuntimeError(
                "Pexels API từ chối key (401). Chương trình đang gọi endpoint "
                "chính thức api.pexels.com; hãy kiểm tra PEXELS_API_KEY trong .env."
            )
        if response.status_code == 400:
            try:
                api_message = response.json()
            except (ValueError, requests.JSONDecodeError):
                api_message = response.text[:300]
            raise RuntimeError(
                "Pexels API từ chối tham số tìm kiếm (400): "
                f"{api_message}"
            )
        response.raise_for_status()
        pages_searched = page
        videos = [
            video
            for video in response.json().get("videos", [])
            if int(video.get("id") or 0) not in seen_ids
        ]
        seen_ids.update(int(video.get("id") or 0) for video in videos)
        if not videos:
            print("    Không còn kết quả ở trang này.")
            break

        ranked = scorer.score_videos(
            videos, positive, avoid, min_duration
        )
        ranked.sort(key=lambda item: item[1], reverse=True)
        if ranked:
            page_video, page_score = ranked[0]
            print(
                f"    Tốt nhất trang: ID {page_video.get('id')} "
                f"· score={page_score:.4f}"
            )
            if page_score > best_score:
                best_video, best_score = page_video, page_score
            if page_score >= min_score:
                print(
                    f"    Đạt ngưỡng {min_score:.3f}; dừng tìm ở trang {page}."
                )
                break
        data = response.json()
        total_results = int(data.get("total_results") or 0)
        if total_results and page * per_page >= total_results:
            break

    return best_video, best_score, pages_searched


def download_video(
    video: dict,
    beat_id: str,
    output_dir: Path,
    session: requests.Session,
) -> Path:
    video_file = best_video_file(video)
    if video_file is None:
        raise ValueError(f"Video {video.get('id')} không có file phù hợp")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{beat_id}_PEXELS_{video['id']}.mp4"
    with session.get(video_file["link"], stream=True, timeout=120) as response:
        response.raise_for_status()
        temporary = destination.with_suffix(".part")
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        temporary.replace(destination)
    return destination


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"ma_beat", "tu_khoa", "hinh_can_tim", "tranh"}
    missing = required - set(rows[0] if rows else [])
    if missing:
        raise ValueError(
            f"{csv_path.name} thiếu cột: {', '.join(sorted(missing))}"
        )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tìm nhiều trang Pexels, chấm ảnh preview bằng model thị giác "
            "và tải footage tốt nhất cho từng Beat."
        )
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help=(
            "Thư mục Project chứa footage.csv và thư mục video. "
            "Footage tải về sẽ được lưu trong <project-dir>/video."
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Ghi đè đường dẫn footage.csv được suy ra từ Project.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Ghi đè thư mục video được suy ra từ Project.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PEXELS_API_KEY", ""),
        help="Pexels API key; ưu tiên đặt biến môi trường PEXELS_API_KEY.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--model-cache-dir",
        type=Path,
        default=DEFAULT_MODEL_CACHE,
    )
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=MAX_PER_PAGE)
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Số Beat xử lý đồng thời (mặc định: 2; dùng 1 để chạy tuần tự).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.24,
        help="Dừng sớm khi ứng viên tốt nhất đạt ngưỡng này.",
    )
    parser.add_argument("--min-duration", type=float, default=5.0)
    return parser


def resolve_project_paths(args: argparse.Namespace) -> None:
    """Resolve footage.csv and video/ from one Project directory."""
    if args.project_dir is not None:
        project_dir = args.project_dir.expanduser().resolve()
        args.project_dir = project_dir
        if args.csv is None:
            args.csv = project_dir / "footage.csv"
        if args.output_dir is None:
            args.output_dir = project_dir / "video"
    else:
        if args.csv is None:
            args.csv = ROOT_DIR / "footage.csv"
        if args.output_dir is None:
            args.output_dir = ROOT_DIR / "video"
    args.csv = args.csv.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()


def validate_args(args: argparse.Namespace) -> None:
    if not args.api_key:
        raise ValueError(
            "Thiếu Pexels API key. Hãy đặt biến môi trường PEXELS_API_KEY "
            "hoặc dùng --api-key."
        )
    if not 1 <= args.max_pages <= MAX_PAGE_LIMIT:
        raise ValueError(
            f"--max-pages phải trong khoảng 1–{MAX_PAGE_LIMIT}."
        )
    if not 1 <= args.per_page <= MAX_PER_PAGE:
        raise ValueError(
            f"--per-page phải trong khoảng 1–{MAX_PER_PAGE}."
        )
    if not 1 <= args.workers <= 8:
        raise ValueError("--workers phải trong khoảng 1–8.")
    if args.min_duration <= 0:
        raise ValueError("--min-duration phải lớn hơn 0.")
    if args.project_dir is not None and not args.project_dir.is_dir():
        raise FileNotFoundError(
            f"Không tìm thấy thư mục Project: {args.project_dir}"
        )
    if not args.csv.is_file():
        raise FileNotFoundError(f"Không tìm thấy CSV: {args.csv}")


def main(argv: Iterable[str] | None = None) -> int:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    load_env_file()
    args = build_parser().parse_args(argv)
    resolve_project_paths(args)
    validate_args(args)
    rows = load_rows(args.csv)
    session = requests.Session()
    scorer = VisualScorer(
        args.model, session, args.model_cache_dir
    )

    print(
        f"Đã nạp {len(rows)} Beat · tối đa {args.max_pages} trang/Beat "
        f"· {args.per_page} video/trang."
    )
    print(
        f"Chế độ đa luồng: tối đa {args.workers} Beat đồng thời."
    )

    def process_one(
        index: int, row: dict[str, str]
    ) -> tuple[str, bool]:
        beat_id = str(row["ma_beat"]).strip().upper()
        print(f"\n[{index}/{len(rows)}] Beat {beat_id}")
        beat_session = requests.Session()
        try:
            video, score, pages = search_best_video(
                row=row,
                api_key=args.api_key,
                scorer=scorer,
                session=beat_session,
                max_pages=args.max_pages,
                per_page=args.per_page,
                min_score=args.min_score,
                min_duration=args.min_duration,
            )
            if video is None:
                print(f"  Không tìm thấy footage đạt điều kiện sau {pages} trang.")
                return beat_id, False
            destination = download_video(
                video, beat_id, args.output_dir, beat_session
            )
            print(
                f"  Đã tải ID {video['id']} · score={score:.4f} "
                f"· {float(video.get('duration') or 0):.1f}s"
            )
            print(f"  Lưu tại: {destination}")
            return beat_id, True
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"  [LỖI] {exc}")
            return beat_id, False
        finally:
            beat_session.close()

    completed = 0
    succeeded = 0
    with ThreadPoolExecutor(
        max_workers=min(args.workers, len(rows)),
        thread_name_prefix="pexels-beat",
    ) as executor:
        futures = [
            executor.submit(process_one, index, row)
            for index, row in enumerate(rows, start=1)
        ]
        for future in as_completed(futures):
            beat_id, success = future.result()
            completed += 1
            succeeded += int(success)
            print(
                f"[HOÀN TẤT {completed}/{len(rows)}] {beat_id} · "
                f"{'đã tải' if success else 'không có kết quả'}"
            )
    print(f"Hoàn thành: {succeeded}/{len(rows)} Beat tải thành công.")
    return 0


def entrypoint(argv: Iterable[str] | None = None) -> int:
    """Open the desktop app by default; preserve the legacy CLI with args."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        from stock_footage_app import main as desktop_main

        return desktop_main([])
    return main(arguments)


if __name__ == "__main__":
    raise SystemExit(entrypoint())
