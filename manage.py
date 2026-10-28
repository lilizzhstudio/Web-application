#!/usr/bin/env python3
"""Lilizzh Studio admin tool.

    python manage.py init                  first-time setup (secret key, admin login, editor passcodes)
    python manage.py run                   start the website + API on http://127.0.0.1:8000
    python manage.py set-admin-password    change the admin password
    python manage.py set-editor-passcode   change (or randomly reset) one editor's passcode
    python manage.py create-admin          add another studio admin
    python manage.py seed-demo             add the two demo clients/orders from the original design
    python manage.py inquiries             list messages sent through the website's inquiry form
    python manage.py check                 audit your configuration before going live

Passwords are typed at a hidden prompt (or piped with --password-stdin) and stored only as scrypt hashes.
Nothing here ever prints a stored password - hashes cannot be turned back into passwords.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import sys
from pathlib import Path

from app.config import BASE_DIR, Settings, load_dotenv
from app.db import connect, init_db
from app.security import hash_password, normalise_email, password_problem, valid_email
from app.seed import (EDITORS, create_admin, has_admin, random_secret, seed_demo, seed_editors,
                      seed_rate_card)

ENV_PATH = BASE_DIR / ".env"
DEFAULT_ADMIN_NAME = "Lilesh Pravin Patil (Lead Admin)"
DEFAULT_ADMIN_EMAIL = "lilizzh.studio@gmail.com"

ENV_TEMPLATE = """\
# Lilizzh Studio - private settings. NEVER commit or share this file (it is in .gitignore).
# Written by `python manage.py init`; edit freely.

# "development" for testing on your own computer, "production" once the site is live on HTTPS.
APP_ENV=development
SECRET_KEY={secret}

# Sent to clients only AFTER they sign in and open the payment window for their own order.
PAY_UPI_ID=
PAY_ACCOUNT_NAME=
PAY_ACCOUNT_NUMBER=
PAY_IFSC=
PAY_BANK_NAME=

# Set to 1 to show "Editor Payout" and "Studio Profit" columns to everyone in the public rate card
# (this is how the original page looked). Default 0 keeps your margins private.
PUBLIC_RATE_CARD_SHOWS_MARGINS=0

# Production extras (see README):
# COOKIE_SECURE=1        (default in production; needs HTTPS)
# TRUST_PROXY=1          (when running behind nginx / Cloudflare / a hosting platform's proxy)
# ALLOWED_ORIGINS=https://yourdomain.com
# MAX_UPLOAD_MB=1024
# DATA_DIR=/var/lib/lilizzh
"""


# ---------------------------------------------------------------- helpers
def read_env() -> dict:
    values = {}
    if ENV_PATH.is_file():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
                key, value = raw.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def set_env(key: str, value: str) -> None:
    """Add or replace KEY=value in .env (keeps comments and other lines)."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.is_file() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


def ensure_env() -> bool:
    """Create .env with a fresh SECRET_KEY if it doesn't exist. Returns True if created."""
    if ENV_PATH.is_file():
        values = read_env()
        if len(values.get("SECRET_KEY", "")) < 32:
            set_env("SECRET_KEY", secrets.token_urlsafe(48))
        return False
    ENV_PATH.write_text(ENV_TEMPLATE.format(secret=secrets.token_urlsafe(48)), encoding="utf-8")
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass
    return True


def open_db() -> tuple:
    load_dotenv(ENV_PATH)
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    return settings, connect(settings.db_path)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def read_password(args, label: str, minimum: int = 12) -> str:
    """Hidden prompt (twice) or a single line from stdin with --password-stdin."""
    if getattr(args, "password_stdin", False):
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        while True:
            password = getpass.getpass(f"{label}: ")
            if getpass.getpass("Type it again to confirm: ") == password:
                break
            print("  The two entries did not match - try again.")
    if len(password) < minimum:
        sys.exit(f"Error: the password must be at least {minimum} characters long.")
    problem = password_problem(password)
    if problem:
        sys.exit(f"Error: {problem}")
    return password


def revoke_sessions(conn, *, user_id=None, editor_id=None) -> None:
    if user_id is not None:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    if editor_id is not None:
        conn.execute("DELETE FROM sessions WHERE editor_id = ?", (editor_id,))


