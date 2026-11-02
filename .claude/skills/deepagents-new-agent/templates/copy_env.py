"""Copy only the API key line(s) from an existing .env into this project's .env. Prints no values.

Usage: python copy_env.py "C:/path/to/other/.env" [KEY_NAME ...]   (default key: GOOGLE_API_KEY)
"""

import sys
from pathlib import Path

src = Path(sys.argv[1])
keys = sys.argv[2:] or ["GOOGLE_API_KEY"]
lines = [line for line in src.read_text(encoding="utf-8").splitlines() if line.split("=", 1)[0].strip() in keys]
dest = Path(__file__).resolve().parent / ".env"
dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Copied {len(lines)} of {len(keys)} key line(s) to {dest.name}.")
