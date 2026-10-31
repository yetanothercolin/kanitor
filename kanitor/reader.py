"""Bounded native reads, polled without blocking curses or filling subprocess pipes."""
import json
from pathlib import Path
import subprocess
import tempfile
import time

from .config_file import configuration_files, load_document

BRIDGE = Path(__file__).with_name('bridge.cjs')


class ReadError(Exception):
    pass


def command(root):
    return ['node', str(BRIDGE), str(root)]


def decode(stdout, stderr, returncode):
    if returncode:
        raise ReadError(stderr.strip() or f'Kanbn reader exited with status {returncode}')
    try:
        data = json.loads(stdout)
        if data.get('source') != 'kanbn' or data.get('readOnly') is not True or not isinstance(data['boards'], list):
            raise ValueError('Invalid snapshot')
        # The native bridge fingerprints every supported config file. Parse it in
        # Python so all viewers and work recording use exactly the same loader.
        root = Path(data['root'])
        expected = {row[0]: row for row in data['watch']['signature']}
        def check_config_signature():
            for path in configuration_files(root):
                try:
                    stat = path.stat()
                    current = [str(path), str(stat.st_ino), str(stat.st_size), str(stat.st_mtime_ns)]
                except FileNotFoundError:
                    current = [str(path), None]
                if current != expected.get(str(path)):
                    raise ReadError('Kanitor configuration changed during the read; retrying.')
        check_config_signature()
        data['customization'], _ = load_document(root)
        check_config_signature()
        return data
    except (ValueError, KeyError, AttributeError, OSError) as error:
        raise ReadError(f'Invalid Kanbn snapshot: {error}') from error


def read_once(root, timeout=10):
    try:
        result = subprocess.run(command(root), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReadError(f'Cannot read Kanbn: {error}') from error
    return decode(result.stdout, result.stderr, result.returncode)


class LiveReader:
    reader_name = 'Kanbn'
    def __init__(self, root, interval=0.5, timeout=10):
        self.root, self.interval, self.timeout = Path(root), interval, timeout
        self.files = [self.root / name for name in ('kanbn.yml', 'kanbn.json')] + configuration_files(self.root)
        self.folders = [self.root / '.kanbn', self.root / '.kanbn' / 'tasks']
        self.snapshot = None
        self.error = ''
        self.revision = 0
        self.process = None
        self._signature = None
        self._last_check = 0
        self._force = True

    def fingerprint(self):
        paths = set(self.files)
        for folder in self.folders:
            if folder.exists():
                paths.update(folder.glob('*.md'))
        result = []
        for path in sorted(paths):
            try:
                stat = path.stat()
                result.append((str(path), str(stat.st_ino), str(stat.st_size), str(stat.st_mtime_ns)))
            except FileNotFoundError:
                result.append((str(path), None))
        return tuple(result)

    def refresh(self):
        self._force = True

    def _finish(self):
        self._output.close()
        self._errors.close()
        self.process = None

    def make_command(self):
        return command(self.root)

    def decode_snapshot(self, stdout, stderr, returncode):
        return decode(stdout, stderr, returncode)

    def accept(self, data):
        if self._reading != self.fingerprint():
            self._force = True
            return False
        self.files = [Path(p) for p in data['watch']['files']]
        self.folders = [Path(p) for p in data['watch']['folders']]
        signature = self.fingerprint()
        if signature != tuple(tuple(row) for row in data['watch']['signature']):
            self._force = True
            return False
        self._signature = signature
        return True

    def poll(self):
        now = time.monotonic()
        if self.process:
            result = self.process.poll()
            if result is None and now - self._started < self.timeout:
                return
            try:
                if result is None:
                    self.process.kill()
                    self.process.wait()
                    raise ReadError(f'{self.reader_name} read exceeded {self.timeout:g} seconds. Press r to retry.')
                self._output.seek(0)
                self._errors.seek(0)
                data = self.decode_snapshot(self._output.read(), self._errors.read(), result)
                if not self.accept(data):
                    return
                self.snapshot, self.error = data, ''
                self.revision += 1
            except (ReadError, OSError, KeyError) as error:
                self.error = str(error)
                self._signature = None
            finally:
                self._finish()
                self._last_check = now
            return
        if not self._force and now - self._last_check < self.interval:
            return
        self._last_check = now
        try:
            signature = self.fingerprint()
            if not self._force and signature == self._signature:
                return
            self._force = False
            self._reading = signature
            # Retry errors even when the filesystem is unchanged (e.g. a transient parse error).
            self._signature = signature if not self.error else None
            self._output = tempfile.TemporaryFile(mode='w+t')
            self._errors = tempfile.TemporaryFile(mode='w+t')
            try:
                self.process = subprocess.Popen(self.make_command(), stdout=self._output, stderr=self._errors)
            except OSError:
                self._finish()
                raise
            self._started = now
        except OSError as error:
            self.error = f'Cannot read {self.reader_name}: {error}'
            self._signature = None

    def close(self):
        if self.process:
            self.process.kill()
            self.process.wait()
            self._finish()
