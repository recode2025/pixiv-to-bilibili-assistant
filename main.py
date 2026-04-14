import asyncio
import random
import time
from pathlib import Path

from loguru import logger

from config.settings import settings
from core.bilibili_client import BilibiliClient
from core.pixiv_client import PixivClient
from core.safety_checker import filter_safe_with_results
from core.content_checker import check_and_generate
from core.bgm_provider import fetch_bgm
from core.video_generator import generate_video
from utils.image_utils import compress_image, convert_to_jpg, download_image
from utils.logger import setup_logger

# 结尾互动话术（AI 生成文案时备用补充）
_CLOSERS = [
    "关注不迷路，每天更新~",
    "觉得好看记得收藏~",
    "想看什么角色评论区告诉我~",
    "双击屏幕有惊喜~",
    "持续更新中，点个关注吧~",
]


def build_dynamic_text(
    ai_copy: str | None,
    artwork,
    *,
    is_video: bool = False,
) -> str:
    """拼接最终动态文案。AI 文案 + 来源信息 + 标签"""
    lines: list[str] = []

    # AI 生成的主体文案
    if ai_copy:
        lines.append(ai_copy)
    else:
        # fallback
        lines.append(f"「{artwork.title}」by {artwork.author}")
        if is_video:
            lines.append("建议全屏观看，细节很多~")

    lines.append("")

    # 标签
    tag_str = " ".join("#" + t.replace(" ", "_") for t in artwork.tags[:5])
    if tag_str:
        lines.append(tag_str)

    # 来源
    lines.append("")
    lines.append(f"转载自 P站 ID: {artwork.artwork_id}")
    lines.append(f"画师：{artwork.author}")

    # 结尾互动（如果 AI 文案里没有互动引导就补一条）
    if ai_copy and any(kw in ai_copy for kw in ("关注", "收藏", "评论", "点赞", "扣")):
        pass  # AI 已经加了互动引导
    else:
        lines.append("")
        lines.append(random.choice(_CLOSERS))

    return "\n".join(lines)


def load_published_ids() -> set[int]:
    path = settings.published_ids_file
    if path.exists():
        return {
            int(line.strip())
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().isdigit()
        }
    return set()


def save_published_id(artwork_id: int) -> None:
    path = settings.published_ids_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{artwork_id}\n")


def _download_and_process(artwork) -> list[Path]:
    """下载作品的所有图片并处理（转换、压缩），返回本地路径列表"""
    downloaded: list[Path] = []
    for i, url in enumerate(artwork.image_urls):
        ext = ".jpg" if ".jpg" in url else ".png"
        save_path = settings.image_dir / f"{artwork.artwork_id}_{i}{ext}"
        result = download_image(url, save_path)
        if not result:
            continue
        try:
            if result.suffix != ".jpg":
                result = convert_to_jpg(result)
            result = compress_image(result)
            downloaded.append(result)
        except Exception as e:
            logger.warning(f"Failed to process image {save_path.name}: {e}")
    return downloaded


async def _publish_image_dynamic(
    bilibili: BilibiliClient,
    artwork,
    safe_images: list[Path],
    ai_copy: str | None,
) -> bool:
    """发布一条图文动态"""
    text = build_dynamic_text(ai_copy, artwork, is_video=False)
    await bilibili.publish_image_dynamic(safe_images, text=text)
    return True


async def _publish_video_dynamic(
    bilibili: BilibiliClient,
    artwork,
    safe_images: list[Path],
    ai_copy: str | None,
    ai_title: str | None = None,
    bgm_path: Path | None = None,
) -> bool:
    """发布一条视频动态：一张图 + 10秒动态效果 + 游戏OST"""
    text = build_dynamic_text(ai_copy, artwork, is_video=True)
    title = ai_title or artwork.title
    cover = safe_images[0] if safe_images else None
    video_path = generate_video([cover], bgm_path=bgm_path)
    await bilibili.publish_video_dynamic(
        video_path,
        text=text,
        title=title,
        source_url=f"https://www.pixiv.net/artworks/{artwork.artwork_id}",
        author=artwork.author,
        cover_path=cover,
    )
    return True


