from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .config import GotifyConfig


class GotifyClient:
    def __init__(self, config: GotifyConfig) -> None:
        self._config = config
        self._endpoint = self._build_endpoint(config.url, config.token)

    def send_markdown(self, title: str, message: str, priority: int | None = None) -> None:
        payload = {
            "title": title,
            "message": message,
            "priority": priority if priority is not None else self._config.priority,
            "extras": {
                "client::display": {
                    "contentType": "text/markdown",
                }
            },
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "imap-gotify/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                if response.status >= 300:
                    raise RuntimeError(f"Gotify returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gotify returned HTTP {exc.code}: {body}") from exc

    @staticmethod
    def _build_endpoint(url: str, token: str) -> str:
        base = url.rstrip("/")
        query = urllib.parse.urlencode({"token": token})
        return f"{base}/message?{query}"
