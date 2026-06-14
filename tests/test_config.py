import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from imap_gotify.config import load_config


class ConfigTest(unittest.TestCase):
    def test_mailbox_ignore_before_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "gotify": {"url": "https://gotify.example.com", "token": "token"},
                        "mailboxes": [
                            {
                                "name": "mail",
                                "host": "imap.example.com",
                                "username": "user",
                                "password": "password",
                                "ignore_before": "2026-06-13T00:00:00+08:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertIsNotNone(config.mailboxes[0].ignore_before)
        self.assertEqual(
            config.mailboxes[0].ignore_before,
            datetime.fromisoformat("2026-06-13T00:00:00+08:00"),
        )


if __name__ == "__main__":
    unittest.main()
