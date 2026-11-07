#!/usr/bin/env python3
"""Save your Garmin Personal API key on this Mac (hidden input) and test it.

Run:  .tools/bin/uv run --python 3.12 --with garmin-connect-personal-api-python sync/save_key.py
The key is stored in ~/.config/garmin/connect-personal-api-key (readable only by you),
which is where Garmin's official client looks for it.
"""
import getpass
import os
from pathlib import Path

from garmin_personal_api import PersonalApiAuthenticator

path = Path("~/.config/garmin/connect-personal-api-key").expanduser()
from garmin_personal_api import HttpError

key = getpass.getpass("Paste your Garmin Personal API key (hidden), then press Enter: ")
key = "".join(key.split()).strip("'\"")  # drop spaces/newlines/quotes picked up while copying
if key.lower().startswith("apikey"):
    key = key[6:]
if not key:
    raise SystemExit("No key entered.")
print(f"Received {len(key)} characters: {key[:4]}...{key[-4:]}  (compare with the key Garmin showed you)")

print("Checking the key with Garmin...")
try:
    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(key, force_refresh=True)
except HttpError as e:
    print(f"\nGarmin rejected the key: {e}")
    print("Check that the characters above match your key. If the key was deleted or regenerated,")
    print("create a new one at https://connect.garmin.com/app/settings/personalApiToken and run this again.")
    raise SystemExit(1)
print("Key works. Access token valid until", __import__("datetime").datetime.fromtimestamp(token.expires_at))

path.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(key)
print(f"Saved to {path}. You can close this tab.")
