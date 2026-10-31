"""Optional stdio MCP adapter; no recorder runs independently of requests."""
import argparse
import asyncio
from copy import deepcopy
from functools import partial
from pathlib import Path
import sys

from .common import WorkError, canonical
from .schemas import INPUT_SCHEMAS, OPERATIONS, READ_ONLY, validate
from .service import WorkService

DESCRIPTIONS = {
    'work_capabilities': 'Discover operation schemas, local metadata requirements, and outcome vocabulary.',
    'work_begin': 'Begin a bounded work session; no phase or worker identity is inferred.',
    'work_transition': 'Atomically end the current declared phase and begin another.',
    'work_span_begin': 'Begin an independent operation span, optionally nested under an open span.',
    'work_span_end': 'Close an operation span after its open children have finished.',
    'work_span_record': 'Record an already-observed operation with reported timestamps and optional measured duration.',
    'work_note': 'Append a note without restarting any interval.',
    'work_end': 'Close a session and current phase after all open spans have finished.',
    'work_amend': 'Append an audited correction, timing adjustment, rebinding, or explicit interruption.',
    'work_read': 'Read paginated immutable events or derived session summaries with timing provenance and warnings.',
}


def tool_schema(name):
    schema = deepcopy(INPUT_SCHEMAS[name])
    schema['properties']['workspace'] = {'type': 'string', 'minLength': 1, 'description': 'Explicit absolute workspace root.'}
    schema['required'].append('workspace')
    return schema


def create_server(service=None):
    import anyio
    from mcp import types
    from mcp.server.lowlevel import Server

    service = service or WorkService()
    server = Server('kanitor-work')

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=name, description=DESCRIPTIONS[name], inputSchema=tool_schema(name),
                           annotations=types.ToolAnnotations(readOnlyHint=name in READ_ONLY,
                                destructiveHint=False, idempotentHint=True, openWorldHint=False))
                for name in OPERATIONS]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            if name not in OPERATIONS:
                raise WorkError('unknown_operation', f'Unknown operation: {name}')
            validate(arguments, tool_schema(name))
            workspace = arguments['workspace']
            if not Path(workspace).is_absolute():
                raise WorkError('invalid_workspace', 'MCP requires an absolute workspace root')
            args = {key: value for key, value in arguments.items() if key != 'workspace'}
            result = await anyio.to_thread.run_sync(partial(service.execute, name, workspace, args))
            return types.CallToolResult(content=[types.TextContent(type='text', text=canonical(result))],
                                        structuredContent=result)
        except WorkError as error:
            result = {'error': error.as_dict()}
            return types.CallToolResult(content=[types.TextContent(type='text', text=canonical(result))],
                                        structuredContent=result, isError=True)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run Kanitor work tools as a local stdio MCP server.')
    parser.parse_args(argv)
    try:
        from mcp.server.stdio import stdio_server
        server = create_server()

        async def serve():
            async with stdio_server() as (reader, writer):
                await server.run(reader, writer, server.create_initialization_options())
        asyncio.run(serve())
        return 0
    except ImportError:
        print('kanitor mcp: install the MCP extra with uv sync --extra mcp or uv tool install "kanitor[mcp]".', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
