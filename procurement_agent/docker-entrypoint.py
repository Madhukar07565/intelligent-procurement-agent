"""Container entrypoint.

Writes the user accounts (password hashes only) from the USERS_JSON secret to
data/users.json, then starts Streamlit. The secret comes from AWS Secrets
Manager through ECS, so no account data is baked into the image.
"""
import json
import os
import sys
from pathlib import Path

DATA = Path(os.getenv("DATA_DIR", "/app/data"))
users_path = Path(os.getenv("USERS_PATH", DATA / "users.json"))
raw = os.environ.pop("USERS_JSON", "")  # remove from the environment Streamlit inherits

if raw:
    users = json.loads(raw)  # fail fast on a malformed secret
    if not isinstance(users, dict) or not users:
        sys.exit("USERS_JSON must be a non-empty JSON object")
    users_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(users_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(users, f)
    print(f"Loaded {len(users)} user account(s)", flush=True)
elif not users_path.exists():
    sys.exit("No user accounts: set USERS_JSON or provide data/users.json")

port = os.getenv("PORT", "8501")
os.execvp("streamlit", ["streamlit", "run", "app.py", "--server.port", port, "--server.address", "0.0.0.0",
                        "--server.headless", "true", "--browser.gatherUsageStats", "false"])
