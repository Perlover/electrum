import os
import pathlib
from unittest import mock

from electrum import logging as electrum_logging
from electrum.logging import redact_log_text, read_recent_logs, set_file_logging, filter_log_for_sharing, what_identifies_us_in_logs
from electrum.simple_config import SimpleConfig

from . import ElectrumTestCase


def _line(logger: str, message: str, level: str = 'INFO') -> str:
    return f'20261116T015645.543541Z | {level:>8} | {logger} | {message}\n'


class TestFilterLogForSharing(ElectrumTestCase):

    def test_only_the_entries_about_lightning_payments_and_the_graph_are_kept(self):
        kept = [
            _line('lnworker.PaySession.[d9f3aa74-419e]', 'pay_to_node starting session'),
            _line('lnworker.LNWallet.[w]', 'sent htlc 1 over 800000x100x1: amount=1000 msat'),
            _line('lnrouter.LNPathFinder', 'found a path. cost=1'),
            _line('lnpeer.Peer.[w, 0322222222-1a2b3c4d]', 'Received INIT', 'DEBUG'),
            _line('channel_db.ChannelDB', 'Deleting 3 orphaned channels'),
            _line('gossip_catch_up', 'catch-up on gossip in the background every 120 minutes'),
            _line('lnworker.LNWallet.[w]', 'Exception in pay_to_node: PaymentFailure()', 'ERROR')
            + 'Traceback (most recent call last):\n  File "lnworker.py", line 1\nPaymentFailure\n',
        ]
        dropped = [
            _line('lnchannel.Channel.[w, 0x1x1]', "sign_next_commitment. psbt='cHNidP8BAN8CAAAAAVY'", 'DEBUG'),
            _line('interface.[myhome.example:50002]', 'connection established'),
            _line('gui.qml.qeinvoice', "outputs=[<TxOutput address=bc1q value=1>] message='rent'"),
            _line('wallet.Standard_Wallet.[w]', 'adding tx'),
            _line('lnwatcher.LNWatcher', 'sweeping'),
            _line('storage.WalletStorage', 'wallet path /data/wallets/w'),
        ]
        text = ''.join(kept[:3] + dropped[:3] + kept[3:] + dropped[3:])
        self.assertEqual(''.join(kept), filter_log_for_sharing(text))
        self.assertEqual('', filter_log_for_sharing('not a log line\n'))


