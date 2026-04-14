from dataclasses import dataclass, field
from pathlib import Path

from pixivpy3 import AppPixivAPI
from loguru import logger

from config.settings import settings


@dataclass
class PixivArtwork:
    artwork_id: int
    title: str
    author: str
    tags: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    is_r18: bool = False


class PixivClient:
    def __init__(self) -> None:
        self._api = AppPixivAPI()
        self._authenticated = False

        # 只给 pixivpy3 的 requests session 设代理，不污染全局环境变量
        if settings.proxy:
            self._api.requests.proxies = {
                "http": settings.proxy,
                "https": settings.proxy,
            }
            logger.info(f"Pixiv proxy set: {settings.proxy}")

    def authenticate(self, refresh_token: str | None = None) -> None:
        token = refresh_token or settings.pixiv_refresh_token
        if not token:
            raise ValueError(
                "Pixiv refresh token is empty. "
                "Set PIXIV_REFRESH_TOKEN in .env or pass it as argument."
            )
        try:
            self._api.auth(refresh_token=token)
            self._authenticated = True
            logger.info("Pixiv authenticated successfully")
        except Exception as e:
            logger.error(f"Pixiv authentication failed: {e}")
            raise

    def _ensure_auth(self) -> None:
        if not self._authenticated:
            raise RuntimeError("Pixiv client not authenticated. Call authenticate() first.")

    def get_ranking(
        self,
        mode: str = "day",
        offset: int = 0,
        limit: int = 30,
    ) -> list[PixivArtwork]:
        """获取排行榜作品。mode: day/week/month"""
        self._ensure_auth()
        result = self._api.illust_ranking(mode=mode, offset=offset)
        if not result or "illusts" not in result:
            logger.warning("No ranking results returned")
            return []

        artworks = []
        for illust in result["illusts"][:limit]:
            artwork = self._parse_illust(illust)
            if artwork:
                artworks.append(artwork)
        logger.info(f"Fetched {len(artworks)} artworks from {mode} ranking")
        return artworks

    def search_by_tag(
        self,
        keyword: str,
        offset: int = 0,
        limit: int = 30,
        sort: str = "date_desc",
    ) -> list[PixivArtwork]:
        """按标签搜索插画。sort: date_desc / popular_desc"""
        self._ensure_auth()
        result = self._api.search_illust(keyword, offset=offset, sort=sort)
        if not result or "illusts" not in result:
            logger.warning(f"No search results for tag: {keyword}")
            return []

        artworks = []
        for illust in result["illusts"][:limit]:
            artwork = self._parse_illust(illust)
            if artwork:
                artworks.append(artwork)
        logger.info(f"Found {len(artworks)} artworks for tag '{keyword}' (sort={sort})")
        return artworks

    # 漫画/漫画条相关标签，用于过滤
    _MANGA_TAGS = frozenset({
        "漫画", "4コマ", "4koma", "manga", "マンガ",
        "エロ漫画", "おっぱい漫画", "4コマ漫画",
    })

    def _parse_illust(self, illust: dict) -> PixivArtwork | None:
        if not illust:
            return None

        artwork_id = illust.get("id", 0)
        title = illust.get("title", "Untitled")
        author = illust.get("user", {}).get("name", "Unknown")
        tags = [t.get("name", "") for t in illust.get("tags", []) if t.get("name")]
        is_r18 = any(t.lower() in ("r-18", "r-18g") for t in tags)

        # 过滤漫画类型作品
        if any(t.lower() in self._MANGA_TAGS for t in tags):
            logger.debug(f"Skipping manga: {title} ({artwork_id})")
            return None

        # 过滤多格条漫（页数过多的多图作品大概率是漫画）
        page_count = len(illust.get("meta_pages", []))
        if page_count > 8:
            logger.debug(f"Skipping long manga ({page_count} pages): {title} ({artwork_id})")
            return None

        image_urls = []
        # 多图作品
        if illust.get("meta_pages"):
            for page in illust["meta_pages"]:
                url = page.get("image_urls", {}).get("original")
                if url:
                    image_urls.append(url)
        # 单图
        elif illust.get("meta_single_page", {}).get("original_image_url"):
            image_urls.append(illust["meta_single_page"]["original_image_url"])

        return PixivArtwork(
            artwork_id=artwork_id,
            title=title,
            author=author,
            tags=tags,
            image_urls=image_urls,
            is_r18=is_r18,
        )

    def fetch_artworks(self) -> list[PixivArtwork]:
        """优先从榜单中筛选热门 IP 作品，不够再用标签搜索补充，合并去重返回。

        策略：
        1) 取日榜 + 周榜，从中筛选带 IP 标签的作品（这些是最热门的）
        2) 对每个 IP 标签按人气搜索补充
        3) 以上都不够时，取完整榜单兜底
        """
        seen_ids: set[int] = set()
        all_artworks: list[PixivArtwork] = []
        ip_tags = {t.strip() for t in settings.pixiv_hot_tags.split(",") if t.strip()}
        needed = settings.daily_image_dynamics + settings.daily_video_dynamics
        per_tag_limit = settings.pixiv_tag_search_limit

        # ---- 第1步：从榜单中筛选 IP 作品（最优先） ----
        for mode in ("day", "week"):
            ranking = self.get_ranking(mode=mode, limit=50)
            for artwork in ranking:
                if artwork.artwork_id in seen_ids:
                    continue
                # 检查是否命中任一 IP 标签
                if ip_tags & set(artwork.tags):
                    seen_ids.add(artwork.artwork_id)
                    all_artworks.append(artwork)
            logger.info(f"After {mode} ranking filter: {len(all_artworks)} IP artworks")

        # ---- 第2步：不够的话，按每个 IP 标签按人气搜索 ----
        if len(all_artworks) < needed:
            logger.info(f"Ranking gave {len(all_artworks)} works, searching by IP tags (popular)...")
            for tag in ip_tags:
                results = self.search_by_tag(tag, limit=per_tag_limit, sort="popular_desc")
                for artwork in results:
                    if artwork.artwork_id not in seen_ids:
                        seen_ids.add(artwork.artwork_id)
                        all_artworks.append(artwork)
                logger.info(f"  Tag '{tag}': total = {len(all_artworks)}")

        # ---- 第3步：还不够的话，用完整榜单兜底（不限 IP） ----
        if len(all_artworks) < needed:
            logger.info(f"Still only {len(all_artworks)} works, supplementing from full ranking...")
            for mode in ("day", "week"):
                ranking = self.get_ranking(mode=mode, limit=50)
                for artwork in ranking:
                    if artwork.artwork_id not in seen_ids:
                        seen_ids.add(artwork.artwork_id)
                        all_artworks.append(artwork)

        logger.info(f"Total unique artworks fetched: {len(all_artworks)}")
        return all_artworks
