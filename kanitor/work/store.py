"""Locked, durable JSONL storage. Caches are verified against the file's bytes."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import threading
import uuid

from .common import WorkError, canonical, loads, utc_now
from .schemas import EVENT_SCHEMA, SCHEMA_VERSION, validate

ZERO_HASH = '0' * 64


def digest(data):
    return hashlib.sha256(data).hexdigest()


def event_hash(event):
    return digest(canonical({key: value for key, value in event.items() if key != 'hash'}).encode())


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_all(fd, data):
    while data:
        size = os.write(fd, data)
        if size == 0:
            raise OSError('Short event-log write')
        data = data[size:]


def atomic_write(path, data):
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4()}.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise WorkError('invalid_workspace', f'Workspace must be an existing directory: {self.root}')
        self.folder = self.root / '.kanitor' / 'work'
        self.path = self.folder / 'events.jsonl'
        self.lock_path = self.folder / '.lock'
        self.events = []
        self.requests = {}
        self.event_ids = set()
        self.prefix = b''
        self.tail = b''
        self.generation = 0
        self.mutex = threading.RLock()

    def _check_paths(self):
        for path in (self.root / '.kanitor', self.folder, self.path, self.lock_path):
            if path.is_symlink():
                raise WorkError('invalid_workspace', f'Work storage must not use symlinks: {path}')

    @contextmanager
    def locked(self, write=False):
        with self.mutex:
            with self._file_locked(write):
                yield

    @contextmanager
    def _file_locked(self, write=False):
        self._check_paths()
        if write:
            for directory in (self.root / '.kanitor', self.folder):
                try:
                    directory.mkdir()
                    sync_directory(directory.parent)
                except FileExistsError:
                    if not directory.is_dir():
                        raise WorkError('storage_error', f'Not a directory: {directory}')
        if not write and not self.lock_path.exists():
            yield
            return
        fd = os.open(self.lock_path, (os.O_RDWR | os.O_CREAT) if write else os.O_RDONLY, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load(self):
        self._check_paths()
        raw = self.path.read_bytes() if self.path.exists() else b''
        boundary = raw.rfind(b'\n') + 1
        prefix, self.tail = raw[:boundary], raw[boundary:]
        if not prefix.startswith(self.prefix):
            self.events, self.requests, self.event_ids = [], {}, set()
            self.prefix = b''
            self.generation += 1
        offset = len(self.prefix)
        try:
            for line in prefix[offset:].splitlines(keepends=True):
                event = loads(line)
                if not isinstance(event, dict):
                    raise WorkError('corrupt_log', 'Event must be an object')
                if event.get('schema_version') != SCHEMA_VERSION:
                    raise WorkError('incompatible_version', f'Unsupported event schema version: {event.get("schema_version")}')
                validate(event, EVENT_SCHEMA, 'event')
                if event['seq'] != len(self.events) + 1:
                    raise WorkError('corrupt_log', 'Nonconsecutive workspace sequence')
                previous = self.events[-1]['hash'] if self.events else ZERO_HASH
                if event['previous_hash'] != previous or event['hash'] != event_hash(event):
                    raise WorkError('corrupt_log', 'Event hash chain does not match')
                if event['request_id'] in self.requests or event['event_id'] in self.event_ids:
                    raise WorkError('corrupt_log', 'Duplicate event or request ID in log')
                self.events.append(event)
                self.requests[event['request_id']] = event
                self.event_ids.add(event['event_id'])
                offset += len(line)
                self.prefix = prefix[:offset]
        except WorkError as error:
            if error.code == 'incompatible_version':
                raise
            raise WorkError('corrupt_log', f'Event log corruption at byte {offset}: {error.message}') from error
        return self.events

    def retry(self, request):
        event = self.requests.get(request['arguments']['request_id'])
        if event is None:
            return None
        if canonical(event['request']) != canonical(request):
            raise WorkError('request_conflict', 'Request ID was already used with different arguments or operation')
        # A previous process may have written a full record and failed at fsync.
        # Make that record durable before returning its original receipt.
        self.sync()
        return event['receipt']

    def sync(self):
        fd = os.open(self.path, os.O_RDWR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        sync_directory(self.folder)

    def append(self, event):
        if self.tail:
            raise WorkError('recovery_required', 'Incomplete final record; run kanitor work recover before writing')
        event['previous_hash'] = self.events[-1]['hash'] if self.events else ZERO_HASH
        event['hash'] = event_hash(event)
        validate(event, EVENT_SCHEMA, 'event')
        data = (canonical(event) + '\n').encode()
        existed = self.path.exists()
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if not existed:
            sync_directory(self.folder)
        self.events.append(event)
        self.requests[event['request_id']] = event
        self.event_ids.add(event['event_id'])
        self.prefix += data

    def recover(self, arguments):
        """Called under the exclusive lock; only an incomplete suffix is repairable."""
        recovery = self.folder / 'recovery'
        if recovery.is_symlink():
            raise WorkError('invalid_workspace', 'Recovery folder must not be a symlink')
        key = digest(arguments['request_id'].encode())
        manifest_path = recovery / f'{key}.json'
        request = {'operation': 'work_recover', 'arguments': arguments}
        if arguments['request_id'] in self.requests:
            raise WorkError('request_conflict', 'Request ID belongs to a committed work event')
        if manifest_path.exists():
            manifest = loads(manifest_path.read_bytes())
            if canonical(manifest['request']) != canonical(request):
                raise WorkError('request_conflict', 'Recovery request ID has different arguments')
            if manifest['state'] == 'completed':
                return manifest['receipt']
            backup = recovery / manifest['backup_name']
            original = backup.read_bytes()
            if digest(original) != manifest['before_hash']:
                raise WorkError('corrupt_log', 'Recovery backup hash does not match')
            prefix = original[:manifest['prefix_size']]
            current = self.path.read_bytes()
            if current == original:
                atomic_write(self.path, prefix)
            elif not current.startswith(prefix):
                raise WorkError('recovery_conflict', 'Log changed since recovery was prepared')
            manifest['state'] = 'completed'
            atomic_write(manifest_path, (canonical(manifest) + '\n').encode())
            self.load()
            return manifest['receipt']
        if not self.tail:
            raise WorkError('no_recovery_needed', 'No incomplete final record; middle corruption cannot be repaired automatically')
        try:
            recovery.mkdir()
            sync_directory(self.folder)
        except FileExistsError:
            pass
        original = self.prefix + self.tail
        backup_name = f'{key}.original.jsonl'
        receipt = {'request_id': arguments['request_id'], 'state': 'recovered',
                   'recorded_at': utc_now(), 'seq': len(self.events), 'removed_bytes': len(self.tail),
                   'backup': str(recovery / backup_name), 'manifest': str(manifest_path)}
        manifest = {'state': 'prepared', 'request': request, 'backup_name': backup_name,
                    'before_hash': digest(original), 'prefix_hash': digest(self.prefix),
                    'prefix_size': len(self.prefix), 'receipt': receipt}
        atomic_write(recovery / backup_name, original)
        atomic_write(manifest_path, (canonical(manifest) + '\n').encode())
        atomic_write(self.path, self.prefix)
        manifest['state'] = 'completed'
        atomic_write(manifest_path, (canonical(manifest) + '\n').encode())
        self.tail = b''
        return receipt
