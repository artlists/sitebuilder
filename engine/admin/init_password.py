#!/usr/bin/env python3
"""Create/update admin users. Stores PBKDF2 hashes only (never plaintext).

Usage:
    python3 admin/init_password.py                    # interactive
    python3 admin/init_password.py SLUT '101#1477'    # non-interactive
"""
import base64
import hashlib
import json
import os
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
USERS = ROOT / "admin" / "users.json"
ITER = 260_000


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER)
    return (f"pbkdf2_sha256${ITER}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}")


def load():
    if USERS.exists():
        try:
            return json.loads(USERS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []


def main():
    if len(sys.argv) == 3:
        username, password = sys.argv[1], sys.argv[2]
    else:
        username = input("username: ").strip()
        import getpass
        password = getpass.getpass("password: ")
    if not username or not password:
        print("empty username/password")
        return 1

    users = load()
    users = [u for u in users if u.get("username") != username]
    users.append({"username": username, "hash": hash_password(password)})
    USERS.parent.mkdir(exist_ok=True)
    USERS.write_text(json.dumps(users, indent=2), encoding="utf-8")
    os.chmod(USERS, 0o600)
    print(f"user '{username}' saved to {USERS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())