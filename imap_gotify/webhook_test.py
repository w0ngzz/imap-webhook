from __future__ import annotations

from datetime import datetime

from .gotify import GotifyClient


def send_test_webhook(client: GotifyClient) -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    client.send_markdown(
        title="imap-gotify webhook 测试",
        message=(
            "## imap-gotify webhook 测试\n\n"
            f"**时间**：{now}  \n"
            "**状态**：Gotify Markdown 推送链路正常\n\n"
            "---\n\n"
            "如果你能看到这条消息，说明 `gotify.url` 和 `gotify.token` 配置可用。"
        ),
    )
