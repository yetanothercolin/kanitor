#!/usr/bin/env python3
"""Measure work-recording overhead on disposable workspaces, outside shipped code."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from kanitor.work.service import WorkService


def stats(values):
    ordered = sorted(values)
    return {'median_ms': round(statistics.median(values), 3),
            'p95_ms': round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 3),
            'minimum_ms': round(ordered[0], 3), 'samples': len(values)}


async def mcp_benchmark(root, sid, samples):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    started = time.perf_counter()
    params = StdioServerParameters(command=sys.executable, args=['-m', 'kanitor', 'mcp'], cwd=REPO)
    with tempfile.TemporaryFile(mode='w+') as errors:
        async with stdio_client(params, errlog=errors) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                read = await session.call_tool('work_read', {'workspace': str(root), 'limit': 1})
                if read.isError:
                    raise RuntimeError(read.content)
                startup = (time.perf_counter() - started) * 1000
                durations = []
                for _ in range(samples):
                    args = {'workspace': str(root), 'session_id': sid, 'text': 'benchmark', 'request_id': str(uuid.uuid4())}
                    before = time.perf_counter()
                    result = await session.call_tool('work_note', args)
                    durations.append((time.perf_counter() - before) * 1000)
                    if result.isError:
                        raise RuntimeError(result.content)
                return {**stats(durations), 'startup_and_first_read_ms': round(startup, 3)}


def benchmark(event_count, samples):
    with tempfile.TemporaryDirectory(prefix='kanitor-work-benchmark-') as folder:
        root = Path(folder).resolve()
        service = WorkService()
        sid = service.execute('work_begin', root, {'label': 'benchmark fixture', 'request_id': 'seed'})['session_id']
        for index in range(event_count):
            service.execute('work_note', root, {'session_id': sid, 'text': 'seed', 'request_id': f'seed-{index}'})
        result = {'seed_events': event_count + 1}
        times = []
        for _ in range(samples):
            args = {'session_id': sid, 'text': 'benchmark', 'request_id': str(uuid.uuid4())}
            before = time.perf_counter()
            service.execute('work_note', root, args)
            times.append((time.perf_counter() - before) * 1000)
        result['warm_library'] = stats(times)
        times = []
        for _ in range(samples):
            args = {'session_id': sid, 'text': 'benchmark', 'request_id': str(uuid.uuid4())}
            before = time.perf_counter()
            subprocess.run([sys.executable, '-m', 'kanitor', 'work', 'note', '--workspace', str(root), '--input', '-'],
                           input=json.dumps(args), text=True, capture_output=True, cwd=REPO, check=True)
            times.append((time.perf_counter() - before) * 1000)
        result['cold_cli'] = stats(times)
        result['warm_mcp'] = (asyncio.run(mcp_benchmark(root, sid, samples)) if importlib.util.find_spec('mcp') else
                              {'skipped': 'Install the mcp extra to measure the real stdio adapter'})
        result['final_log_bytes'] = (root / '.kanitor/work/events.jsonl').stat().st_size
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=int, default=1000, help='Seed notes for the substantial-log measurement.')
    parser.add_argument('--samples', type=int, default=10)
    args = parser.parse_args()
    if args.events < 0 or args.samples < 1:
        parser.error('events must be nonnegative and samples must be positive')
    print(json.dumps({'empty': benchmark(0, args.samples), 'substantial': benchmark(args.events, args.samples)}, indent=2))


if __name__ == '__main__':
    main()
