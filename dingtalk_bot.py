"""
dingtalk_bot.py
---------------
使用 dingtalk-stream SDK 监听钉钉消息。
收到消息后：
  - 存入共享队列，供 Flask Web 服务读取展示
  - 保存 sessionWebhook，用于后续主动回复
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

import requests

import dingtalk_stream
from dingtalk_stream import AckMessage

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("dingtalk_bot")

_message_store: deque = deque(maxlen=config.MAX_HISTORY)
_store_lock = threading.Lock()

_bot_loop: asyncio.AbstractEventLoop | None = None

_session_map: dict[str, dict] = {}
_session_lock = threading.Lock()

_id_counter = 0

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _download_dingtalk_file(download_code: str, file_extension: str) -> str | None:
    url = f"https://oapi.dingtalk.com/media/download?access_token=&media_id={download_code}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and resp.content:
            filename = f"{download_code[:16]}.{file_extension}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return f"/static/uploads/{filename}"
    except Exception as e:
        logger.error("下载文件失败: %s", e)
    return None


def _push_message(msg: dict):
    with _store_lock:
        _message_store.append(msg)


def get_messages(since_id: int = 0) -> list[dict]:
    with _store_lock:
        return [m for m in _message_store if m["id"] > since_id]


# ── 直接用 requests POST sessionWebhook（绕过 handler 实例问题） ──────────

def _reply_via_webhook(session_key: str, text: str) -> bool:
    with _session_lock:
        session = _session_map.get(session_key)
    if not session:
        logger.warning("找不到会话: %s", session_key)
        return False

    webhook = session.get("webhook")
    sender_staff_id = session.get("sender_staff_id")

    if not webhook:
        logger.warning("webhook 为空，无法回复: %s", session_key)
        return False

    payload = {
        "msgtype": "text",
        "text": {"content": text},
    }
    if sender_staff_id:
        payload["at"] = {"atUserIds": [sender_staff_id]}

    headers = {"Content-Type": "application/json", "Accept": "*/*"}
    try:
        resp = requests.post(webhook, headers=headers, data=json.dumps(payload), timeout=10)
        resp.raise_for_status()
        logger.info("回复成功 → %s: %s", session_key, text)
        return True
    except Exception as e:
        logger.error("回复失败: %s", e)
        return False


def reply_to_session(session_key: str, text: str) -> bool:
    """从 Flask 线程调用，向指定会话回复"""
    return _reply_via_webhook(session_key, text)


# ── 消息处理器 ───────────────────────────────────────────────────────────────

class MyMessageHandler(dingtalk_stream.ChatbotHandler):
    """处理机器人消息回调"""

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        data = callback.data or {}

        incoming = dingtalk_stream.ChatbotMessage.from_dict(data)
        sender = incoming.sender_nick or incoming.sender_staff_id or "未知"
        session_key = incoming.sender_staff_id or sender
        conversation_type = incoming.conversation_type or "1"
        webhook = data.get("sessionWebhook") or incoming.session_webhook
        sender_staff_id = incoming.sender_staff_id
        msg_type = data.get("msgtype") or "text"

        with _session_lock:
            _session_map[session_key] = {
                "webhook": webhook,
                "sender_staff_id": sender_staff_id,
                "conversation_type": conversation_type,
            }

        msg_content = {"id": _next_id(), "ts": datetime.now().strftime("%H:%M:%S"),
                       "direction": "in", "sender": sender, "session_key": session_key,
                       "conversation_type": conversation_type, "msg_type": msg_type}

        if msg_type == "text":
            text = incoming.text.content.strip() if incoming.text else ""
            msg_content["text"] = text
            logger.info("收到文本 | 发送人: %s | 内容: %s", sender, text)

        elif msg_type == "picture":
            download_code = ""
            if incoming.text:
                try:
                    download_code = incoming.text.get("downloadCode", "")
                except (AttributeError, KeyError):
                    download_code = ""
            if not download_code:
                download_code = data.get("content", {}).get("downloadCode", "") if isinstance(data.get("content"), dict) else ""
            if download_code:
                file_url = _download_dingtalk_file(download_code, "jpg")
                msg_content["text"] = "[图片]"
                msg_content["file_url"] = file_url
                logger.info("收到图片 | 发送人: %s | downloadCode: %s", sender, download_code[:20])
            else:
                msg_content["text"] = "[图片]"

        elif msg_type == "audio":
            download_code = ""
            duration = 0
            if incoming.text:
                try:
                    download_code = incoming.text.get("downloadCode", "")
                    duration = incoming.text.get("duration", 0)
                except (AttributeError, KeyError):
                    download_code = ""
            if not download_code:
                content = data.get("content", {}) if isinstance(data.get("content"), dict) else {}
                download_code = content.get("downloadCode", "")
                duration = content.get("duration", 0)
            if download_code:
                file_url = _download_dingtalk_file(download_code, "amr")
                msg_content["text"] = f"[语音 {duration}秒]"
                msg_content["file_url"] = file_url
                msg_content["duration"] = duration
                logger.info("收到语音 | 发送人: %s | duration: %s", sender, duration)
            else:
                msg_content["text"] = "[语音]"

        elif msg_type == "file":
            download_code = ""
            if incoming.text:
                try:
                    download_code = incoming.text.get("downloadCode", "")
                except (AttributeError, KeyError):
                    download_code = ""
            if not download_code:
                download_code = data.get("content", {}).get("downloadCode", "") if isinstance(data.get("content"), dict) else ""
            if download_code:
                file_url = _download_dingtalk_file(download_code, "file")
                msg_content["text"] = "[文件]"
                msg_content["file_url"] = file_url
                logger.info("收到文件 | 发送人: %s | downloadCode: %s", sender, download_code[:20])
            else:
                msg_content["text"] = "[文件]"
        else:
            text = incoming.text.content.strip() if incoming.text else ""
            msg_content["text"] = text or f"[未知类型: {msg_type}]"
            logger.info("收到未知类型消息 | 发送人: %s | 类型: %s", sender, msg_type)

        _push_message(msg_content)
        return AckMessage.STATUS_OK, "OK"


# ── 启动 Bot（子线程） ──────────────────────────────────────────────────────

def _run_bot():
    global _bot_loop
    _bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_bot_loop)

    credential = dingtalk_stream.Credential(config.APP_KEY, config.APP_SECRET)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        MyMessageHandler(),
    )

    logger.info("DingTalk Stream Bot 启动中…")
    _bot_loop.run_until_complete(client.start_forever())


def start_bot_thread():
    t = threading.Thread(target=_run_bot, name="dingtalk-bot", daemon=True)
    t.start()
    logger.info("Bot 线程已启动")
    return t


# ── 直接运行 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    start_bot_thread()
    print("Bot 后台运行中，按 Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("退出")
