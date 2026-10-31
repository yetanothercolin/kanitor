"""Read-only worker used by the TUI; deliberately independent of MCP and kanbn."""
import sys

from .common import WorkError, canonical
from .service import WorkService


def main():
    try:
        print(canonical(WorkService().viewer_snapshot(sys.argv[1])))
        return 0
    except WorkError as error:
        print(error.message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
