"""
Where activated policy versions live.

The seam mirrors the one already used for demand and crowd sensing: an
abstract store, a local implementation that needs nothing, and a cloud one
selected by configuration. The demo runs offline on the local store; setting
`RAILSETU_POLICY_STORE=s3` moves the same records to S3 without any caller
changing.

Each document in the library has its own namespace, its own manifest and its
own sequence of versions, so amending crowd thresholds never appears in the
history of train precedence.

A version is IMMUTABLE once written. Correcting a bad policy means activating
a new version (or rolling back, which also writes a new version) — never
editing history. That is the whole point of a change register: the record of
what was in force at a given moment has to survive the decision to change it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.config import Settings

log = logging.getLogger("railsetu.policy.store")

MANIFEST = "index.json"
REGISTRY = "_registry.json"   # documents added through the UI


@dataclass
class PolicyVersion:
    """One activation: the document, who changed it, why, and what it did."""
    id: str                       # content hash, git-style short id
    seq: int                      # 1, 2, 3 … activation order
    title: str
    description: str
    author_name: str
    author_email: str
    created_at: str               # ISO8601 UTC
    yaml: str                     # the full document AS ACTIVATED
    parent_id: str | None = None
    diff_stats: dict = field(default_factory=dict)
    changes: list = field(default_factory=list)   # semantic changes vs parent
    impact: dict = field(default_factory=dict)    # measured effect at push time
    rollback_of: str | None = None                # set when this RESTORES an earlier version wholesale
    reverts: str | None = None                    # set when this backs out one earlier change
    # Where the change was made from. Either coordinates the browser supplied
    # (with the author's permission) or an explicit record that none were
    # available — never an inferred or approximated position.
    location: dict = field(default_factory=dict)

    def summary(self) -> dict:
        """Listing shape — everything but the full document."""
        d = asdict(self)
        d.pop("yaml", None)
        return d


def make_id(yaml_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{seq}:{yaml_text}".encode()).hexdigest()
    return h[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PolicyStore(ABC):
    """Every method is scoped to one document in the library."""

    @abstractmethod
    def list_versions(self, doc_key: str) -> list[dict]:
        """Newest first. Summaries only."""

    @abstractmethod
    def get_version(self, doc_key: str, version_id: str) -> PolicyVersion | None: ...

    @abstractmethod
    def put_version(self, doc_key: str, version: PolicyVersion) -> None: ...

    @abstractmethod
    def get_registry(self) -> list[dict]:
        """Documents added through the UI, so they survive a restart."""

    @abstractmethod
    def put_registry(self, rows: list[dict]) -> None: ...

    def head(self, doc_key: str) -> PolicyVersion | None:
        """The version of this document currently in force."""
        rows = self.list_versions(doc_key)
        return self.get_version(doc_key, rows[0]["id"]) if rows else None

    def next_seq(self, doc_key: str) -> int:
        rows = self.list_versions(doc_key)
        return (max((r["seq"] for r in rows), default=0)) + 1

    def health(self) -> dict:
        return {"store": type(self).__name__, "status": "ok"}


# --------------------------------------------------------------------------
# local
# --------------------------------------------------------------------------

class LocalPolicyStore(PolicyStore):
    """JSON files on disk. Default, needs no credentials, survives restarts."""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _path(self, doc_key: str, name: str) -> str:
        d = os.path.join(self.root, doc_key)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def _manifest(self, doc_key: str) -> list[dict]:
        p = self._path(doc_key, MANIFEST)
        if not os.path.exists(p):
            return []
        try:
            with open(p) as fh:
                return json.load(fh).get("versions", [])
        except (OSError, ValueError) as exc:
            log.warning("policy manifest unreadable (%s): %s", p, exc)
            return []

    def _write_manifest(self, doc_key: str, rows: list[dict]) -> None:
        tmp = self._path(doc_key, MANIFEST + ".tmp")
        with open(tmp, "w") as fh:
            json.dump({"versions": rows}, fh, indent=2)
        os.replace(tmp, self._path(doc_key, MANIFEST))   # atomic

    def list_versions(self, doc_key: str) -> list[dict]:
        return sorted(self._manifest(doc_key), key=lambda r: r["seq"], reverse=True)

    def get_version(self, doc_key: str, version_id: str) -> PolicyVersion | None:
        p = self._path(doc_key, f"{version_id}.json")
        if not os.path.exists(p):
            return None
        try:
            with open(p) as fh:
                return PolicyVersion(**json.load(fh))
        except (OSError, ValueError, TypeError) as exc:
            log.warning("policy version %s unreadable: %s", version_id, exc)
            return None

    def put_version(self, doc_key: str, version: PolicyVersion) -> None:
        with open(self._path(doc_key, f"{version.id}.json"), "w") as fh:
            json.dump(asdict(version), fh, indent=2)
        rows = [r for r in self._manifest(doc_key) if r["id"] != version.id]
        rows.append(version.summary())
        self._write_manifest(doc_key, rows)
        log.info("%s: version %s (seq %d) written locally", doc_key, version.id, version.seq)

    def get_registry(self) -> list[dict]:
        p = os.path.join(self.root, REGISTRY)
        if not os.path.exists(p):
            return []
        try:
            with open(p) as fh:
                return json.load(fh).get("documents", [])
        except (OSError, ValueError) as exc:
            log.warning("added-document registry unreadable: %s", exc)
            return []

    def put_registry(self, rows: list[dict]) -> None:
        os.makedirs(self.root, exist_ok=True)
        tmp = os.path.join(self.root, REGISTRY + ".tmp")
        with open(tmp, "w") as fh:
            json.dump({"documents": rows}, fh, indent=2)
        os.replace(tmp, os.path.join(self.root, REGISTRY))

    def health(self) -> dict:
        n = 0
        if os.path.isdir(self.root):
            n = sum(1 for d in os.listdir(self.root)
                    if os.path.isdir(os.path.join(self.root, d)))
        return {"store": "LocalPolicyStore", "status": "ok",
                "root": self.root, "documents": n}


# --------------------------------------------------------------------------
# S3
# --------------------------------------------------------------------------

class S3PolicyStore(PolicyStore):
    """Versions as objects under a prefix, plus a manifest for cheap listing.

    Listing every object and reading each one would cost an API call per
    version on every page load, so the manifest is the index and the per-
    version objects are only fetched when one is opened.
    """

    def __init__(self, settings: Settings):
        import boto3  # imported lazily so the local store needs no boto3

        self.bucket = settings.policy_s3_bucket
        self.prefix = settings.policy_s3_prefix.strip("/")
        self.region = settings.policy_s3_region or None
        self._s3 = boto3.client("s3", region_name=self.region)
        # boto3 does NOT validate credentials when the client is built, so
        # without this probe a store with bad keys constructs happily, reports
        # itself healthy, and then silently loses every write. Fail loudly here
        # instead, so build_policy_store can fall back to the local register.
        self._s3.head_bucket(Bucket=self.bucket)

    def _key(self, doc_key: str, name: str) -> str:
        parts = [p for p in (self.prefix, doc_key, name) if p]
        return "/".join(parts)

    def _get_json(self, doc_key: str, name: str):
        """Fetch one object. A MISSING key is normal (empty register) and returns
        None; anything else is a real fault and is raised, so health() and the
        caller can tell "nothing here yet" apart from "cannot reach the store"."""
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=self._key(doc_key, name))
            return json.loads(obj["Body"].read())
        except self._s3.exceptions.NoSuchKey:
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("s3 get %s failed: %s", name, exc)
            raise

    def _put_json(self, doc_key: str, name: str, payload) -> None:
        self._s3.put_object(
            Bucket=self.bucket, Key=self._key(doc_key, name),
            Body=json.dumps(payload, indent=2).encode(),
            ContentType="application/json",
        )

    def _manifest(self, doc_key: str) -> list[dict]:
        data = self._get_json(doc_key, MANIFEST)
        return (data or {}).get("versions", [])

    def list_versions(self, doc_key: str) -> list[dict]:
        return sorted(self._manifest(doc_key), key=lambda r: r["seq"], reverse=True)

    def get_version(self, doc_key: str, version_id: str) -> PolicyVersion | None:
        data = self._get_json(doc_key, f"{version_id}.json")
        if not data:
            return None
        try:
            return PolicyVersion(**data)
        except TypeError as exc:
            log.warning("policy version %s has unexpected shape: %s", version_id, exc)
            return None

    def put_version(self, doc_key: str, version: PolicyVersion) -> None:
        self._put_json(doc_key, f"{version.id}.json", asdict(version))
        rows = [r for r in self._manifest(doc_key) if r["id"] != version.id]
        rows.append(version.summary())
        self._put_json(doc_key, MANIFEST, {"versions": rows})
        log.info("%s: version %s (seq %d) written to s3://%s/%s",
                 doc_key, version.id, version.seq, self.bucket,
                 self._key(doc_key, ""))

    def get_registry(self) -> list[dict]:
        return (self._get_json("", REGISTRY) or {}).get("documents", [])

    def put_registry(self, rows: list[dict]) -> None:
        self._put_json("", REGISTRY, {"documents": rows})

    def health(self) -> dict:
        try:
            from . import documents as docs
            return {"store": "S3PolicyStore", "status": "ok",
                    "bucket": self.bucket, "prefix": self.prefix,
                    "region": self.region, "documents": len(docs.all_documents())}
        except Exception as exc:  # noqa: BLE001
            return {"store": "S3PolicyStore", "status": "error",
                    "bucket": self.bucket, "error": str(exc)}


def build_policy_store(settings: Settings) -> PolicyStore:
    if settings.policy_store == "s3":
        try:
            store = S3PolicyStore(settings)
            log.info("policy register on s3://%s/%s", store.bucket, store.prefix)
            return store
        except Exception as exc:  # noqa: BLE001
            # Missing credentials, wrong region, unreachable bucket. This must
            # not take the platform down — the register degrades to local, and
            # says so, rather than silently accepting writes that go nowhere.
            log.error("S3 policy register unavailable (%s); using the local register instead", exc)
    root = settings.policy_local_root
    if not os.path.isabs(root):
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # backend/
        root = os.path.join(base, root)
    return LocalPolicyStore(root)
