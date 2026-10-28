"""Application settings, read from environment variables (and an optional .env file).

Nothing secret is hard-coded here. Payment details, the session secret and the
admin bootstrap credentials all come from the environment.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE per line). Real environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _num(value: Optional[str], default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_env: str
    secret_key: str
    data_dir: Path
    max_upload_mb: int
    session_hours: int
    admin_session_hours: int
    usd_to_inr: float
    public_margins: bool
    cookie_secure: bool
    trust_proxy: bool
    allowed_origins: tuple
    csp_report_only: bool
    tz_offset_minutes: int
    pay_upi_id: str
    pay_account_name: str
    pay_account_number: str
    pay_ifsc: str
    pay_bank_name: str
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    bootstrap_admin_name: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lilizzh.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def payment_configured(self) -> bool:
        return bool(self.pay_upi_id and self.pay_account_name)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        e = os.environ if env is None else env
        app_env = (e.get("APP_ENV") or "development").strip().lower()
        secret = (e.get("SECRET_KEY") or "").strip()
        if app_env == "production" and len(secret) < 32:
            raise RuntimeError(
                "SECRET_KEY must be set to a random string of at least 32 characters when "
                "APP_ENV=production. Run `python manage.py init` to generate one."
            )
        if not secret:
            # Development convenience only: sessions reset whenever the server restarts.
            secret = secrets.token_urlsafe(48)
        data_dir = Path(e.get("DATA_DIR") or (BASE_DIR / "data")).expanduser()
        origins = tuple(
            o.strip().lower() for o in (e.get("ALLOWED_ORIGINS") or "").split(",") if o.strip()
        )
        return cls(
            app_env=app_env,
            secret_key=secret,
            data_dir=data_dir,
            max_upload_mb=int(_num(e.get("MAX_UPLOAD_MB"), 1024)),
            session_hours=int(_num(e.get("SESSION_HOURS"), 24 * 7)),
            admin_session_hours=int(_num(e.get("ADMIN_SESSION_HOURS"), 8)),
            usd_to_inr=_num(e.get("USD_TO_INR"), 86.0),
            public_margins=_bool(e.get("PUBLIC_RATE_CARD_SHOWS_MARGINS"), False),
            cookie_secure=_bool(e.get("COOKIE_SECURE"), app_env == "production"),
            trust_proxy=_bool(e.get("TRUST_PROXY"), False),
            allowed_origins=origins,
            csp_report_only=_bool(e.get("CSP_REPORT_ONLY"), False),
            tz_offset_minutes=int(_num(e.get("TZ_OFFSET_MINUTES"), 330)),
            pay_upi_id=(e.get("PAY_UPI_ID") or "").strip(),
            pay_account_name=(e.get("PAY_ACCOUNT_NAME") or "").strip(),
            pay_account_number=(e.get("PAY_ACCOUNT_NUMBER") or "").strip(),
            pay_ifsc=(e.get("PAY_IFSC") or "").strip(),
            pay_bank_name=(e.get("PAY_BANK_NAME") or "").strip(),
            bootstrap_admin_email=(e.get("ADMIN_EMAIL") or "").strip(),
            bootstrap_admin_password=e.get("ADMIN_PASSWORD") or "",
            bootstrap_admin_name=(e.get("ADMIN_NAME") or "Studio Admin").strip(),
        )


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    return Settings.from_env()
