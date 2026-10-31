"""JSON-in/JSON-out command adapter for shared work operations."""
import argparse
from pathlib import Path
import sys

from .common import WorkError, canonical, loads
from .schemas import INPUT_SCHEMAS
from .service import WorkService


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise WorkError('invalid_arguments', message)


def main(argv=None):
    parser = Parser(description='Durable work records. Operations accept JSON and print JSON results.')
    operations = {name.removeprefix('work_').replace('_', '-'): name for name in INPUT_SCHEMAS}
    parser.add_argument('operation', choices=operations)
    parser.add_argument('--workspace', required=True, type=Path, help='Explicit workspace root; relative paths are resolved locally.')
    parser.add_argument('--input', type=str, help='Operation JSON file, or - for stdin. Omit for empty read arguments.')
    try:
        args = parser.parse_args(argv)
        if args.input == '-':
            arguments = loads(sys.stdin.read())
        elif args.input:
            arguments = loads(Path(args.input).expanduser().read_bytes())
        else:
            arguments = {}
        result = WorkService().execute(operations[args.operation], args.workspace, arguments)
        print(canonical(result))
        return 0
    except WorkError as error:
        print(canonical({'error': error.as_dict()}))
        return 1
    except OSError as error:
        print(canonical({'error': WorkError('io_error', str(error)).as_dict()}))
        return 1
