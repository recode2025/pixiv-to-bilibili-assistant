"""从B站搜索热门二次元纯音乐，下载音频作为视频BGM。"""

import asyncio
import re
import random
from pathlib import Path

import requests
from loguru import logger

from config.settings import settings

_BGM_DIR = Path(__file__).resolve().parent.parent / "storage" / "bgm"

# 搜索关键词，每次随机挑一个（只用游戏厂商 OST）
_BGM_KEYWORDS = [
    "HOYO-MiX 原神 OST 纯音乐",
    "HOYO-MiX 崩坏星穹铁道 OST",
    "HOYO-MiX 绝区零 纯音乐 BGM",
    "塞壬唱片 明日方舟 OST 纯音乐",
    "塞壬唱片 Arknights BGM",
    "鸣潮 OST 纯音乐 BGM",
    "原神 纯音乐 背景音乐 钢琴曲",
    "崩坏星穹铁道 纯音乐 钢琴",
    "明日方舟 纯音乐 氛围感",
    "终末地 OST 纯音乐",
]


async def _get_credential():
    """加载B站凭据"""
    import json
    from bilibili_api import Credential

    cred_path = Path(settings.bilibili_credential_path)
    data = json.loads(cred_path.read_text(encoding="utf-8"))
    return Credential(
        sessdata=data.get("sessdata", ""),
        bili_jct=data.get("bili_jct", ""),
        buvid3=data.get("buvid3", ""),
        dedeuserid=data.get("dedeuserid", ""),
    )


async def _search_bgm_videos(page_size: int = 20) -> list[dict]:
    """搜索B站二次元纯音乐视频，返回结果列表"""
    from bilibili_api import search

    keyword = random.choice(_BGM_KEYWORDS)
    result = await search.search_by_type(
        keyword=keyword,
        search_type=search.SearchObjectType.VIDEO,
        order_type=search.OrderVideo.TOTALRANK,
        page=1,
        page_size=page_size,
    )
    videos = result.get("result", [])
    # 过滤：时长 1-10 分钟（太长的不要），排除直播回放
    filtered = []
    for v in videos:
        dur = v.get("duration", 0)
        # duration 格式 "mm:ss" 或 秒数
        if isinstance(dur, str):
            parts = dur.split(":")
            try:
                dur = int(parts[0]) * 60 + int(parts[1])
            except (ValueError, IndexError):
                continue
        if 60 <= dur <= 600:  # 1-10分钟
            filtered.append(v)
    logger.info(f"BGM search '{keyword}': {len(filtered)} suitable videos (from {len(videos)} total)")
    return filtered


async def _get_audio_url(bvid: str) -> str | None:
    """从视频获取音频下载 URL"""
    from bilibili_api import video

    cred = await _get_credential()
    v = video.Video(bvid=bvid, credential=cred)

    try:
        urls = await v.get_download_url(0)
    except Exception as e:
        logger.warning(f"Failed to get download URL for {bvid}: {e}")
        return None

    dash = urls.get("dash", {})
    audio_list = dash.get("audio", [])
    if not audio_list:
        logger.warning(f"No audio stream for {bvid}")
        return None

    # 选第一个音频流
    return audio_list[0].get("baseUrl") or audio_list[0].get("base_url")


def _download_audio(url: str, save_path: Path) -> bool:
    """下载音频文件"""
    headers = {
        "Referer": "https://www.bilibili.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    # 从 settings 加 cookie
    import json

    cred_path = Path(settings.bilibili_credential_path)
    if cred_path.exists():
        data = json.loads(cred_path.read_text(encoding="utf-8"))
        cookies = {"SESSDATA": data.get("sessdata", "")}
    else:
        cookies = {}

    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=30, stream=True)
        resp.raise_for_status()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = save_path.stat().st_size / 1024 / 1024
        logger.info(f"Downloaded BGM: {save_path.name} ({size_mb:.1f}MB)")
        return True
    except Exception as e:
        logger.warning(f"Failed to download BGM: {e}")
        save_path.unlink(missing_ok=True)
        return False


def _extract_audio_from_mp4(mp4_path: Path, output_path: Path) -> bool:
    """用 ffmpeg 从 mp4 提取音频为 mp3"""
    import subprocess

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(mp4_path),
                "-vn", "-acodec", "libmp3lame", "-q:a", "4",
                str(output_path),
            ],
            capture_output=True,
            timeout=60,
        )
        if output_path.exists() and output_path.stat().st_size > 0:
            return True
        logger.warning("ffmpeg output file missing or empty")
        return False
    except FileNotFoundError:
        logger.warning("ffmpeg not found, cannot extract audio")
        return False
    except Exception as e:
        logger.warning(f"ffmpeg failed: {e}")
        return False


async def fetch_bgm() -> Path | None:
    """从B站搜索并下载一首二次元纯音乐作为BGM。

    Returns: 音频文件路径（mp3），失败返回 None
    """
    _BGM_DIR.mkdir(parents=True, exist_ok=True)

    # 如果已有缓存的 BGM，随机返回一个
    existing = list(_BGM_DIR.glob("*.mp3"))
    if len(existing) >= 5:
        chosen = random.choice(existing)
        logger.info(f"Using cached BGM: {chosen.name}")
        return chosen

    # 搜索视频
    videos = await _search_bgm_videos()
    if not videos:
        logger.warning("No BGM videos found")
        return existing[0] if existing else None

    # 随机挑一个
    random.shuffle(videos)
    for v in videos:
        bvid = v.get("bvid", "")
        title = re.sub(r"<.*?>", "", v.get("title", "bgm"))
        # 文件名安全化
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:40]
        save_path = _BGM_DIR / f"{bvid}.mp4"
        mp3_path = _BGM_DIR / f"{safe_title}_{bvid}.mp3"

        if mp3_path.exists():
            logger.info(f"BGM already cached: {mp3_path.name}")
            return mp3_path

        # 获取音频 URL 并下载
        audio_url = await _get_audio_url(bvid)
        if not audio_url:
            continue

        if _download_audio(audio_url, save_path):
            # 从 mp4 提取 mp3
            if _extract_audio_from_mp4(save_path, mp3_path):
                save_path.unlink(missing_ok=True)
                return mp3_path
            # ffmpeg 不可用时直接用 mp4
            logger.info("Using mp4 as BGM directly (ffmpeg not available)")
            return save_path

    # 全部失败，用缓存的
    if existing:
        return random.choice(existing)
    return None
