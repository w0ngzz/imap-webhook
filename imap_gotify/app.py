from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
import threading

from .config import AppConfig, load_config, redact_config
from .gotify import GotifyClient
from .login_test import list_folders, print_folder_lists, print_login_results, test_logins
from .state import StateStore
from .watcher import MailboxWatcher
from .web import serve_config_ui, start_config_ui_thread
from .webhook_test import send_test_webhook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forward new IMAP mail to Gotify.")
    parser.add_argument("-c", "--config", default="config.json", help="Path to config JSON.")
    parser.add_argument("--check-config", action="store_true", help="Validate config and exit.")
    parser.add_argument("--test-login", action="store_true", help="Login to every mailbox and folder, then exit.")
    parser.add_argument("--list-folders", action="store_true", help="List IMAP folders for every mailbox, then exit.")
    parser.add_argument("--test-webhook", action="store_true", help="Send a Markdown test message to Gotify, then exit.")
    parser.add_argument("--web", action="store_true", help="Run the web configuration UI instead of the watcher.")
    parser.add_argument("--web-enable", action="store_true", help="Run the web configuration UI alongside the watcher.")
    parser.add_argument("--web-host", default="127.0.0.1", help="Host for --web.")
    parser.add_argument("--web-port", type=int, default=8080, help="Port for --web.")
    parser.add_argument(
        "--web-username",
        default=os.getenv("IMAP_WEBHOOK_WEB_USERNAME"),
        help="Username for web UI basic auth. Defaults to admin when password is set.",
    )
    parser.add_argument(
        "--web-password",
        default=os.getenv("IMAP_WEBHOOK_WEB_PASSWORD"),
        help="Password for web UI basic auth. If omitted, web auth is disabled.",
    )
    parser.add_argument("--log-file", help="Path to persistent log file. Overrides config log_path.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    if args.web:
        log_path = Path(args.log_file) if args.log_file else Path("logs/imap-gotify.log")
        setup_logging(logging.DEBUG if args.verbose else logging.INFO, log_path)
        serve_config_ui(args.config, args.web_host, args.web_port, args.web_username, args.web_password)
        return 0

    config = load_config(args.config)
    log_path = Path(args.log_file) if args.log_file else config.log_path
    setup_logging(logging.DEBUG if args.verbose else logging.INFO, log_path)
    if args.check_config:
        print(json.dumps(redact_config(config), ensure_ascii=False, indent=2))
        return 0
    if args.test_login:
        results = test_logins(config)
        print_login_results(results)
        return 0 if all(result.ok for result in results) else 1
    if args.list_folders:
        results = list_folders(config)
        print_folder_lists(results)
        return 0 if all(result.ok for result in results) else 1
    if args.test_webhook:
        gotify = GotifyClient(config.gotify)
        try:
            send_test_webhook(gotify)
        except Exception as exc:
            print(f"Gotify webhook test failed: {exc}", file=sys.stderr)
            return 1
        else:
            print("Gotify webhook test message sent.")
            return 0

    manager = WatcherManager(config)
    stop_event = threading.Event()
    reload_watcher = ConfigReloadWatcher(Path(args.config), config)
    web_server = None

    if args.web_enable:
        web_server = start_config_ui_thread(
            args.config,
            args.web_host,
            args.web_port,
            args.web_username,
            args.web_password,
        )

    def stop(_signum: int, _frame: object) -> None:
        logging.info("stopping")
        stop_event.set()
        manager.stop()
        if web_server is not None:
            web_server.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    manager.start()

    while not stop_event.wait(2):
        if not reload_watcher.changed():
            continue
        try:
            new_config = load_config(args.config)
        except Exception:
            reload_watcher.mark_failed()
            continue
        manager.reload(new_config)
        reload_watcher.mark_loaded(new_config)

    manager.join()
    if web_server is not None:
        web_server.server_close()
    return 0


def setup_logging(level: int, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[console_handler, file_handler], force=True)
    logging.info("logging to %s", log_path)


class WatcherManager:
    def __init__(self, config: AppConfig) -> None:
        self._state: StateStore | None = None
        self._watchers: list[MailboxWatcher] = []
        self._configure(config)

    def _configure(self, config: AppConfig) -> None:
        self._state = StateStore(config.database_path)
        gotify = GotifyClient(config.gotify)
        self._watchers = [MailboxWatcher(mailbox, gotify, self._state) for mailbox in config.mailboxes]

    def start(self) -> None:
        for watcher in self._watchers:
            watcher.start()

    def stop(self) -> None:
        for watcher in self._watchers:
            watcher.stop()

    def join(self) -> None:
        for watcher in self._watchers:
            watcher.join()
        if self._state is not None:
            self._state.close()
            self._state = None

    def reload(self, config: AppConfig) -> None:
        logging.info("reloading config")
        self.stop()
        self.join()
        self._configure(config)
        self.start()
        logging.info("config reloaded")


class ConfigReloadWatcher:
    def __init__(self, config_path: Path, config: AppConfig) -> None:
        self._config_path = config_path
        self._config_signature = self._signature(config_path)
        self._reload_flag = self._reload_flag_path(config)
        self._flag_signature = self._signature(self._reload_flag)
        self._last_failed: tuple[float | None, float | None] | None = None

    def changed(self) -> bool:
        signatures = (self._signature(self._config_path), self._signature(self._reload_flag))
        changed = signatures != (self._config_signature, self._flag_signature)
        if changed and signatures != self._last_failed:
            return True
        return False

    def mark_loaded(self, config: AppConfig) -> None:
        self._reload_flag = self._reload_flag_path(config)
        self._config_signature = self._signature(self._config_path)
        self._flag_signature = self._signature(self._reload_flag)
        self._last_failed = None

    def mark_failed(self) -> None:
        signatures = (self._signature(self._config_path), self._signature(self._reload_flag))
        self._last_failed = signatures
        logging.exception("config reload failed; keeping previous watchers")

    @staticmethod
    def _reload_flag_path(config: AppConfig) -> Path:
        return config.database_path.parent / "reload.flag"

    @staticmethod
    def _signature(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None


if __name__ == "__main__":
    sys.exit(main())
