from __future__ import annotations

import imaplib
from dataclasses import dataclass
import base64
import re

from .config import AppConfig, MailboxConfig


@dataclass(frozen=True)
class FolderLoginResult:
    folder: str
    ok: bool
    message_count: int | None = None
    uidvalidity: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class MailboxLoginResult:
    name: str
    host: str
    username: str
    ok: bool
    idle_supported: bool | None = None
    folders: list[FolderLoginResult] | None = None
    error: str | None = None


@dataclass(frozen=True)
class FolderListItem:
    name: str
    display_name: str
    delimiter: str | None
    flags: str


@dataclass(frozen=True)
class MailboxFolderList:
    name: str
    host: str
    username: str
    ok: bool
    folders: list[FolderListItem] | None = None
    error: str | None = None


def test_logins(config: AppConfig) -> list[MailboxLoginResult]:
    return [_test_mailbox(mailbox) for mailbox in config.mailboxes]


def list_folders(config: AppConfig) -> list[MailboxFolderList]:
    return [_list_mailbox_folders(mailbox) for mailbox in config.mailboxes]


def print_folder_lists(results: list[MailboxFolderList]) -> None:
    for result in results:
        if not result.ok:
            print(f"[FAIL] {result.name} ({result.username}@{result.host})")
            print(f"       {result.error}")
            continue

        print(f"[OK]   {result.name} ({result.username}@{result.host})")
        for folder in result.folders or []:
            if folder.name == folder.display_name:
                print(f"       {folder.name} flags={folder.flags}")
            else:
                print(f"       {folder.name} display={folder.display_name} flags={folder.flags}")


def print_login_results(results: list[MailboxLoginResult]) -> None:
    for result in results:
        if not result.ok:
            print(f"[FAIL] {result.name} ({result.username}@{result.host})")
            print(f"       {result.error}")
            continue

        idle = "yes" if result.idle_supported else "no"
        print(f"[OK]   {result.name} ({result.username}@{result.host}) IDLE={idle}")
        for folder in result.folders or []:
            if folder.ok:
                print(
                    "       "
                    f"{folder.folder}: messages={folder.message_count}, "
                    f"uidvalidity={folder.uidvalidity}"
                )
            else:
                print(f"       {folder.folder}: FAIL {folder.error}")


def _test_mailbox(mailbox: MailboxConfig) -> MailboxLoginResult:
    imap: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
    try:
        imap = _connect(mailbox)
        idle_supported = _has_idle(imap)
        folder_results = [_test_folder(imap, folder) for folder in mailbox.folders]
        ok = all(folder.ok for folder in folder_results)
        return MailboxLoginResult(
            name=mailbox.name,
            host=mailbox.host,
            username=mailbox.username,
            ok=ok,
            idle_supported=idle_supported,
            folders=folder_results,
        )
    except Exception as exc:
        return MailboxLoginResult(
            name=mailbox.name,
            host=mailbox.host,
            username=mailbox.username,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def _list_mailbox_folders(mailbox: MailboxConfig) -> MailboxFolderList:
    imap: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
    try:
        imap = _connect(mailbox)
        typ, data = imap.list()
        if typ != "OK":
            return MailboxFolderList(
                name=mailbox.name,
                host=mailbox.host,
                username=mailbox.username,
                ok=False,
                error=str(data),
            )
        folders = [_parse_list_response(item) for item in data or [] if item]
        return MailboxFolderList(
            name=mailbox.name,
            host=mailbox.host,
            username=mailbox.username,
            ok=True,
            folders=[folder for folder in folders if folder is not None],
        )
    except Exception as exc:
        return MailboxFolderList(
            name=mailbox.name,
            host=mailbox.host,
            username=mailbox.username,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def _connect(mailbox: MailboxConfig) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
    if mailbox.ssl:
        imap: imaplib.IMAP4 | imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
            mailbox.host,
            mailbox.port,
            timeout=20,
        )
    else:
        imap = imaplib.IMAP4(mailbox.host, mailbox.port, timeout=20)
    imap.login(mailbox.username, mailbox.password)
    return imap


def _test_folder(imap: imaplib.IMAP4, folder: str) -> FolderLoginResult:
    try:
        typ, data = imap.select(_quote_folder(folder), readonly=True)
        if typ != "OK":
            return FolderLoginResult(folder=folder, ok=False, error=str(data))

        message_count = _parse_message_count(data)
        uidvalidity = _response_value(imap, "UIDVALIDITY")
        return FolderLoginResult(
            folder=folder,
            ok=True,
            message_count=message_count,
            uidvalidity=uidvalidity,
        )
    except Exception as exc:
        return FolderLoginResult(folder=folder, ok=False, error=f"{type(exc).__name__}: {exc}")


def _has_idle(imap: imaplib.IMAP4) -> bool:
    return "IDLE" in {
        cap.decode("ascii", errors="ignore").upper() if isinstance(cap, bytes) else cap.upper()
        for cap in imap.capabilities
    }


def _parse_message_count(data: list[bytes] | tuple[bytes, ...]) -> int | None:
    if not data or not data[0]:
        return None
    try:
        return int(data[0])
    except (TypeError, ValueError):
        return None


def _response_value(imap: imaplib.IMAP4, name: str) -> str | None:
    typ, data = imap.response(name)
    if typ != "OK" or not data or not data[0]:
        return None
    value = data[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _quote_folder(folder: str) -> str:
    escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


_LIST_RE = re.compile(rb"^\((?P<flags>.*?)\)\s+(?P<delimiter>NIL|\"(?:\\.|[^\"])*\")\s+(?P<name>.+)$")


def _parse_list_response(item: bytes | str) -> FolderListItem | None:
    raw = item if isinstance(item, bytes) else item.encode("utf-8", errors="replace")
    match = _LIST_RE.match(raw)
    if not match:
        return None

    name = _decode_mailbox_token(match.group("name"))
    delimiter_token = match.group("delimiter")
    delimiter = None if delimiter_token == b"NIL" else _decode_mailbox_token(delimiter_token)
    flags = match.group("flags").decode("ascii", errors="replace")
    return FolderListItem(
        name=name,
        display_name=_decode_modified_utf7(name),
        delimiter=delimiter,
        flags=flags,
    )


def _decode_mailbox_token(token: bytes) -> str:
    token = token.strip()
    if len(token) >= 2 and token[:1] == b'"' and token[-1:] == b'"':
        token = token[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
    return token.decode("ascii", errors="replace")


def _decode_modified_utf7(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        amp = value.find("&", index)
        if amp < 0:
            result.append(value[index:])
            break
        result.append(value[index:amp])
        end = value.find("-", amp)
        if end < 0:
            result.append(value[amp:])
            break
        encoded = value[amp + 1 : end]
        if not encoded:
            result.append("&")
        else:
            b64 = encoded.replace(",", "/")
            padding = "=" * (-len(b64) % 4)
            try:
                result.append(base64.b64decode(b64 + padding).decode("utf-16-be"))
            except Exception:
                result.append(value[amp : end + 1])
        index = end + 1
    return "".join(result)