class TestRedactLogText(ElectrumTestCase):

    NODE_ID = '03' + 'ab' * 32  # 66 hex: a public node, kept
    HASH = 'cd' * 32

    def test_what_identifies_the_user_is_replaced(self):
        for text, expected in (
            ('pay_invoice lnbc1500n1pj9xyzpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdq ok', 'pay_invoice <invoice 1> ok'),
            ('uri lightning:LNBC1500N1PJ9XYZPP5QQQSYQCYQ5RQWZQFQQQSYQCYQ5RQWZQFQQQSYQCYQ5RQWZQFQYPQDQ', 'uri <invoice 1>'),
            ('offer lno1qgsqvgnwgcg35z6ee2h3yczraddm72xrfua9uve2rlrm9deu7xyfzrc2qajx2enpw4k8g93pq', 'offer <invoice 1>'),
            ('lnurl LNURL1DP68GURN8GHJ7UM9WFMXJCM99E3K7MF0V9CXJ0M385EKVCENXC6R2C35XVUKXEFCV5MKVV34X5EKZD3EV56NYD3HXQURZEPEXEJXXEPNXSCRVWFNV9NXZCN9XQ6XYEFHVGCXXCMYXYMNSERXFQ5FNS', 'lnurl <lnurl 1>'),
            ('to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq and BC1QAR0SRRR7XFKVY5L643LYDNW9RE59GTZZWF5MDQ.', 'to <address 1> and <address 2>.'),
            ('to bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297 and bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080',
             'to <address 1> and <address 2>'),
            ('to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2 and 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy', 'to <address 1> and <address 2>'),
            ('key xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8',
             'key <key 1>'),
            ('wif L1aW4aubDFB7yfras2S1mN3bqg9nwySY8nkoLmJebSLD5BWv3ENZ', 'wif <key 1>'),
            (f'RHASH={self.HASH}. txid {self.HASH}:1, again {self.HASH}', 'RHASH=<hash 1>. txid <hash 1>:1, again <hash 1>'),
            (f"payment_key='{self.HASH}{'ef' * 32}'", "payment_key='<hash 1>'"),  # hash and secret together
            ("htlc: UpdateAddHtlc(amount_msat=1, payment_hash=b'\\xe8\\xb6\\xec>\\xcc+\\'x', cltv_abs=600147)",
             "htlc: UpdateAddHtlc(amount_msat=1, payment_hash=<bytes 1>, cltv_abs=600147)"),
            ("{'payment_secret': b\" \\x90\\xd2'\\xceQb\"}", "{'payment_secret': <bytes 1>}"),
            ("psbt='cHNidP8BAN8CAAAAAVYaijTIyjVkVrTTgLtSyhbZ/qi9tGFAPpXdD2gtKKZ5AAAAAAD/////'", "psbt='<data 1>'"),
            ('<TxOutput script=0014e8df018c7e326cc253faac7e46cdc51e68542c42 value=1>', '<TxOutput script=<hash 1> value=1>'),
            ('peer 203.0.113.7:9735, 203.0.113.7. and [2001:db8::1]:9735 and fe80:: and ::ffff:192.0.2.1 and '
             '2001:0db8:85a3:0000:0000:8a2e:0370:7334',
             'peer <ip 5>:9735, <ip 5>. and [<ip 2>]:9735 and <ip 3> and <ip 4> and <ip 1>'),
            ('tor ' + 'A' * 56 + '.ONION:9735', 'tor <onion 1>:9735'),
            ("channels_with_funds: {(b'\\xeaV', b'\\x03\\xb6'): (499980692000, 5)}, have_direct_channel=False",
             'channels_with_funds: <balances>, have_direct_channel=False'),
            (_line('lnworker.PaySession.[d9f3aa74-419e]', 'waiting'), _line('lnworker.PaySession.[<payment 1>]', 'waiting')),
            (_line('lnworker.LNWallet.[my wallet]', 'x') + _line('lnpeer.Peer.[my wallet, 0322222222-1a2b3c4d]', 'y')
             + _line('lnpeer.Peer.[LNGossip, 0322222222-1a2b3c4d]', 'z') + _line('lnworker.LNPeerManager.[LNGossip]', 'w'),
             _line('lnworker.LNWallet.[<wallet 1>]', 'x') + _line('lnpeer.Peer.[<wallet 1>, 0322222222-1a2b3c4d]', 'y')
             + _line('lnpeer.Peer.[LNGossip, 0322222222-1a2b3c4d]', 'z') + _line('lnworker.LNPeerManager.[LNGossip]', 'w')),
            ('load wallet /data/user/0/org.electrum.electrum/files/data/wallets/savings',
             'load wallet /data/user/0/org.electrum.electrum/files/data/wallets/<wallet 1>'),
            ('interface.[myhome.example:50002] | connected', 'interface.[<server 1>] | connected'),
        ):
            self.assertEqual(expected, redact_log_text(text), msg=text)

    def test_what_is_about_the_network_is_kept(self):
        for text in (
            f'error reported by {self.NODE_ID}',
            '0322222222 -[700000x5x0 0+0ppm cltv 40]-> 0344444444',  # (a route starts with us: see below)
            'requesting channel graph since 2026-11-15T09:50:21, for 24915 seconds',
            _line('lnworker.LNGossip', 'amount_to_pay=164927000 msat. caught up on gossip in 90 seconds'),
            'Electrum version: 4.8.4. code=<OnionFailureCode.TEMPORARY_CHANNEL_FAILURE: 4103>',
            'gossip_db status. sync progress: (26556, 26556, 100). num_nodes=11496',
            'htlc failed at edge 3 of 4 (channel 700123x456x7)',
        ):
            self.assertEqual(text, redact_log_text(text), msg=text)

    def test_our_node_channels_and_wallets_are_replaced_and_numbered(self):
        our_node_id = '02' + '11' * 32
        text = (f'nodeID={our_node_id}. route: {our_node_id[:10]} -[800000x100x1 1000+1ppm]-> 0322222222 '
                f'-[800000x100x12]-> 0344444444, again 800000x100x1 and 800000x100x2 of wallet a, not of "wallet ab"')
        self.assertEqual(
            'nodeID=<our node 1>. route: <our node 2> -[<our channel 1> 1000+1ppm]-> 0322222222 '
            '-[800000x100x12]-> 0344444444, again <our channel 1> and <our channel 2> of <wallet 1>, not of "wallet ab"',
            redact_log_text(text, our_node_ids=[our_node_id], our_channels=['800000x100x1', '800000x100x2'],
                            wallet_names=['wallet a', 'ab']))

    def test_our_node_and_channels_are_found_where_the_log_says_they_are_ours(self):
        # e.g. in the logs of a wallet that is not loaded when they get shared
        text = ('sent htlc 6 over 800000x100x1: amount=1000 msat, fee=1 msat. '
                'route: 0211111111 -[800000x100x1 1000+1ppm cltv 144, own channel]-> 0322222222 -[700000x5x0 0+0ppm]-> 0344444444\n'
                'htlc succeeded. route: 0211111111 -[800000x200x0 1000+1ppm]-> 0355555555\n'
                'report 800000x100x1 to be able to forward 1000 msat. 0211111111 is us\n')
        self.assertEqual(
            'sent htlc 6 over <our channel 1>: amount=1000 msat, fee=1 msat. '
            'route: <our node 1> -[<our channel 1> 1000+1ppm cltv 144, own channel]-> 0322222222 -[700000x5x0 0+0ppm]-> 0344444444\n'
            'htlc succeeded. route: <our node 1> -[<our channel 2> 1000+1ppm]-> 0355555555\n'
            'report <our channel 1> to be able to forward 1000 msat. <our node 1> is us\n',
            redact_log_text(text))
        # our whole node id, once the log shows the start of it is ours
        self.assertEqual('route: <our node 1> -[<our channel 1> 1+1ppm]-> 0322222222. <our node 2> and ' + self.NODE_ID,
                         redact_log_text('route: 0211111111 -[800000x1x1 1+1ppm]-> 0322222222. 0211111111' + '22' * 28
                                         + ' and ' + self.NODE_ID))

    def test_home_directory_is_replaced(self):
        home = os.path.expanduser('~')
        self.assertEqual('File "~/electrum/lnworker.py", line 1',
                         redact_log_text(f'File "{home}/electrum/lnworker.py", line 1'))

    def test_large_text_is_redacted_in_reasonable_time(self):
        import time
        text = _line('lnworker.LNWallet.[w]', f'sent htlc 1 over 800000x100x1: RHASH={self.HASH} route: '
                     '0211111111 -[800000x100x1 1000+1ppm]-> 0322222222') * 20_000  # ~4 MB
        t0 = time.monotonic()
        redact_log_text(text)
        self.assertLess(time.monotonic() - t0, 30)


