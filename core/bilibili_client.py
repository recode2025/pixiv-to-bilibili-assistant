import asyncio
import json
import os
import ssl
from pathlib import Path

from bilibili_api import Credential, Picture, comment, dynamic
from bilibili_api import login
from loguru import logger

from config.settings import settings


def _kill_proxy():
    """彻底杀掉所有代理设置：环境变量 + Windows 系统代理 + aiohttp trust_env"""
    # 1. 清环境变量
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    # 2. NO_PROXY 通配符，阻止任何库走代理
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    # 3. 猴子补丁 aiohttp，禁用 trust_env（不再读 Windows 注册表代理）
    try:
        import aiohttp
        _orig_init = aiohttp.ClientSession.__init__

        def _patched_init(self, *args, **kwargs):
            kwargs.setdefault("trust_env", False)
            _orig_init(self, *args, **kwargs)

        aiohttp.ClientSession.__init__ = _patched_init
    except Exception:
        pass


class BilibiliClient:
    def __init__(self) -> None:
        self._credential: Credential | None = None
        _kill_proxy()
        self._cred_path = Path(settings.bilibili_credential_path)

    def login_qrcode(self) -> None:
        """扫码登录（终端显示二维码）"""
        logger.info("Starting Bilibili QR code login...")
        credential = login.login_with_qrcode_term()
        if not credential:
            raise RuntimeError("QR code login failed")

        self._credential = credential
        self._save_credential()
        logger.info("Bilibili login successful!")

    def load_credential(self) -> bool:
        """从本地加载已保存的凭据"""
        if not self._cred_path.exists():
            return False

        try:
            data = json.loads(self._cred_path.read_text(encoding="utf-8"))
            self._credential = Credential(
                sessdata=data.get("sessdata", ""),
                bili_jct=data.get("bili_jct", ""),
                buvid3=data.get("buvid3", ""),
                dedeuserid=data.get("dedeuserid", ""),
            )
            logger.info("Loaded saved Bilibili credential")
            return True
        except Exception as e:
            logger.warning(f"Failed to load credential: {e}")
            return False

    def _save_credential(self) -> None:
        if not self._credential:
            return
        self._cred_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sessdata": self._credential.sessdata,
            "bili_jct": self._credential.bili_jct,
            "buvid3": self._credential.buvid3,
            "dedeuserid": self._credential.dedeuserid,
        }
        self._cred_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug(f"Credential saved to {self._cred_path}")

    def _ensure_credential(self) -> Credential:
        if not self._credential:
            raise RuntimeError("Bilibili not logged in. Call login_qrcode() or load_credential() first.")
        return self._credential

    async def publish_image_dynamic(
        self,
        image_paths: list[Path],
        text: str = "",
    ) -> int | None:
        """发布图文动态，最多9张图，带重试和超时处理"""
        credential = self._ensure_credential()
        if len(image_paths) > 9:
            logger.warning(f"Too many images ({len(image_paths)}), truncating to 9")
            image_paths = image_paths[:9]

        # 加载图片为 Picture 对象
        pictures: list[Picture] = []
        for path in image_paths:
            try:
                pic = Picture.from_file(str(path))
                pictures.append(pic)
                logger.debug(f"Loaded image: {path.name}")
            except Exception as e:
                logger.error(f"Failed to load image {path.name}: {e}")

        if not pictures:
            logger.error("No images loaded, aborting dynamic publish")
            return None

        # 构建动态
        dyn_builder = dynamic.BuildDynamic()
        if text:
            dyn_builder.add_text(text)
        for pic in pictures:
            dyn_builder.add_image(pic)

        _kill_proxy()
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                # 给 aiohttp 足够的上传时间（5分钟）
                resp = await asyncio.wait_for(
                    dynamic.send_dynamic(
                        info=dyn_builder,
                        credential=credential,
                    ),
                    timeout=300,
                )
                dyn_id = resp.get("data", {}).get("dynamic_id", "unknown")
                logger.info(f"Published image dynamic: id={dyn_id}")
                return dyn_id
            except asyncio.TimeoutError:
                logger.warning(f"Publish attempt {attempt}/{max_retries} timed out")
                if attempt < max_retries:
                    logger.info("Retrying in 10s...")
                    await asyncio.sleep(10)
            except Exception as e:
                import traceback
                logger.error(f"Publish attempt {attempt}/{max_retries} failed: {e}\n{traceback.format_exc()}")
                if attempt < max_retries:
                    logger.info("Retrying in 10s...")
                    await asyncio.sleep(10)

        logger.error("All publish attempts failed")
        return None

    async def publish_video_dynamic(
        self,
        video_path: Path,
        text: str = "",
        title: str = "Pixiv精选",
        source_url: str = "",
        author: str = "",
        cover_path: Path | None = None,
    ) -> int | None:
        """发布视频动态（转载），返回 dynamic_id"""
        credential = self._ensure_credential()

        from bilibili_api import video_uploader

        page = video_uploader.VideoUploaderPage(
            path=str(video_path),
            title=title,
            description=text,
        )

        # 封面：用 Picture 对象上传
        cover = ""
        if cover_path and cover_path.exists():
            try:
                cover = Picture.from_file(str(cover_path))
            except Exception as e:
                logger.warning(f"Failed to load cover image: {e}")

        uploader = video_uploader.VideoUploader(
            pages=[page],
            meta=video_uploader.VideoMeta(
                title=title,
                desc=text,
                tid=122,
                cover=cover,
                tags=["pixiv", "二次元", "美图", "转载"],
                original=False,
                source=source_url or "pixiv.net",
            ),
            credential=credential,
            line=video_uploader.Lines.QN,
        )

        max_retries = 3
        _kill_proxy()
        for attempt in range(1, max_retries + 1):
            try:
                result = await asyncio.wait_for(uploader.start(), timeout=600)
                logger.info(f"Video uploaded: {result}")
                aid = None
                if isinstance(result, dict):
                    aid = result.get("aid") or result.get("bvid")
                if aid:
                    dyn_id = await self._find_dynamic_by_aid(aid)
                    if dyn_id:
                        return dyn_id
                return None
            except (asyncio.TimeoutError, ssl.SSLError, ConnectionError) as e:
                logger.warning(f"Video upload attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    wait = 15 * attempt
                    logger.info(f"Retrying in {wait}s...")
                    await asyncio.sleep(wait)
            except Exception as e:
                logger.error(f"Failed to upload video: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(10)

        logger.error("All video upload attempts failed")
        return None

    async def _find_dynamic_by_aid(self, aid) -> int | None:
        """通过 aid/bvid 查找对应的动态 ID"""
        import httpx

        try:
            credential = self._ensure_credential()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                    params={"offset": ""},
                    cookies={"SESSDATA": credential.sessdata},
                )
                data = resp.json()
                items = data.get("data", {}).get("items", [])
                for item in items[:5]:
                    card_type = item.get("desc", {}).get("type", 0)
                    if card_type == 2:
                        rid = item.get("desc", {}).get("rid")
                        dyn_id = item.get("desc", {}).get("dynamic_id")
                        if rid == aid or str(rid) == str(aid):
                            logger.info(f"Found dynamic_id={dyn_id} for aid={aid}")
                            return int(dyn_id)
        except Exception as e:
            logger.warning(f"Failed to find dynamic by aid: {e}")
        return None

    async def get_dynamic_info(self, dynamic_id: int) -> dict | None:
        """获取动态详情"""
        try:
            info = await dynamic.get_dynamic_info(
                dynamic_id=dynamic_id,
                credential=self._ensure_credential(),
            )
            return info.get("data", {}) if info else None
        except Exception as e:
            logger.error(f"Failed to get dynamic info: {e}")
            return None

    def _resolve_comment_oid(self, dyn_info: dict, dynamic_id: int) -> tuple[int, comment.CommentResourceType]:
        card_type = dyn_info.get("card_type", 0) or dyn_info.get("desc", {}).get("type", 0)
        if card_type == 2:
            rid = dyn_info.get("desc", {}).get("rid", dynamic_id)
            return int(rid), comment.CommentResourceType.DYNAMIC_DRAW
        else:
            return int(dynamic_id), comment.CommentResourceType.DYNAMIC

    async def comment_with_images(
        self,
        dynamic_id: int,
        image_paths: list[Path],
        text: str = "原图在这里~",
    ) -> dict | None:
        """在动态评论区发带图的评论"""
        credential = self._ensure_credential()

        dyn_info = await self.get_dynamic_info(dynamic_id)
        if not dyn_info:
            logger.error("Cannot get dynamic info for comment")
            return None

        oid, resource_type = self._resolve_comment_oid(dyn_info, dynamic_id)
        logger.info(f"Commenting on oid={oid}, type={resource_type.name}")

        pictures: list[Picture] = []
        for path in image_paths:
            try:
                pic = Picture.from_file(str(path))
                pictures.append(pic)
            except Exception as e:
                logger.warning(f"Failed to load image for comment: {path.name}: {e}")

        if not pictures:
            logger.warning("No pictures loaded for comment, sending text only")

        try:
            result = await comment.send_comment(
                text=text,
                oid=oid,
                type_=resource_type,
                credential=credential,
                pic=pictures if pictures else None,
            )
            logger.info(f"Comment posted with {len(pictures)} image(s)")
            return result
        except Exception as e:
            logger.error(f"Failed to post comment: {e}")
            return None
