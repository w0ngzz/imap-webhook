import unittest

from imap_gotify.mail_markdown import parse_message, to_markdown


class MailMarkdownTest(unittest.TestCase):
    def test_html_message_to_markdown(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: =?utf-8?b?5rWL6K+V6YKu5Lu2?=\r\n"
            b"Message-ID: <x@example.com>\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b"<h1>Hello</h1><p><b>CPU</b> high<br>"
            b'<a href="https://example.com">open</a></p>'
        )

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("**Subject**: 测试邮件", markdown)
        self.assertIn("# Hello", markdown)
        self.assertIn("**CPU** high", markdown)
        self.assertIn("[open](https://example.com)", markdown)

    def test_html_message_can_keep_links_and_remote_images(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: image\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b'<p><a href="https://example.com/very/long/path">open</a></p>'
            b'<img alt="chart" src="https://example.com/chart.png">'
            b'<img width="1" height="1" src="https://example.com/pixel.gif">'
        )

        markdown = to_markdown(
            parse_message(
                raw,
                4000,
                include_link_urls=True,
                include_remote_images=True,
            )
        )

        self.assertIn("[open](https://example.com/very/long/path)", markdown)
        self.assertIn("![chart](https://example.com/chart.png)", markdown)
        self.assertNotIn("pixel.gif", markdown)

    def test_html_message_ignores_css_and_head_content(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: css\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b"<html><head><title>Hidden title</title>"
            b"<style>#outlook a { padding:0; } @media only screen { body { color:red; } }</style>"
            b"</head><body><h1>Card frozen</h1><p>Your card has been frozen.</p></body></html>"
        )

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("# Card frozen", markdown)
        self.assertIn("Your card has been frozen.", markdown)
        self.assertNotIn("#outlook", markdown)
        self.assertNotIn("@media", markdown)
        self.assertNotIn("Hidden title", markdown)

    def test_html_url_text_gets_short_label(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: link\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b'<a href="https://example.com/some/really/long/tracking/url?token=abcdef">'
            b"https://example.com/some/really/long/tracking/url?token=abcdef</a>"
        )

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("[example.com](https://example.com/some/really/long/tracking/url?token=abcdef)", markdown)
        self.assertNotIn("]https://", markdown)

    def test_html_long_tracking_links_are_not_inlined(self) -> None:
        long_url = "https://www.paypal.com/hk/smarthelp/home?" + "utm_campaign=" + ("x" * 180)
        raw = (
            "From: Alice <alice@example.com>\r\n"
            "To: me@example.com\r\n"
            "Subject: tracking\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            f"<table><tr><td>    <a href=\"{long_url}\">Help and Contact</a></td></tr></table>"
            "<p>Shipment address</p>"
        ).encode("utf-8")

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn(f"[Help and Contact]({long_url})", markdown)
        self.assertIn("Shipment address", markdown)
        self.assertNotIn("\n    Help and Contact", markdown)

    def test_html_layout_tables_are_flattened_not_markdown_tables(self) -> None:
        raw = (
            b"From: DoorDash <no-reply@doordash.com>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: login\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b"<table><tr><td><a href=\"https://www.doordash.com\">doordash.com</a></td></tr>"
            b"<tr><td>New login to your DoorDash account</td></tr>"
            b"<tr><td><table><tr><td>When: 6/13/26</td><td>Device Type: Windows</td></tr></table></td></tr>"
            b"</table>"
        )

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("[doordash.com](https://www.doordash.com)", markdown)
        self.assertIn("New login to your DoorDash account", markdown)
        self.assertIn("Device Type: Windows", markdown)
        self.assertNotIn("| ---", markdown)
        self.assertNotIn("| |", markdown)

    def test_html_url_text_uses_short_label_for_tracking_href(self) -> None:
        long_url = "http://email.mg.ether.fi/c/" + ("x" * 220)
        raw = (
            "From: Ether.fi <info@ether.fi>\r\n"
            "To: me@example.com\r\n"
            "Subject: card\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<table>"
            "<tr><td>Card ...8543 has been frozen</td></tr>"
            "<tr><td>Your card ending in 8543 has been successfully frozen.</td></tr>"
            f"<tr><td><a href=\"{long_url}\">{long_url}</a></td></tr>"
            "</table>"
        ).encode("utf-8")

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("Card ...8543 has been frozen", markdown)
        self.assertIn("Your card ending in 8543", markdown)
        self.assertIn(f"[email.mg.ether.fi]({long_url})", markdown)
        self.assertNotIn(f"]({long_url})\n\n[email.mg.ether.fi]", markdown)
        self.assertNotIn(f"[{long_url}]", markdown)

    def test_truncation_does_not_cut_inside_markdown_link(self) -> None:
        long_url = "http://email.mg.ether.fi/c/" + ("x" * 500)
        raw = (
            "From: Ether.fi <info@ether.fi>\r\n"
            "To: me@example.com\r\n"
            "Subject: card\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<p>Card ...8543 has been frozen</p>"
            "<p>Your card cannot be used while frozen.</p>"
            f"<p><a href=\"{long_url}\">{long_url}</a></p>"
        ).encode("utf-8")

        markdown = to_markdown(parse_message(raw, 50))

        self.assertIn("Card ...8543 has been frozen", markdown)
        self.assertIn("...content truncated", markdown)
        self.assertNotIn("xxxxxxxxxxxxxxxxxxxxxxxx", markdown)

    def test_truncation_counts_link_label_not_href(self) -> None:
        long_url = "http://email.mg.ether.fi/c/" + ("x" * 500)
        raw = (
            "From: Ether.fi <info@ether.fi>\r\n"
            "To: me@example.com\r\n"
            "Subject: card\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<p>Card frozen</p>"
            "<p>Your card cannot be used while frozen.</p>"
            f"<p><a href=\"{long_url}\">View Cards</a></p>"
            "<p>Please contact us if you have any questions.</p>"
        ).encode("utf-8")

        markdown = to_markdown(parse_message(raw, 120))

        self.assertIn(f"[View Cards]({long_url})", markdown)
        self.assertIn("Please contact us", markdown)
        self.assertNotIn("...content truncated", markdown)

    def test_layout_rows_get_paragraph_spacing(self) -> None:
        raw = (
            b"From: Ether.fi <info@ether.fi>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: card\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"\r\n"
            b"<table>"
            b"<tr><td>Card frozen</td></tr>"
            b"<tr><td>Your card cannot be used while frozen.</td></tr>"
            b"<tr><td>You can unfreeze your card at any time.</td></tr>"
            b"</table>"
        )

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("Card frozen\n\nYour card cannot be used", markdown)
        self.assertIn("while frozen.\n\nYou can unfreeze", markdown)

    def test_plain_text_long_urls_use_markdown_link_by_default(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\r\n"
            b"To: me@example.com\r\n"
            b"Subject: link\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Open https://example.com/some/really/long/tracking/url?token=abcdef"
        )

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("[example.com](https://example.com/some/really/long/tracking/url?token=abcdef)", markdown)

    def test_plain_text_url_stops_before_cjk_punctuation(self) -> None:
        raw = (
            "From: Alice <alice@example.com>\r\n"
            "To: me@example.com\r\n"
            "Subject: link\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Open https://www.example.com）点击继续"
        ).encode("utf-8")

        markdown = to_markdown(parse_message(raw, 4000))

        self.assertIn("[example.com](https://www.example.com)）点击继续", markdown)


if __name__ == "__main__":
    unittest.main()
