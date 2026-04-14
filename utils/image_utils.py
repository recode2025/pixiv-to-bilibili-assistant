import io
from pathlib import Path

import httpx
from PIL import Image
from loguru import logger

from config.settings import settings

_HEADERS = {
    "Referer": "https://www.pixiv.net/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

MAX_RETRIES = 3
BILIBILI_IMAGE_MAX_SIZE = 20 * 1024 * 1024  # 20MB


def download_image(url: str, save_path: Path) -> Path | None:
    proxy = settings.proxy or None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with httpx.Client(proxy=proxy, timeout=30, follow_redirects=True) as client:
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
                content = resp.content
                if len(content) < 1024:
                    logger.warning(f"Downloaded file too small ({len(content)} bytes), likely invalid")
                    continue
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(content)
                # 验证是否为有效图片
                try:
                    with Image.open(save_path) as img:
                        img.verify()
                except Exception:
                    logger.warning(f"Downloaded file is not a valid image: {save_path.name}")
                    save_path.unlink(missing_ok=True)
                    continue
                logger.debug(f"Downloaded: {save_path.name}")
                return save_path
        except Exception as e:
            logger.warning(f"Download attempt {attempt}/{MAX_RETRIES} failed for {url}: {e}")
    return None


def convert_to_jpg(src: Path, dst: Path | None = None) -> Path:
    dst = dst or src.with_suffix(".jpg")
    img = Image.open(src)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(dst, "JPEG", quality=95)
    # 验证输出文件
    try:
        with Image.open(dst) as vimg:
            vimg.verify()
    except Exception:
        logger.error(f"convert_to_jpg produced invalid file: {dst.name}")
        dst.unlink(missing_ok=True)
        raise
    if dst != src:
        src.unlink(missing_ok=True)
    return dst


def compress_image(path: Path, max_bytes: int = BILIBILI_IMAGE_MAX_SIZE) -> Path:
    size = path.stat().st_size
    if size <= max_bytes:
        return path

    img = Image.open(path)
    quality = 95
    buf = io.BytesIO()
    while quality > 50:
        buf.seek(0)
        buf.truncate()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            break
        quality -= 5

    path.write_bytes(buf.getvalue())
    logger.debug(f"Compressed {path.name} to {path.stat().st_size // 1024}KB (quality={quality})")
    return path


def add_watermark(image_path: Path, text: str = "pixiv.to.bilibili") -> Path:
    from PIL import ImageDraw, ImageFont

    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    position = (img.width - w - 10, img.height - h - 10)
    draw.text(position, text, fill=(255, 255, 255, 180), font=font)
    img.save(image_path, "JPEG", quality=95)
    return image_path
