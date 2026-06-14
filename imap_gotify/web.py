from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any

from .config import load_config
from .gotify import GotifyClient
from .login_test import test_logins
from .webhook_test import send_test_webhook


def create_config_ui_server(config_path: str | Path, host: str, port: int) -> ThreadingHTTPServer:
    path = Path(config_path)

    class Handler(_ConfigHandler):
        config_path = path

    return ThreadingHTTPServer((host, port), Handler)


def start_config_ui_thread(config_path: str | Path, host: str, port: int) -> ThreadingHTTPServer:
    server = create_config_ui_server(config_path, host, port)
    thread = threading.Thread(
        target=server.serve_forever,
        name="config-web",
        daemon=True,
    )
    thread.start()
    print(f"imap-gotify config UI listening on http://{host}:{port}")
    return server


def serve_config_ui(config_path: str | Path, host: str, port: int) -> None:
    server = create_config_ui_server(config_path, host, port)
    print(f"imap-gotify config UI listening on http://{host}:{port}")
    server.serve_forever()


class _ConfigHandler(BaseHTTPRequestHandler):
    config_path: Path

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send_html(_index_html())
            return
        if self.path == "/api/config":
            self._send_json({"ok": True, "config": _read_config_json(self.config_path)})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/save":
                _validate_config_payload(self.config_path, payload.get("config"))
                _write_config_json(self.config_path, payload.get("config"))
                config = load_config(self.config_path)
                _touch_reload_flag(config.database_path.parent)
                self._send_json({"ok": True})
                return
            if self.path == "/api/test-login":
                config = _load_payload_or_file(self.config_path, payload.get("config"))
                results = [_dataclass_to_json(result) for result in test_logins(config)]
                self._send_json({"ok": all(item["ok"] for item in results), "results": results})
                return
            if self.path == "/api/test-webhook":
                config = _load_payload_or_file(self.config_path, payload.get("config"))
                send_test_webhook(GotifyClient(config.gotify))
                self._send_json({"ok": True})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status=400)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8")) if data else {}

    def _send_json(self, value: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _read_config_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "database_path": "state/imap-gotify.sqlite3",
            "log_path": "logs/imap-gotify.log",
            "gotify": {"url": "", "token": "", "priority": 5, "timeout_seconds": 15},
            "mailboxes": [],
        }
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_config_json(path: Path, config: Any) -> None:
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _load_payload_or_file(path: Path, config: Any):
    if config is None:
        return load_config(path)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / path.name
        _write_config_json(temp_path, config)
        return load_config(temp_path)


def _validate_config_payload(path: Path, config: Any) -> None:
    _load_payload_or_file(path, config)


