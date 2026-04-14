from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from config.settings import settings
from utils.logger import setup_logger


def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler()

    # 避免循环导入，在任务函数内 import
    def job() -> None:
        import asyncio
        from main import run
        asyncio.run(run())

    scheduler.add_job(
        job,
        "cron",
        hour=settings.schedule_cron_hour,
        minute=settings.schedule_cron_minute,
        id="pixiv_to_bilibili",
        max_instances=1,
        misfire_grace_time=300,
    )

    logger.info(
        f"Scheduler configured: daily at {settings.schedule_cron_hour:02d}:{settings.schedule_cron_minute:02d}"
    )
    return scheduler


def main() -> None:
    setup_logger()
    logger.info("Starting scheduler...")
    scheduler = create_scheduler()

    # 启动时立即执行一次
    logger.info("Running initial task...")
    import asyncio
    from main import run
    asyncio.run(run())

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