async def run() -> None:
    setup_logger()
    logger.info("=== Pixiv to Bilibili Bot Started ===")

    # 1. Bilibili 登录
    bilibili = BilibiliClient()
    if not bilibili.load_credential():
        bilibili.login_qrcode()

    # 2. Pixiv 认证
    pixiv = PixivClient()
    pixiv.authenticate()

    # 3. 获取作品列表
    artworks = pixiv.fetch_artworks()
    if not artworks:
        logger.warning("No artworks found, exiting")
        return

    published = load_published_ids()
    logger.info(f"Already published {len(published)} artworks on record")

    # 4. 过滤：去已发布、去R18、去无图作品
    candidates = []
    for artwork in artworks:
        if artwork.artwork_id in published:
            logger.info(f"Skipping already published: {artwork.title} ({artwork.artwork_id})")
            continue
        if artwork.is_r18 and settings.nsfw_threshold < 0.9:
            logger.info(f"Skipping R-18 artwork: {artwork.title}")
            continue
        if not artwork.image_urls:
            logger.warning(f"No images for artwork: {artwork.title}")
            continue
        candidates.append(artwork)

    random.shuffle(candidates)
    logger.info(f"Candidate artworks after filtering: {len(candidates)}")

    # 5. 下载 + NSFW过滤 + 内容审核 + AI标题/文案 → 得到 ready_artworks
    #    (artwork, safe_images, ai_title, ai_copy)
    ready_artworks: list[tuple] = []
    for artwork in candidates:
        if len(ready_artworks) >= settings.daily_image_dynamics + settings.daily_video_dynamics:
            break

        downloaded = _download_and_process(artwork)
        if not downloaded:
            logger.warning(f"All downloads failed for: {artwork.title}")
            continue

        safe_images, safety_results = filter_safe_with_results(downloaded)
        if not safe_images:
            logger.info(f"All images rejected by NSFW check: {artwork.title}")
            continue

        safe_images = safe_images[: settings.images_per_dynamic]

        # 一次 API：审核 + 生成标题 + 文案
        result = check_and_generate(safe_images[0])
        if not result["pass"]:
            logger.info(
                f"Rejected by content check: {artwork.title} - {result['reason']}"
            )
            continue
        ai_title = result.get("title")
        ai_copy = result["copy"]

        ready_artworks.append((artwork, safe_images, ai_title, ai_copy))

    logger.info(
        f"Ready to publish: {len(ready_artworks)} artworks "
        f"(target: {settings.daily_image_dynamics} image + {settings.daily_video_dynamics} video)"
    )

    # 6. 分配：前 N 条图文，后 M 条视频
    n_image = min(settings.daily_image_dynamics, len(ready_artworks))
    n_video = min(settings.daily_video_dynamics, len(ready_artworks) - n_image)

    image_batch = ready_artworks[:n_image]
    video_batch = ready_artworks[n_image : n_image + n_video]

    total_published = 0

    # 7. 发布图文动态
    for i, (artwork, safe_images, ai_title, ai_copy) in enumerate(image_batch):
        logger.info(f"[Image {i+1}/{n_image}] Publishing: {artwork.title} ({artwork.artwork_id})")
        try:
            await _publish_image_dynamic(bilibili, artwork, safe_images, ai_copy)
            save_published_id(artwork.artwork_id)
            total_published += 1
            logger.info(f"[Image {i+1}/{n_image}] Published successfully")
        except Exception as e:
            logger.error(f"[Image {i+1}/{n_image}] Failed: {e}")

        if i < n_image - 1 or n_video > 0:
            delay = settings.publish_delay_min
            logger.info(f"Sleeping {delay}s before next publish...")
            time.sleep(delay)

    # 8. 发布视频动态（先获取 BGM）
    bgm_path = None
    if n_video > 0:
        logger.info("Fetching BGM for video dynamics...")
        bgm_path = await fetch_bgm()

    for i, (artwork, safe_images, ai_title, ai_copy) in enumerate(video_batch):
        logger.info(f"[Video {i+1}/{n_video}] Publishing: {artwork.title} ({artwork.artwork_id})")
        try:
            await _publish_video_dynamic(bilibili, artwork, safe_images, ai_copy, ai_title, bgm_path)
            save_published_id(artwork.artwork_id)
            total_published += 1
            logger.info(f"[Video {i+1}/{n_video}] Published successfully")
        except Exception as e:
            logger.error(f"[Video {i+1}/{n_video}] Failed: {e}")

        if i < n_video - 1:
            delay = settings.publish_delay_min
            logger.info(f"Sleeping {delay}s before next publish...")
            time.sleep(delay)

    logger.info(f"=== Bot Finished: published {total_published} dynamics ===")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
