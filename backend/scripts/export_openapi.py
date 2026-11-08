"""Export the OpenAPI spec to a JSON file without starting the server.

``--plugin`` exports the plug-in API's spec instead: what an installed plug-in may call.
"""

import json
import os
import sys
from pathlib import Path

# Add backend to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set required env vars with dummy values so Settings() validates
# without a .env file (no DB connection or crypto needed for schema export)
# 64-hex dummy satisfying the startup validator; schema export does no crypto.
os.environ.setdefault(
    "SECRET_KEY", "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
)

from app.main import app, plugin_openapi


def main():
    args = sys.argv[1:]
    spec = plugin_openapi() if "--plugin" in args else app.openapi()
    paths = [arg for arg in args if arg != "--plugin"]
    output = paths[0] if paths else "-"
    content = json.dumps(spec, indent=2)
    if output == "-":
        print(content)
    else:
        Path(output).write_text(content)


if __name__ == "__main__":
    main()