# --------------------------------------------------------------- commands
def cmd_init(args) -> None:
    created = ensure_env()
    print(("Created" if created else "Using existing"), f"{ENV_PATH.name} (private settings, permissions 600).")
    settings, conn = open_db()
    try:
        if not conn.execute("SELECT 1 FROM rate_card").fetchone():
            print(f"Loaded rate card ({seed_rate_card(conn)} tiers).")

        passcodes = seed_editors(conn)

        if has_admin(conn) and not args.force:
            print("An admin account already exists - leaving it unchanged "
                  "(use `set-admin-password` to change the password).")
        else:
            print("\n--- Admin account ---")
            name = args.admin_name or (DEFAULT_ADMIN_NAME if args.password_stdin else ask("Admin display name", DEFAULT_ADMIN_NAME))
            email = normalise_email(args.admin_email or (DEFAULT_ADMIN_EMAIL if args.password_stdin else ask("Admin e-mail", DEFAULT_ADMIN_EMAIL)))
            if not valid_email(email):
                sys.exit("Error: that e-mail address does not look right.")
            password = read_password(args, "Choose an admin password (12+ characters)")
            if not create_admin(conn, name, email, password):
                sys.exit("Error: a user with that e-mail already exists. Use `set-admin-password` instead.")
            print(f"Admin account created for {email}.")

        if not args.password_stdin and not read_env().get("PAY_UPI_ID"):
            print("\n--- Payment details shown to clients (optional - press Enter to skip, edit .env later) ---")
            for key, label in (("PAY_UPI_ID", "UPI ID"), ("PAY_ACCOUNT_NAME", "Account holder name"),
                               ("PAY_ACCOUNT_NUMBER", "Account number / phone"), ("PAY_IFSC", "IFSC code"),
                               ("PAY_BANK_NAME", "Bank name")):
                value = ask(label)
                if value:
                    set_env(key, value)

        if passcodes:
            print("\n--- Editor passcodes (shown ONCE - give each editor theirs, then clear your screen) ---")
            for ed in EDITORS:
                if ed["id"] in passcodes:
                    print(f"  {ed['name']:<16} ({ed['id']})   {passcodes[ed['id']]}")
            print("Only secure hashes are stored. Forgot one? `python manage.py set-editor-passcode ed-1 --random`")
        print("\nAll set. Start the site with:  python manage.py run")
    finally:
        conn.close()


def cmd_run(args) -> None:
    try:
        import uvicorn
    except ImportError:
        sys.exit("uvicorn is not installed. Run: pip install -r requirements.txt")
    load_dotenv(ENV_PATH)
    settings = Settings.from_env()
    if settings.is_production and args.host == "127.0.0.1":
        print("Production mode: put this behind HTTPS (nginx / Caddy / your host's proxy) and set TRUST_PROXY=1.")
    uvicorn.run("app.main:app_factory", factory=True, host=args.host, port=args.port,
                proxy_headers=settings.trust_proxy, forwarded_allow_ips="*" if settings.trust_proxy else None)


def cmd_set_admin_password(args) -> None:
    ensure_env()
    settings, conn = open_db()
    try:
        email = normalise_email(args.email) if args.email else None
        row = (conn.execute("SELECT * FROM users WHERE role='ADMIN' AND email = ?", (email,)).fetchone() if email
               else conn.execute("SELECT * FROM users WHERE role='ADMIN' ORDER BY id LIMIT 1").fetchone())
        if row is None:
            sys.exit("No such admin. Run `python manage.py init` (or `create-admin`) first.")
        password = read_password(args, f"New password for {row['email']} (12+ characters)")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row["id"]))
        revoke_sessions(conn, user_id=row["id"])
        print(f"Password updated for {row['email']}. Existing sign-ins were ended.")
    finally:
        conn.close()


def cmd_create_admin(args) -> None:
    ensure_env()
    settings, conn = open_db()
    try:
        email = normalise_email(args.email)
        if not valid_email(email):
            sys.exit("Error: that e-mail address does not look right.")
        password = read_password(args, f"Password for {email} (12+ characters)")
        if not create_admin(conn, args.name or "Studio Admin", email, password):
            sys.exit("Error: a user with that e-mail already exists.")
        print(f"Admin account created for {email}.")
    finally:
        conn.close()


def cmd_set_editor_passcode(args) -> None:
    ensure_env()
    settings, conn = open_db()
    try:
        row = conn.execute("SELECT id, name FROM editors WHERE id = ?", (args.editor_id,)).fetchone()
        if row is None:
            ids = ", ".join(r["id"] for r in conn.execute("SELECT id FROM editors ORDER BY sort_order"))
            sys.exit(f"Unknown editor '{args.editor_id}'. Choose one of: {ids}")
        if args.random:
            passcode = random_secret(12)
            shown = True
        else:
            passcode = read_password(args, f"New passcode for {row['name']} (10+ characters)", minimum=10)
            shown = False
        conn.execute("UPDATE editors SET passcode_hash = ? WHERE id = ?", (hash_password(passcode), row["id"]))
        revoke_sessions(conn, editor_id=row["id"])
        print(f"Passcode updated for {row['name']}. Existing sign-ins were ended.")
        if shown:
            print(f"New passcode (shown once): {passcode}")
    finally:
        conn.close()


