# Copyright (C) 2019 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

import logging
import logging.handlers
import datetime
from functools import lru_cache
import sys
import pathlib
import os
import platform
import re
from typing import Optional, TYPE_CHECKING, Set, Iterable, List
import copy
import subprocess
import hashlib

if TYPE_CHECKING:
    from .simple_config import SimpleConfig
    from .wallet import Abstract_Wallet


class LogFormatterForFiles(logging.Formatter):

    def formatTime(self, record, datefmt=None):
        # timestamps follow ISO 8601 UTC
        date = datetime.datetime.fromtimestamp(record.created).astimezone(datetime.timezone.utc)
        if not datefmt:
            datefmt = "%Y%m%dT%H%M%S.%fZ"
        return date.strftime(datefmt)

    def format(self, record):
        record = _shorten_name_of_logrecord(record)
        return super().format(record)


file_formatter = LogFormatterForFiles(fmt="%(asctime)22s | %(levelname)8s | %(name)s | %(message)s")


class LogFormatterForConsole(logging.Formatter):

    def formatTime(self, record, datefmt=None):
        t = record.relativeCreated / 1000
        return f"{t:6.2f}"

    def format(self, record):
        record = copy.copy(record)  # avoid mutating arg
        record = _shorten_name_of_logrecord(record)
        text = super().format(record)
        return text


# try to make console log lines short... no timestamp, short levelname, no "electrum."
console_formatter = LogFormatterForConsole(fmt="%(asctime)s | %(levelname).1s | %(name)s | %(message)s")


def _shorten_name_of_logrecord(record: logging.LogRecord) -> logging.LogRecord:
    record = copy.copy(record)  # avoid mutating arg
    # strip the main module name from the logger name
    if record.name.startswith("electrum."):
        record.name = record.name[9:]
    # manual map to shorten common module names
    record.name = record.name.replace("interface.Interface", "interface", 1)
    record.name = record.name.replace("network.Network", "network", 1)
    record.name = record.name.replace("synchronizer.Synchronizer", "synchronizer", 1)
    record.name = record.name.replace("verifier.SPV", "verifier", 1)
    record.name = record.name.replace("gui.qt.main_window.ElectrumWindow", "gui.qt.main_window", 1)
    return record


class TruncatingMemoryHandler(logging.handlers.MemoryHandler):
    """An in-memory log handler that only keeps the first N log messages
    and discards the rest.
    """
    target: Optional['logging.Handler']

    def __init__(self):
        logging.handlers.MemoryHandler.__init__(
            self,
            capacity=1,  # note: this is the flushing frequency, ~unused by us
            flushLevel=logging.DEBUG,
        )
        self.max_size = 100  # max num of messages we keep
        self.num_messages_seen = 0
        self.__never_dumped = True

    # note: this flush implementation *keeps* the buffer as-is, instead of clearing it
    def flush(self):
        self.acquire()
        try:
            if self.target:
                for record in self.buffer:
                    if record.levelno >= self.target.level:
                        self.target.handle(record)
        finally:
            self.release()

    def dump_to_target(self, target: 'logging.Handler'):
        self.acquire()
        try:
            self.setTarget(target)
            self.flush()
            self.setTarget(None)
        finally:
            self.__never_dumped = False
            self.release()

    def emit(self, record):
        self.num_messages_seen += 1
        if len(self.buffer) < self.max_size:
            super().emit(record)

    def close(self) -> None:
        # Check if captured log lines were never to dumped to e.g. stderr,
        # and if so, try to do it now. This is useful e.g. in case of sys.exit().
        if self.__never_dumped:
            _configure_stderr_logging()
        super().close()


def _sortkey_of_log_file_oldest_first(p: pathlib.PurePath):
    fname = p.name
    basename, ext, counter = str(fname).partition(".log")
    # - each time electrum is launched, there will be a new basename, ordered by date
    # - for any given basename, there might be multiple log files, differing by counter
    #   - empty counter is newest, then .1 is older, .2 is even older, etc
    try:
        counter = int(counter[1:]) if counter else 0  # convert ".2" -> 2
    except ValueError:
        _logger.warning(f"failed to parse log file name: {fname}")
        counter = 0
    return basename, -counter


