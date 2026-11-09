import os

from electrum.logging import read_latest_logs

from . import ElectrumTestCase


class TestReadLatestLogs(ElectrumTestCase):

    def _write(self, name: str, content: bytes):
        with open(os.path.join(self.electrum_path, name), "wb") as f:
            f.write(content)

    def test_no_logs(self):
        self.assertEqual("", read_latest_logs(self.electrum_path))

    def test_ignores_other_files(self):
        self._write("some_other_file.txt", b"not a log\n")
        self.assertEqual("", read_latest_logs(self.electrum_path))

    def test_files_are_returned_oldest_first(self):
        self._write("electrum_log_20260101T000000Z_1.log", b"run1\n")
        self._write("electrum_log_20260102T000000Z_2.log.2", b"run2 oldest\n")
        self._write("electrum_log_20260102T000000Z_2.log.1", b"run2 older\n")
        self._write("electrum_log_20260102T000000Z_2.log", b"run2 newest\n")
        self.assertEqual(
            "run1\nrun2 oldest\nrun2 older\nrun2 newest\n",
            read_latest_logs(self.electrum_path))

    def test_only_the_end_is_returned_starting_with_a_whole_line(self):
        self._write("electrum_log_20260101T000000Z_1.log", b"old line that will not fit\n")
        self._write("electrum_log_20260102T000000Z_2.log", b"aaaaaaaaaa\nbbbbbbbbbb\ncccccccccc\n")
        self.assertEqual(
            "bbbbbbbbbb\ncccccccccc\n",
            read_latest_logs(self.electrum_path, max_size=30))

    def test_end_can_span_several_files(self):
        self._write("electrum_log_20260101T000000Z_1.log", b"aaaaaaaaaa\nbbbbbbbbbb\n")
        self._write("electrum_log_20260102T000000Z_2.log", b"cccccccccc\n")
        self.assertEqual(
            "bbbbbbbbbb\ncccccccccc\n",
            read_latest_logs(self.electrum_path, max_size=25))

    def test_invalid_utf8_does_not_raise(self):
        self._write("electrum_log_20260101T000000Z_1.log", b"ok \xff\xfe line\n")
        self.assertIn("ok", read_latest_logs(self.electrum_path))