def _touch_reload_flag(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    flag = state_dir / "reload.flag"
    flag.write_text(datetime.now().astimezone().isoformat(), encoding="utf-8")


def _dataclass_to_json(value: Any) -> Any:
    result = asdict(value)
    return _jsonify(result)


def _jsonify(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    return value


def _index_html() -> str:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>imap-gotify config</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #222;
      --muted: #656565;
      --line: #d9d9d2;
      --accent: #0f766e;
      --danger: #b42318;
    }
    @media (prefers-color-scheme: dark) {
      :root { --bg: #111312; --panel: #1a1d1b; --text: #f2f2ee; --muted: #aaa; --line: #333832; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
    header { position: sticky; top: 0; z-index: 1; background: var(--bg); border-bottom: 1px solid var(--line); }
    .bar { max-width: 1120px; margin: 0 auto; padding: 14px 20px; display: flex; gap: 12px; align-items: center; justify-content: space-between; }
    h1 { margin: 0; font-size: 20px; }
    main { max-width: 1120px; margin: 0 auto; padding: 20px; display: grid; gap: 18px; }
    section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
    h2 { margin: 0 0 12px; font-size: 16px; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; }
    label { display: grid; gap: 5px; color: var(--muted); }
    input, select { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--text); }
    input[type="checkbox"] { width: auto; }
    .span-2 { grid-column: span 2; }
    .span-3 { grid-column: span 3; }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .span-8 { grid-column: span 8; }
    .span-12 { grid-column: span 12; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    button { border: 1px solid var(--line); border-radius: 6px; padding: 9px 12px; background: var(--panel); color: var(--text); cursor: pointer; }
    button.primary { background: var(--accent); border-color: var(--accent); color: white; }
    button.danger { color: var(--danger); }
    .mailbox { border-top: 1px solid var(--line); padding-top: 14px; margin-top: 14px; }
    .status { white-space: pre-wrap; color: var(--muted); }
    @media (max-width: 760px) { .grid > * { grid-column: span 12 !important; } .bar { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <h1>imap-gotify 配置</h1>
      <div class="row">
        <button id="testLogin">测试 IMAP</button>
        <button id="testWebhook">测试 Gotify</button>
        <button id="save" class="primary">保存配置</button>
      </div>
    </div>
  </header>
  <main>
    <section>
      <h2>Gotify</h2>
      <div class="grid">
        <label class="span-6">URL<input id="gotifyUrl" placeholder="https://gotify.example.com"></label>
        <label class="span-6">Token<input id="gotifyToken" type="password"></label>
        <label class="span-3">Priority<input id="gotifyPriority" type="number" value="5"></label>
        <label class="span-3">Timeout seconds<input id="gotifyTimeout" type="number" value="15"></label>
        <label class="span-3">Database path<input id="databasePath" value="state/imap-gotify.sqlite3"></label>
        <label class="span-3">Log path<input id="logPath" value="logs/imap-gotify.log"></label>
      </div>
    </section>
    <section>
      <div class="row" style="justify-content: space-between;">
        <h2>IMAP mailboxes</h2>
        <button id="addMailbox">添加邮箱</button>
      </div>
      <div id="mailboxes"></div>
    </section>
    <section>
      <h2>状态</h2>
      <div id="status" class="status">加载中...</div>
    </section>
  </main>
  <template id="mailboxTemplate">
    <div class="mailbox">
      <div class="grid">
        <label class="span-3">Name<input data-field="name"></label>
        <label class="span-3">Host<input data-field="host" placeholder="imap.qq.com"></label>
        <label class="span-2">Port<input data-field="port" type="number" value="993"></label>
        <label class="span-2">SSL<select data-field="ssl"><option value="true">true</option><option value="false">false</option></select></label>
        <div class="span-2 row"><button class="danger remove" type="button">删除</button></div>
        <label class="span-4">Username<input data-field="username"></label>
        <label class="span-4">Password<input data-field="password" type="password"></label>
        <label class="span-4">Folders<input data-field="folders" placeholder="INBOX"></label>
        <label class="span-2">Poll seconds<input data-field="poll_seconds" type="number" value="60"></label>
        <label class="span-2">Idle seconds<input data-field="idle_seconds" type="number" value="1740"></label>
        <label class="span-2">Initial sync<select data-field="initial_sync"><option value="skip">skip</option><option value="process">process</option></select></label>
        <label class="span-2">Priority<input data-field="priority" type="number"></label>
        <label class="span-2">Max body chars<input data-field="max_body_chars" type="number" value="4000"></label>
        <label class="span-2">Ignore before<input data-field="ignore_before" placeholder="2026-06-13T00:00:00+08:00"></label>
        <label class="span-3 row"><input data-field="include_link_urls" type="checkbox"> Include links</label>
        <label class="span-3 row"><input data-field="include_remote_images" type="checkbox"> Remote images</label>
      </div>
    </div>
  </template>
  <script>
    let current = null;
    const $ = (id) => document.getElementById(id);
    const status = (text) => $("status").textContent = text;
    const numberOrNull = (value) => value === "" ? null : Number(value);
    const intOr = (value, fallback) => value === "" ? fallback : Number(value);

    function addMailbox(mailbox = {}) {
      const node = $("mailboxTemplate").content.firstElementChild.cloneNode(true);
      const set = (field, value) => {
        const input = node.querySelector(`[data-field="${field}"]`);
        if (!input) return;
        if (input.type === "checkbox") input.checked = Boolean(value);
        else input.value = value ?? "";
      };
      set("name", mailbox.name || "");
      set("host", mailbox.host || "");
      set("port", mailbox.port ?? 993);
      set("ssl", String(mailbox.ssl ?? true));
      set("username", mailbox.username || "");
      set("password", mailbox.password || "");
      set("folders", (mailbox.folders || ["INBOX"]).join(", "));
      set("poll_seconds", mailbox.poll_seconds ?? 60);
      set("idle_seconds", mailbox.idle_seconds ?? 1740);
      set("initial_sync", mailbox.initial_sync || "skip");
      set("priority", mailbox.priority ?? "");
      set("max_body_chars", mailbox.max_body_chars ?? 4000);
      set("ignore_before", mailbox.ignore_before || "");
      set("include_link_urls", mailbox.include_link_urls ?? true);
      set("include_remote_images", mailbox.include_remote_images ?? false);
      node.querySelector(".remove").onclick = () => node.remove();
      $("mailboxes").appendChild(node);
    }

    function render(config) {
      current = config;
      $("gotifyUrl").value = config.gotify?.url || "";
      $("gotifyToken").value = config.gotify?.token || "";
      $("gotifyPriority").value = config.gotify?.priority ?? 5;
      $("gotifyTimeout").value = config.gotify?.timeout_seconds ?? 15;
      $("databasePath").value = config.database_path || "state/imap-gotify.sqlite3";
      $("logPath").value = config.log_path || "logs/imap-gotify.log";
      $("mailboxes").innerHTML = "";
      (config.mailboxes || []).forEach(addMailbox);
      if (!(config.mailboxes || []).length) addMailbox();
      status("配置已加载");
    }

    function collect() {
      const mailboxes = [...document.querySelectorAll(".mailbox")].map(node => {
        const get = (field) => node.querySelector(`[data-field="${field}"]`);
        const folders = get("folders").value.split(",").map(x => x.trim()).filter(Boolean);
        const mailbox = {
          name: get("name").value.trim(),
          host: get("host").value.trim(),
          port: intOr(get("port").value, 993),
          ssl: get("ssl").value === "true",
          username: get("username").value.trim(),
          password: get("password").value,
          folders: folders.length ? folders : ["INBOX"],
          poll_seconds: intOr(get("poll_seconds").value, 60),
          idle_seconds: intOr(get("idle_seconds").value, 1740),
          initial_sync: get("initial_sync").value,
          priority: numberOrNull(get("priority").value),
          max_body_chars: intOr(get("max_body_chars").value, 4000),
          include_link_urls: get("include_link_urls").checked,
          include_remote_images: get("include_remote_images").checked,
        };
        if (get("ignore_before").value.trim()) mailbox.ignore_before = get("ignore_before").value.trim();
        if (mailbox.priority === null) delete mailbox.priority;
        return mailbox;
      });
      return {
        database_path: $("databasePath").value || "state/imap-gotify.sqlite3",
        log_path: $("logPath").value || "logs/imap-gotify.log",
        gotify: {
          url: $("gotifyUrl").value.trim(),
          token: $("gotifyToken").value,
          priority: intOr($("gotifyPriority").value, 5),
          timeout_seconds: intOr($("gotifyTimeout").value, 15),
        },
        mailboxes,
      };
    }

    async function post(path) {
      status("执行中...");
      const res = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({config: collect()}),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "request failed");
      return data;
    }

    $("addMailbox").onclick = () => addMailbox();
    $("save").onclick = async () => {
      try { await post("/api/save"); status("已保存配置"); }
      catch (err) { status(String(err)); }
    };
    $("testWebhook").onclick = async () => {
      try { await post("/api/test-webhook"); status("Gotify 测试消息已发送"); }
      catch (err) { status(String(err)); }
    };
    $("testLogin").onclick = async () => {
      try {
        const data = await post("/api/test-login");
        status(JSON.stringify(data.results, null, 2));
      } catch (err) { status(String(err)); }
    };

    fetch("/api/config")
      .then(res => res.json())
      .then(data => render(data.config))
      .catch(err => status(String(err)));
  </script>
</body>
</html>
"""