def cmd_seed_demo(args) -> None:
    ensure_env()
    settings, conn = open_db()
    try:
        seed_editors(conn)
        creds = seed_demo(conn, settings)
        if creds:
            print("Demo clients created (random passwords, shown once):")
            for email, password in creds.items():
                print(f"  {email:<26} {password}")
        else:
            print("Demo data already present.")
    finally:
        conn.close()


def cmd_inquiries(args) -> None:
    settings, conn = open_db()
    try:
        rows = conn.execute("SELECT id,name,email,phone,created_at FROM inquiries ORDER BY id DESC LIMIT ?",
                            (args.limit,)).fetchall()
        if not rows:
            print("No inquiries yet.")
        for r in rows:
            print(f"#{r['id']:<4} {r['created_at']}  {r['name']}  <{r['email']}>  {r['phone']}")
    finally:
        conn.close()


def cmd_check(args) -> None:
    load_dotenv(ENV_PATH)
    problems, notes = [], []
    env = {**os.environ}
    settings = None
    try:
        settings = Settings.from_env(env)
    except RuntimeError as exc:
        problems.append(str(exc))
    if settings:
        if not settings.is_production:
            problems.append("APP_ENV is not 'production'. Set APP_ENV=production before going live.")
        if not settings.cookie_secure:
            problems.append("COOKIE_SECURE is off. Serve the site over HTTPS and set COOKIE_SECURE=1.")
        if len(env.get("SECRET_KEY", "")) < 32:
            problems.append("SECRET_KEY is missing or too short. Run `python manage.py init`.")
        if not settings.payment_configured:
            notes.append("Payment details are not set (PAY_* in .env): the payment window will say so.")
        if settings.public_margins:
            notes.append("PUBLIC_RATE_CARD_SHOWS_MARGINS=1: editor payouts and studio profit are visible to everyone.")
        if settings.db_path.is_file():
            conn = connect(settings.db_path)
            try:
                if not has_admin(conn):
                    problems.append("No admin account. Run `python manage.py init`.")
                if conn.execute("SELECT COUNT(*) FROM editors WHERE passcode_hash IS NULL OR passcode_hash=''").fetchone()[0]:
                    problems.append("Some editors have no passcode. Run `python manage.py set-editor-passcode <id> --random`.")
            finally:
                conn.close()
        else:
            problems.append("No database yet. Run `python manage.py init`.")
        if not settings.trust_proxy:
            notes.append("TRUST_PROXY is off. If a proxy (nginx, Cloudflare...) sits in front, set TRUST_PROXY=1 "
                         "so login lockouts use real visitor addresses.")
    if ENV_PATH.is_file() and (ENV_PATH.stat().st_mode & 0o077):
        problems.append(".env is readable by other users on this machine. Run: chmod 600 .env")
    for note in notes:
        print("note:  ", note)
    for problem in problems:
        print("FIX:   ", problem)
    if not problems:
        print("OK - configuration looks production-ready.")
    sys.exit(1 if problems else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lilizzh Studio admin tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="first-time setup")
    p.add_argument("--admin-name")
    p.add_argument("--admin-email")
    p.add_argument("--password-stdin", action="store_true", help="read the admin password from stdin (non-interactive)")
    p.add_argument("--force", action="store_true", help="create the admin even if one exists")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("run", help="start the server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("set-admin-password", help="change an admin password")
    p.add_argument("--email")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_set_admin_password)

    p = sub.add_parser("create-admin", help="add another admin")
    p.add_argument("--email", required=True)
    p.add_argument("--name")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("set-editor-passcode", help="change or reset an editor's passcode")
    p.add_argument("editor_id", help="ed-1, ed-2, ed-3 or ed-4")
    p.add_argument("--random", action="store_true", help="generate a random passcode and print it once")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_set_editor_passcode)

    p = sub.add_parser("seed-demo", help="add demo clients and orders")
    p.set_defaults(func=cmd_seed_demo)

    p = sub.add_parser("inquiries", help="list messages sent through the website's inquiry form")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_inquiries)

    p = sub.add_parser("check", help="audit configuration")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
