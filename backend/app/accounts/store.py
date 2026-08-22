"""
Where user accounts live.

Same seam as the demand provider, the crowd sensor and the policy register: an
abstract store, a local implementation that needs nothing, and an S3 one chosen
by configuration. An account is created the first time an address signs in and
updated on every sign-in after that.

The account record is deliberately small. It exists to answer one question —
"who made this change?" — so it holds an address, a display name derived from
it, and when the platform last saw them. Nothing else about a person is kept.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.config import Settings

log = logging.getLogger("railsetu.accounts.store")

INDEX = "index.json"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    e = normalise(email)
    return bool(e) and len(e) <= 254 and bool(EMAIL_RE.match(e))


def account_key(email: str) -> str:
    """Stable object id for an address, so the address is not a filename."""
    return hashlib.sha256(normalise(email).encode()).hexdigest()[:16]


def display_name_for(email: str) -> str:
    """'asha.rao@ir.gov.in' -> 'Asha Rao'. A readable label, nothing more."""
    local = normalise(email).split("@")[0]
    parts = [p for p in re.split(r"[._\-+]+", local) if p]
    if not parts:
        return normalise(email)
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Account:
    email: str
    display_name: str
    created_at: str
    last_seen_at: str
    sign_in_count: int = 1

    def public(self) -> dict:
        return asdict(self)


class AccountStore(ABC):
    @abstractmethod
    def get(self, email: str) -> Account | None: ...

    @abstractmethod
    def put(self, account: Account) -> None: ...

    @abstractmethod
    def list_accounts(self) -> list[dict]: ...

    def health(self) -> dict:
        return {"store": type(self).__name__, "status": "ok"}


class LocalAccountStore(AccountStore):
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.root, name)

    def _index(self) -> list[dict]:
        p = self._path(INDEX)
        if not os.path.exists(p):
            return []
        try:
            with open(p) as fh:
                return json.load(fh).get("accounts", [])
        except (OSError, ValueError) as exc:
            log.warning("account index unreadable (%s): %s", p, exc)
            return []

    def _write_index(self, rows: list[dict]) -> None:
        tmp = self._path(INDEX + ".tmp")
        with open(tmp, "w") as fh:
            json.dump({"accounts": rows}, fh, indent=2)
        os.replace(tmp, self._path(INDEX))

    def get(self, email: str) -> Account | None:
        p = self._path(f"{account_key(email)}.json")
        if not os.path.exists(p):
            return None
        try:
            with open(p) as fh:
                return Account(**json.load(fh))
        except (OSError, ValueError, TypeError) as exc:
            log.warning("account %s unreadable: %s", account_key(email), exc)
            return None

    def put(self, account: Account) -> None:
        with open(self._path(f"{account_key(account.email)}.json"), "w") as fh:
            json.dump(asdict(account), fh, indent=2)
        rows = [r for r in self._index() if r.get("email") != account.email]
        rows.append(account.public())
        self._write_index(rows)

    def list_accounts(self) -> list[dict]:
        return sorted(self._index(), key=lambda r: r.get("last_seen_at", ""), reverse=True)

    def health(self) -> dict:
        return {"store": "LocalAccountStore", "status": "ok",
                "root": self.root, "accounts": len(self._index())}


class S3AccountStore(AccountStore):
    def __init__(self, settings: Settings):
        import boto3

        self.bucket = settings.accounts_s3_bucket
        self.prefix = settings.accounts_s3_prefix.strip("/")
        self.region = settings.accounts_s3_region or None
        self._s3 = boto3.client("s3", region_name=self.region)
        # boto3 builds a client without contacting AWS, so credentials are only
        # proven here. Without this probe a broken store would look healthy and
        # then drop every write. See the policy register for the same reasoning.
        self._s3.head_bucket(Bucket=self.bucket)

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    def _get_json(self, name: str):
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=self._key(name))
            return json.loads(obj["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("s3 get %s failed: %s", name, exc)
            raise

    def _put_json(self, name: str, payload) -> None:
        self._s3.put_object(
            Bucket=self.bucket, Key=self._key(name),
            Body=json.dumps(payload, indent=2).encode(),
            ContentType="application/json",
        )

    def _index(self) -> list[dict]:
        return (self._get_json(INDEX) or {}).get("accounts", [])

    def get(self, email: str) -> Account | None:
        data = self._get_json(f"{account_key(email)}.json")
        if not data:
            return None
        try:
            return Account(**data)
        except TypeError as exc:
            log.warning("account record has unexpected shape: %s", exc)
            return None

    def put(self, account: Account) -> None:
        self._put_json(f"{account_key(account.email)}.json", asdict(account))
        rows = [r for r in self._index() if r.get("email") != account.email]
        rows.append(account.public())
        self._put_json(INDEX, {"accounts": rows})

    def list_accounts(self) -> list[dict]:
        return sorted(self._index(), key=lambda r: r.get("last_seen_at", ""), reverse=True)

    def health(self) -> dict:
        try:
            return {"store": "S3AccountStore", "status": "ok", "bucket": self.bucket,
                    "prefix": self.prefix, "region": self.region,
                    "accounts": len(self._index())}
        except Exception as exc:  # noqa: BLE001
            return {"store": "S3AccountStore", "status": "error",
                    "bucket": self.bucket, "error": str(exc)}


def build_account_store(settings: Settings) -> AccountStore:
    if settings.accounts_store == "s3":
        try:
            store = S3AccountStore(settings)
            log.info("accounts on s3://%s/%s", store.bucket, store.prefix)
            return store
        except Exception as exc:  # noqa: BLE001
            log.error("S3 account store unavailable (%s); using the local store instead", exc)
    root = settings.accounts_local_root
    if not os.path.isabs(root):
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # backend/
        root = os.path.join(base, root)
    return LocalAccountStore(root)
