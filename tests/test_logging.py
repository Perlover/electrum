import logging
import os
import pathlib
import tempfile
from unittest import mock

from electrum import logging as electrum_logging
from electrum.logging import redact_log_text, read_recent_logs, set_file_logging
from electrum.simple_config import SimpleConfig

from . import ElectrumTestCase


class TestRedactLogText(ElectrumTestCase):

    NODE_ID = '03' + 'ab' * 32  # 66 hex: a public node, kept
    HASH = 'cd' * 32  # 64 hex: a payment hash, a txid, a channel id

    def test_what_identifies_the_user_is_removed(self):
        for text, expected in (
            ('pay_invoice lnbc1500n1pj9xyzpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq ok', 'pay_invoice <invoice> ok'),
            ('offer lno1qgsqvgnwgcg35z6ee2h3yczraddm72xrfua9uve2rlrm9deu7xyfzrc2qajx2enpw4k8g93pq', 'offer <bolt12>'),
            ('lnurl LNURL1DP68GURN8GHJ7UM9WFMXJCM99E3K7MF0V9CXJ0M385EKVCENXC6R2C35XVUKXEFCV5MKVV34X5EKZD3EV56NYD3HXQURZEPEXEJXXEPNXSCRVWFNV9NXZCN9XQ6XYEFHVGCXXCMYXYMNSERXFQ5FNS', 'lnurl <lnurl>'),
            ('to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq.', 'to <address>.'),
            ('to tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx', 'to <address>'),
            ('to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2 and 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy', 'to <address> and <address>'),
            ('xpub xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8',
             'xpub <xkey>'),
            (f'RHASH={self.HASH}. txid {self.HASH}:1', 'RHASH=<hash>. txid <hash>:1'),
            ('peer 203.0.113.7:9735 and [2001:db8::1]:9735 and 2001:0db8:85a3:0000:0000:8a2e:0370:7334',
             'peer <ip>:9735 and [<ip>]:9735 and <ip>'),
            ('tor ' + 'a' * 56 + '.onion:9735', 'tor <onion>:9735'),
        ):
            self.assertEqual(expected, redact_log_text(text), msg=text)

    def test_what_is_about_the_network_is_kept(self):
        for text in (
            f'error reported by {self.NODE_ID}',
            'route: 0211111111 -[800000x100x1 1000+1ppm cltv 144]-> 0322222222',
            'requesting channel graph since 2026-11-15T09:50:21, for 24915 seconds',
            '20261116T015645.543541Z |     INFO | lnworker.PaySession.[d9f3aa74-419e] | amount_to_pay=164927000 msat',
            'Electrum version: 4.8.4. code=<OnionFailureCode.TEMPORARY_CHANNEL_FAILURE: 4103>',
            'gossip_db status. sync progress: (26556, 26556, 100). num_nodes=11496',
        ):
            self.assertEqual(text, redact_log_text(text), msg=text)

    def test_private_strings_are_removed_too(self):
        our_node_id = '02' + '11' * 32
        text = (f'created LNWallet[my wallet] with nodeID={our_node_id}. '
                f'route: {our_node_id[:10]} -[800000x100x1 1000+1ppm]-> 0322222222 -[700000x200x0]->')
        redacted = redact_log_text(text, private_strings=[our_node_id, our_node_id[:10], '800000x100x1', 'my wallet', 'ab'])
        self.assertEqual(
            'created LNWallet[<private>] with nodeID=<private>. route: <private> -[<private> 1000+1ppm]-> 0322222222 -[700000x200x0]->',
            redacted)
        self.assertEqual('a cab b', redact_log_text('a cab b', private_strings=['ab', '']))  # too short to remove


class TestReadRecentLogs(ElectrumTestCase):

    def setUp(self):
        super().setUp()
        self.config = SimpleConfig({'electrum_path': self.electrum_path})
        self.log_dir = pathlib.Path(self.config.path) / 'logs'
        self.log_dir.mkdir()

    def _write(self, name: str, lines):
        with open(self.log_dir / name, 'w', encoding='utf-8') as f:
            f.write(''.join(line + '\n' for line in lines))

    def test_newest_files_come_last_and_the_text_starts_at_a_whole_line(self):
        self._write('electrum_log_20261114T000000Z_1.log', ['old-1', 'old-2'])
        self._write('electrum_log_20261115T000000Z_2.log.1', ['mid-1', 'mid-2'])  # rotated: older than .log
        self._write('electrum_log_20261115T000000Z_2.log', ['new-1', 'new-2'])
        self._write('something-else.txt', ['not a log'])
        self.assertEqual('old-1\nold-2\nmid-1\nmid-2\nnew-1\nnew-2\n', read_recent_logs(self.config, max_size=1000))
        self.assertEqual('mid-2\nnew-1\nnew-2\n', read_recent_logs(self.config, max_size=20))
        self.assertEqual('new-2\n', read_recent_logs(self.config, max_size=7))
        self.assertEqual('new-1\nnew-2\n', read_recent_logs(self.config, max_size=12))

    def test_no_logs(self):
        self.assertEqual('', read_recent_logs(self.config, max_size=1000))
        os.rmdir(self.log_dir)
        self.assertEqual('', read_recent_logs(self.config, max_size=1000))


class TestSetFileLogging(ElectrumTestCase):

    def setUp(self):
        super().setUp()
        self.config = SimpleConfig({'electrum_path': self.electrum_path})
        if electrum_logging.get_logfile_path() is not None:
            self.skipTest('the test process writes logs to a file already')
        self.addCleanup(set_file_logging, self.config, False)

    def test_file_logging_starts_and_stops_while_running(self):
        set_file_logging(self.config, True)
        path = electrum_logging.get_logfile_path()
        self.assertEqual(pathlib.Path(self.config.path) / 'logs', path.parent)
        logger = electrum_logging.get_logger('test_file_logging')
        logger.info('written to the file')
        set_file_logging(self.config, True)  # again: nothing changes
        self.assertEqual(path, electrum_logging.get_logfile_path())
        set_file_logging(self.config, False)
        self.assertIsNone(electrum_logging.get_logfile_path())
        logger.info('not written any more')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('written to the file', content)
        self.assertNotIn('not written any more', content)
        self.assertIn('written to the file', read_recent_logs(self.config, max_size=10_000))
        set_file_logging(self.config, False)  # again: nothing changes

    def test_a_debug_build_always_writes_logs(self):
        set_file_logging(self.config, True)
        with mock.patch('electrum.util.is_android_debug_apk', return_value=True):
            set_file_logging(self.config, False)
        self.assertIsNotNone(electrum_logging.get_logfile_path())
