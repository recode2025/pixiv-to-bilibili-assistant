import base64
import json
from pathlib import Path

import requests
from loguru import logger

from config.settings import settings

_DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def _encode_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Failed to parse as JSON: {text[:200]}")
        return None


# ----------------------------------------------------------------
# 合并调用：审核 + 文案生成，一次 API 搞定
# ----------------------------------------------------------------

_COMBINED_PROMPT = """你是一个资深二次元画师 + B站动态博主，负责审核插画质量并写发布文案。

请仔细检查这张动漫插画，完成两个任务：

【任务1：画工审核】
你需要像专业画师一样逐项检查，只有画工扎实、没有硬伤的图才能通过。

必须逐项检查（任何一项不达标就判定为不通过）：
- 整体画工：线条是否流畅干净，色彩是否协调，不是粗糙草稿或低质量AI图
- 面部：五官比例是否正常，眼睛是否有神，不是崩脸或空洞眼神
- 手部：手指数量是否正确（5根），姿态是否自然，不是扭曲畸形
- 胸部：形状是否自然合理，不是违反物理的夸张球形或明显画崩
- 身体比例：头身比、肩宽、腰臀比例是否在正常动漫夸张范围内
- 四肢关节：肘部、膝盖、脚踝等关节是否正常，没有反关节或断裂感

以下情况算正常，不应判为问题：
- 百合、福瑞、同性恋、CP互动等主题内容
- 正常的动漫风格夸张（大眼睛、长发等）
- 适度性感的穿着和姿势（只要人体结构画得对）

判定标准：宁可漏掉一张好图，也不要放过画崩的图。只有你确信画工达标才通过。

【任务2：写标题 + 文案】
标题要求：
- 5-15个字，超短，一秒抓住眼球
- 要精准踩中二次元玩家的XP：老婆/老公/惨/涩/萌/帅/绝了等
- 像朋友群里看到好图随手转发的那句话
- 标题里不要加引号、书名号、标点符号
- 好的例子：「这个芙宁娜也太绝了」「今天也是被老婆帅醒的一天」「这图我能盯一整年」「帅到合不拢嘴」
- 差的例子：「Pixiv精选插画分享」（太无聊）

文案要求：
- 撩人暗示、勾起好奇心，让人想点进来看
- 可以适当"开车"但不违规、不低俗
- 根据图片内容自然发挥：男角色用"帅/老公/颜值"角度，女角色用"美/老婆/心动"角度，CP用嗑糖角度
- 百合、福瑞、同性恋内容都正常描述
- 3-5句话，不要emoji
- 结尾加一句引导互动（关注/收藏/评论）
- 不要加标签或来源信息

请严格按以下 JSON 格式回复，不要添加其他文字：
{"pass": true, "reason": "", "title": "这里写短标题", "copy": "这里写文案内容"}
不通过时：{"pass": false, "reason": "手部畸形", "title": "", "copy": ""}
"""


def check_and_generate(image_path: Path) -> dict:
    """一次 API 调用完成审核 + 标题 + 文案生成。

    Returns:
        {"pass": bool, "reason": str, "title": str | None, "copy": str | None}
    """
    api_key = settings.dashscope_api_key
    if not api_key:
        logger.warning("DASHSCOPE_API_KEY not set, skipping content check & copy generation")
        return {"pass": True, "reason": "no_api_key", "title": None, "copy": None}

    image_b64 = _encode_image(image_path)
    payload = {
        "model": settings.qwen_vl_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _COMBINED_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            }
        ],
        "temperature": 0.7,
        "max_tokens": 400,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            _DASHSCOPE_URL,
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"DashScope API call failed for {image_path.name}: {e}")
        return {"pass": True, "reason": f"api_error: {e}", "title": None, "copy": None}

    result = _parse_json(text)
    if result is None:
        return {"pass": True, "reason": "parse_error", "title": None, "copy": None}

    passed = result.get("pass", True)
    reason = result.get("reason", "")
    title = result.get("title", "")
    if title:
        title = title.strip().strip('"').strip("'")
    copy = result.get("copy")
    if copy:
        copy = copy.strip().strip('"').strip("'")

    status = "PASS" if passed else "REJECT"
    logger.info(f"[CheckAndGen] {image_path.name}: {status}, title={title}, copy={bool(copy)}")
    return {"pass": passed, "reason": reason, "title": title, "copy": copy}
