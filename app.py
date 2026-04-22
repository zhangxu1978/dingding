"""
app.py
------
Flask Web 服务 — 提供对话监控页面和回复接口。
启动时同步拉起 dingtalk_bot 线程。
"""

import os
from flask import Flask, jsonify, render_template, request

import config
from dingtalk_bot import get_messages, reply_to_session, start_bot_thread

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")


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


if __name__ == "__main__":
    start_bot_thread()
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=False,   # 避免 reloader 导致 bot 线程被重启两次
    )
