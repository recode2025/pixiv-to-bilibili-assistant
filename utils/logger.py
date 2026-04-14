import sys

from loguru import logger

from config.settings import settings


def setup_logger() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    logger.add(
        str(settings.image_dir.parent / "bot.log"),
        rotation="10 MB",
        retention="7 days",
        level=settings.log_level,
        encoding="utf-8",
    )
