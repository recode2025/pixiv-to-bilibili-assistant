@echo off
cd /d D:\pixiv-to-bilibili
call conda activate pixiv-bot
python scheduler.py
pause
