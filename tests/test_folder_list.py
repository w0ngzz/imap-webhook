import unittest

from imap_gotify.login_test import _decode_modified_utf7, _parse_list_response


class FolderListTest(unittest.TestCase):
    def test_decodes_modified_utf7_folder_name(self) -> None:
        self.assertEqual(_decode_modified_utf7("&V4NXPpCuTvY-"), "垃圾邮件")

    def test_parse_list_response_returns_raw_and_display_name(self) -> None:
        item = _parse_list_response(b'(\\HasNoChildren \\Junk) "/" "&V4NXPpCuTvY-"')

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.name, "&V4NXPpCuTvY-")
        self.assertEqual(item.display_name, "垃圾邮件")
        self.assertEqual(item.delimiter, "/")
        self.assertEqual(item.flags, "\\HasNoChildren \\Junk")


if __name__ == "__main__":
    unittest.main()
