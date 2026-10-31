"""Shared JSON/YAML loading for native views, projects, and work recording."""
import json
import math
from pathlib import Path

from .config import CONFIG_NAMES, ConfigError, parse_config


def yaml_module():
    try:
        import yaml
    except ModuleNotFoundError as error:
        if error.name != 'yaml':
            raise
        raise ConfigError(
            "PyYAML is missing from this Kanitor environment. From the checkout, run "
            "uv tool install --reinstall --editable . (use '.[mcp]' to retain MCP support), "
            "or run Kanitor with uv run kanitor."
        ) from error
    return yaml


def config_path(root):
    """Prefer the existing JSON configuration, then YML, then YAML; never merge."""
    return next((Path(root) / name for name in CONFIG_NAMES if (Path(root) / name).exists()),
                Path(root) / CONFIG_NAMES[0])


def configuration_files(root):
    """Watch local overrides and potential declaring workspaces for fallback."""
    root = Path(root)
    folders = (root,) if config_path(root).exists() else (root, *root.parents)
    return [folder / name for folder in folders for name in CONFIG_NAMES]


def _pairs(items):
    result = {}
    for key, value in items:
        if not isinstance(key, str):
            raise ValueError('mapping keys must be strings (quote numeric or boolean keys)')
        if key in result:
            raise ValueError(f'duplicate key: {key!r}')
        result[key] = value
    return result


def _yaml_load(text):
    yaml = yaml_module()

    class Loader(yaml.SafeLoader):
        pass

    # ISO timestamps in metadata schemas and examples remain strings, as in JSON.
    Loader.yaml_implicit_resolvers = {
        key: [(tag, regex) for tag, regex in rules if tag != 'tag:yaml.org,2002:timestamp']
        for key, rules in Loader.yaml_implicit_resolvers.items()
    }

    def mapping(loader, node):
        # Explicit duplicates are mistakes; inherited merge values may be
        # overridden normally (for example: <<: *base, title: Owner).
        _pairs((loader.construct_object(key), None) for key, _ in node.value
               if key.tag != 'tag:yaml.org,2002:merge')
        loader.flatten_mapping(node)
        result = {}
        for key, value in node.value:
            name = loader.construct_object(key)
            if not isinstance(name, str):
                raise ValueError('mapping keys must be strings (quote numeric or boolean keys)')
            result[name] = loader.construct_object(value)
        return result

    Loader.add_constructor('tag:yaml.org,2002:map', mapping)
    try:
        return yaml.load(text, Loader=Loader)
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from error


def _check_values(value, ancestors=None):
    """Keep YAML values compatible with JSON snapshots and work schemas."""
    ancestors = set() if ancestors is None else ancestors
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise ValueError('recursive YAML aliases are not supported')
        ancestors.add(id(value))
        if isinstance(value, dict) and any(not isinstance(key, str) for key in value):
            raise ValueError('mapping keys must be strings')
        for item in (value.values() if isinstance(value, dict) else value):
            _check_values(item, ancestors)
        ancestors.remove(id(value))
    elif not (value is None or type(value) in (str, bool, int)
              or type(value) is float and math.isfinite(value)):
        raise ValueError('configuration must contain JSON-compatible values')


def _load_local(root, *, validate_view=True):
    """Read one directory's selected file without inheriting project rosters."""
    path = config_path(root)
    try:
        if not path.exists():
            return {}, path
        text = path.read_text(encoding='utf-8')
        if path.suffix == '.json':
            data = json.loads(text, object_pairs_hook=_pairs)
        else:
            data = _yaml_load(text)
            if data is None:
                data = {}
        if validate_view:
            _check_values(data)
            parse_config(data, source=path.name)
        elif not isinstance(data, dict):
            raise ValueError('configuration must be an object')
        return data, path
    except ConfigError:
        raise
    except (OSError, ValueError, RecursionError) as error:
        raise ConfigError(f'{path.name}: {error}') from error


def load_document(root, *, validate_view=True):
    """Resolve one config; recorders validate their own rules, independently of views."""
    root = Path(root).expanduser().absolute()
    target = root.resolve()
    data, path = _load_local(root, validate_view=validate_view)
    if path.exists():
        return data, path
    for parent in root.parents:
        try:
            inherited, source = _load_local(parent, validate_view=False)
        except ConfigError:
            # An unreadable ancestor cannot declare this workspace. Local
            # files remain strict; ancestor discovery must not break unrelated
            # projects just because they share a directory tree.
            continue
        projects = inherited.get('projects', ())
        if not isinstance(projects, (list, tuple)):
            continue
        for relative in projects:
            # Invalid display/project settings must not prevent work recording.
            # Inheritance still requires an explicit, valid descendant path.
            if (not isinstance(relative, str) or not relative.strip() or not relative.isprintable()
                    or Path(relative).is_absolute() or '..' in Path(relative).parts or not Path(relative).parts):
                continue
            try:
                project = (parent / relative).resolve()
            except (OSError, RuntimeError):
                continue
            if project == target and project.is_relative_to(parent.resolve()) and project != parent.resolve():
                if validate_view:
                    try:
                        _check_values(inherited)
                        parse_config(inherited, source=str(source))
                    except (ValueError, RecursionError) as error:
                        if isinstance(error, ConfigError):
                            raise
                        raise ConfigError(f'{source}: {error}') from error
                # Only settings flow down. The parent's roster belongs to its
                # Projects view, and must not create another hierarchy layer.
                return {key: value for key, value in inherited.items() if key != 'projects'}, source
    return data, path
