"""The MCP surface: how ChatGPT sees this machine.

The tool list is built at runtime from what the platform can actually do
(PRD 14.3). Advertising a tool that cannot work costs quota and credibility
every time the model tries it and gets an error.
"""

from pharness.core.mcp.server import build_server

__all__ = ["build_server"]
