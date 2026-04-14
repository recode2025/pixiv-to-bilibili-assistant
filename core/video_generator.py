import math
import random
from pathlib import Path

from moviepy import (
    VideoClip,
    concatenate_videoclips,
    AudioFileClip,
    CompositeVideoClip,
    vfx,
)
from moviepy.audio.fx import AudioFadeOut
from loguru import logger

from config.settings import settings


def _ease_in_out(t: float) -> float:
    """缓入缓出插值，让运动更丝滑"""
    return t * t * (3 - 2 * t)


def _anime_pan_clip(
    image_path: Path,
    duration: float,
    target_size: tuple[int, int],
    effect_type: str | None = None,
) -> VideoClip:
    """二次元风动态效果：缩放/平移/聚焦，带缓入缓出"""
    from PIL import Image, ImageFilter
    import numpy as np

    img = Image.open(str(image_path)).convert("RGB")
    tw, th = target_size

    # 随机选效果
    if effect_type is None:
        effect_type = random.choice([
            "zoom_in", "zoom_out", "pan_left", "pan_right",
            "pan_up", "pan_down", "focus_center",
            "zoom_in_fast", "drift",
        ])

    # 参数范围
    if effect_type == "zoom_in":
        zoom_start, zoom_end = 1.0, random.uniform(1.15, 1.25)
        pan_dx, pan_dy = 0, 0
    elif effect_type == "zoom_out":
        zoom_start, zoom_end = random.uniform(1.15, 1.25), 1.0
        pan_dx, pan_dy = 0, 0
    elif effect_type == "zoom_in_fast":
        zoom_start, zoom_end = 1.0, random.uniform(1.25, 1.35)
        pan_dx, pan_dy = 0, 0
    elif effect_type == "pan_left":
        zoom_start, zoom_end = 1.1, 1.1
        pan_dx, pan_dy = random.randint(40, 80), 0
    elif effect_type == "pan_right":
        zoom_start, zoom_end = 1.1, 1.1
        pan_dx, pan_dy = -random.randint(40, 80), 0
    elif effect_type == "pan_up":
        zoom_start, zoom_end = 1.1, 1.1
        pan_dx, pan_dy = 0, random.randint(40, 80)
    elif effect_type == "pan_down":
        zoom_start, zoom_end = 1.1, 1.1
        pan_dx, pan_dy = 0, -random.randint(40, 80)
    elif effect_type == "focus_center":
        zoom_start, zoom_end = 1.15, 1.0
        pan_dx, pan_dy = 0, 0
    elif effect_type == "drift":
        zoom_start, zoom_end = 1.05, random.uniform(1.12, 1.18)
        pan_dx = random.randint(-50, 50)
        pan_dy = random.randint(-50, 50)
    else:
        zoom_start, zoom_end = 1.0, 1.12
        pan_dx, pan_dy = 0, 0

    def make_frame(t):
        progress = _ease_in_out(t / duration)
        zoom = zoom_start + (zoom_end - zoom_start) * progress
        dx = int(pan_dx * progress)
        dy = int(pan_dy * progress)

        zw, zh = int(tw * zoom), int(th * zoom)
        resized = img.resize((zw, zh), Image.LANCZOS)

        cx, cy = zw // 2 + dx, zh // 2 + dy
        left = max(0, cx - tw // 2)
        top = max(0, cy - th // 2)
        right = left + tw
        bottom = top + th

        if right > zw:
            left = zw - tw
            right = zw
        if bottom > zh:
            top = zh - th
            bottom = zh
        left = max(0, left)
        top = max(0, top)

        return np.array(resized.crop((left, top, right, bottom)))

    return VideoClip(make_frame, duration=duration)


def _crossfade(clip_a: VideoClip, clip_b: VideoClip, duration: float) -> VideoClip:
    """两个片段之间的交叉溶解转场"""
    from moviepy import CompositeVideoClip

    # clip_b 在转场开始时切入
    b_start = clip_a.duration - duration
    part_a = clip_a.subclipped(b_start)
    part_b = clip_b.subclipped(0, min(duration, clip_b.duration))

    # 各自加淡入淡出
    part_a = part_a.with_effects([vfx.FadeOut(duration)])
    part_b = part_b.with_effects([vfx.FadeIn(duration)])

    return CompositeVideoClip([part_a, part_b])


def _vignette_frame(frame, intensity: float = 0.3):
    """给画面加暗角效果，增加二次元氛围感"""
    import numpy as np
    h, w = frame.shape[:2]
    y, x = np.ogrid[:h, :w]
    cx, cy = w / 2, h / 2
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    vignette = 1 - intensity * (dist / max_dist) ** 1.5
    vignette = np.clip(vignette, 0, 1)

    result = frame.astype(np.float32)
    for c in range(3):
        result[:, :, c] *= vignette
    return np.clip(result, 0, 255).astype(np.uint8)


def _get_resolution_from_images(image_paths: list[Path]) -> tuple[int, int]:
    """从第一张图获取原始比例，短边对齐 1080，限制最大 1920"""
    from PIL import Image

    img = Image.open(str(image_paths[0]))
    w, h = img.size

    if w <= h:
        new_w = 1080
        new_h = int(h / w * 1080)
    else:
        new_h = 1080
        new_w = int(w / h * 1080)

    new_w = min(new_w, 1920)
    new_h = min(new_h, 1920)
    new_w = new_w if new_w % 2 == 0 else new_w + 1
    new_h = new_h if new_h % 2 == 0 else new_h + 1
    return (new_w, new_h)


def generate_video(
    image_paths: list[Path],
    output_path: Path | None = None,
    bgm_path: Path | None = None,
) -> Path:
    """
    生成二次元风动态视频：一张图 + 10秒动态效果 + 暗角 + BGM。
    - 单张图 10 秒，带缩放/平移/暗角
    - 多张图时自动分配时间
    - 强制配 BGM
    """
    if not image_paths:
        raise ValueError("No images provided for video generation")

    output_path = output_path or settings.video_dir / "output.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    resolution = _get_resolution_from_images(image_paths)

    # 单张图固定 10s，多张图总时长 10s 均分
    target_total = 10.0
    if len(image_paths) == 1:
        per_image = target_total
    else:
        per_image = target_total / len(image_paths)
        per_image = max(2.0, min(3.5, per_image))
    crossfade_dur = 0.6

    logger.info(
        f"Video: {resolution[0]}x{resolution[1]}, "
        f"{len(image_paths)} image(s) x {per_image:.1f}s"
    )

    # 为每张图随机分配不同的动态效果
    effects = random.choice([
        ["zoom_in", "pan_left", "zoom_out", "focus_center"],
        ["zoom_in_fast", "pan_right", "drift", "zoom_out"],
        ["drift", "zoom_in", "pan_down", "focus_center"],
        ["pan_left", "zoom_in", "pan_right", "zoom_in_fast"],
    ])

    # 生成各片段
    clips = []
    for i, img_path in enumerate(image_paths):
        effect = effects[i % len(effects)]
        clip = _anime_pan_clip(img_path, per_image, resolution, effect_type=effect)

        # 加暗角
        clip = clip.image_transform(_vignette_frame)

        clips.append(clip)

    # 用交叉溶解拼接
    if len(clips) == 1:
        final = clips[0]
    else:
        segments = [clips[0]]
        for i in range(1, len(clips)):
            transition = _crossfade(clips[i - 1], clips[i], crossfade_dur)
            segments.append(transition)
            remaining = clips[i].subclipped(crossfade_dur)
            segments.append(remaining)
        final = concatenate_videoclips(segments, method="compose")

    actual_duration = final.duration
    logger.info(f"Total video duration: {actual_duration:.1f}s")

    # 添加 BGM
    if bgm_path and bgm_path.exists():
        try:
            bgm = AudioFileClip(str(bgm_path))
            if bgm.duration > actual_duration:
                start = random.uniform(0, bgm.duration - actual_duration)
                bgm = bgm.subclipped(start, start + actual_duration)
            else:
                bgm = bgm.loop(duration=actual_duration)
            bgm = bgm.with_effects([AudioFadeOut(2.0)])
            final = final.with_audio(bgm)
            logger.info(f"Added BGM: {bgm_path.name}")
        except Exception as e:
            logger.warning(f"Failed to add BGM, generating without audio: {e}")

    final.write_videofile(
        str(output_path),
        fps=settings.video_fps,
        codec="libx264",
        bitrate="4000k",
        audio_bitrate="128k",
        logger=None,
    )
    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"Video saved: {output_path} ({size_mb:.1f}MB)")
    return output_path
