from __future__ import annotations

import imaplib
import logging
import select
import threading
import time

from .config import MailboxConfig
from .gotify import GotifyClient
from .mail_markdown import parse_message, to_markdown
from .state import StateStore

LOGGER = logging.getLogger(__name__)


class ReconnectNeeded(RuntimeError):
    pass


class MailboxWatcher:
    def __init__(self, config: MailboxConfig, gotify: GotifyClient, state: StateStore) -> None:
        self._config = config
        self._gotify = gotify
        self._state = state
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for folder in self._config.folders:
            thread = threading.Thread(
                target=self._run_folder,
                name=f"imap-{self._config.name}-{folder}",
                args=(folder,),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()

    def join(self) -> None:
        for thread in self._threads:
            thread.join()

    def _run_folder(self, folder: str) -> None:
        backoff = 5
        while not self._stop.is_set():
            imap: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
            try:
                imap = self._connect()
                uidvalidity = self._select_folder(imap, folder)
                self._initialise_folder(imap, folder, uidvalidity)
                backoff = 5

                while not self._stop.is_set():
                    self._process_new_messages(imap, folder, uidvalidity)
                    self._wait_for_changes(imap)
            except ReconnectNeeded as exc:
                LOGGER.warning(
                    "imap reconnect needed mailbox=%s folder=%s reason=%s; reconnecting in %ss",
                    self._config.name,
                    folder,
                    exc,
                    backoff,
                )
                self._sleep(backoff)
                backoff = min(backoff * 2, 300)
            except Exception:
                LOGGER.exception(
                    "watcher failed for mailbox=%s folder=%s; reconnecting in %ss",
                    self._config.name,
                    folder,
                    backoff,
                )
                self._sleep(backoff)
                backoff = min(backoff * 2, 300)
            finally:
                if imap is not None:
                    try:
                        imap.logout()
                    except Exception:
                        pass

    def _connect(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        LOGGER.info("connecting mailbox=%s host=%s", self._config.name, self._config.host)
        if self._config.ssl:
            imap: imaplib.IMAP4 | imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
                self._config.host,
                self._config.port,
            )
        else:
            imap = imaplib.IMAP4(self._config.host, self._config.port)
        imap.login(self._config.username, self._config.password)
        return imap

    def _select_folder(self, imap: imaplib.IMAP4, folder: str) -> str:
        typ, data = imap.select(f'"{folder}"')
        if typ != "OK":
            raise RuntimeError(f"cannot select folder {folder}: {data}")
        typ, data = imap.response("UIDVALIDITY")
        if typ == "OK" and data and data[0]:
            return _decode_bytes(data[0])
        return "unknown"

    def _initialise_folder(self, imap: imaplib.IMAP4, folder: str, uidvalidity: str) -> None:
        if self._state.highest_uid(self._config.name, folder, uidvalidity) > 0:
            return

        uids = self._search_uids(imap, "ALL")
        if not uids:
            return

        if self._config.initial_sync == "process":
            LOGGER.info("processing existing messages mailbox=%s folder=%s", self._config.name, folder)
            self._process_uids(imap, folder, uidvalidity, uids)
            return

        highest_uid = max(int(uid) for uid in uids)
        self._state.mark_processed(
            self._config.name,
            folder,
            uidvalidity,
            str(highest_uid),
            None,
        )
        LOGGER.info(
            "initial sync skipped history mailbox=%s folder=%s highest_uid=%s",
            self._config.name,
            folder,
            highest_uid,
        )

    def _process_new_messages(self, imap: imaplib.IMAP4, folder: str, uidvalidity: str) -> None:
        highest = self._state.highest_uid(self._config.name, folder, uidvalidity)
        criteria = f"UID {highest + 1}:*" if highest else "ALL"
        uids = [uid for uid in self._search_uids(imap, criteria) if int(uid) > highest]
        self._process_uids(imap, folder, uidvalidity, uids)

    def _process_uids(
        self,
        imap: imaplib.IMAP4,
        folder: str,
        uidvalidity: str,
        uids: list[str],
    ) -> None:
        for uid in uids:
            if self._stop.is_set():
                return
            if self._state.has_processed(self._config.name, folder, uidvalidity, uid):
                continue

            raw = self._fetch_message(imap, uid)
            mail = parse_message(
                raw,
                self._config.max_body_chars,
                include_link_urls=self._config.include_link_urls,
                include_remote_images=self._config.include_remote_images,
            )
            if self._should_ignore_mail(mail):
                self._state.mark_processed(self._config.name, folder, uidvalidity, uid, mail.message_id)
                LOGGER.info(
                    "ignored old mail mailbox=%s folder=%s uid=%s date=%s subject=%s",
                    self._config.name,
                    folder,
                    uid,
                    mail.date,
                    mail.subject,
                )
                continue
            title = f"新邮件：{mail.subject or '(无主题)'}"
            message = to_markdown(mail)
            self._gotify.send_markdown(title, message, self._config.priority)
            self._state.mark_processed(self._config.name, folder, uidvalidity, uid, mail.message_id)
            LOGGER.info(
                "forwarded mail mailbox=%s folder=%s uid=%s subject=%s",
                self._config.name,
                folder,
                uid,
                mail.subject,
            )

    def _should_ignore_mail(self, mail: object) -> bool:
        ignore_before = self._config.ignore_before
        mail_date = getattr(mail, "date_time", None)
        return bool(ignore_before and mail_date and mail_date < ignore_before)

    def _search_uids(self, imap: imaplib.IMAP4, criteria: str) -> list[str]:
        typ, data = imap.uid("SEARCH", None, *criteria.split())
        if typ != "OK":
            raise RuntimeError(f"uid search failed: {data}")
        if not data or not data[0]:
            return []
        return _decode_bytes(data[0]).split()

    def _fetch_message(self, imap: imaplib.IMAP4, uid: str) -> bytes:
        typ, data = imap.uid("FETCH", uid, "(RFC822)")
        if typ != "OK":
            raise RuntimeError(f"uid fetch failed for {uid}: {data}")
        for item in data:
            if isinstance(item, tuple) and item[1]:
                return item[1]
        raise RuntimeError(f"message body missing for uid {uid}")

    def _wait_for_changes(self, imap: imaplib.IMAP4) -> None:
        capabilities = {
            cap.decode("ascii", errors="ignore").upper() if isinstance(cap, bytes) else cap.upper()
            for cap in imap.capabilities
        }
        if "IDLE" in capabilities:
            self._idle(max(1, min(self._config.idle_seconds, self._config.poll_seconds)), imap)
        else:
            self._sleep(self._config.poll_seconds)

    def _idle(self, max_wait_seconds: int, imap: imaplib.IMAP4) -> None:
        try:
            tag = imap._new_tag()
            imap.send(tag + b" IDLE\r\n")
            response = imap.readline()
        except (OSError, EOFError, imaplib.IMAP4.abort) as exc:
            raise ReconnectNeeded(f"failed to enter IDLE: {exc}") from exc

        if not response.startswith(b"+"):
            raise ReconnectNeeded(f"IDLE not accepted: {response!r}")

        deadline = time.monotonic() + max_wait_seconds
        wait_error: BaseException | None = None
        finish_error: BaseException | None = None
        wake_reason = "timeout"
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                wait_seconds = min(1, max(0, deadline - time.monotonic()))
                readable, _, _ = select.select([imap.sock], [], [], wait_seconds)
                if not readable:
                    continue
                line = imap.readline()
                if line:
                    wake_reason = _decode_bytes(line).strip()
                    break
        except (OSError, EOFError, imaplib.IMAP4.abort) as exc:
            wait_error = exc
        finally:
            try:
                imap.send(b"DONE\r\n")
                imap.readline()
            except (OSError, EOFError, imaplib.IMAP4.abort) as exc:
                finish_error = exc

        if wait_error is not None:
            raise ReconnectNeeded(f"IDLE wait failed: {wait_error}") from wait_error
        if finish_error is not None:
            raise ReconnectNeeded(f"failed to leave IDLE: {finish_error}") from finish_error
        LOGGER.debug(
            "idle finished mailbox=%s max_wait=%ss reason=%s",
            self._config.name,
            max_wait_seconds,
            wake_reason,
        )

    def _sleep(self, seconds: int) -> None:
        self._stop.wait(seconds)


def _decode_bytes(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
