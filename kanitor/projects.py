"""Declared descendant projects with workspace defaults and local overrides."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import time

from .config import ColumnRules, ConfigError, parse_config
from .config_file import config_path, load_document
from .reader import ReadError, read_once, warning_messages


@dataclass(frozen=True)
class Project:
    path: str
    root: Path


class ProjectCatalog:
    def __init__(self, root, interval=.5):
        self.root = Path(root).resolve()
        self.interval = interval
        self.projects = []
        self.rules = ColumnRules()
        self.declared = False
        self.error = ''
        self.revision = 0
        self._checked = None

    def poll(self, force=False):
        now = time.monotonic()
        if not force and self._checked is not None and now - self._checked < self.interval:
            return False
        self._checked = now
        before = self.projects, self.error, self.declared, self.rules
        try:
            data, path = load_document(self.root)
            self.declared = isinstance(data, dict) and 'projects' in data
            rules = parse_config(data, source=path.name)
            paths = rules.projects or ()
            projects, roots = [], set()
            for relative in paths:
                root = (self.root / relative).resolve()
                if not root.is_relative_to(self.root) or root == self.root:
                    raise ConfigError(f'{path.name}: projects path {relative!r} must stay under its configuration directory')
                if root in roots:
                    raise ConfigError(f'{path.name}: projects path {relative!r} duplicates another project directory')
                roots.add(root)
                projects.append(Project(relative, root))
            self.projects, self.error, self.rules = projects, '', rules
        except (ValueError, OSError, RuntimeError) as error:
            self.error = f'{config_path(self.root).name}: {error}' if not isinstance(error, ConfigError) else str(error)
        changed = before != (self.projects, self.error, self.declared, self.rules)
        if changed:
            self.revision += 1
        return changed


def project_snapshot(project):
    result = {'path': project.path, 'root': str(project.root), 'error': ''}
    try:
        result['snapshot'] = read_once(project.root)
    except ReadError as error:
        result['error'] = str(error)
    return result


def read_projects(catalog):
    with ThreadPoolExecutor(max_workers=4) as pool:
        projects = list(pool.map(project_snapshot, catalog.projects))
    return {'source': 'kanitor-projects', 'root': str(catalog.root), 'readOnly': True, 'projects': projects}


def plain_projects(snapshot):
    lines = [f"{snapshot['root']} * Projects"]
    for project in snapshot['projects']:
        if project['error']:
            summary = 'Unavailable: ' + project['error']
        else:
            boards = project['snapshot']['boards']
            summary = f"{len(boards)} boards · {len({card['id'] for board in boards for card in board['tasks']})} tasks"
        lines.append(f"{project['path']}: {summary}")
        for message in warning_messages(project.get('snapshot')):
            lines.append(f'  Warning: {message}')
    if not snapshot['projects']:
        lines.append('No projects configured. Add subdirectory paths to the Kanitor configuration projects list.')
    return '\n'.join(lines)
