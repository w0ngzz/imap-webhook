from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter


@dataclass(frozen=True)
class ParsedMail:
    subject: str
    sender: str
    recipients: str
    cc: str
    date: str
    date_time: datetime | None
    message_id: str | None
    body_markdown: str
    attachments: list[str]


class _MailMarkdownConverter(MarkdownConverter):
    def __init__(self, include_link_urls: bool, include_remote_images: bool) -> None:
        strip_tags: list[str] = []
        if not include_remote_images:
            strip_tags.append("img")
        super().__init__(
            autolinks=False,
            heading_style="ATX",
            newline_style="BACKSLASH",
            strip=strip_tags,
            table_infer_header=True,
            wrap=False,
        )
        self.include_link_urls = include_link_urls
        self.include_remote_images = include_remote_images

    def convert_a(self, el: object, text: str, parent_tags: set[str]) -> str:
        href = el.get("href")  # type: ignore[attr-defined]
        cleaned = _clean_link_text(text)
        return _format_html_link(cleaned, href, self.include_link_urls)

    def convert_img(self, el: object, text: str, parent_tags: set[str]) -> str:
        attrs = {key: value for key, value in el.attrs.items()}  # type: ignore[attr-defined]
        src = attrs.get("src")
        if not self.include_remote_images or not src or not _is_http_url(src) or _looks_like_tracking_pixel(attrs):
            return ""
        alt = attrs.get("alt") or "mail image"
        return f"![{_clean_inline_text(alt)}]({src})"

    def convert_div(self, el: object, text: str, parent_tags: set[str]) -> str:
        return _format_block(text)

    def convert_p(self, el: object, text: str, parent_tags: set[str]) -> str:
        return _format_block(text)

    def convert_table(self, el: object, text: str, parent_tags: set[str]) -> str:
        return _format_block(text)

    def convert_tbody(self, el: object, text: str, parent_tags: set[str]) -> str:
        return text

    def convert_thead(self, el: object, text: str, parent_tags: set[str]) -> str:
        return text

    def convert_tfoot(self, el: object, text: str, parent_tags: set[str]) -> str:
        return text

    def convert_tr(self, el: object, text: str, parent_tags: set[str]) -> str:
        return _format_block(text)

    def convert_td(self, el: object, text: str, parent_tags: set[str]) -> str:
        return _clean_table_cell_text(text)

    def convert_th(self, el: object, text: str, parent_tags: set[str]) -> str:
        return _clean_table_cell_text(text)




def parse_message(
    raw: bytes,
    max_body_chars: int,
    include_link_urls: bool = True,
    include_remote_images: bool = False,
) -> ParsedMail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    date_time = _parse_date(msg.get("Date"))
    body = _extract_body(msg)
    if body[1] == "html":
        body_text = _html_to_markdown(
            body[0],
            include_link_urls=include_link_urls,
            include_remote_images=include_remote_images,
        )
    else:
        body_text = body[0].strip()
        body_text = _format_plain_text_urls(body_text, include_link_urls)

    if _markdown_visible_length(body_text) > max_body_chars:
        body_text = _truncate_markdown(body_text, max_body_chars)

    return ParsedMail(
        subject=_decode_header_value(msg.get("Subject", "(no subject)")),
        sender=_format_addresses(msg.get("From", "")),
        recipients=_format_addresses(msg.get("To", "")),
        cc=_format_addresses(msg.get("Cc", "")),
        date=_format_date(msg.get("Date"), date_time),
        date_time=date_time,
        message_id=msg.get("Message-ID"),
        body_markdown=body_text or "(no body)",
        attachments=_attachment_names(msg),
    )


def to_markdown(mail: ParsedMail) -> str:
    lines = [
        "## New mail",
        "",
        f"**From**: {mail.sender or '(unknown)'}  ",
        f"**To**: {mail.recipients or '(unknown)'}  ",
        f"**Date**: {mail.date or '(unknown)'}  ",
        f"**Subject**: {mail.subject or '(no subject)'}",
    ]
    if mail.cc:
        lines.append(f"**Cc**: {mail.cc}")

    lines.extend(["", "---", "", mail.body_markdown])

    if mail.attachments:
        lines.extend(["", "---", "", "### Attachments"])
        lines.extend(f"- {name}" for name in mail.attachments)

    return "\n".join(lines)


def _extract_body(msg: Message) -> tuple[str, str]:
    plain: str | None = None
    html_body: str | None = None

    if isinstance(msg, EmailMessage):
        for part in msg.walk():
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
            if content_type == "text/plain" and plain is None:
                plain = content
            elif content_type == "text/html" and html_body is None:
                html_body = content
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        plain = payload.decode(charset, errors="replace")

    if plain:
        return plain, "plain"
    if html_body:
        return html_body, "html"
    return "", "plain"


