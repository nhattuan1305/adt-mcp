"""Entry point: `python -m adt_mcp` runs MCP + web admin on one port."""
import os
import httpx
from .registry import SystemRegistry
from .adt_client import ADTClient
from .server import build_server


def main() -> None:
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    systems_path = os.environ.get(
        "ADT_MCP_SYSTEMS", os.path.join(base, "systems.json"))
    port = int(os.environ.get("ADT_MCP_PORT", "8765"))

    registry = SystemRegistry(systems_path)
    adt = ADTClient(httpx.Client(timeout=30.0, verify=True))
    mcp = build_server(registry, adt)
    mcp.settings.port = port
    mcp.settings.host = "127.0.0.1"
    print(f"ADT MCP on http://127.0.0.1:{port}  (MCP at /mcp, admin at /)")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
