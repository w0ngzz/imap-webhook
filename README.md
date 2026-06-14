# imap-gotify

实时监控多个 IMAP 邮箱，收到新邮件后转换成 Markdown，并推送到 Gotify。

## 特性

- 多邮箱、多文件夹监听
- 优先使用 IMAP IDLE，邮箱不支持时自动轮询
- 邮件元信息和正文转 Markdown
- Gotify Markdown 渲染
- SQLite 记录 UID，避免重启后重复推送
- 默认跳过历史邮件，只推送服务启动后的新邮件

## 快速开始

需要 Python 3.11 或更高版本。

```powershell
Copy-Item config.example.json config.json
python -m imap_gotify --check-config -c config.json
python -m imap_gotify --test-login -c config.json
python -m imap_gotify --test-webhook -c config.json
python -m imap_gotify -c config.json
```

Gotify 的应用 token 在 Gotify Web UI 的 `Apps` 页面创建。

`--test-login` 会逐个邮箱登录，并检查配置中的文件夹是否可以打开。成功时会输出邮件数、`UIDVALIDITY` 和服务器是否支持 IMAP IDLE。

`--test-webhook` 会向 Gotify 发送一条 Markdown 测试消息，用来确认 `gotify.url` 和 `gotify.token` 是否配置正确。

监听运行时会优先使用 IMAP IDLE 实时等待新邮件；同时会最多每 `poll_seconds` 秒主动退出 IDLE 并重新检查一次 UID，避免邮箱服务器漏发 IDLE 通知时错过新邮件。

## 配置

编辑 `config.json`：

```json
{
  "database_path": "state/imap-gotify.sqlite3",
  "gotify": {
    "url": "https://gotify.example.com",
    "token": "YOUR_GOTIFY_APP_TOKEN",
    "priority": 5
  },
  "mailboxes": [
    {
      "name": "gmail-main",
      "host": "imap.gmail.com",
      "port": 993,
      "ssl": true,
      "username": "user@gmail.com",
      "password": "app-password-or-imap-token",
      "folders": ["INBOX"],
      "initial_sync": "skip"
    }
  ]
}
```

字段说明：

- `initial_sync`: `skip` 表示首次启动跳过历史邮件，`process` 表示首次启动也推送已有邮件。
- `poll_seconds`: 邮箱不支持 IDLE 时的轮询间隔；邮箱支持 IDLE 时也会作为兜底主动检查间隔。
- `poll_seconds`: 邮箱支持 IDLE 时也会作为兜底检查间隔。
- `idle_seconds`: 单次 IDLE 最大持续时间，默认 1740 秒，实际等待不会超过 `poll_seconds`。
- `max_body_chars`: 推送正文最大字符数，超出会截断。
- `priority`: 邮箱级 Gotify 优先级；不填时使用全局 Gotify 优先级。
- `include_link_urls`: 是否在 Markdown 中保留可点击链接，默认 `true`。链接会显示成文字或域名，不直接铺开超长 URL。
- `include_remote_images`: 是否把 HTML 邮件里的远程图片转成 Markdown 图片，默认 `false`。开启后 Gotify 客户端能否显示，取决于图片 URL 是否公网可访问、客户端是否渲染远程图片。

## 邮件 Markdown 格式

推送内容会包含：

- 发件人
- 收件人
- 时间
- 主题
- 正文
- 附件文件名列表

如果邮件有 `text/plain` 正文，会优先使用纯文本；如果只有 HTML，会做一个轻量 HTML 到 Markdown 的转换。

## 注意事项

很多邮箱不能直接使用登录密码，需要使用 IMAP 授权码或应用专用密码。Gmail、Outlook、QQ、163 等邮箱尤其需要注意这一点。

## Docker deployment

Run one container with Docker Compose:

```bash
sudo mkdir -p /opt/imap-webhook/data
sudo chown -R $USER:$USER /opt/imap-webhook
cd /opt/imap-webhook
```

Create `docker-compose.yml`:

```yaml
services:
  imap-webhook:
    image: w0ng22/imap-webhook:latest
    container_name: imap-webhook
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ./data:/data
```

Start it:

```bash
docker compose up -d
docker compose logs -f
```

On first start, the container creates:

```text
data/config.json
data/state/
data/logs/
```

Use an SSH tunnel from your computer:

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

Then open `http://127.0.0.1:8080` locally. Edit the generated config from the web UI and save it. The watcher will hot reload valid config changes.

Run one-off checks:

```bash
docker compose run --rm imap-webhook python -m imap_gotify --check-config -c /data/config.json
docker compose run --rm imap-webhook python -m imap_gotify --test-login -c /data/config.json
docker compose run --rm imap-webhook python -m imap_gotify --list-folders -c /data/config.json
docker compose run --rm imap-webhook python -m imap_gotify --test-webhook -c /data/config.json
```

Keep `data/` mounted when moving to a new server. It contains config, IMAP UID state, and logs.

## Web configuration UI

Run the local configuration UI only:

```bash
python -m imap_gotify --web --web-host 127.0.0.1 --web-port 8080 -c config.json
```

Run the watcher and web UI in one process:

```bash
python -m imap_gotify -c config.json --web-enable --web-host 127.0.0.1 --web-port 8080
```

## Hot reload

The watcher checks the config file and `state/reload.flag` every 2 seconds. When the web UI saves a valid config, it writes `config.json`, touches `state/reload.flag`, and the running watcher restarts its IMAP watchers without restarting the container.

If a saved config is invalid, the watcher logs the reload error and keeps the previous working watchers running.
