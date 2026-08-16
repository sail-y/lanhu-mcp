import sys
import anyio
from contextlib import asynccontextmanager
import mcp.types as types
from mcp.shared.message import SessionMessage
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

MODE = None  # 'length' or 'line'


def _detect_first_byte(stream):
    while True:
        b = stream.read(1)
        if not b:
            return None
        if b not in (b' ', b'\t', b'\r', b'\n'):
            return b


@asynccontextmanager
async def codex_stdio_server(stdin=None, stdout=None):

    """Auto-detect length-prefixed (Codex) vs line-delimited (others) MCP stdio framing."""
    global MODE
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def stdin_reader():
        global MODE
        try:
            first = await anyio.to_thread.run_sync(_detect_first_byte, stdin)
            if first is None:
                return

            if first == b'C':
                MODE = 'length'
                header = first
                while not (header.endswith(b'\r\n\r\n') or header.endswith(b'\n\n')):
                    chunk = await anyio.to_thread.run_sync(stdin.read, 1)
                    if not chunk:
                        return
                    header += chunk
                length = 0
                for line in header.decode('utf-8', errors='replace').splitlines():
                    if line.lower().startswith('content-length:'):
                        length = int(line.split(':', 1)[1].strip())
                        break
                body = b''
                while len(body) < length:
                    chunk = await anyio.to_thread.run_sync(stdin.read, length - len(body))
                    if not chunk:
                        return
                    body += chunk
                line = body.decode('utf-8', errors='replace')
            elif first == b'{':
                MODE = 'line'
                line_buffer = first
                while True:
                    chunk = await anyio.to_thread.run_sync(stdin.read, 1)
                    if not chunk:
                        break
                    line_buffer += chunk
                    if chunk == b'\n':
                        break
                line = line_buffer.decode('utf-8', errors='replace').strip()
            else:
                MODE = 'line'
                line_buffer = first
                while True:
                    chunk = await anyio.to_thread.run_sync(stdin.read, 1)
                    if not chunk:
                        break
                    line_buffer += chunk
                    if chunk == b'\n':
                        break
                line = line_buffer.decode('utf-8', errors='replace').strip()

            if line:
                msg = types.JSONRPCMessage.model_validate_json(line)
                await read_stream_writer.send(SessionMessage(msg))

            while True:
                if MODE == 'length':
                    header = b''
                    while not (header.endswith(b'\r\n\r\n') or header.endswith(b'\n\n')):
                        chunk = await anyio.to_thread.run_sync(stdin.read, 1)
                        if not chunk:
                            return
                        header += chunk
                    length = 0
                    for line2 in header.decode('utf-8', errors='replace').splitlines():
                        if line2.lower().startswith('content-length:'):
                            length = int(line2.split(':', 1)[1].strip())
                            break
                    body = b''
                    while len(body) < length:
                        chunk = await anyio.to_thread.run_sync(stdin.read, length - len(body))
                        if not chunk:
                            return
                        body += chunk
                    line = body.decode('utf-8', errors='replace')
                else:
                    line_buffer = b''
                    while True:
                        chunk = await anyio.to_thread.run_sync(stdin.read, 1)
                        if not chunk:
                            return
                        line_buffer += chunk
                        if chunk == b'\n':
                            break
                    line = line_buffer.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue

                msg = types.JSONRPCMessage.model_validate_json(line)
                await read_stream_writer.send(SessionMessage(msg))
        except anyio.ClosedResourceError:
            pass
        finally:
            await read_stream_writer.aclose()

    async def stdout_writer():
        async with write_stream_reader:
            async for session_message in write_stream_reader:
                json_text = session_message.message.model_dump_json(
                    by_alias=True, exclude_none=True
                )
                if MODE == 'length':
                    body = json_text.encode('utf-8')
                    header = b'Content-Length: ' + str(len(body)).encode('utf-8') + b'\r\n\r\n'
                    await anyio.to_thread.run_sync(stdout.write, header + body)
                    await anyio.to_thread.run_sync(stdout.flush)
                else:
                    await anyio.to_thread.run_sync(stdout.write, (json_text + '\n').encode('utf-8'))
                    await anyio.to_thread.run_sync(stdout.flush)

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)
        yield read_stream, write_stream


def install():

    import mcp.server.stdio as stdio_module
    stdio_module.stdio_server = codex_stdio_server
    try:
        import fastmcp.server.mixins.transport as transport_module
        transport_module.stdio_server = codex_stdio_server
    except Exception:
        pass