class TestWhatIdentifiesUs(ElectrumTestCase):

    def test_what_identifies_us_in_the_logs_comes_from_the_wallets(self):
        from electrum.lnutil import ShortChannelID
        chan = mock.Mock(short_channel_id=ShortChannelID.from_components(800000, 100, 1))
        chan.get_local_scid_alias.return_value = ShortChannelID.from_components(16000000, 1, 2)
        chan.get_remote_scid_alias.return_value = None
        backup = mock.Mock(short_channel_id=None)
        backup.get_local_scid_alias.return_value = None
        backup.get_remote_scid_alias.return_value = ShortChannelID.from_components(16000000, 3, 4)
        with_lightning = mock.Mock()
        with_lightning.basename.return_value = 'savings'
        with_lightning.lnworker.node_keypair.pubkey = bytes.fromhex('02' + '11' * 32)
        with_lightning.lnworker.channels = {b'1': chan}
        with_lightning.lnworker.channel_backups = {b'2': backup}
        without_lightning = mock.Mock(lnworker=None)
        without_lightning.basename.return_value = 'cold'
        self.assertEqual(
            {'our_node_ids': ['02' + '11' * 32], 'our_channels': ['800000x100x1', '16000000x1x2', '16000000x3x4'],
             'wallet_names': ['savings', 'cold']},
            what_identifies_us_in_logs([with_lightning, without_lightning]))
        self.assertEqual({'our_node_ids': [], 'our_channels': [], 'wallet_names': []}, what_identifies_us_in_logs([]))


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
        self.assertEqual('new-1\nnew-2\n', read_recent_logs(self.config, max_size=12))  # a whole file
        self.assertEqual('new-2\n', read_recent_logs(self.config, max_size=6))  # starts right at a line

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
        logger.warning('written to the file')
        set_file_logging(self.config, True)  # again: nothing changes
        self.assertEqual(path, electrum_logging.get_logfile_path())
        set_file_logging(self.config, False)
        self.assertIsNone(electrum_logging.get_logfile_path())
        logger.warning('not written any more')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('written to the file', content)
        self.assertNotIn('not written any more', content)
        set_file_logging(self.config, False)  # again: nothing changes
        # switched on again within the same second: a new file, the first one is kept
        set_file_logging(self.config, True)
        self.assertNotEqual(path, electrum_logging.get_logfile_path())
        with open(path, encoding='utf-8') as f:
            self.assertEqual(content, f.read())

    def test_a_debug_build_always_writes_logs(self):
        set_file_logging(self.config, True)
        with mock.patch('electrum.util.is_android_debug_apk', return_value=True):
            set_file_logging(self.config, False)
        self.assertIsNotNone(electrum_logging.get_logfile_path())
