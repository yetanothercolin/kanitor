"""Cancellable background work snapshots for Activity and Task Squares."""
import sys

from ..config_file import configuration_files
from ..reader import LiveReader, ReadError
from .common import WorkError, loads


class WorkReader(LiveReader):
    reader_name = 'Work'
    def __init__(self, root, interval=.5, timeout=10):
        super().__init__(root, interval, timeout)
        self.files = [self.root / '.kanitor/work/events.jsonl'] + configuration_files(self.root)
        self.folders = []

    def make_command(self):
        return [sys.executable, '-m', 'kanitor.work.snapshot', str(self.root)]

    def fingerprint(self):
        self.files = [self.root / '.kanitor/work/events.jsonl'] + configuration_files(self.root)
        return super().fingerprint()

    def decode_snapshot(self, stdout, stderr, returncode):
        if returncode:
            raise ReadError(stderr.strip() or 'Work snapshot could not be read')
        try:
            data = loads(stdout)
            if data.get('readOnly') is not True or not isinstance(data['sessions'], list) or not isinstance(data['events'], list):
                raise ValueError('Invalid work snapshot')
            return data
        except (WorkError, ValueError, KeyError, AttributeError) as error:
            raise ReadError(str(error)) from error

    def accept(self, data):
        # Appends during a read are valid: publish the prefix and catch up next poll.
        self._signature = self._reading
        return True

