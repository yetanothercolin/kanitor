"""Command-line entry point for interactive and snapshot exploration."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .model import Explorer, find_root, plain_snapshot
from .reader import ReadError, read_once


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['work']:
        from .work.cli import main as work_main
        return work_main(argv[1:])
    if argv[:1] == ['mcp']:
        from .work.mcp import main as mcp_main
        return mcp_main(argv[1:])
    parser = argparse.ArgumentParser(description='Kanbn explorer. Use "kanitor work --help" for recording or "kanitor mcp" for MCP.')
    parser.add_argument('--version', action='version', version=f'kanitor {__version__}')
    parser.add_argument('--root', type=Path, help='Workspace (default: discover from the current directory).')
    parser.add_argument('--board', help='Initially selected board slug.')
    parser.add_argument('--project', help='Declared relative project path to open directly.')
    parser.add_argument('--search', default='', help='Initial task search.')
    parser.add_argument('--once', action='store_true', help='Print a plain-text snapshot and exit.')
    parser.add_argument('--json', action='store_true', help='Print the complete native snapshot and exit.')
    parser.add_argument('--agent-guide', action='store_true', help='Print agent guidance, including custom column configuration.')
    parser.add_argument('--init-yml', action='store_true', help='Create an annotated .kanitor.yml with defaults in --root or the current directory.')
    args = parser.parse_args(argv)
    if args.agent_guide:
        print(Path(__file__).with_name('agent_guide.txt').read_text(encoding='utf-8'), end='')
        return 0
    if args.init_yml:
        from .config_template import init_yml
        from .config import ConfigError
        try:
            path = init_yml(args.root if args.root else Path.cwd())
        except (ConfigError, OSError) as error:
            print(f'kanitor: {error}', file=sys.stderr)
            return 1
        print(f'Created {path}')
        return 0
    root = args.root.expanduser().resolve() if args.root else find_root(Path.cwd())
    from .projects import ProjectCatalog, plain_projects, read_projects
    catalog = ProjectCatalog(root)
    catalog.poll(force=True)
    multiple = catalog.declared or (catalog.error and not any(
        (root / name).exists() for name in ('.kanbn', 'kanbn.json', 'kanbn.yml')))
    selected_project = None
    if args.project:
        selected_project = next((project for project in catalog.projects if project.path == str(Path(args.project))), None)
        if catalog.error or selected_project is None:
            from .config_file import config_path
            print('kanitor: ' + (catalog.error or f'Project {args.project!r} is not declared in {config_path(root)}'), file=sys.stderr)
            return 1
    if multiple and not selected_project and (args.board or args.search):
        print('kanitor: Use --project with --board or --search when watching multiple projects.', file=sys.stderr)
        return 1
    explorer = Explorer(args.board)
    explorer.query = args.search
    if args.once or args.json:
        try:
            if multiple and not selected_project:
                if catalog.error:
                    raise ReadError(catalog.error)
                data = read_projects(catalog)
                print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else plain_projects(data))
                return int(any(project['error'] for project in data['projects']))
            if selected_project:
                root = selected_project.root
            data = read_once(root)
            if args.board and not any(b['slug'] == args.board for b in data['boards']):
                raise ReadError(f'Board {args.board!r} does not exist.')
            explorer.apply(data)
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else plain_snapshot(data, explorer))
            return 0
        except ReadError as error:
            print(f'kanitor: {error}', file=sys.stderr)
            return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('kanitor: An interactive terminal is required. Use --once or --json for a snapshot.', file=sys.stderr)
        return 1
    try:
        from .ui import run
        run(root, explorer, start_in_board=bool(args.board or args.search),
            catalog=catalog if multiple else None, selected_project=selected_project)
        return 0
    except KeyboardInterrupt:
        return 0
    except (ImportError, OSError) as error:
        print(f'kanitor: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