def _log_files_oldest_first(path) -> List[pathlib.Path]:
    return sorted(pathlib.Path(path).glob("electrum_log_*.log*"), key=_sortkey_of_log_file_oldest_first)


def _delete_old_logs(path, *, num_files_keep: int, max_total_size: int):
    """Delete old logfiles, only keeping the latest few."""
    files = _log_files_oldest_first(path)
    total_size = sum(os.stat(f).st_size for f in files)  # in bytes
    num_files_remaining = len(files)
    for f in files:
        fsize = os.stat(f).st_size
        if total_size < max_total_size and num_files_remaining <= num_files_keep:
            break
        total_size -= fsize
        num_files_remaining -= 1
        try:
            os.remove(f)
        except OSError as e:
            _logger.warning(f"cannot delete old logfile: {e}")


_logfile_path = None
_file_handler = None  # type: Optional[logging.Handler]
def _configure_file_logging(
    log_directory: pathlib.Path,
    *,
    num_files_keep: int,
    max_total_size: int,
):
    from .util import os_chmod

    global _logfile_path, _file_handler
    assert _logfile_path is None, 'file logging already initialized'
    log_directory.mkdir(exist_ok=True, mode=0o700)

    _delete_old_logs(log_directory, num_files_keep=num_files_keep, max_total_size=max_total_size)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PID = os.getpid()
    _logfile_path = log_directory / f"electrum_log_{timestamp}_{PID}.log"
    num = 1
    while _logfile_path.exists():  # file logging got switched off and on again within the second
        _logfile_path = log_directory / f"electrum_log_{timestamp}_{PID}_{num}.log"
        num += 1
    # we create the file with restrictive perms, instead of letting FileHandler create it
    with open(_logfile_path, "w+") as f:
        os_chmod(_logfile_path, 0o600)

    logfile_backupcount = 4
    file_handler = logging.handlers.RotatingFileHandler(
        _logfile_path,
        maxBytes=max_total_size // (logfile_backupcount+1),
        backupCount=logfile_backupcount,
        encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    _file_handler = file_handler
    if _inmemory_startup_logs:
        _inmemory_startup_logs.dump_to_target(file_handler)


console_stderr_handler = None
def _configure_stderr_logging(*, verbosity=None):
    # log to stderr; by default only WARNING and higher
    global console_stderr_handler
    if console_stderr_handler is not None:
        _logger.warning("stderr handler already exists")
        return
    console_stderr_handler = logging.StreamHandler(sys.stderr)
    console_stderr_handler.setFormatter(console_formatter)
    if not verbosity:
        console_stderr_handler.setLevel(logging.WARNING)
        root_logger.addHandler(console_stderr_handler)
    else:
        console_stderr_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(console_stderr_handler)
        _process_verbosity_log_levels(verbosity)
    if _inmemory_startup_logs:
        _inmemory_startup_logs.dump_to_target(console_stderr_handler)


def _process_verbosity_log_levels(verbosity):
    if verbosity == '*' or not isinstance(verbosity, str):
        return
    # example verbosity:
    #   debug,network=error,interface=error      // effectively blacklists network and interface
    #   warning,network=debug,interface=debug    // effectively whitelists network and interface
    filters = verbosity.split(',')
    for filt in filters:
        if not filt: continue
        items = filt.split('=')
        if len(items) == 1:
            level = items[0]
            electrum_logger.setLevel(level.upper())
        elif len(items) == 2:
            logger_name, level = items
            logger = get_logger(logger_name)
            logger.setLevel(level.upper())
        else:
            raise Exception(f"invalid log filter: {filt}")


class _CustomLogger(logging.getLoggerClass()):
    def __init__(self, name, *args, **kwargs):
        super().__init__(name, *args, **kwargs)
        self.msg_hashes_seen = set()  # type: Set[bytes]
        # ^ note: size grows without bounds, but only for log lines using "only_once".

    def _log(self, level, msg: str, *args, only_once: bool = False, **kwargs) -> None:
        """Overridden to add 'only_once' arg to logger.debug()/logger.info()/logger.warning()/etc."""
        if only_once:  # if set, this logger will only log this msg a single time during its lifecycle
            msg_hash = hashlib.sha256(msg.encode("utf-8")).digest()
            if msg_hash in self.msg_hashes_seen:
                return
            self.msg_hashes_seen.add(msg_hash)
        super()._log(level, msg, *args, **kwargs)

logging.setLoggerClass(_CustomLogger)


# enable logs universally (including for other libraries)
root_logger = logging.getLogger()
root_logger.setLevel(logging.WARNING)

# Start collecting log messages now, into an in-memory buffer. This buffer is only
# used until the proper log handlers are fully configured, including their verbosity,
# at which point we will dump its contents into those, and remove this log handler.
# Note: this is set up at import-time instead of e.g. as part of a function that is
#       called from run_electrum (the main script). This is to have this run as early
#       as possible.
# Note: some users might use Electrum as a python library and not use run_electrum,
#       in which case these logs might never get redirected or cleaned up.
#       Also, the python docs recommend libraries not to set a handler, to
#       avoid interfering with the user's logging.
_inmemory_startup_logs = None
if getattr(sys, "_ELECTRUM_RUNNING_VIA_RUNELECTRUM", False):
    _inmemory_startup_logs = TruncatingMemoryHandler()
    root_logger.addHandler(_inmemory_startup_logs)

# creates a logger specifically for electrum library
electrum_logger = logging.getLogger("electrum")
electrum_logger.setLevel(logging.DEBUG)


# --- External API

def get_logger(name: str) -> _CustomLogger:
    prefix = "electrum."
    if name.startswith(prefix):
        name = name[len(prefix):]
    return electrum_logger.getChild(name)


_logger = get_logger(__name__)
_logger.setLevel(logging.INFO)


class Logger:

    def __init__(self):
        self.logger = self.__get_logger_for_obj()

    def __get_logger_for_obj(self) -> logging.Logger:
        cls = self.__class__
        if cls.__module__:
            name = f"{cls.__module__}.{cls.__name__}"
        else:
            name = cls.__name__
        try:
            diag_name = self.diagnostic_name()
        except Exception as e:
            raise Exception("diagnostic name not yet available?") from e
        if diag_name:
            name += f".[{diag_name}]"
        logger = get_logger(name)
        return logger

    def diagnostic_name(self):
        return ''


def configure_logging(config: 'SimpleConfig', *, log_to_file: Optional[bool] = None) -> None:
    from .util import is_android_debug_apk

    verbosity = config.get('verbosity')
    if not verbosity and config.GUI_ENABLE_DEBUG_LOGS:
        verbosity = '*'
    _configure_stderr_logging(verbosity=verbosity)

    if log_to_file is None:
        log_to_file = config.WRITE_LOGS_TO_DISK
        log_to_file |= is_android_debug_apk()
    if log_to_file:
        log_directory = pathlib.Path(config.path) / "logs"
        num_files_keep = config.LOGS_NUM_FILES_KEEP
        max_total_size = config.LOGS_MAX_TOTAL_SIZE_BYTES
        _configure_file_logging(log_directory, num_files_keep=num_files_keep, max_total_size=max_total_size)

    # clean up and delete in-memory logs
    global _inmemory_startup_logs
    if _inmemory_startup_logs:
        num_discarded = _inmemory_startup_logs.num_messages_seen - _inmemory_startup_logs.max_size
        if num_discarded > 0:
            _logger.warning(f"Too many log messages! Some have been discarded. "
                            f"(discarded {num_discarded} messages)")
        _inmemory_startup_logs.close()
        root_logger.removeHandler(_inmemory_startup_logs)
        _inmemory_startup_logs = None

    from . import ELECTRUM_VERSION
    from .constants import GIT_REPO_URL
    _logger.info(f"Electrum version: {ELECTRUM_VERSION} - https://electrum.org - {GIT_REPO_URL}")
    _logger.info(f"Python version: {sys.version}. On platform: {describe_os_version()}")
    _logger.info(f"Logging to file: {str(_logfile_path)}")
    _logger.info(f"Log filters: verbosity {repr(verbosity)}")


def get_logfile_path() -> Optional[pathlib.Path]:
    return _logfile_path


def set_file_logging(config: 'SimpleConfig', enabled: bool) -> None:
    """Starts or stops writing the logs to files, while running. (configure_logging does it at startup)"""
    from .util import is_android_debug_apk
    global _logfile_path, _file_handler
    if enabled and _logfile_path is None:
        _configure_file_logging(
            pathlib.Path(config.path) / "logs",
            num_files_keep=config.LOGS_NUM_FILES_KEEP,
            max_total_size=config.LOGS_MAX_TOTAL_SIZE_BYTES)
        _logger.info(f"Logging to file: {str(_logfile_path)}")
    elif not enabled and _file_handler is not None and not is_android_debug_apk():
        _logger.info("Logging to file stops")
        root_logger.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
        _logfile_path = None


def read_recent_logs(config: 'SimpleConfig', *, max_size: int) -> str:
    """Returns the end of the newest log files, oldest first: at most max_size bytes, starting at a whole line."""
    parts = []  # newest first
    size = 0
    starts_mid_line = False  # whether the oldest part we read starts in the middle of a line
    for path in reversed(_log_files_oldest_first(pathlib.Path(config.path) / "logs")):
        if size >= max_size:
            break
        try:
            with open(path, 'rb') as f:
                start = max(0, os.path.getsize(path) - (max_size - size))
                f.seek(max(0, start - 1))
                data = f.read(max_size - size + (1 if start else 0))
        except OSError:
            continue
        if start:
            # (the byte before tells whether we start at a whole line)
            starts_mid_line, data = data[:1] != b'\n', data[1:]
        else:
            starts_mid_line = False
        parts.append(data)
        size += len(data)
    text = b''.join(reversed(parts)).decode('utf-8', 'replace')
    if starts_mid_line:
        text = text[text.find('\n') + 1:]
    return text


# The logs that a user may send to the developers keep only what is about Lightning payments and the network
# graph: the loggers of these modules. Others print transactions, PSBTs, addresses, labels and the like.
SHARED_LOG_SOURCES = (
    'lnworker', 'lnrouter', 'lnpeer', 'channel_db', 'gossip_catch_up', 'trampoline', 'lnverifier', 'lnonion',
    'mpp_split', 'lnutil',
)
_LOG_ENTRY_HEAD = re.compile(r'^\d{8}T\d{6}\.\d+Z \|\s*\w+ \| ([^.| \[]+)')


def filter_log_for_sharing(text: str) -> str:
    """Keeps the entries of the log written by SHARED_LOG_SOURCES, with the lines that continue them."""
    kept = []
    keep = False
    for line in text.splitlines(keepends=True):
        if m := _LOG_ENTRY_HEAD.match(line):
            keep = m.group(1) in SHARED_LOG_SOURCES
        if keep:
            kept.append(line)
    return ''.join(kept)


class _LogRedactor:
    """Replaces what identifies the user's coins, payments and connections in log text by placeholders,
    numbered within the text, so that what refers to the same thing can still be told."""

    _BECH32 = '02-9ac-hj-np-z'
    _RULES = (  # (kind, pattern, group to replace or 0). order matters
        ('bytes', re.compile(r"""\bb(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")"""), 0),
        ('invoice', re.compile(rf'\b(?:lightning:)?ln(?:bc|tbs|tb|bcrt|sb)[0-9]*[munp]?1[{_BECH32}]{{20,}}', re.I), 0),
        ('invoice', re.compile(rf'\b(?:lightning:)?ln[oir]1[{_BECH32}]{{20,}}', re.I), 0),
        ('lnurl', re.compile(rf'\b(?:lightning:)?lnurl1[{_BECH32}]{{20,}}', re.I), 0),
        ('address', re.compile(rf'\b(?:bc|tb|bcrt)1[{_BECH32}]{{8,87}}\b', re.I), 0),
        ('key', re.compile(r'\b[xyztuvYZUV](?:pub|prv)[1-9A-HJ-NP-Za-km-z]{100,}'), 0),
        ('key', re.compile(r'\b[5KLc9][1-9A-HJ-NP-Za-km-z]{50,51}\b'), 0),  # WIF
        ('address', re.compile(r'\b[13mn2][1-9A-HJ-NP-Za-km-z]{25,34}\b'), 0),
        ('onion', re.compile(r'\b[a-z2-7]{56}\.onion\b', re.I), 0),
        # 20 bytes or more in hex (hashes, secrets, txids, channel ids, scripts, transactions), but node ids
        ('hash', re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{40,}(?![0-9a-fA-F])'), 0),
        ('data', re.compile(r'(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])'), 0),  # base64
        ('ip', re.compile(r'(?<![\w.:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![\w:])'), 0),
        ('ip', re.compile(r'(?<![\w.:])(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?::'
                          r'(?:(?:[0-9a-fA-F]{1,4}:)*(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F]{1,4}))?(?![\w:.])'), 0),
        ('ip', re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)(?!\w)'), 0),
        ('server', re.compile(r'interface\.\[([^\]]+)\]'), 1),
        ('payment', re.compile(r'PaySession\.\[([0-9a-f]{8}-[0-9a-f]{4})\]'), 1),
        ('wallet', re.compile(r'(?:LNWallet|LNPeerManager)\.\[(?!LNGossip\])([^\]]+)\]'), 1),
        ('wallet', re.compile(r'Peer\.\[(?!LNGossip,)([^\],]+), '), 1),
        ('wallet', re.compile(r'/wallets/([^/\s\'"]+)'), 1),
    )
    _NODE_ID = re.compile(r'0[23][0-9a-fA-F]{64}')
    _HEX = re.compile(r'[0-9a-fA-F]+')
    _CHANNELS_WITH_FUNDS = re.compile(r'channels_with_funds: \{.*?\}(?=, have_direct_channel|$)', re.M)
    # what this wallet logs about its own payments
    _OUR_CHANNEL = re.compile(r'sent htlc \d+ over ([0-9]+x[0-9]+x[0-9]+)')
    _OUR_FIRST_HOP = re.compile(r'route: ([0-9a-f]{10}) -\[([0-9]+x[0-9]+x[0-9]+) ')

    def __init__(self, *, our_node_ids: Iterable[str] = (), our_channels: Iterable[str] = (),
                 wallet_names: Iterable[str] = ()):
        self._numbers = {}  # (kind, value) -> number
        self._counts = {}  # kind -> how many
        self._ours = {}  # value -> kind
        home = os.path.expanduser('~')
        self._home = home if len(home) > 1 else ''  # (tracebacks show paths in it, with the user name)
        for kind, values in (('our node', our_node_ids), ('our channel', our_channels), ('wallet', wallet_names)):
            for value in values:
                if value and len(value) >= 3:
                    self._ours[value] = kind

    def _placeholder(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key not in self._numbers:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._numbers[key] = self._counts[kind]
        return f'<{kind} {self._numbers[key]}>'

    def redact(self, text: str) -> str:
        ours = dict(self._ours)
        for m in self._OUR_CHANNEL.finditer(text):
            ours.setdefault(m.group(1), 'our channel')
        for m in self._OUR_FIRST_HOP.finditer(text):
            ours.setdefault(m.group(1), 'our node')
            ours.setdefault(m.group(2), 'our channel')
        for value in list(ours):
            if ours[value] == 'our node' and self._NODE_ID.fullmatch(value):
                ours.setdefault(value[:10], 'our node')  # routes are logged with the start of node ids
        our_node_id_starts = {value for value, kind in ours.items() if kind == 'our node' and len(value) == 10}
        for m in self._NODE_ID.finditer(text):
            if m.group(0)[:10] in our_node_id_starts:
                ours.setdefault(m.group(0), 'our node')
        if self._home:
            text = text.replace(self._home, '~')
        if ours:
            pattern = re.compile(
                r'(?<![0-9A-Za-z])(?:' + '|'.join(re.escape(v) for v in sorted(ours, key=len, reverse=True))
                + r')(?![0-9A-Za-z])')
            text = pattern.sub(lambda m: self._placeholder(ours[m.group(0)], m.group(0)), text)
        text = self._CHANNELS_WITH_FUNDS.sub('channels_with_funds: <balances>', text)
        for kind, pattern, group in self._RULES:
            def replace(m, kind=kind, group=group):
                if kind == 'hash' and len(m.group(0)) == 66 and m.group(0)[:2] in ('02', '03'):
                    return m.group(0)  # a node id: the nodes of the network are public
                if kind == 'data' and self._HEX.fullmatch(m.group(0)):
                    return m.group(0)  # (what is left of hex are node ids)
                if group == 0:
                    return self._placeholder(kind, m.group(0))
                start, end = m.span(group)
                return m.group(0)[:start - m.start()] + self._placeholder(kind, m.group(group)) + m.group(0)[end - m.start():]
            text = pattern.sub(replace, text)
        return text


def what_identifies_us_in_logs(wallets: Iterable['Abstract_Wallet']) -> dict:
    """The node ids, channels and wallet names of these wallets, as redact_log_text takes them."""
    from .lnutil import ShortChannelID
    ours = {'our_node_ids': [], 'our_channels': [], 'wallet_names': []}
    for wallet in wallets:
        ours['wallet_names'].append(wallet.basename())
        lnworker = wallet.lnworker
        if lnworker is None:
            continue
        ours['our_node_ids'].append(lnworker.node_keypair.pubkey.hex())
        for chan in list(lnworker.channels.values()) + list(lnworker.channel_backups.values()):
            if chan.short_channel_id:
                ours['our_channels'].append(str(chan.short_channel_id))
            for alias in (chan.get_local_scid_alias(), chan.get_remote_scid_alias()):
                if alias:
                    ours['our_channels'].append(str(ShortChannelID(alias)))
    return ours


def redact_log_text(text: str, *, our_node_ids: Iterable[str] = (), our_channels: Iterable[str] = (),
                    wallet_names: Iterable[str] = ()) -> str:
    """See _LogRedactor. The node ids, channels and wallet names given are replaced too: those of the wallets
    loaded now. Those of other wallets are found where the logs mention them as ours."""
    return _LogRedactor(our_node_ids=our_node_ids, our_channels=our_channels, wallet_names=wallet_names).redact(text)


def describe_os_version() -> str:
    if 'ANDROID_DATA' in os.environ:
        import jnius
        bv = jnius.autoclass('android.os.Build$VERSION')
        b = jnius.autoclass('android.os.Build')
        return "Android {} on {} {} ({})".format(bv.RELEASE, b.BRAND, b.DEVICE, b.DISPLAY)
    else:
        return platform.platform()


@lru_cache  # result unlikely to change while running. though "-dirty" could technically change
def get_git_version() -> Optional[str]:
    dir = os.path.dirname(os.path.realpath(__file__))
    try:
        # note: this searches $PATH and perhaps $PWD for an executable named "git".  attack surface?
        version = subprocess.check_output(
            ['git', 'describe', '--always', '--dirty'],
            cwd=dir,
            timeout=5,  # seconds
        )
        version = str(version, "utf8").strip()
    except Exception:
        version = None
    return version
