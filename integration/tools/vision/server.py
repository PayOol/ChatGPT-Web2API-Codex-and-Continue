"""Read a user-authorized local image for the Web2API vision bridge."""

import json, sys, urllib.request, os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from media_registry import publish, MAX_BYTES

mcp = FastMCP("Vision")


@mcp.tool()
def view_image(path: str) -> dict:
    """Attach pixels of a local image to the next ChatGPT Web2API turn. Use only images relevant to the user's authorized task. Accepts a path relative to the opened workspace or an explicit absolute path; PNG/JPEG/WebP/GIF, at most 12 MB and 25 megapixels. Unlike image_info this delivers image content, not just metadata."""
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise ValueError("Image file does not exist")
    if candidate.stat().st_size > MAX_BYTES:
        raise ValueError("Image exceeds 12 MB")
    with urllib.request.urlopen(
        os.environ.get("W2A_API_BASE", "http://127.0.0.1:8080/v1").removesuffix("/v1") + "/health",
        timeout=3,
    ) as r:
        health = json.load(r)
    if not health.get("image_inputs"):
        raise RuntimeError("The local Web2API service has not activated image transport yet")
    return publish(candidate.read_bytes(), origin="local-image")


if __name__ == "__main__":
    mcp.run(transport="stdio")
