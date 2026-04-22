# 钉钉消息助手

基于 **dingtalk-stream** + **Flask** 的钉钉消息接收与回复工具。
在浏览器中打开一个对话页面，即可实时查看并回复钉钉机器人收到的消息。

---

## 目录结构

```
dingding/
├── config.py          # ← 填写你的 AppKey / AppSecret
├── app.py             # Flask Web 服务入口
├── dingtalk_bot.py    # dingtalk-stream 监听服务
├── requirements.txt
└── templates/
    └── index.html     # 对话页面
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 填写配置

打开 `config.py`，将占位符替换为你的机器人/应用凭据：

```python
APP_KEY    = "你的AppKey"      # 替换
APP_SECRET = "你的AppSecret"   # 替换
```

> 在钉钉开放平台 → 应用管理 → 你的机器人 → 凭证与基础信息 中获取。

### 3. 启动

```bash
python app.py
```

### 4. 打开页面

浏览器访问 [http://localhost:3300](http://localhost:3300)

---

## 功能说明

| 功能 | 描述 |
|------|------|
| 实时接收 | 通过 dingtalk-stream 长连接接收消息，无需公网 IP |
| 多会话 | 左侧列表按发送人分组，切换自由 |
| 未读角标 | 非当前会话的新消息显示红点角标 |
| 快速回复 | 输入框 Enter 发送，Shift+Enter 换行 |
| 浏览器通知 | 页面不在前台时弹出系统通知（需授权） |

---

## 常见问题

**Q: 收不到消息？**  
A: 检查 `APP_KEY` / `APP_SECRET` 是否正确；钉钉机器人需要在「消息接收模式」中选择 **Stream 模式**。

**Q: 回复失败？**  
A: 确认机器人权限包含「发送消息」；群聊机器人需要有群消息发送权限。

**Q: 如何在服务器上长期运行？**  
A: 使用 `nohup python app.py &` 或配置 systemd / pm2 守护进程。
