from dataclasses import dataclass
from pathlib import Path

import opennsfw2 as nsfw
from loguru import logger

from config.settings import settings


@dataclass
class SafetyResult:
    path: Path
    score: float
    safe: bool
    borderline: bool


def check_image(image_path: Path, threshold: float | None = None) -> SafetyResult:
    """检测单张图片的NSFW分数"""
    threshold = threshold or settings.nsfw_threshold
    score = nsfw.predict_image(str(image_path))

    # score < 0.3: 安全, 0.3 <= score < threshold: 擦边(放行), score >= threshold: 拒绝
    borderline = 0.3 <= score < threshold
    rejected = score >= threshold

    return SafetyResult(
        path=image_path,
        score=round(score, 4),
        safe=not rejected,
        borderline=borderline,
    )


def check_images(image_paths: list[Path], threshold: float | None = None) -> list[SafetyResult]:
    """批量检测图片"""
    results = []
    for p in image_paths:
        try:
            result = check_image(p, threshold)
            status = "SAFE"
            if result.borderline:
                status = "BORDERLINE"
            if not result.safe:
                status = "REJECTED"
            logger.info(f"[NSFW] {p.name}: score={result.score:.4f} -> {status}")
            results.append(result)
        except Exception as e:
            logger.warning(f"Failed to check {p.name}: {e}")
    return results


def filter_safe_images(image_paths: list[Path], threshold: float | None = None) -> list[Path]:
    """过滤出安全的图片"""
    results = check_images(image_paths, threshold)
    safe_paths = [r.path for r in results if r.safe]
    rejected = len(results) - len(safe_paths)
    if rejected:
        logger.info(f"Filtered out {rejected} unsafe image(s)")
    return safe_paths


def filter_safe_with_results(
    image_paths: list[Path], threshold: float | None = None
) -> tuple[list[Path], list[SafetyResult]]:
    """过滤安全图片，同时返回所有检测结果（用于文案生成）"""
    results = check_images(image_paths, threshold)
    safe_paths = [r.path for r in results if r.safe]
    rejected = len(results) - len(safe_paths)
    if rejected:
        logger.info(f"Filtered out {rejected} unsafe image(s)")
    return safe_paths, results
