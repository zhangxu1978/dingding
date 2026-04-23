"""
app.py
------
Flask Web 服务 — 提供对话监控页面和回复接口。
启动时同步拉起 dingtalk_bot 线程。
"""

import os
import re
from flask import Flask, jsonify, render_template, request

import config
import database
import threading
import time
import logging
import requests
from dingtalk_bot import get_messages, reply_to_session, start_bot_thread

logger = logging.getLogger("auto-reply")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")

database.init_db()


def _auto_reply_scan():
    """自动回复扫描线程"""
    while True:
        try:
            pending = database.get_pending_auto_reply()
            for session_key, messages in pending.items():
                # 合并文本
                texts = [m.get("text", "") for m in messages if m.get("text")]
                if not texts:
                    continue
                # 生成带消息ID的session_key
                message_ids = [m["id"] for m in messages]
                id_str = ",".join(map(str, message_ids))
                api_session_key = f"{session_key}-{id_str}"
                combined_text = "\n".join(texts)
                logger.info(f"待自动回复 [{api_session_key}]: {combined_text[:100]}...")
                # 调用自动回复 API
                try:
                    resp = requests.post(
                        config.AUTO_REPLY_API_URL,
                        json={"session_key": api_session_key, "message": combined_text},
                        timeout=30
                    )
                    if resp.status_code == 200:
                        logger.info(f"自动回复请求发送成功: {api_session_key}")
                    else:
                        logger.warning(f"自动回复请求失败 [{resp.status_code}]: {resp.text[:200]}")
                except Exception as e:
                    logger.error(f"调用自动回复API异常: {e}")
            time.sleep(config.AUTO_REPLY_SCAN_INTERVAL)
        except Exception as e:
            logger.error(f"自动回复扫描异常: {e}")
            time.sleep(5)


def start_auto_reply_thread():
    """启动自动回复扫描线程"""
    t = threading.Thread(target=_auto_reply_scan, name="auto-reply-scan", daemon=True)
    t.start()
    logger.info("自动回复扫描线程已启动")
    return t


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/messages")
def api_messages():
    """前端轮询接口：返回 id > since_id 的新消息"""
    since_id = int(request.args.get("since_id", 0))
    msgs = get_messages(since_id)
    return jsonify({"messages": msgs})


@app.route("/api/reply", methods=["POST"])
def api_reply():
    """前端发送回复"""
    data = request.get_json(force=True)
    session_key = data.get("session_key", "")
    text = data.get("text", "").strip()
    if not session_key or not text:
        return jsonify({"ok": False, "error": "参数缺失"}), 400

    ok = reply_to_session(session_key, text)
    return jsonify({"ok": ok})


@app.route("/api/config", methods=["GET"])
def api_get_config():
    public_config = {
        "AUTO_REPLY": config.AUTO_REPLY,
    }
    return jsonify(public_config)


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json(force=True)
    if "AUTO_REPLY" in data:
        config.AUTO_REPLY = bool(data["AUTO_REPLY"])
        config_path = os.path.join(BASE_DIR, "config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = re.sub(
            r"(AUTO_REPLY\s*=\s*)(True|False)",
            r"\g<1>" + ("True" if config.AUTO_REPLY else "False"),
            content
        )
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    return jsonify({"ok": True})


@app.route("/api/history/sessions", methods=["GET"])
def api_history_sessions():
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))
    sessions = database.get_sessions(page=page, page_size=page_size)
    return jsonify({"sessions": sessions})


@app.route("/api/history/messages", methods=["GET"])
def api_history_messages():
    session_key = request.args.get("session_key", "")
    if not session_key:
        return jsonify({"ok": False, "error": "session_key required"}), 400
    messages = database.get_session_messages(session_key)
    return jsonify({"messages": messages})


@app.route("/api/auto-reply/complete", methods=["POST"])
def api_auto_reply_complete():
    """自动回复完成接口（供自动回复机器人调用）"""
    data = request.get_json(force=True)
    session_key = data.get("session_key", "")
    reply_text = data.get("reply_text", "").strip()
    if not session_key:
        return jsonify({"ok": False, "error": "session_key required"}), 400
    try:
        # 解析 session_key 中的消息 ID 列表
        if "-" in session_key:
            real_session_key, id_str = session_key.rsplit("-", 1)
            message_ids = [int(id_) for id_ in id_str.split(",") if id_.isdigit()]
        else:
            real_session_key = session_key
            message_ids = []
        # 发送回复消息
        if reply_text:
            ok = reply_to_session(real_session_key, reply_text)
            if not ok:
                return jsonify({"ok": False, "error": "发送回复失败"}), 500
        # 标记自动回复完成
        if message_ids:
            database.mark_auto_reply_completed_by_ids(message_ids)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"自动回复完成失败: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    start_bot_thread()
    start_auto_reply_thread()
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=False,   # 避免 reloader 导致 bot 线程被重启两次
    )
