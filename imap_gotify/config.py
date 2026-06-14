from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GotifyConfig:
    url: str
    token: str
    priority: int = 5
    timeout_seconds: int = 15


@dataclass(frozen=True)
class MailboxConfig:
    name: str
    host: str
    username: str
    password: str
    port: int = 993
    ssl: bool = True
    folders: list[str] = field(default_factory=lambda: ["INBOX"])
    poll_seconds: int = 60
    idle_seconds: int = 1740
    initial_sync: str = "skip"
    priority: int | None = None
    max_body_chars: int = 4000
    include_link_urls: bool = True
    include_remote_images: bool = False
    ignore_before: datetime | None = None


@dataclass(frozen=True)
class AppConfig:
    gotify: GotifyConfig
    mailboxes: list[MailboxConfig]
    database_path: Path = Path("state/imap-gotify.sqlite3")
    log_path: Path = Path("logs/imap-gotify.log")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    gotify = GotifyConfig(**raw["gotify"])
    mailboxes = [_load_mailbox_config(item) for item in raw.get("mailboxes", [])]
    if not mailboxes:
        raise ValueError("config must contain at least one mailbox")

    database_path = Path(raw.get("database_path", "state/imap-gotify.sqlite3"))
    if not database_path.is_absolute():
        database_path = config_path.parent / database_path

    log_path = Path(raw.get("log_path", "logs/imap-gotify.log"))
    if not log_path.is_absolute():
        log_path = config_path.parent / log_path

    return AppConfig(gotify=gotify, mailboxes=mailboxes, database_path=database_path, log_path=log_path)


def redact_config(config: AppConfig) -> dict[str, Any]:
    return {
        "gotify": {
            "url": config.gotify.url,
            "token": "***",
            "priority": config.gotify.priority,
        },
        "mailboxes": [
            {
                "name": mailbox.name,
                "host": mailbox.host,
                "username": mailbox.username,
                "password": "***",
                "folders": mailbox.folders,
                "ignore_before": mailbox.ignore_before.isoformat() if mailbox.ignore_before else None,
            }
            for mailbox in config.mailboxes
        ],
        "database_path": str(config.database_path),
        "log_path": str(config.log_path),
    }


def _load_mailbox_config(raw: dict[str, Any]) -> MailboxConfig:
    item = dict(raw)
    if item.get("ignore_before"):
        item["ignore_before"] = _parse_config_datetime(str(item["ignore_before"]))
    else:
        item["ignore_before"] = None
    return MailboxConfig(**item)


def _parse_config_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ignore_before datetime: {value}") from exc
    return parsed.astimezone()
