import os
import sys
import time
import json
import asyncio
import pty
import fcntl
import termios
import struct
import select
from fastapi import WebSocket, WebSocketDisconnect
from core.config import connected_agents

async def handle_local_terminal(websocket: WebSocket):
    master_fd, slave_fd = pty.openpty()

    # Set non-blocking
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Default size 80x24
    winsize = struct.pack("HHHH", 24, 80, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

    pid = os.fork()
    if pid == 0:
        # Child process
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.environ["TERM"] = "xterm-256color"
        os.environ["LANG"] = "en_US.UTF-8"
        os.environ["LC_ALL"] = "en_US.UTF-8"
        os.execlp("/bin/bash", "/bin/bash", "-l")
        sys.exit(0)

    os.close(slave_fd)

    async def read_from_pty():
        try:
            while True:
                await asyncio.sleep(0.02)
                r, _, _ = select.select([master_fd], [], [], 0)
                if r:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        await websocket.send_bytes(data)
                    except (BlockingIOError, OSError):
                        pass
        except (WebSocketDisconnect, asyncio.CancelledError, Exception):
            pass

    async def write_to_pty():
        try:
            while True:
                msg = await websocket.receive()
                if "text" in msg:
                    data = msg["text"]
                    try:
                        # Check resize message format: {"resize": [cols, rows]}
                        js = json.loads(data)
                        if "resize" in js:
                            cols, rows = js["resize"]
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                            continue
                    except Exception:
                        pass
                    os.write(master_fd, data.encode('utf-8'))
                elif "bytes" in msg:
                    os.write(master_fd, msg["bytes"])
        except (WebSocketDisconnect, asyncio.CancelledError, Exception):
            pass

    reader_task = asyncio.create_task(read_from_pty())
    writer_task = asyncio.create_task(write_to_pty())

    try:
        # Exit as soon as either writer (client disconnects) or reader exits
        done, pending = await asyncio.wait(
            [reader_task, writer_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
    finally:
        try:
            os.close(master_fd)
        except Exception:
            pass
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except Exception:
            pass

async def handle_remote_terminal(websocket: WebSocket, node_id: str):
    agent = connected_agents.get(node_id)
    if not agent:
        await websocket.send_text("\r\n[!] Agent is offline. Cannot open terminal session.\r\n")
        await websocket.close()
        return

    session_id = f"term_{int(time.time()*1000)}"
    agent_ws = agent["ws"]

    # Tell agent to open terminal
    await agent_ws.send_json({"action": "open_terminal", "session_id": session_id})

    async def browser_to_agent():
        try:
            while True:
                msg = await websocket.receive()
                if "text" in msg:
                    await agent_ws.send_json({"action": "term_input", "session_id": session_id, "data": msg["text"]})
                elif "bytes" in msg:
                    await agent_ws.send_bytes(msg["bytes"])
        except Exception:
            pass

    agent["term_sessions"] = agent.get("term_sessions", {})
    agent["term_sessions"][session_id] = websocket

    try:
        await browser_to_agent()
    finally:
        agent["term_sessions"].pop(session_id, None)
        try:
            await agent_ws.send_json({"action": "close_terminal", "session_id": session_id})
        except Exception:
            pass
