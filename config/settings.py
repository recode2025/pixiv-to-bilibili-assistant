from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / "config" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Proxy
    proxy: str = ""  # e.g. http://127.0.0.1:7890 or socks5://127.0.0.1:1080

    # Pixiv
    pixiv_refresh_token: str = ""
    pixiv_hot_tags: str = "原神,崩壊：スターレイル,終末地,ゼンレスゾーンゼロ,鳴潮"
    pixiv_tag_search_limit: int = 10  # 每个标签搜索数量
    pixiv_max_images: int = 9

    # NSFW
    nsfw_threshold: float = 0.7

    # Content check (阿里云 DashScope)
    dashscope_api_key: str = ""
    qwen_vl_model: str = "qwen-vl-plus"

    # Video
    video_resolution_width: int = 1080
    video_resolution_height: int = 1920
    video_fps: int = 30
    video_image_duration: float = 5.0
    video_transition_duration: float = 1.0

    # Bilibili
    bilibili_credential_path: str = str(BASE_DIR / "storage" / "bilibili_credential.json")

    # Scheduler
    schedule_cron_hour: int = 9
    schedule_cron_minute: int = 0

    # Batch publish
    daily_image_dynamics: int = 8  # 每天图文动态数量
    daily_video_dynamics: int = 3  # 每天视频动态数量
    publish_delay_min: int = 60  # 两次发布间隔（秒）
    images_per_dynamic: int = 6  # 每条动态最多几张图

    # Logging
    log_level: str = "INFO"

    # Paths
    @property
    def image_dir(self) -> Path:
        return BASE_DIR / "storage" / "images"

    @property
    def video_dir(self) -> Path:
        return BASE_DIR / "storage" / "videos"

    @property
    def published_ids_file(self) -> Path:
        return BASE_DIR / "storage" / "published_ids.txt"


settings = Settings()
