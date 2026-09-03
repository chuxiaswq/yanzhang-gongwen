"""MCP transports for the Gongwen writing service.

The server factory is exposed lazily so ``python -m gongwen_mcp.server`` keeps
its stdio process free of the duplicate-module warning produced by an eager
package import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gongwen_mcp.server import close_server as close_server
    from gongwen_mcp.server import create_server as create_server


def __getattr__(name: str) -> object:
    if name in {"close_server", "create_server"}:
        from gongwen_mcp import server

        return getattr(server, name)
    raise AttributeError(name)


__all__ = ["close_server", "create_server"]
