"""Local, optional view preferences; independent of configuration and work logs."""
import json
import os
from pathlib import Path
import tempfile


class UnsupportedState(ValueError):
    pass


class ViewState:
    def __init__(self, root):
        self.folder = Path(root) / '.kanitor'
        self.path = self.folder / 'view-state.json'

    def _check_paths(self):
        if self.folder.is_symlink() or self.path.is_symlink():
            raise OSError('view preferences must not use symlinks')

    def _read(self):
        self._check_paths()
        if not self.path.exists():
            return {'version': 1}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('view preferences must be an object')
        version = data.get('version', 1)
        if type(version) is not int or version != 1:
            raise UnsupportedState('view preferences use an unsupported version')
        return data

    def flag(self, name, default=False):
        try:
            value = self._read().get(name)
            return value if type(value) is bool else default
        except (OSError, ValueError, RecursionError):
            return default

    def set_flag(self, name, value):
        return self._set(name, value)

    def mapping(self, name):
        try:
            value = self._read().get(name)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, RecursionError):
            return {}

    def set_mapping_entry(self, name, key, value):
        return self._set(name, value, key=key)

    def _set(self, name, value, key=None):
        """Save only an explicit change; return a nonfatal error for the UI."""
        temporary = None
        try:
            try:
                data = self._read()
            except UnsupportedState:
                raise
            except (ValueError, RecursionError):
                data = {'version': 1}
            if key is not None:
                mapping = data.get(name)
                value = {**(mapping if isinstance(mapping, dict) else {}), key: value}
            data.update(version=1, **{name: value})
            self.folder.mkdir(mode=0o700, exist_ok=True)
            self._check_paths()
            fd, filename = tempfile.mkstemp(prefix='.view-state.', suffix='.tmp', dir=self.folder)
            temporary = Path(filename)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return ''
        except (OSError, ValueError, RecursionError) as error:
            return f'Could not save view preferences: {error}'
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