def _attachment_names(msg: Message) -> list[str]:
    names: list[str] = []
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        filename = part.get_filename()
        names.append(_decode_header_value(filename) if filename else "(unnamed attachment)")
    return names


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def _format_addresses(value: str) -> str:
    addresses = []
    for name, address in getaddresses([value]):
        decoded_name = _decode_header_value(name)
        if decoded_name and address:
            addresses.append(f"{decoded_name} <{address}>")
        elif address:
            addresses.append(address)
        elif decoded_name:
            addresses.append(decoded_name)
    return ", ".join(addresses)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone()
    except Exception:
        return None


def _format_date(value: str | None, parsed: datetime | None) -> str:
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M:%S %z")
    return value or ""


def _html_to_markdown(html_body: str, include_link_urls: bool, include_remote_images: bool) -> str:
    converter = _MailMarkdownConverter(
        include_link_urls=include_link_urls,
        include_remote_images=include_remote_images,
    )
    return _clean_markdown(converter.convert(_remove_hidden_html(html_body)))


def _remove_hidden_html(html_body: str) -> str:
    soup = BeautifulSoup(html_body, "html.parser")
    for tag in soup(["style", "script", "head", "title", "meta", "noscript"]):
        tag.decompose()
    return str(soup)


def _clean_markdown(text: str) -> str:
    text = re.sub(r"\n[ \t]{4,}", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate_markdown(text: str, max_chars: int) -> str:
    parts: list[str] = []
    visible = 0
    pos = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]*)\)", text):
        before = text[pos : match.start()]
        remaining = max_chars - visible
        if remaining <= 0:
            break
        if len(before) > remaining:
            parts.append(before[:remaining])
            visible = max_chars
            break
        parts.append(before)
        visible += len(before)

        label = match.group(1)
        remaining = max_chars - visible
        if len(label) > remaining:
            break
        parts.append(match.group(0))
        visible += len(label)
        pos = match.end()

    if visible < max_chars:
        remaining_text = text[pos:]
        parts.append(remaining_text[: max_chars - visible])

    cut = "".join(parts).rstrip()
    return f"{cut}\n\n...content truncated" if cut else "...content truncated"


def _markdown_visible_length(text: str) -> int:
    length = 0
    pos = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]*)\)", text):
        length += len(text[pos : match.start()])
        length += len(match.group(1))
        pos = match.end()
    length += len(text[pos:])
    return length


def _format_block(text: str, newlines: int = 2) -> str:
    text = text.strip()
    if not text:
        return ""
    sep = "\n" * newlines
    return f"{sep}{text}{sep}"


def _clean_table_cell_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return f"{text}\n" if text else ""


def _format_plain_text_urls(text: str, include_link_urls: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:!?)]}")
        suffix = match.group(0)[len(url) :]
        if include_link_urls:
            return f"[{_link_label('', url)}]({url}){suffix}"
        return f"[{_link_label('', url)}]{suffix}"

    return re.sub(r'https?://[^\s<>\]\)）}。，！？；：、"\']+', replace, text)


def _format_html_link(text: str, href: str | None, include_link_urls: bool) -> str:
    label = _link_label(text, href)
    if not include_link_urls or not href or not _is_http_url(href):
        return text or label
    if _is_http_url(text):
        label = _link_label("", href)
    link = f"[{label}]({href})"
    return f"\n\n{link}\n\n" if _looks_like_call_to_action(label) else link


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_call_to_action(label: str) -> bool:
    words = label.strip().split()
    return 1 <= len(words) <= 4 and any(char.isalpha() for char in label)


def _looks_like_tracking_pixel(attrs: dict[str, str | None]) -> bool:
    width = _parse_dimension(attrs.get("width"))
    height = _parse_dimension(attrs.get("height"))
    return width is not None and height is not None and width <= 1 and height <= 1


def _parse_dimension(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _clean_inline_text(value: str) -> str:
    return re.sub(r"[\[\]\n\r]+", " ", html.unescape(value)).strip() or "mail image"


def _clean_link_text(value: str) -> str:
    return re.sub(r"[\[\]\n\r]+", " ", html.unescape(value)).strip()


def _link_label(text: str, href: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if cleaned and not _is_http_url(cleaned) and len(cleaned) <= 80:
        return cleaned

    if href and _is_http_url(href):
        parsed = urlparse(href)
        host = parsed.netloc.removeprefix("www.")
        return host or "link"

    return cleaned[:80] if cleaned else "link"
