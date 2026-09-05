"""SQLite database layer for CashPilot.

Stores earnings history, user configuration, and deployment records.
DB file lives at /data/cashpilot.db (Docker volume mount) with a local
fallback to ./data/cashpilot.db for development.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

from app import earnapp_policy

_logger = logging.getLogger(__name__)

# ISO alpha-2 code is the stable location/filter key. Raw country names remain
# stored as evidence and the browser derives a readable label from the code.
_COUNTRY_CODE_ALIASES = {
    "australia": "AU",
    "canada": "CA",
    "france": "FR",
    "germany": "DE",
    "india": "IN",
    "japan": "JP",
    "netherlands": "NL",
    "singapore": "SG",
    "south korea": "KR",
    "taiwan": "TW",
    "thailand": "TH",
    "uk": "GB",
    "united kingdom": "GB",
    "united states": "US",
    "usa": "US",
    "viet nam": "VN",
    "vietnam": "VN",
}


def canonical_proxy_country_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text == "UK":
        return "GB"
    return text if len(text) == 2 and text.isalpha() else ""


def canonical_proxy_location(country_code: Any, country_name: Any = "") -> str:
    code = canonical_proxy_country_code(country_code)
    if code:
        return code
    alias = str(country_name or "").strip().lower()
    return _COUNTRY_CODE_ALIASES.get(alias, "")


def _proxy_location_sql() -> str:
    name_cases = " ".join(
        f"WHEN '{name.replace(chr(39), chr(39) + chr(39))}' THEN '{code}'"
        for name, code in _COUNTRY_CODE_ALIASES.items()
    )
    return f"""CASE
        WHEN trim(coalesce(pe.exit_ip, '')) = '' AND lower(coalesce(pe.status, '')) = 'dead' THEN 'Generic check failed'
        WHEN trim(coalesce(pe.exit_ip, '')) = '' THEN 'Egress unresolved'
        WHEN length(trim(coalesce(pe.country_code, ''))) = 2
             AND upper(trim(pe.country_code)) GLOB '[A-Z][A-Z]'
          THEN CASE upper(trim(pe.country_code)) WHEN 'UK' THEN 'GB' ELSE upper(trim(pe.country_code)) END
        WHEN trim(coalesce(pe.country_name, '')) != '' THEN CASE lower(pe.country_name) {name_cases} ELSE pe.country_name END
        ELSE 'Metadata pending'
    END"""


class MystWalletPublicIpInUse(RuntimeError):
    pass


class NknWalletLeaseActive(RuntimeError):
    """Raised when deleting a worker would strand an active NKN wallet lease."""


class ProtectedEarnAppWorkerReference(RuntimeError):
    """Raised when deleting a worker would mutate an inspection-only EarnApp node."""


class ProtectedEarnAppProxyError(RuntimeError):
    """Raised when a proxy mutation would affect an inspection-only node."""


DB_DIR = Path(os.getenv("CASHPILOT_DATA_DIR", "/data"))
DB_PATH = DB_DIR / "cashpilot.db"

# ---------------------------------------------------------------------------
# Credential encryption (Fernet)
# ---------------------------------------------------------------------------

_FERNET_KEY_FILE = DB_DIR / ".fernet_key"

# Keys that contain secrets and must be encrypted at rest
SECRET_CONFIG_KEYS = {
    "password",
    "token",
    "auth_token",
    "access_token",
    "access_key",
    "api_key",
    "secret_key",
    "session_cookie",
    # Dashboard sessions are bearer credentials even when a provider names the
    # field differently from the generic cookie/token conventions above.
    "dashboard_session",
    "auth_cookie",
    "oauth_token",
    "brd_sess_id",
    "remember_web",
    "xsrf_token",
    # Added after an audit found the at-rest boundary was a naming convention
    # with nothing enforcing it: a collector argument called "cookie" or "seed"
    # was silently stored in plaintext. Matching is by suffix and reads are
    # backward compatible (a value without the "enc:" prefix is returned as-is),
    # so widening this list only affects new writes.
    "cookie",
    "credential",
    "bearer",
    "jwt",
    "passphrase",
    "phrase",
    "secret",
    "seed",
    "mnemonic",
    "private_key",
    "keyfile",
    "credentials_json",
    "main_db",
    "refresh_token",
    "store_wynd_status",
    "store_wynd_user_id",
    "store_wynd_browser_id",
    "store_wynd_device_privkey",
    "store_wynd_device_pubkey",
    "store_wynd_device_id",
    "store_wynd_device_registered_pubkey",
    "store_wynd_device_registered_user_id",
    "store_token_expiry",
    "store_auto_update",
    "store_wynd_authenticated",
    "store_refresh_token",
    "store_access_token",
    "user_id",
    "chrome_profile_key",
}


def _is_secret_key(key: str) -> bool:
    """Return True if a config key holds a secret value (by suffix match)."""
    lower = key.lower()
    return any(lower.endswith(s) for s in SECRET_CONFIG_KEYS)


_TRUTHY = {"1", "true", "yes", "on"}

# Set when CASHPILOT_ENCRYPTION_KEY is present but not a usable Fernet key.
_fernet_key_error: str | None = None
# Set when the key could not be written to disk, i.e. it dies with this process.
_fernet_key_persist_error: str | None = None
_fernet_key_is_ephemeral = False


def _load_or_create_fernet() -> Fernet:
    """Resolve the key used to encrypt stored credentials.

    Precedence is deliberate, and file-first:

      1. ``<data>/.fernet_key`` always wins when it exists.
      2. Otherwise ``CASHPILOT_ENCRYPTION_KEY``, which is then persisted.
      3. Otherwise a fresh key is generated and persisted.

    Reading the file first is what makes the environment variable safe to
    introduce. Env-first would mean anyone who sets it on a running instance
    instantly loses every credential already encrypted under the file key. The
    restore case is unaffected, because a wiped volume has no file for the
    environment value to lose to.

    Note this is NOT ``CASHPILOT_SECRET_KEY``, which signs sessions and lives at
    ``<data>/.secret_key``. They are separate keys with separate jobs.
    """
    global _fernet_key_error, _fernet_key_persist_error, _fernet_key_is_ephemeral

    env_raw = os.getenv("CASHPILOT_ENCRYPTION_KEY", "").strip()
    env_key: bytes | None = None
    env_invalid: str | None = None
    if env_raw:
        try:
            Fernet(env_raw.encode())
            env_key = env_raw.encode()
        except (ValueError, TypeError) as exc:
            # Do not quietly generate a replacement: that is the same silent
            # failure this function exists to remove. Record it and let startup
            # refuse.
            # Recorded, not raised yet: if a valid key file exists it wins, and a
            # malformed env value is then just as moot as a valid-but-different
            # one. Only promote this to a startup failure if we would actually
            # have to fall back to the environment.
            env_invalid = (
                f"CASHPILOT_ENCRYPTION_KEY is set but is not a valid Fernet key "
                f"({exc or 'malformed'}). It must be a urlsafe-base64 32-byte key, as "
                'produced by `python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"`.'
            )

    # 1. An existing key file always wins.
    unusable: str | None = None
    try:
        if _FERNET_KEY_FILE.is_file():
            raw = _FERNET_KEY_FILE.read_text().strip()
            if raw:
                try:
                    fernet = Fernet(raw.encode())
                except (ValueError, TypeError) as exc:
                    unusable = f"it is not a valid Fernet key ({exc})"
                else:
                    if env_invalid:
                        _logger.warning(
                            "%s Ignoring it: the key already stored at %s wins.",
                            env_invalid,
                            _FERNET_KEY_FILE,
                        )
                    if env_key and env_key != raw.encode():
                        _logger.warning(
                            "CASHPILOT_ENCRYPTION_KEY differs from the key already stored "
                            "at %s. The stored key wins, because switching keys would make "
                            "every existing credential unreadable. To adopt the environment "
                            "key instead, remove the file and re-enter your credentials.",
                            _FERNET_KEY_FILE,
                        )
                    return fernet
            # An empty file means no key was ever stored, so replacing it loses
            # nothing. Fall through and mint one.
    except OSError as exc:
        unusable = f"it could not be read ({exc})"

    if unusable:
        # Refuse rather than overwrite. Credentials already in the database were
        # encrypted under the key this file was meant to hold, so replacing it
        # destroys the only artifact that could still decrypt them.
        _fernet_key_error = (
            f"the key file {_FERNET_KEY_FILE} exists but {unusable}. Refusing to "
            "overwrite it: any credential already stored was encrypted under that "
            "key, and replacing the file would make them permanently unreadable. "
            "Restore the file from backup, or move it aside and re-enter your "
            "credentials."
        )
        _logger.error("%s", _fernet_key_error)
        # Return a working cipher so importing this module stays side-effect free;
        # startup refuses via verify_encryption_key_persisted().
        return Fernet(Fernet.generate_key())

    if env_invalid:
        # No usable file key, so the supplied value was the one that mattered.
        # Generating a replacement would silently discard whatever the user was
        # trying to restore.
        _fernet_key_error = env_invalid
        _logger.error("%s", _fernet_key_error)
        return Fernet(Fernet.generate_key())

    # 2/3. Adopt the supplied key, or mint one.
    key = env_key if env_key else Fernet.generate_key()
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        # Create with 0o600 up front rather than chmod-ing afterwards: writing
        # first would leave the key briefly readable to anyone, depending on umask.
        fd = os.open(_FERNET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        # An existing file keeps its old mode, so tighten it regardless.
        _FERNET_KEY_FILE.chmod(0o600)
        _logger.info(
            "%s credential-encryption key at %s",
            "Adopted the supplied" if env_key else "Generated a new",
            _FERNET_KEY_FILE,
        )
    except OSError as exc:
        _fernet_key_persist_error = str(exc)
        # Ephemeral only when the key was MINTED here. A key supplied through
        # CASHPILOT_ENCRYPTION_KEY is identical on every restart, so failing to
        # cache it to disk loses nothing — the hazard this flag exists for
        # (a fresh random key on next boot, silently orphaning every stored
        # credential) cannot happen.
        #
        # Treating both cases the same made startup refuse to continue and told
        # the user to "supply a key via CASHPILOT_ENCRYPTION_KEY" — which is
        # exactly what they had already done.
        _fernet_key_is_ephemeral = env_key is None
        if env_key is None:
            _logger.error(
                "Could not persist the credential-encryption key to %s: %s. "
                "Credentials encrypted now will be unreadable after a restart.",
                _FERNET_KEY_FILE,
                exc,
            )
        else:
            # Same failure, different consequence. The key came from the
            # environment, so the next boot gets the identical key and nothing
            # is lost — as long as the variable stays set. Saying "unreadable
            # after a restart" here would be simply untrue, and it is the sort
            # of false alarm that teaches people to ignore the real one.
            _logger.warning(
                "Could not cache the credential-encryption key to %s: %s. "
                "This is not data loss: the key came from CASHPILOT_ENCRYPTION_KEY and will be "
                "read from there again on the next start. Keep that variable set — without the "
                "cached file it is now the only copy.",
                _FERNET_KEY_FILE,
                exc,
            )
    return Fernet(key)


_fernet = _load_or_create_fernet()


def verify_encryption_key_persisted() -> None:
    """Raise unless the credential-encryption key will survive a restart.

    Call this from application startup, never at import time: ``app.database``
    is imported by the test suite with the default ``/data``, which does not
    exist on a development machine, so importing must stay side-effect free.

    Continuing with a key that cannot be persisted is not a kindness. Every
    credential stored during this run becomes undecryptable the moment the
    process restarts, and the symptom the user eventually sees is a provider
    auth failure, which points nowhere near the real cause.
    """
    if _fernet_key_error:
        raise RuntimeError(
            f"{_fernet_key_error} Refusing to start rather than encrypting credentials under a throwaway key."
        )

    if not _fernet_key_is_ephemeral:
        return

    if os.getenv("CASHPILOT_ALLOW_EPHEMERAL_KEY", "").strip().lower() in _TRUTHY:
        _logger.warning(
            "Running with an EPHEMERAL credential-encryption key because "
            "CASHPILOT_ALLOW_EPHEMERAL_KEY is set. Every stored credential will "
            "become unreadable when this process restarts."
        )
        return

    raise RuntimeError(
        f"Cannot persist the credential-encryption key to {_FERNET_KEY_FILE}: "
        f"{_fernet_key_persist_error}. Credentials encrypted now would be "
        "permanently unreadable after a restart, so CashPilot is refusing to "
        "start. Fix the permissions or the volume mount for the data directory "
        "(CASHPILOT_DATA_DIR), supply a key via CASHPILOT_ENCRYPTION_KEY on a "
        "writable volume, or set CASHPILOT_ALLOW_EPHEMERAL_KEY=true if you "
        "genuinely want a throwaway instance."
    )


# Mirrors worker_api._AUTH_FAILURE_DISCARD_AFTER. Named rather than inlined so
# the number in the operator-facing message above cannot drift away from the
# behaviour it describes; a test asserts the two agree.
_WORKER_KEY_DISCARD_AFTER = 10


_ENC_PREFIX = "enc:"

_MYST_WALLETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS myst_wallets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_fingerprint TEXT    NOT NULL UNIQUE,
    raw_wallet_enc     TEXT    NOT NULL,
    address            TEXT    NOT NULL DEFAULT '',
    state              TEXT    NOT NULL DEFAULT 'AVAILABLE',
    funding            TEXT    NOT NULL DEFAULT 'FUNDED',
    leased_to_worker_id INTEGER,
    leased_to_client_id TEXT    NOT NULL DEFAULT '',
    leased_at           TEXT,
    release_reason      TEXT    NOT NULL DEFAULT '',
    wallet_assignment_version INTEGER NOT NULL DEFAULT 0,
    node_identity      TEXT    NOT NULL DEFAULT '',
    runtime_status     TEXT    NOT NULL DEFAULT '',
    public_ip          TEXT    NOT NULL DEFAULT '',
    last_heartbeat_at  TEXT,
    evidence_json      TEXT    NOT NULL DEFAULT '{}',
    quarantined_reason TEXT    NOT NULL DEFAULT '',
    imported_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_NKN_WALLETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS nkn_wallets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_fingerprint TEXT    NOT NULL UNIQUE,
    folder_name        TEXT    NOT NULL UNIQUE,
    wallet_json_enc    TEXT    NOT NULL,
    wallet_pswd_enc    TEXT    NOT NULL,
    address            TEXT    NOT NULL DEFAULT '',
    state              TEXT    NOT NULL DEFAULT 'AVAILABLE',
    leased_to_worker_id INTEGER,
    leased_to_client_id TEXT    NOT NULL DEFAULT '',
    leased_at           TEXT,
    release_reason      TEXT    NOT NULL DEFAULT '',
    wallet_assignment_version INTEGER NOT NULL DEFAULT 0,
    node_identity      TEXT    NOT NULL DEFAULT '',
    runtime_status     TEXT    NOT NULL DEFAULT '',
    public_ip          TEXT    NOT NULL DEFAULT '',
    last_heartbeat_at  TEXT,
    evidence_json      TEXT    NOT NULL DEFAULT '{}',
    quarantined_reason TEXT    NOT NULL DEFAULT '',
    imported_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_EARNAPP_ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS earnapp_accounts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_key          TEXT    NOT NULL UNIQUE,
    account_name         TEXT    NOT NULL,
    email                TEXT    NOT NULL DEFAULT '',
    auth_method          TEXT    NOT NULL CHECK(auth_method IN ('google', 'apple')),
    credentials_enc      TEXT    NOT NULL,
    credential_keys_json TEXT    NOT NULL DEFAULT '[]',
    token_expires_at     TEXT,
    cookie_expires_at    TEXT,
    state                TEXT    NOT NULL DEFAULT 'ACTIVE',
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS earnapp_logical_nodes (
    logical_node_id    TEXT    PRIMARY KEY,
    account_id         INTEGER NOT NULL,
    platform           TEXT    NOT NULL DEFAULT 'unknown'
                               CHECK(platform IN ('unknown', 'macos', 'ios', 'ubuntu')),
    state              TEXT    NOT NULL DEFAULT 'PLANNED',
    generation         INTEGER NOT NULL DEFAULT 1,
    assigned_worker_id INTEGER,
    last_worker_id     INTEGER,
    device_id          TEXT    NOT NULL DEFAULT '',
    current_proxy_id   INTEGER,
    preferred_proxy_id INTEGER,
    proxy_health       TEXT    NOT NULL DEFAULT 'unknown'
                               CHECK(proxy_health IN ('healthy', 'unhealthy', 'unknown')),
    observed_egress_ip TEXT    NOT NULL DEFAULT '',
    expected_egress_ip TEXT    NOT NULL DEFAULT '',
    proxy_checked_at   TEXT,
    proxy_health_reason TEXT  NOT NULL DEFAULT '',
    last_heartbeat_at  TEXT,
    recovery_started_at TEXT,
    recovery_hold_until TEXT,
    usage_baseline      REAL NOT NULL DEFAULT 0,
    window_started_at   TEXT,
    same_proxy_recreates INTEGER NOT NULL DEFAULT 0,
    rotate_count        INTEGER NOT NULL DEFAULT 0,
    lifecycle_action    TEXT NOT NULL DEFAULT 'observe',
    quarantine_reason   TEXT NOT NULL DEFAULT '',
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE RESTRICT,
    FOREIGN KEY(assigned_worker_id) REFERENCES workers(id) ON DELETE SET NULL,
    FOREIGN KEY(current_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL,
    FOREIGN KEY(preferred_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_earnapp_logical_nodes_account_state
    ON earnapp_logical_nodes(account_id, state);

CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_logical_nodes_device_id_unique
    ON earnapp_logical_nodes(device_id) WHERE device_id != '';

CREATE TABLE IF NOT EXISTS earnapp_replacement_tickets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_node_id  TEXT    NOT NULL,
    target_worker_id INTEGER NOT NULL,
    generation       INTEGER NOT NULL,
    token_hash       TEXT    NOT NULL UNIQUE,
    expires_at       TEXT    NOT NULL,
    used_at          TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE,
    FOREIGN KEY(target_worker_id) REFERENCES workers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_earnapp_replacement_tickets_target
    ON earnapp_replacement_tickets(logical_node_id, target_worker_id, used_at, expires_at);

CREATE TABLE IF NOT EXISTS earnapp_proxy_reservations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_node_id    TEXT    NOT NULL,
    worker_id          INTEGER NOT NULL,
    generation         INTEGER NOT NULL,
    expected_proxy_id  INTEGER NOT NULL,
    proxy_id           INTEGER NOT NULL,
    binding_version    TEXT    NOT NULL,
    state              TEXT    NOT NULL DEFAULT 'ACTIVE'
                       CHECK(state IN ('ACTIVE', 'COMMITTED', 'RELEASED', 'EXPIRED')),
    reserved_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at         TEXT    NOT NULL,
    released_at        TEXT,
    release_reason     TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE,
    FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE,
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_proxy_reservations_active_proxy
    ON earnapp_proxy_reservations(proxy_id) WHERE state = 'ACTIVE';

CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_proxy_reservations_active_binding
    ON earnapp_proxy_reservations(logical_node_id, binding_version) WHERE state = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_earnapp_proxy_reservations_expiry
    ON earnapp_proxy_reservations(state, expires_at);

CREATE TABLE IF NOT EXISTS earnapp_account_control_routes (
    account_id               INTEGER PRIMARY KEY,
    proxy_id                 INTEGER NOT NULL,
    state                    TEXT    NOT NULL DEFAULT 'ACTIVE',
    assigned_logical_node_id TEXT    NOT NULL DEFAULT '',
    leased_at                TEXT    NOT NULL DEFAULT (datetime('now')),
    released_at              TEXT,
    release_reason           TEXT    NOT NULL DEFAULT '',
    updated_at               TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS earnapp_account_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL,
    money_balance  REAL    NOT NULL DEFAULT 0,
    money_total    REAL    NOT NULL DEFAULT 0,
    online_nodes   INTEGER NOT NULL DEFAULT 0,
    offline_nodes  INTEGER NOT NULL DEFAULT 0,
    devices_json   TEXT    NOT NULL DEFAULT '[]',
    payment_json   TEXT    NOT NULL DEFAULT '{}',
    collected_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_earnapp_account_snapshots_latest
    ON earnapp_account_snapshots(account_id, id DESC);
"""

_EARNAPP_ACCOUNTS_TABLE_SQL = """
CREATE TABLE earnapp_accounts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_key          TEXT    NOT NULL UNIQUE,
    account_name         TEXT    NOT NULL,
    email                TEXT    NOT NULL DEFAULT '',
    auth_method          TEXT    NOT NULL CHECK(auth_method IN ('google', 'apple')),
    credentials_enc      TEXT    NOT NULL,
    credential_keys_json TEXT    NOT NULL DEFAULT '[]',
    token_expires_at     TEXT,
    cookie_expires_at    TEXT,
    state                TEXT    NOT NULL DEFAULT 'ACTIVE',
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

_EARNAPP_LEGACY_MIGRATION_KEY = "migration.earnapp_accounts.legacy_v19"

_EARNAPP_ACCOUNT_REQUIRED_COLUMNS = {
    "id",
    "profile_key",
    "account_name",
    "email",
    "auth_method",
    "credentials_enc",
    "credential_keys_json",
    "token_expires_at",
    "cookie_expires_at",
    "state",
    "created_at",
    "updated_at",
}

_EARNAPP_LEGACY_ACCOUNT_REQUIRED_COLUMNS = {
    "id",
    "account_name",
    "cookies_enc",
    "state",
    "created_at",
    "updated_at",
}

_EARNAPP_V19_ACCOUNT_REQUIRED_COLUMNS = _EARNAPP_ACCOUNT_REQUIRED_COLUMNS

_EARNAPP_CHILD_COLUMNS = {
    "earnapp_logical_nodes": {
        "logical_node_id",
        "account_id",
        "platform",
        "state",
        "generation",
        "assigned_worker_id",
        "last_worker_id",
        "device_id",
        "current_proxy_id",
        "preferred_proxy_id",
        "proxy_health",
        "observed_egress_ip",
        "expected_egress_ip",
        "proxy_checked_at",
        "proxy_health_reason",
        "last_heartbeat_at",
        "recovery_started_at",
        "recovery_hold_until",
        "usage_baseline",
        "window_started_at",
        "same_proxy_recreates",
        "rotate_count",
        "lifecycle_action",
        "quarantine_reason",
        "created_at",
        "updated_at",
    },
    "earnapp_account_control_routes": {
        "account_id",
        "proxy_id",
        "state",
        "assigned_logical_node_id",
        "leased_at",
        "released_at",
        "release_reason",
        "updated_at",
    },
    "earnapp_account_snapshots": {
        "id",
        "account_id",
        "money_balance",
        "money_total",
        "online_nodes",
        "offline_nodes",
        "devices_json",
        "payment_json",
        "collected_at",
    },
    "earnapp_replacement_tickets": {
        "id",
        "logical_node_id",
        "target_worker_id",
        "generation",
        "token_hash",
        "expires_at",
        "used_at",
        "created_at",
    },
    "earnapp_proxy_reservations": {
        "id",
        "logical_node_id",
        "worker_id",
        "generation",
        "expected_proxy_id",
        "proxy_id",
        "binding_version",
        "state",
        "reserved_at",
        "expires_at",
        "released_at",
        "release_reason",
    },
}

_EARNAPP_CHILD_FOREIGN_KEYS = {
    "earnapp_logical_nodes": {
        "account_id": ("earnapp_accounts", "id", "RESTRICT"),
        "assigned_worker_id": ("workers", "id", "SET NULL"),
        "current_proxy_id": ("proxy_endpoints", "id", "SET NULL"),
        "preferred_proxy_id": ("proxy_endpoints", "id", "SET NULL"),
    },
    "earnapp_account_control_routes": {
        "account_id": ("earnapp_accounts", "id", "CASCADE"),
        "proxy_id": ("proxy_endpoints", "id", "RESTRICT"),
    },
    "earnapp_account_snapshots": {
        "account_id": ("earnapp_accounts", "id", "CASCADE"),
    },
    "earnapp_replacement_tickets": {
        "logical_node_id": ("earnapp_logical_nodes", "logical_node_id", "CASCADE"),
        "target_worker_id": ("workers", "id", "CASCADE"),
    },
    "earnapp_proxy_reservations": {
        "logical_node_id": ("earnapp_logical_nodes", "logical_node_id", "CASCADE"),
        "worker_id": ("workers", "id", "CASCADE"),
        "proxy_id": ("proxy_endpoints", "id", "CASCADE"),
    },
}

_EARNAPP_CHILD_PRIMARY_KEYS = {
    "earnapp_logical_nodes": ("logical_node_id",),
    "earnapp_account_control_routes": ("account_id",),
    "earnapp_account_snapshots": ("id",),
    "earnapp_replacement_tickets": ("id",),
    "earnapp_proxy_reservations": ("id",),
}

_EARNAPP_CHILD_INDEXES = {
    "earnapp_logical_nodes": {
        "idx_earnapp_logical_nodes_account_state",
        "idx_earnapp_logical_nodes_device_id_unique",
    },
    "earnapp_account_control_routes": set(),
    "earnapp_account_snapshots": {"idx_earnapp_account_snapshots_latest"},
    "earnapp_replacement_tickets": {"idx_earnapp_replacement_tickets_target"},
    "earnapp_proxy_reservations": {
        "idx_earnapp_proxy_reservations_active_proxy",
        "idx_earnapp_proxy_reservations_active_binding",
        "idx_earnapp_proxy_reservations_expiry",
    },
}

# Index names alone are not a schema contract: a damaged volume can retain the
# expected name while pointing at the wrong columns, order, or partial predicate.
# Keep the definitions explicit so a persisted completion marker cannot bless
# an index that only looks right in ``PRAGMA index_list``.
_EARNAPP_CHILD_INDEX_CONTRACTS = {
    "earnapp_logical_nodes": {
        "idx_earnapp_logical_nodes_account_state": {
            "columns": ("account_id", "state"),
            "unique": False,
            "partial": False,
            "where": None,
            "descending": (False, False),
        },
        "idx_earnapp_logical_nodes_device_id_unique": {
            "columns": ("device_id",),
            "unique": True,
            "partial": True,
            "where": "device_id!=''",
            "descending": (False,),
        },
    },
    "earnapp_account_snapshots": {
        "idx_earnapp_account_snapshots_latest": {
            "columns": ("account_id", "id"),
            "unique": False,
            "partial": False,
            "where": None,
            "descending": (False, True),
        },
    },
    "earnapp_replacement_tickets": {
        "idx_earnapp_replacement_tickets_target": {
            "columns": ("logical_node_id", "target_worker_id", "used_at", "expires_at"),
            "unique": False,
            "partial": False,
            "where": None,
            "descending": (False, False, False, False),
        },
    },
    "earnapp_proxy_reservations": {
        "idx_earnapp_proxy_reservations_active_proxy": {
            "columns": ("proxy_id",),
            "unique": True,
            "partial": True,
            "where": "state='ACTIVE'",
            "descending": (False,),
        },
        "idx_earnapp_proxy_reservations_active_binding": {
            "columns": ("logical_node_id", "binding_version"),
            "unique": True,
            "partial": True,
            "where": "state='ACTIVE'",
            "descending": (False, False),
        },
        "idx_earnapp_proxy_reservations_expiry": {
            "columns": ("state", "expires_at"),
            "unique": False,
            "partial": False,
            "where": None,
            "descending": (False, False),
        },
    },
}

_EARNAPP_CHILD_UNIQUE_COLUMNS = {
    "earnapp_replacement_tickets": {"token_hash"},
}

_EARNAPP_ACCOUNT_COLUMN_TYPES = {column: "TEXT" for column in _EARNAPP_ACCOUNT_REQUIRED_COLUMNS - {"id"}} | {
    "id": "INTEGER"
}

_EARNAPP_ACCOUNT_DEFAULTS = {
    "id": None,
    "profile_key": None,
    "account_name": None,
    "email": "''",
    "auth_method": None,
    "credentials_enc": None,
    "credential_keys_json": "'[]'",
    "token_expires_at": None,
    "cookie_expires_at": None,
    "state": "'ACTIVE'",
    "created_at": "datetime('now')",
    "updated_at": "datetime('now')",
}


def encrypt_value(value: str) -> str:
    """Encrypt a string value, returning an 'enc:' prefixed token."""
    return _ENC_PREFIX + _fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    """Decrypt an 'enc:' prefixed token back to plaintext."""
    if not value.startswith(_ENC_PREFIX):
        return value  # Not encrypted (legacy data)
    try:
        return _fernet.decrypt(value[len(_ENC_PREFIX) :].encode()).decode()
    except InvalidToken:
        # Deliberately ERROR, not WARNING: this is unattended software, and the
        # downstream symptom is a provider auth failure that points nowhere near
        # the real cause.
        _logger.error(
            "Failed to decrypt a stored credential: the credential-encryption key "
            "(CASHPILOT_ENCRYPTION_KEY / %s) does not match the key this value was "
            "encrypted with. This is NOT a bad credential and NOT CASHPILOT_SECRET_KEY, "
            "which only signs sessions. Restore the original encryption key to recover, "
            "or re-enter the affected credentials.",
            _FERNET_KEY_FILE,
        )
        return ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    platform   TEXT    NOT NULL,
    balance    REAL    NOT NULL,
    currency   TEXT    NOT NULL DEFAULT 'USD',
    date       TEXT    NOT NULL,
    -- USD per 1 unit of `currency` when this reading was taken (so USD rows store
    -- 1.0). Rates are only cached live, so without storing it here the historical
    -- value of a non-USD balance (MYST and other currencies) cannot be reconstructed later at
    -- any accuracy — which is what a net-profit or tax export needs. NULL only when
    -- the rate was genuinely unavailable, never a guess.
    fx_rate_usd REAL,
    -- WHO took this reading. 'server' is this CashPilot's own collectors; a
    -- paired client pushing its history uses its own worker client_id.
    --
    -- Load-bearing, not bookkeeping. A balance is a RUNNING TOTAL and earnings
    -- are the delta between CONSECUTIVE readings. Two samplers of one provider
    -- account interleaved into a single series oscillate -- server 10, desktop
    -- 9, server 11, desktop 10 -- and because a drop clamps to zero, the total
    -- comes out SYSTEMATICALLY UNDERSTATED while looking entirely plausible.
    -- Deltas are therefore taken per (platform, source) and only then summed.
    source     TEXT    NOT NULL DEFAULT 'server',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
-- NOTE: the (platform, source, date) unique index is created in the MIGRATION,
-- not here. On an upgraded volume `CREATE TABLE IF NOT EXISTS earnings` is a
-- no-op, so an index declared here would reference `source` before the ALTER
-- adds it and every upgrade would fail on "no such column: source". The
-- existing fx-migration test models exactly that volume and caught it.

-- updated_at exists so a credential's AGE is knowable. Several collectors use
-- values copied out of a browser and some expire in hours; without a timestamp
-- the UI cannot say "this will stop working tonight" before it does, and a dead
-- collector looks identical to a provider outage.
-- updated_at is nullable with no default, deliberately, and this must MATCH
-- what an upgraded volume gets. SQLite's ALTER TABLE ADD COLUMN cannot add a
-- NOT NULL column without a default, and adding a default would back-fill --
-- which is exactly the thing the migration refuses to do, because stamping
-- every existing credential with the moment of the upgrade once made a
-- short-lived session cookie that had expired days earlier report as fresh.
--
-- So a fresh install had NOT NULL DEFAULT (datetime('now')) and an upgraded one
-- had a plain nullable column, permanently. Nothing broke today because both
-- writers set the value explicitly — but the next writer to rely on the default
-- would store NULL on upgraded volumes only, and the credential-age report
-- filters WHERE updated_at IS NOT NULL, so those keys would quietly vanish from
-- it. A bug that only appears on volumes older than a given release is the
-- hardest kind to reproduce from a report (CashPilot-f62).
--
-- NULL is also the honest value: it means "nobody recorded when this was set",
-- which is what both consumers already assume.
CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT
);

-- spec_encrypted holds the FULL resolved container spec as it was actually
-- deployed (image, env, volumes, ports, command, resources), Fernet-encrypted
-- because env carries credentials. Without it a redeploy has to rebuild the
-- spec from the catalog and silently produces a different container whenever
-- the running one diverged - which is how node identities get orphaned.
-- env_vars_encrypted predates this and was never written; spec_encrypted
-- supersedes it.
CREATE TABLE IF NOT EXISTS deployments (
    slug               TEXT PRIMARY KEY,
    container_id       TEXT NOT NULL,
    env_vars_encrypted TEXT NOT NULL DEFAULT '',
    spec_encrypted     TEXT NOT NULL DEFAULT '',
    deployed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    status             TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS provider_instances (
    instance_id    TEXT PRIMARY KEY,
    slug           TEXT NOT NULL,
    worker_id      INTEGER,
    mode           TEXT NOT NULL DEFAULT 'direct' CHECK(mode IN ('direct', 'proxy')),
    container_id   TEXT NOT NULL DEFAULT '',
    sidecar_id     TEXT NOT NULL DEFAULT '',
    proxy_id       INTEGER,
    status         TEXT NOT NULL DEFAULT 'planned',
    spec_encrypted TEXT NOT NULL DEFAULT '',
    deployed_at    TEXT,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE SET NULL,
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    password   TEXT    NOT NULL,
    role       TEXT    NOT NULL DEFAULT 'viewer',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    -- Declared here as well as in the migration below, so a FRESH install does
    -- not run an ALTER TABLE it never needed. Found by the startup log added in
    -- CashPilot-sfbh: a brand-new database reported "Migrations applied this
    -- boot: users.password_changed_at", which is exactly the noise that makes an
    -- operator stop reading migration output.
    --
    -- Safe both ways: CREATE TABLE IF NOT EXISTS is a no-op on an existing
    -- database, so it still gets the column from the migration. (Unlike adding
    -- an INDEX here, which runs on existing tables and fails on a column they do
    -- not have yet -- that mistake broke the upgrade path twice.)
    password_changed_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS workers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'online',
    containers      TEXT    NOT NULL DEFAULT '[]',
    apps            TEXT    NOT NULL DEFAULT '[]',
    system_info     TEXT    NOT NULL DEFAULT '{}',
    last_heartbeat  TEXT,
    api_key_enc     TEXT,
    key_confirmed   INTEGER NOT NULL DEFAULT 0,
    key_issued_at   TEXT,
    registered_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS proxy_providers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    type           TEXT    NOT NULL,
    base_url       TEXT    NOT NULL DEFAULT '',
    api_key_enc    TEXT    NOT NULL DEFAULT '',
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(type, name)
);

CREATE TABLE IF NOT EXISTS proxy_endpoints (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id       INTEGER,
    provider_proxy_id TEXT,
    endpoint          TEXT    NOT NULL,
    host              TEXT    NOT NULL,
    port              INTEGER NOT NULL,
    protocol          TEXT    NOT NULL CHECK(protocol IN ('http', 'socks5')),
    username          TEXT    NOT NULL DEFAULT '',
    password_enc      TEXT    NOT NULL DEFAULT '',
    location          TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'unknown',
    expiry_date       TEXT,
    days_left         INTEGER,
    hours_left        INTEGER,
    exit_ip           TEXT,
    udp_ok            INTEGER,
    latency_ms        INTEGER,
    last_synced_at    TEXT,
    last_checked_at   TEXT,
    country_code      TEXT    NOT NULL DEFAULT '',
    country_name      TEXT    NOT NULL DEFAULT '',
    geo_source        TEXT    NOT NULL DEFAULT '',
    geo_confidence    TEXT    NOT NULL DEFAULT 'unknown',
    geo_checked_at    TEXT,
    ip_type           TEXT    NOT NULL DEFAULT 'unknown',
    ip_type_source    TEXT    NOT NULL DEFAULT '',
    ip_type_confidence TEXT   NOT NULL DEFAULT 'unknown',
    ip_type_checked_at TEXT,
    duplicate_egress  INTEGER NOT NULL DEFAULT 0,
    canonical_proxy_id INTEGER,
    duplicate_reason TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(provider_id) REFERENCES proxy_providers(id) ON DELETE SET NULL,
    FOREIGN KEY(canonical_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL,
    UNIQUE(provider_id, provider_proxy_id)
);

CREATE TABLE IF NOT EXISTS proxy_assignments (
    worker_id  INTEGER PRIMARY KEY,
    proxy_id   INTEGER,
    mode       TEXT NOT NULL DEFAULT 'proxy' CHECK(mode IN ('proxy', 'direct', 'auto')),
    fallback   TEXT NOT NULL DEFAULT 'hold' CHECK(fallback IN ('hold', 'rotate')),
    assignment_version INTEGER NOT NULL DEFAULT 0,
    applied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE,
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS proxy_provider_masks (
    proxy_id      INTEGER NOT NULL,
    provider_slug TEXT    NOT NULL,
    reason        TEXT    NOT NULL DEFAULT '',
    masked_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(proxy_id, provider_slug),
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proxy_probe_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_id       INTEGER NOT NULL,
    profile        TEXT    NOT NULL,
    probe_status   TEXT    NOT NULL DEFAULT 'unknown',
    verdict        TEXT    NOT NULL DEFAULT '',
    eligibility    TEXT    NOT NULL DEFAULT 'unknown',
    reason         TEXT    NOT NULL DEFAULT '',
    exit_ip        TEXT    NOT NULL DEFAULT '',
    latency_ms     INTEGER,
    probe_version  TEXT    NOT NULL DEFAULT '',
    evidence_json  TEXT    NOT NULL DEFAULT '{}',
    checked_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proxy_import_batches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id    INTEGER,
    source_name    TEXT    NOT NULL DEFAULT 'manual',
    raw_input_enc  TEXT    NOT NULL DEFAULT '',
    parsed_count   INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(provider_id) REFERENCES proxy_providers(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS proxy_import_rows (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id       INTEGER NOT NULL,
    row_number     INTEGER NOT NULL,
    proxy_id       INTEGER,
    raw_line_enc   TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(batch_id) REFERENCES proxy_import_batches(id) ON DELETE CASCADE,
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL,
    UNIQUE(batch_id, row_number)
);

CREATE TABLE IF NOT EXISTS provider_proxy_leases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_slug  TEXT    NOT NULL,
    worker_id      INTEGER NOT NULL,
    instance_id    TEXT    NOT NULL,
    proxy_id       INTEGER NOT NULL,
    exit_ip        TEXT    NOT NULL DEFAULT '',
    leased_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    released_at    TEXT,
    release_reason TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE,
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS myst_wallets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_fingerprint TEXT    NOT NULL UNIQUE,
    raw_wallet_enc     TEXT    NOT NULL,
    address            TEXT    NOT NULL DEFAULT '',
    state              TEXT    NOT NULL DEFAULT 'AVAILABLE',
    funding            TEXT    NOT NULL DEFAULT 'FUNDED',
    leased_to_worker_id INTEGER,
    leased_to_client_id TEXT    NOT NULL DEFAULT '',
    leased_at           TEXT,
    release_reason      TEXT    NOT NULL DEFAULT '',
    wallet_assignment_version INTEGER NOT NULL DEFAULT 0,
    node_identity      TEXT    NOT NULL DEFAULT '',
    runtime_status     TEXT    NOT NULL DEFAULT '',
    public_ip          TEXT    NOT NULL DEFAULT '',
    last_heartbeat_at  TEXT,
    evidence_json      TEXT    NOT NULL DEFAULT '{}',
    quarantined_reason TEXT    NOT NULL DEFAULT '',
    imported_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nkn_wallets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_fingerprint TEXT    NOT NULL UNIQUE,
    folder_name        TEXT    NOT NULL UNIQUE,
    wallet_json_enc    TEXT    NOT NULL,
    wallet_pswd_enc    TEXT    NOT NULL,
    address            TEXT    NOT NULL DEFAULT '',
    state              TEXT    NOT NULL DEFAULT 'AVAILABLE',
    leased_to_worker_id INTEGER,
    leased_to_client_id TEXT    NOT NULL DEFAULT '',
    leased_at           TEXT,
    release_reason      TEXT    NOT NULL DEFAULT '',
    wallet_assignment_version INTEGER NOT NULL DEFAULT 0,
    node_identity      TEXT    NOT NULL DEFAULT '',
    runtime_status     TEXT    NOT NULL DEFAULT '',
    public_ip          TEXT    NOT NULL DEFAULT '',
    last_heartbeat_at  TEXT,
    evidence_json      TEXT    NOT NULL DEFAULT '{}',
    quarantined_reason TEXT    NOT NULL DEFAULT '',
    imported_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id             INTEGER PRIMARY KEY,
    setup_mode          TEXT    NOT NULL DEFAULT 'fresh',
    selected_categories TEXT    NOT NULL DEFAULT '[]',
    timezone            TEXT    NOT NULL DEFAULT 'UTC',
    setup_completed     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Alerts worth a human's attention (collector failures today; container crashes and
-- earnings flatlines later). Persisted rather than kept in memory so they survive a
-- restart: passive income is unattended, and an alert that only exists in a running
-- process is an alert nobody ever sees.
CREATE TABLE IF NOT EXISTS payouts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    platform     TEXT    NOT NULL,
    amount       REAL    NOT NULL,
    currency     TEXT    NOT NULL DEFAULT 'USD',
    -- USD per 1 unit of `currency` WHEN THE PAYOUT LANDED, mirroring the
    -- earnings table. A MYST payout valued at today's rate would silently
    -- restate history every time the token moves.
    fx_rate_usd  REAL,
    -- 0 until a human says this really was a payout. A balance also falls for
    -- provider corrections and reset sessions, and recording a guess as income
    -- corrupts lifetime-earned in a way the user cannot see.
    confirmed    INTEGER NOT NULL DEFAULT 0,
    method       TEXT    NOT NULL DEFAULT '',
    detected_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_payouts_platform ON payouts(platform, confirmed);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL,
    subject    TEXT    NOT NULL,
    message    TEXT    NOT NULL DEFAULT '',
    -- What KIND of failure the message describes: 'auth' | 'transient' |
    -- 'shape', or NULL when the collector could not tell. NULL means unknown,
    -- never transient -- the UI renders unknown as a plain failure, not as
    -- "will self-heal" (CashPilot-5bdm).
    category   TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS health_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT    NOT NULL,
    event      TEXT    NOT NULL,
    detail     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Durable per-user session-revocation epochs. A signed session cookie whose iat
-- predates a user's revoked_before is rejected. DELIBERATELY has no FOREIGN KEY to
-- users: when a user is deleted the revocation MUST outlive the row, so the deleted
-- account's still-valid 30-day cookies keep being rejected across UI restarts
-- (otherwise the in-memory epoch resets on restart and a deleted/demoted user's old
-- cookie regains their old role). Warmed into auth's in-memory epoch cache at startup.
CREATE TABLE IF NOT EXISTS session_revocations (
    user_id        INTEGER PRIMARY KEY,
    revoked_before REAL    NOT NULL
);

-- The (platform, SOURCE, date) unique index is created in the MIGRATION, not
-- here, and this must stay that way. _SCHEMA is replayed on EVERY startup, and
-- on an upgraded volume `CREATE TABLE IF NOT EXISTS earnings` is a no-op -- so
-- an index declared here names `source` before the ALTER has added it and
-- init_db dies with "no such column: source", taking the whole app down on
-- upgrade. I made that mistake twice; the fx-migration test catches it both
-- times.
--
-- Source is part of the key because two machines may legitimately report the
-- same platform on the same day -- the normal case once a client pushes its
-- history -- while one machine reporting a platform twice for one day is still
-- a duplicate to be upserted away.

CREATE INDEX IF NOT EXISTS idx_earnings_created
    ON earnings (created_at);

CREATE INDEX IF NOT EXISTS idx_earnings_date
    ON earnings (date);

CREATE INDEX IF NOT EXISTS idx_workers_status
    ON workers (status);

CREATE INDEX IF NOT EXISTS idx_provider_instances_slug
    ON provider_instances (slug, worker_id, mode);

CREATE INDEX IF NOT EXISTS idx_proxy_provider_masks_provider
    ON proxy_provider_masks(provider_slug, proxy_id);

CREATE INDEX IF NOT EXISTS idx_proxy_endpoints_exit_ip
    ON proxy_endpoints(exit_ip);

CREATE INDEX IF NOT EXISTS idx_proxy_probe_results_latest
    ON proxy_probe_results(proxy_id, profile, id DESC);

CREATE INDEX IF NOT EXISTS idx_proxy_import_rows_proxy
    ON proxy_import_rows(proxy_id, batch_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_proxy_leases_active_instance
    ON provider_proxy_leases(provider_slug, worker_id, instance_id)
    WHERE released_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_proxy_leases_active_proxy
    ON provider_proxy_leases(proxy_id)
    WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_provider_proxy_leases_active_exit
    ON provider_proxy_leases(exit_ip)
    WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_health_events_slug
    ON health_events (slug, created_at);

CREATE INDEX IF NOT EXISTS idx_health_events_created
    ON health_events (created_at);

CREATE INDEX IF NOT EXISTS idx_alerts_created
    ON alerts (created_at);
"""


# ---------------------------------------------------------------------------
# Shared connection management
# ---------------------------------------------------------------------------
#
# Each event loop gets a single long-lived aiosqlite connection. In production
# there is one uvicorn loop, so all 36 DB helpers reuse one connection instead
# of opening (and WAL-initialising) a fresh one on every call. Tests use
# ``asyncio.run(...)`` which creates a brand-new loop per call, so each test
# gets its own isolated connection.
#
# The 36 helpers keep their ``db = await _get_db(); try: ... finally:
# await db.close()`` shape unchanged. ``_get_db()`` hands back a
# ``_BorrowedConnection`` proxy whose ``.close()`` is a no-op, so the borrowed
# handle's ``finally`` never actually tears down the shared connection.

_shared_conns: dict[int, aiosqlite.Connection] = {}
_shared_conn_locks: dict[int, asyncio.Lock] = {}
_shared_conn_owners: dict[int, asyncio.Task[Any]] = {}
_shared_conn_depths: dict[int, int] = {}
_proxy_assignment_locks: dict[int, asyncio.Lock] = {}
_nkn_wallet_locks: dict[int, asyncio.Lock] = {}
_earnapp_locks: dict[int, asyncio.Lock] = {}


def _proxy_assignment_lock() -> asyncio.Lock:
    """Serialize multi-statement proxy assignment transactions per event loop."""
    loop_key = id(asyncio.get_running_loop())
    lock = _proxy_assignment_locks.get(loop_key)
    if lock is None:
        lock = asyncio.Lock()
        _proxy_assignment_locks[loop_key] = lock
    return lock


def _nkn_wallet_lock() -> asyncio.Lock:
    """Serialize NKN wallet lease transactions per event loop."""
    loop_key = id(asyncio.get_running_loop())
    lock = _nkn_wallet_locks.get(loop_key)
    if lock is None:
        lock = asyncio.Lock()
        _nkn_wallet_locks[loop_key] = lock
    return lock


def _earnapp_lock() -> asyncio.Lock:
    """Serialize EarnApp account/node assignments per event loop."""
    loop_key = id(asyncio.get_running_loop())
    lock = _earnapp_locks.get(loop_key)
    if lock is None:
        lock = asyncio.Lock()
        _earnapp_locks[loop_key] = lock
    return lock


class _BorrowedConnection:
    """A borrowed view onto a shared aiosqlite connection.

    Delegates every attribute (execute, commit, fetch*, row_factory, ...) to
    the real connection, but turns ``close()`` into an async no-op and makes
    ``async with`` a pass-through. This lets call sites keep their
    ``finally: await db.close()`` pattern byte-for-byte while the underlying
    connection stays open and shared for the lifetime of the event loop.
    """

    __slots__ = ("_conn", "_key", "_released")

    def __init__(self, conn: aiosqlite.Connection, key: int) -> None:
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_released", False)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_conn"), name, value)

    async def close(self) -> None:
        """Release this exclusive borrow while leaving the connection open."""
        if object.__getattribute__(self, "_released"):
            return
        object.__setattr__(self, "_released", True)
        key = object.__getattribute__(self, "_key")
        depth = _shared_conn_depths.get(key, 0)
        if depth > 1:
            _shared_conn_depths[key] = depth - 1
            return

        conn = object.__getattribute__(self, "_conn")
        try:
            if conn.in_transaction:
                await conn.rollback()
        finally:
            _shared_conn_depths.pop(key, None)
            _shared_conn_owners.pop(key, None)
            _shared_conn_locks[key].release()

    async def __aenter__(self) -> _BorrowedConnection:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _open_connection() -> aiosqlite.Connection:
    """Create an unawaited aiosqlite connection with row factory + PRAGMAs.

    The returned object is the ``aiosqlite.connect(...)`` awaitable/context
    manager; the caller awaits it to obtain the live connection. The row
    factory and PRAGMAs are applied once per connection in ``_get_db()``.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return aiosqlite.connect(str(DB_PATH))


async def _open_transaction_connection() -> aiosqlite.Connection:
    """Open an isolated connection for a short compare-and-swap transaction."""
    conn = await _open_connection()
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA synchronous=NORMAL")
    return conn


async def _get_db() -> _BorrowedConnection:
    """Return a borrowed handle on this event loop's shared connection.

    Opens (and caches) a connection the first time it is needed on a given
    loop, or whenever the cached connection has been closed. The returned
    ``_BorrowedConnection`` is safe to ``close()`` — it is a no-op.
    """
    loop = asyncio.get_running_loop()
    key = id(loop)
    lock = _shared_conn_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _shared_conn_locks[key] = lock
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("shared SQLite connection requires an asyncio task")
    if _shared_conn_owners.get(key) is task:
        _shared_conn_depths[key] = _shared_conn_depths.get(key, 0) + 1
    else:
        await lock.acquire()
        _shared_conn_owners[key] = task
        _shared_conn_depths[key] = 1
    conn = _shared_conns.get(key)
    try:
        needs_open = conn is None
        if conn is not None:
            try:
                needs_open = not conn._running
            except AttributeError:
                needs_open = False

        if needs_open:
            conn = await _open_connection()
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=5000")
            # In WAL mode NORMAL is durable across app crashes (only a power loss can lose
            # the last transactions) and skips an fsync on every commit — a large win on the
            # write-heavy health-check path that commits per service each cycle.
            await conn.execute("PRAGMA synchronous=NORMAL")
            _shared_conns[key] = conn

        return _BorrowedConnection(conn, key)
    except BaseException:
        depth = _shared_conn_depths.get(key, 0)
        if depth > 1:
            _shared_conn_depths[key] = depth - 1
        else:
            _shared_conn_depths.pop(key, None)
            _shared_conn_owners.pop(key, None)
            lock.release()
        raise


async def connect_shared() -> None:
    """Eagerly open the shared connection for the current event loop."""
    db = await _get_db()
    await db.close()


async def close_shared() -> None:
    """Close and forget the current event loop's shared connection."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    key = id(loop)
    lock = _shared_conn_locks.get(key)
    if _shared_conn_owners.get(key) is asyncio.current_task():
        raise RuntimeError("cannot close shared SQLite connection while it is borrowed")
    if lock is not None:
        await lock.acquire()
    try:
        conn = _shared_conns.pop(key, None)
        if conn is not None:
            await conn.close()
    finally:
        if lock is not None:
            _shared_conn_locks.pop(key, None)
            _shared_conn_owners.pop(key, None)
            _shared_conn_depths.pop(key, None)
            lock.release()


async def _dedupe_earnings_before_indexing(db: Any) -> None:
    """Clear the way for the unique earnings index on an old volume.

    ``_SCHEMA`` is replayed on EVERY startup, and it contains
    ``CREATE UNIQUE INDEX IF NOT EXISTS idx_earnings_platform_date``. On an
    installation whose ``/data`` predates that index and that accumulated two
    rows for the same platform and date, creating it raises IntegrityError —
    inside ``executescript``, which nothing catches, during ``lifespan`` — and
    the application does not start AT ALL. Verified: a two-duplicate-row
    database fails ``init_db`` with "UNIQUE constraint failed".

    That is the one piece of schema evolution here without a defensive
    migration; every other column change is guarded by a ``PRAGMA table_info``
    check. Recovering by hand means opening SQLite on a container that will not
    boot, which is a bad thing to ask of someone whose dashboard just died.

    Deliberately conservative: this touches nothing unless the index is genuinely
    absent AND duplicates genuinely exist, and it keeps the HIGHEST id per
    (platform, date) — the most recently written row, which is what an upsert
    would have left behind had the index been there all along.
    """
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_earnings_platform_source_date'"
    )
    if await cursor.fetchone():
        return  # Index already present, so duplicates cannot exist.

    cursor = await db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'earnings'")
    if not await cursor.fetchone():
        return  # Fresh install; the table is about to be created cleanly.

    # This runs BEFORE the `source` column is added, so the key must match
    # whichever schema is actually on disk. Referencing `source` unconditionally
    # crashes init_db on exactly the volume this helper exists to rescue.
    cursor = await db.execute("PRAGMA table_info(earnings)")
    has_source = any(row["name"] == "source" for row in await cursor.fetchall())
    key = "platform || '|' || COALESCE(source, 'server') || '|' || date" if has_source else "platform || '|' || date"
    group_by = "platform, source, date" if has_source else "platform, date"

    cursor = await db.execute(f"SELECT COUNT(*) - COUNT(DISTINCT {key}) AS extra FROM earnings")
    row = await cursor.fetchone()
    extra = int(row["extra"] or 0)
    if extra <= 0:
        return

    _logger.warning(
        "Found %d duplicate earnings row(s) predating the unique index. Keeping the most recent "
        "reading for each platform and date and removing the rest, so the index can be created "
        "and the application can start.",
        extra,
    )
    await db.execute(f"DELETE FROM earnings WHERE id NOT IN (SELECT MAX(id) FROM earnings GROUP BY {group_by})")
    await db.commit()


async def _encrypt_legacy_plaintext_credentials(db: Any) -> int:
    """Re-encrypt secret config values written before at-rest encryption existed.

    Reads are backward compatible — decrypt_value returns an unprefixed value
    as-is — which is what makes an upgrade work at all, and also what left the
    plaintext sitting there forever. Two users on identical code end up with
    different at-rest protection for the same secret, and nothing tells the
    upgraded one: a copied backup, a Duplicacy snapshot or a shared /data hands
    over the live provider password. It stays plaintext until the user happens
    to re-enter it.

    This also covers keys that only BECAME secret later. The suffix list was
    widened after an audit found the boundary was a naming convention with
    nothing enforcing it, and values written before that widening are plaintext
    under a key that is now recognised as a credential.

    Never runs under an ephemeral key. Encrypting with a key that vanishes on
    restart would turn a readable credential into a permanently unrecoverable
    one — strictly worse than the plaintext this is meant to fix.
    """
    if _fernet_key_is_ephemeral:
        _logger.warning(
            "Not re-encrypting stored credentials: the credential-encryption key is "
            "ephemeral, so anything encrypted now would be unreadable after a restart. "
            "Set CASHPILOT_ENCRYPTION_KEY or fix the data directory, then restart."
        )
        return 0

    cursor = await db.execute("SELECT key, value FROM config")
    rows = await cursor.fetchall()
    stale = [
        (r["key"], r["value"])
        for r in rows
        if r["value"] and _is_secret_key(r["key"]) and not str(r["value"]).startswith(_ENC_PREFIX)
    ]
    if not stale:
        return 0

    for key, value in stale:
        await db.execute("UPDATE config SET value = ? WHERE key = ?", (encrypt_value(str(value)), key))
    await db.commit()
    # The key NAMES are safe to log and are what an operator needs to confirm the
    # pass did what they expect. The values are exactly what must never appear.
    _logger.info(
        "Encrypted %d stored credential(s) that predated at-rest encryption: %s",
        len(stale),
        ", ".join(sorted(k for k, _ in stale)),
    )
    return len(stale)


def _normalise_legacy_earnapp_credentials(raw: Mapping[str, Any]) -> dict[str, str]:
    """Map the retired account-pool key names onto the Chrome importer contract."""
    aliases = {
        "auth": "auth",
        "auth_method": "auth-method",
        "auth-method": "auth-method",
        "oauth_refresh_token": "oauth-refresh-token",
        "oauth-refresh-token": "oauth-refresh-token",
        "oauth_token": "oauth-token",
        "oauth-token": "oauth-token",
        "xsrf_token": "xsrf-token",
        "xsrf-token": "xsrf-token",
        "brd_sess_id": "brd_sess_id",
        "cg_uuid": "cg_uuid",
    }
    cookies: dict[str, str] = {}
    for key, value in raw.items():
        target = aliases.get(str(key))
        text = str(value or "").strip()
        if target and text:
            cookies[target] = text
    return cookies


async def _table_exists(db: Any, table_name: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (str(table_name),),
    )
    return await cursor.fetchone() is not None


async def _table_columns(db: Any, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    return {row["name"] for row in await cursor.fetchall()}


async def _table_sql(db: Any, table_name: str) -> str:
    row = await (
        await db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (str(table_name),))
    ).fetchone()
    return str(row["sql"] or "") if row else ""


async def _table_index_names(db: Any, table_name: str) -> set[str]:
    rows = await (await db.execute(f"PRAGMA index_list({table_name})")).fetchall()
    return {str(row["name"]) for row in rows}


async def _table_primary_key_columns(db: Any, table_name: str) -> tuple[str, ...]:
    rows = await (await db.execute(f"PRAGMA table_info({table_name})")).fetchall()
    return tuple(str(row["name"]) for row in sorted(rows, key=lambda row: int(row["pk"] or 0)) if row["pk"])


def _normalise_sql_default(value: Any) -> str:
    text = str(value or "").strip().lower()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return re.sub(r"\s+", "", text)


async def _table_has_unique_column(db: Any, table_name: str, column_name: str) -> bool:
    for index in await (await db.execute(f"PRAGMA index_list({table_name})")).fetchall():
        if not int(index["unique"] or 0):
            continue
        # A partial unique index does not enforce uniqueness for every row.
        # Callers that explicitly need a partial contract validate its exact
        # predicate separately.
        if int(index["partial"] or 0):
            continue
        columns = [
            str(row["name"]) for row in await (await db.execute(f"PRAGMA index_info({str(index['name'])})")).fetchall()
        ]
        if columns == [column_name]:
            return True
    return False


def _normalise_sql_fragment(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


async def _table_index_matches_contract(
    db: Any,
    table_name: str,
    index_name: str,
    contract: Mapping[str, Any],
) -> bool:
    """Check an index's complete persisted definition, not only its name."""
    index_row = next(
        (
            row
            for row in await (await db.execute(f"PRAGMA index_list({table_name})")).fetchall()
            if str(row["name"]) == index_name
        ),
        None,
    )
    if index_row is None:
        return False

    info_rows = await (await db.execute(f"PRAGMA index_info({index_name})")).fetchall()
    columns = tuple(str(row["name"] or "") for row in sorted(info_rows, key=lambda row: int(row["seqno"])))
    if columns != tuple(contract["columns"]):
        return False
    if bool(int(index_row["unique"] or 0)) != bool(contract["unique"]):
        return False
    if bool(int(index_row["partial"] or 0)) != bool(contract["partial"]):
        return False

    xinfo_rows = await (await db.execute(f"PRAGMA index_xinfo({index_name})")).fetchall()
    key_rows = [row for row in xinfo_rows if int(row["key"] or 0)]
    key_rows.sort(key=lambda row: int(row["seqno"]))
    descending = tuple(bool(int(row["desc"] or 0)) for row in key_rows)
    if descending != tuple(contract["descending"]):
        return False

    expected_where = contract.get("where")
    sql_row = await (
        await db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        )
    ).fetchone()
    sql = _normalise_sql_fragment(sql_row["sql"] if sql_row else "")
    actual_where = sql.split("where", 1)[1] if "where" in sql else None
    return actual_where == (_normalise_sql_fragment(expected_where) if expected_where is not None else None)


async def _account_fk_target(db: Any, table_name: str) -> str:
    cursor = await db.execute(f"PRAGMA foreign_key_list({table_name})")
    for row in await cursor.fetchall():
        if row["from"] == "account_id":
            return str(row["table"] or "")
    return ""


async def _logical_node_fk_target(db: Any, table_name: str) -> str:
    cursor = await db.execute(f"PRAGMA foreign_key_list({table_name})")
    for row in await cursor.fetchall():
        if row["from"] == "logical_node_id":
            return str(row["table"] or "")
    return ""


async def _tables_referencing(db: Any, parent_table: str) -> set[str]:
    """Return user tables with a foreign key to ``parent_table``."""
    rows = await (
        await db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    ).fetchall()
    references: set[str] = set()
    for row in rows:
        table_name = str(row["name"])
        foreign_keys = await (await db.execute(f"PRAGMA foreign_key_list({table_name})")).fetchall()
        if any(str(key["table"] or "") == parent_table for key in foreign_keys):
            references.add(table_name)
    return references


async def _table_schema_objects(db: Any, table_name: str) -> list[str]:
    """Capture explicit indexes and triggers so an FK rebuild cannot drop them."""
    rows = await (
        await db.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE tbl_name = ?
              AND type IN ('index', 'trigger')
              AND sql IS NOT NULL
            ORDER BY CASE type WHEN 'index' THEN 0 ELSE 1 END, name
            """,
            (str(table_name),),
        )
    ).fetchall()
    return [str(row["sql"]) for row in rows]


async def _restore_table_schema_objects(db: Any, statements: list[str]) -> None:
    for statement in statements:
        await db.execute(statement)


async def _assert_no_external_trigger_references(db: Any, table_name: str) -> None:
    """Do not rename a table while another trigger still names it.

    SQLite rewrites those trigger bodies to the temporary backup name during
    ``ALTER TABLE ... RENAME``.  Dropping the backup would then leave a live
    trigger pointing at a table that no longer exists.
    """
    rows = await (
        await db.execute(
            """
            SELECT name, tbl_name, sql
            FROM sqlite_master
            WHERE type = 'trigger' AND sql IS NOT NULL
            """
        )
    ).fetchall()
    quoted = re.compile(
        rf"(?<![A-Za-z0-9_])(?:{re.escape(table_name)}|\"{re.escape(table_name)}\"|`{re.escape(table_name)}`|\[{re.escape(table_name)}\])(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    for row in rows:
        if str(row["tbl_name"] or "") != table_name and quoted.search(str(row["sql"] or "")):
            raise RuntimeError(f"external trigger references EarnApp child table {table_name}: {row['name']}")


async def _assert_known_earnapp_account_children(db: Any, parent_table: str) -> None:
    allowed = {
        "earnapp_account_leases",
        "earnapp_account_leases_legacy_v18",
        "earnapp_logical_nodes",
        "earnapp_account_control_routes",
        "earnapp_account_snapshots",
    }
    unknown = sorted(await _tables_referencing(db, parent_table) - allowed)
    if unknown:
        raise RuntimeError(f"unknown EarnApp account child tables: {', '.join(unknown)}")


async def _assert_known_earnapp_logical_node_children(db: Any, parent_table: str) -> None:
    allowed = {"earnapp_proxy_reservations", "earnapp_replacement_tickets"}
    unknown = sorted(await _tables_referencing(db, parent_table) - allowed)
    if unknown:
        raise RuntimeError(f"unknown EarnApp logical-node child tables: {', '.join(unknown)}")


def _legacy_earnapp_state(value: Any, *, credentials_valid: bool) -> str:
    state = str(value or "").strip().upper()
    if state == "DELETED":
        return "DELETED"
    if state in {"DISABLED", "EXPIRED", "AUTH_FAILED"}:
        return state
    # Legacy rows do not carry an authoritative auth-method binding.  Even
    # decryptable credentials therefore require an explicit Chrome re-import
    # before they may be activated.
    return "DISABLED"


def _credential_values_equal(left: Any, right: Any) -> bool:
    """Compare Fernet values without equating two failed decryptions."""
    left_raw = str(left or "")
    right_raw = str(right or "")
    if left_raw == right_raw:
        return True
    if not left_raw or not right_raw:
        return False
    left_plain = decrypt_value(left_raw)
    right_plain = decrypt_value(right_raw)
    if not left_plain or not right_plain:
        return False
    return left_plain == right_plain


async def _earnapp_migration_marker(db: Any) -> str:
    if not await _table_exists(db, "config"):
        return ""
    row = await (
        await db.execute("SELECT value FROM config WHERE key = ?", (_EARNAPP_LEGACY_MIGRATION_KEY,))
    ).fetchone()
    return str(row["value"] or "") if row else ""


async def _mark_earnapp_migration_complete(db: Any) -> None:
    row = await (
        await db.execute("SELECT value FROM config WHERE key = ?", (_EARNAPP_LEGACY_MIGRATION_KEY,))
    ).fetchone()
    if row and str(row["value"] or "") != "complete":
        raise RuntimeError("Conflicting EarnApp migration marker")
    if not row:
        await db.execute(
            # Old volumes may not have received config.updated_at yet; the
            # regular init migration adds that column later in the same boot.
            "INSERT INTO config (key, value) VALUES (?, 'complete')",
            (_EARNAPP_LEGACY_MIGRATION_KEY,),
        )


async def _ensure_earnapp_logical_node_identity_schema(db: Any, applied: list[str]) -> None:
    """Upgrade the v19 logical-node table without rewriting existing rows.

    Platform is intentionally nullable in meaning (``unknown`` for legacy
    rows), while ``device_id`` is unique only when populated.  A duplicate
    non-empty device ID is unsafe to resolve automatically because it could
    represent two remote devices; fail closed before creating the index.
    """
    if not await _table_exists(db, "earnapp_logical_nodes"):
        return
    columns = await _table_columns(db, "earnapp_logical_nodes")
    if "platform" not in columns:
        await db.execute(
            """
            ALTER TABLE earnapp_logical_nodes
            ADD COLUMN platform TEXT NOT NULL DEFAULT 'unknown'
                CHECK(platform IN ('unknown', 'macos', 'ios', 'ubuntu'))
            """
        )
        applied.append("earnapp_logical_nodes.platform")
    invalid = await (
        await db.execute(
            """
            SELECT logical_node_id, platform
            FROM earnapp_logical_nodes
            WHERE platform NOT IN ('unknown', 'macos', 'ios', 'ubuntu')
            LIMIT 1
            """
        )
    ).fetchone()
    if invalid:
        raise RuntimeError(
            f"EarnApp logical node {invalid['logical_node_id']} has unsupported platform {invalid['platform']}"
        )
    duplicate = await (
        await db.execute(
            """
            SELECT device_id, COUNT(*) AS count
            FROM earnapp_logical_nodes
            WHERE device_id IS NOT NULL AND device_id != ''
            GROUP BY device_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchone()
    if duplicate:
        raise RuntimeError(f"EarnApp logical-node device_id collision requires review: {duplicate['device_id']}")
    await db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_logical_nodes_device_id_unique
        ON earnapp_logical_nodes(device_id) WHERE device_id != ''
        """
    )


async def _ensure_earnapp_logical_node_proxy_health_schema(db: Any, applied: list[str]) -> None:
    """Add node-scoped proxy evidence without rewriting identity-bearing rows."""
    if not await _table_exists(db, "earnapp_logical_nodes"):
        return
    columns = await _table_columns(db, "earnapp_logical_nodes")
    additions = {
        "proxy_health": ("TEXT NOT NULL DEFAULT 'unknown' CHECK(proxy_health IN ('healthy', 'unhealthy', 'unknown'))"),
        "observed_egress_ip": "TEXT NOT NULL DEFAULT ''",
        "expected_egress_ip": "TEXT NOT NULL DEFAULT ''",
        "proxy_checked_at": "TEXT",
        "proxy_health_reason": "TEXT NOT NULL DEFAULT ''",
        "usage_baseline": "REAL NOT NULL DEFAULT 0",
        "window_started_at": "TEXT",
        "same_proxy_recreates": "INTEGER NOT NULL DEFAULT 0",
        "rotate_count": "INTEGER NOT NULL DEFAULT 0",
        "lifecycle_action": "TEXT NOT NULL DEFAULT 'observe'",
        "quarantine_reason": "TEXT NOT NULL DEFAULT ''",
    }
    for column, declaration in additions.items():
        if column not in columns:
            await db.execute(f"ALTER TABLE earnapp_logical_nodes ADD COLUMN {column} {declaration}")
            applied.append(f"earnapp_logical_nodes.{column}")

    invalid = await (
        await db.execute(
            """
            SELECT logical_node_id, proxy_health
            FROM earnapp_logical_nodes
            WHERE proxy_health NOT IN ('healthy', 'unhealthy', 'unknown')
            LIMIT 1
            """
        )
    ).fetchone()
    if invalid:
        raise RuntimeError(
            f"EarnApp logical node {invalid['logical_node_id']} has invalid proxy health {invalid['proxy_health']}"
        )


async def _validate_earnapp_archive_schema(db: Any, table_name: str, required: set[str]) -> set[int] | None:
    """Validate an immutable migration archive and return its source IDs."""
    if not await _table_exists(db, table_name):
        return None
    columns = await _table_columns(db, table_name)
    missing = required - columns
    if missing:
        raise RuntimeError(f"EarnApp archive {table_name} missing columns: {', '.join(sorted(missing))}")
    rows = await (await db.execute(f"SELECT id FROM {table_name} ORDER BY id")).fetchall()
    return {int(row["id"]) for row in rows}


async def _validate_completed_earnapp_migration(
    db: Any,
    *,
    allowed_missing_tables: frozenset[str] = frozenset(),
) -> None:
    """Fail closed if a completion marker no longer describes a safe schema."""
    if not await _table_exists(db, "earnapp_accounts"):
        raise RuntimeError("EarnApp migration completion marker requires canonical schema")
    canonical_columns = await _table_columns(db, "earnapp_accounts")
    missing = _EARNAPP_ACCOUNT_REQUIRED_COLUMNS - canonical_columns
    if missing:
        raise RuntimeError(f"EarnApp canonical schema missing columns: {', '.join(sorted(missing))}")
    canonical_info = {
        str(row["name"]): row for row in await (await db.execute("PRAGMA table_info(earnapp_accounts)")).fetchall()
    }
    profile_indexes = await (await db.execute("PRAGMA index_list(earnapp_accounts)")).fetchall()
    has_unique_profile_key = False
    for index in profile_indexes:
        if not int(index["unique"] or 0) or int(index["partial"] or 0):
            continue
        names = [
            str(row["name"]) for row in await (await db.execute(f"PRAGMA index_info({str(index['name'])})")).fetchall()
        ]
        if names == ["profile_key"]:
            has_unique_profile_key = True
            break
    canonical_sql = (await _table_sql(db, "earnapp_accounts")).lower()
    canonical_sql_compact = re.sub(r"\s+", "", canonical_sql)
    if (
        int(canonical_info["id"]["pk"] or 0) != 1
        or any(
            str(canonical_info[name]["type"] or "").upper() != expected
            for name, expected in _EARNAPP_ACCOUNT_COLUMN_TYPES.items()
        )
        or any(
            not int(canonical_info[name]["notnull"] or 0)
            for name in _EARNAPP_ACCOUNT_REQUIRED_COLUMNS - {"id", "token_expires_at", "cookie_expires_at"}
        )
        or any(
            _normalise_sql_default(canonical_info[name]["dflt_value"]) != _normalise_sql_default(expected)
            for name, expected in _EARNAPP_ACCOUNT_DEFAULTS.items()
        )
        or not has_unique_profile_key
        or "autoincrement" not in canonical_sql_compact
        or "check(auth_methodin('google','apple'))" not in canonical_sql_compact
    ):
        raise RuntimeError("EarnApp canonical schema constraints do not match the current contract")

    for table_name, required_columns in _EARNAPP_CHILD_COLUMNS.items():
        if not await _table_exists(db, table_name):
            if table_name in allowed_missing_tables:
                continue
            raise RuntimeError(f"EarnApp canonical child schema missing table: {table_name}")
        child_columns = await _table_columns(db, table_name)
        if child_columns != required_columns:
            raise RuntimeError(f"EarnApp canonical child schema mismatch: {table_name}")
        if await _table_primary_key_columns(db, table_name) != _EARNAPP_CHILD_PRIMARY_KEYS[table_name]:
            raise RuntimeError(f"EarnApp canonical child schema primary-key mismatch: {table_name}")
        missing_indexes = _EARNAPP_CHILD_INDEXES[table_name] - await _table_index_names(db, table_name)
        if missing_indexes:
            raise RuntimeError(
                f"EarnApp canonical child schema index mismatch: {table_name}: {', '.join(sorted(missing_indexes))}"
            )
        invalid_indexes = {
            index_name
            for index_name, contract in _EARNAPP_CHILD_INDEX_CONTRACTS.get(table_name, {}).items()
            if not await _table_index_matches_contract(db, table_name, index_name, contract)
        }
        if invalid_indexes:
            raise RuntimeError(
                f"EarnApp canonical child schema index mismatch: {table_name}: {', '.join(sorted(invalid_indexes))}"
            )
        missing_unique = {
            column
            for column in _EARNAPP_CHILD_UNIQUE_COLUMNS.get(table_name, set())
            if not await _table_has_unique_column(db, table_name, column)
        }
        if missing_unique:
            raise RuntimeError(
                "EarnApp canonical child schema unique-constraint mismatch: "
                f"{table_name}: {', '.join(sorted(missing_unique))}"
            )
        foreign_keys = {
            str(row["from"]): (str(row["table"]), str(row["to"]), str(row["on_delete"]).upper())
            for row in await (await db.execute(f"PRAGMA foreign_key_list({table_name})")).fetchall()
        }
        if foreign_keys != _EARNAPP_CHILD_FOREIGN_KEYS[table_name]:
            raise RuntimeError(f"EarnApp canonical child schema foreign-key mismatch: {table_name}")

    v18_rows = await _validate_earnapp_archive_schema(
        db, "earnapp_accounts_legacy_v18", _EARNAPP_LEGACY_ACCOUNT_REQUIRED_COLUMNS
    )
    v19_rows = await _validate_earnapp_archive_schema(
        db, "earnapp_accounts_v19_legacy", _EARNAPP_V19_ACCOUNT_REQUIRED_COLUMNS
    )
    if v18_rows is None and v19_rows is None:
        raise RuntimeError("EarnApp migration completion marker requires an archive")
    v18_rows = v18_rows or set()
    v19_rows = v19_rows or set()
    if v18_rows & v19_rows:
        raise RuntimeError("EarnApp migration archives contain duplicate account IDs")
    archive_ids = v18_rows | v19_rows

    # Account metadata and credentials can be intentionally refreshed after
    # migration; only the archived primary-key set is immutable.
    placeholders = ", ".join("?" for _ in archive_ids)
    if archive_ids:
        rows = await (
            await db.execute(
                f"SELECT id FROM earnapp_accounts WHERE id IN ({placeholders}) ORDER BY id",
                tuple(sorted(archive_ids)),
            )
        ).fetchall()
        canonical_ids = {int(row["id"]) for row in rows}
        missing_ids = sorted(archive_ids - canonical_ids)
        if missing_ids:
            raise RuntimeError(f"EarnApp canonical/archive parity mismatch for account IDs: {missing_ids}")


async def _quarantine_synthetic_legacy_accounts(db: Any, applied: list[str]) -> None:
    """Disable accounts left ACTIVE by the unsafe v1.11.1 migration."""
    if not await _table_exists(db, "earnapp_accounts"):
        return
    columns = await _table_columns(db, "earnapp_accounts")
    if not {"profile_key", "state"} <= columns:
        return
    cursor = await db.execute(
        """
        UPDATE earnapp_accounts
        SET state = 'DISABLED', updated_at = datetime('now')
        WHERE profile_key LIKE 'legacy-account-%' AND state = 'ACTIVE'
        """
    )
    if cursor.rowcount:
        applied.append("earnapp_accounts.legacy_active_quarantine")


def _decode_legacy_earnapp_credentials(encrypted: str) -> tuple[dict[str, str], str, bool]:
    if not encrypted:
        return {}, "", False
    decrypted = decrypt_value(encrypted)
    if not decrypted:
        return {}, "", False
    try:
        decoded = json.loads(decrypted)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "", False
    if not isinstance(decoded, Mapping):
        return {}, "", False
    cookies = _normalise_legacy_earnapp_credentials(decoded)
    valid = bool(cookies.get("oauth-refresh-token") and cookies.get("xsrf-token"))
    email = str(decoded.get("email") or "").strip()
    return cookies if valid else {}, email, valid


async def _ensure_earnapp_proxy_reservation_schema(db: Any, applied: list[str] | None = None) -> None:
    table_exists = await _table_exists(db, "earnapp_proxy_reservations")
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS earnapp_proxy_reservations (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            logical_node_id    TEXT    NOT NULL,
            worker_id          INTEGER NOT NULL,
            generation         INTEGER NOT NULL,
            expected_proxy_id  INTEGER NOT NULL,
            proxy_id           INTEGER NOT NULL,
            binding_version    TEXT    NOT NULL,
            state              TEXT    NOT NULL DEFAULT 'ACTIVE'
                               CHECK(state IN ('ACTIVE', 'COMMITTED', 'RELEASED', 'EXPIRED')),
            reserved_at        TEXT    NOT NULL DEFAULT (datetime('now')),
            expires_at         TEXT    NOT NULL,
            released_at        TEXT,
            release_reason     TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE,
            FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE,
            FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
        )
        """
    )
    if not table_exists and applied is not None:
        applied.append("earnapp_proxy_reservations")

    # Do not try to heal an existing table with a different shape. The
    # completion-marker validator below must reject it without hiding damage
    # behind indexes created against a non-canonical schema.
    if await _table_columns(db, "earnapp_proxy_reservations") != _EARNAPP_CHILD_COLUMNS["earnapp_proxy_reservations"]:
        return

    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_proxy_reservations_active_proxy "
        "ON earnapp_proxy_reservations(proxy_id) WHERE state = 'ACTIVE'"
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_proxy_reservations_active_binding "
        "ON earnapp_proxy_reservations(logical_node_id, binding_version) WHERE state = 'ACTIVE'"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_earnapp_proxy_reservations_expiry "
        "ON earnapp_proxy_reservations(state, expires_at)"
    )


async def _create_earnapp_current_schema(db: Any) -> None:
    if not await _table_exists(db, "earnapp_accounts"):
        await db.execute(_EARNAPP_ACCOUNTS_TABLE_SQL)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS earnapp_logical_nodes (
            logical_node_id    TEXT    PRIMARY KEY,
            account_id         INTEGER NOT NULL,
            platform           TEXT    NOT NULL DEFAULT 'unknown'
                                       CHECK(platform IN ('unknown', 'macos', 'ios', 'ubuntu')),
            state              TEXT    NOT NULL DEFAULT 'PLANNED',
            generation         INTEGER NOT NULL DEFAULT 1,
            assigned_worker_id INTEGER,
            last_worker_id     INTEGER,
            device_id          TEXT    NOT NULL DEFAULT '',
            current_proxy_id   INTEGER,
            preferred_proxy_id INTEGER,
            proxy_health       TEXT    NOT NULL DEFAULT 'unknown'
                                       CHECK(proxy_health IN ('healthy', 'unhealthy', 'unknown')),
            observed_egress_ip TEXT    NOT NULL DEFAULT '',
            expected_egress_ip TEXT    NOT NULL DEFAULT '',
            proxy_checked_at   TEXT,
            proxy_health_reason TEXT  NOT NULL DEFAULT '',
            last_heartbeat_at  TEXT,
            recovery_started_at TEXT,
            recovery_hold_until TEXT,
            usage_baseline      REAL NOT NULL DEFAULT 0,
            window_started_at   TEXT,
            same_proxy_recreates INTEGER NOT NULL DEFAULT 0,
            rotate_count        INTEGER NOT NULL DEFAULT 0,
            lifecycle_action    TEXT NOT NULL DEFAULT 'observe',
            quarantine_reason   TEXT NOT NULL DEFAULT '',
            created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE RESTRICT,
            FOREIGN KEY(assigned_worker_id) REFERENCES workers(id) ON DELETE SET NULL,
            FOREIGN KEY(current_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL,
            FOREIGN KEY(preferred_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS earnapp_replacement_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logical_node_id TEXT NOT NULL,
            target_worker_id INTEGER NOT NULL,
            generation INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE,
            FOREIGN KEY(target_worker_id) REFERENCES workers(id) ON DELETE CASCADE
        )
        """
    )
    await _ensure_earnapp_proxy_reservation_schema(db)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS earnapp_account_control_routes (
            account_id INTEGER PRIMARY KEY,
            proxy_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'ACTIVE',
            assigned_logical_node_id TEXT NOT NULL DEFAULT '',
            leased_at TEXT NOT NULL DEFAULT (datetime('now')),
            released_at TEXT,
            release_reason TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE,
            FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE RESTRICT
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS earnapp_account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            money_balance REAL NOT NULL DEFAULT 0,
            money_total REAL NOT NULL DEFAULT 0,
            online_nodes INTEGER NOT NULL DEFAULT 0,
            offline_nodes INTEGER NOT NULL DEFAULT 0,
            devices_json TEXT NOT NULL DEFAULT '[]',
            collected_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_earnapp_logical_nodes_account_state ON earnapp_logical_nodes(account_id, state)"
    )
    await db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_earnapp_logical_nodes_device_id_unique
        ON earnapp_logical_nodes(device_id) WHERE device_id != ''
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_earnapp_replacement_tickets_target
        ON earnapp_replacement_tickets(logical_node_id, target_worker_id, used_at, expires_at)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_earnapp_account_snapshots_latest
        ON earnapp_account_snapshots(account_id, id DESC)
        """
    )


async def _rebuild_earnapp_child_table(db: Any, table_name: str) -> None:
    if not await _table_exists(db, table_name):
        return
    if await _account_fk_target(db, table_name) not in {"earnapp_accounts_legacy_v18", "earnapp_accounts_v19"}:
        return
    backup = f"{table_name}_legacy_fk_v19"
    if await _table_exists(db, backup):
        raise RuntimeError(f"Interrupted EarnApp FK repair left {backup}")
    if table_name == "earnapp_logical_nodes":
        await _assert_known_earnapp_logical_node_children(db, table_name)
    await _assert_no_external_trigger_references(db, table_name)
    schema_objects = await _table_schema_objects(db, table_name)
    await db.execute(f"ALTER TABLE {table_name} RENAME TO {backup}")
    if table_name == "earnapp_logical_nodes":
        await db.execute(
            """
            CREATE TABLE earnapp_logical_nodes (
                logical_node_id TEXT PRIMARY KEY, account_id INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(platform IN ('unknown', 'macos', 'ios', 'ubuntu')),
                state TEXT NOT NULL DEFAULT 'PLANNED', generation INTEGER NOT NULL DEFAULT 1,
                assigned_worker_id INTEGER, last_worker_id INTEGER, device_id TEXT NOT NULL DEFAULT '',
                current_proxy_id INTEGER, preferred_proxy_id INTEGER,
                proxy_health TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(proxy_health IN ('healthy', 'unhealthy', 'unknown')),
                observed_egress_ip TEXT NOT NULL DEFAULT '', expected_egress_ip TEXT NOT NULL DEFAULT '',
                proxy_checked_at TEXT, proxy_health_reason TEXT NOT NULL DEFAULT '',
                last_heartbeat_at TEXT,
                recovery_started_at TEXT, recovery_hold_until TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE RESTRICT,
                FOREIGN KEY(assigned_worker_id) REFERENCES workers(id) ON DELETE SET NULL,
                FOREIGN KEY(current_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL,
                FOREIGN KEY(preferred_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
            )
            """
        )
    elif table_name == "earnapp_account_control_routes":
        await db.execute(
            """
            CREATE TABLE earnapp_account_control_routes (
                account_id INTEGER PRIMARY KEY, proxy_id INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'ACTIVE', assigned_logical_node_id TEXT NOT NULL DEFAULT '',
                leased_at TEXT NOT NULL DEFAULT (datetime('now')), released_at TEXT,
                release_reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE,
                FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE RESTRICT
            )
            """
        )
    elif table_name == "earnapp_account_snapshots":
        await db.execute(
            """
            CREATE TABLE earnapp_account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL,
                money_balance REAL NOT NULL DEFAULT 0, money_total REAL NOT NULL DEFAULT 0,
                online_nodes INTEGER NOT NULL DEFAULT 0, offline_nodes INTEGER NOT NULL DEFAULT 0,
                devices_json TEXT NOT NULL DEFAULT '[]',
                payment_json TEXT NOT NULL DEFAULT '{}',
                collected_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(account_id) REFERENCES earnapp_accounts(id) ON DELETE CASCADE
            )
            """
        )
    columns = await _table_columns(db, table_name)
    backup_columns = await _table_columns(db, backup)
    expected_columns = _EARNAPP_CHILD_COLUMNS[table_name]
    unexpected_columns = backup_columns - expected_columns
    if unexpected_columns:
        raise RuntimeError(
            f"Unsupported {table_name} columns during EarnApp FK repair: {', '.join(sorted(unexpected_columns))}"
        )
    common = sorted(columns & backup_columns)
    names = ", ".join(common)
    await db.execute(f"INSERT INTO {table_name} ({names}) SELECT {names} FROM {backup}")
    if table_name == "earnapp_logical_nodes":
        # Rebind cascading children while the renamed parent still exists;
        # dropping it first would delete those rows through ON DELETE CASCADE.
        await _rebuild_earnapp_logical_child_table(db, "earnapp_replacement_tickets")
    await db.execute(f"DROP TABLE {backup}")
    await _restore_table_schema_objects(db, schema_objects)


async def _rebuild_earnapp_logical_child_table(db: Any, table_name: str) -> None:
    """Rebind a table that references logical nodes after their safe rebuild."""
    if not await _table_exists(db, table_name):
        return
    if await _logical_node_fk_target(db, table_name) not in {
        "earnapp_logical_nodes_legacy_fk_v19",
        "earnapp_logical_nodes_v19",
    }:
        return
    await _assert_no_external_trigger_references(db, table_name)
    backup = f"{table_name}_legacy_fk_v19"
    if await _table_exists(db, backup):
        raise RuntimeError(f"Interrupted EarnApp logical-node FK repair left {backup}")
    schema_objects = await _table_schema_objects(db, table_name)
    await db.execute(f"ALTER TABLE {table_name} RENAME TO {backup}")
    await db.execute(
        """
        CREATE TABLE earnapp_replacement_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logical_node_id TEXT NOT NULL,
            target_worker_id INTEGER NOT NULL,
            generation INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(logical_node_id) REFERENCES earnapp_logical_nodes(logical_node_id) ON DELETE CASCADE,
            FOREIGN KEY(target_worker_id) REFERENCES workers(id) ON DELETE CASCADE
        )
        """
    )
    columns = await _table_columns(db, table_name)
    backup_columns = await _table_columns(db, backup)
    expected_columns = _EARNAPP_CHILD_COLUMNS[table_name]
    unexpected_columns = backup_columns - expected_columns
    if unexpected_columns:
        raise RuntimeError(
            f"Unsupported {table_name} columns during EarnApp FK repair: {', '.join(sorted(unexpected_columns))}"
        )
    common = sorted(columns & backup_columns)
    names = ", ".join(common)
    await db.execute(f"INSERT INTO {table_name} ({names}) SELECT {names} FROM {backup}")
    await db.execute(f"DROP TABLE {backup}")
    await _restore_table_schema_objects(db, schema_objects)


async def _archive_legacy_earnapp_tables(db: Any) -> None:
    if not await _table_exists(db, "earnapp_accounts"):
        return
    columns = await _table_columns(db, "earnapp_accounts")
    if "profile_key" in columns:
        return
    if await _table_exists(db, "earnapp_accounts_legacy_v18"):
        raise RuntimeError("Both live and archived legacy earnapp_accounts tables exist")
    await _assert_known_earnapp_account_children(db, "earnapp_accounts")
    await _assert_no_external_trigger_references(db, "earnapp_accounts")
    if await _table_exists(db, "earnapp_account_leases"):
        if await _table_exists(db, "earnapp_account_leases_legacy_v18"):
            raise RuntimeError("Both live and archived legacy EarnApp lease tables exist")
        await db.execute("ALTER TABLE earnapp_account_leases RENAME TO earnapp_account_leases_legacy_v18")
    await db.execute("ALTER TABLE earnapp_accounts RENAME TO earnapp_accounts_legacy_v18")


async def _recover_stranded_earnapp_v19(db: Any) -> None:
    if not await _table_exists(db, "earnapp_accounts_v19"):
        return
    if await _table_exists(db, "earnapp_accounts_v19_legacy"):
        raise RuntimeError("Both live and archived earnapp_accounts_v19 tables exist")
    columns = await _table_columns(db, "earnapp_accounts_v19")
    missing = _EARNAPP_V19_ACCOUNT_REQUIRED_COLUMNS - columns
    if missing:
        raise RuntimeError(
            f"Unsupported interrupted earnapp_accounts_v19 schema; missing columns: {', '.join(sorted(missing))}"
        )
    await _assert_known_earnapp_account_children(db, "earnapp_accounts_v19")
    await _create_earnapp_current_schema(db)
    for source in await (await db.execute("SELECT * FROM earnapp_accounts_v19 ORDER BY id")).fetchall():
        current = await (
            await db.execute("SELECT * FROM earnapp_accounts WHERE id = ?", (int(source["id"]),))
        ).fetchone()
        state = str(source["state"] or "").upper()
        expected_state = (
            "DELETED"
            if state == "DELETED"
            else (state if state in {"DISABLED", "EXPIRED", "AUTH_FAILED"} else "DISABLED")
        )
        expected = {
            "profile_key": str(source["profile_key"] or ""),
            "account_name": str(source["account_name"] or ""),
            "email": str(source["email"] or ""),
            "auth_method": str(source["auth_method"] or "").lower(),
            "credentials_enc": str(source["credentials_enc"] or ""),
            "credential_keys_json": str(source["credential_keys_json"] or "[]"),
            "token_expires_at": source["token_expires_at"],
            "cookie_expires_at": source["cookie_expires_at"],
            "state": expected_state,
            "created_at": source["created_at"],
            "updated_at": source["updated_at"],
        }
        if current:
            equal = all(
                (
                    _credential_values_equal(current["credentials_enc"], expected["credentials_enc"])
                    if key == "credentials_enc"
                    else current[key] == value
                )
                for key, value in expected.items()
            )
            if not equal:
                raise RuntimeError(f"Conflicting partial EarnApp account row {source['id']}")
            continue
        await db.execute(
            """
            INSERT INTO earnapp_accounts
                (id, profile_key, account_name, email, auth_method, credentials_enc,
                 credential_keys_json, token_expires_at, cookie_expires_at, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(source["id"]),
                expected["profile_key"],
                expected["account_name"],
                expected["email"],
                expected["auth_method"],
                expected["credentials_enc"],
                expected["credential_keys_json"],
                expected["token_expires_at"],
                expected["cookie_expires_at"],
                expected["state"],
                expected["created_at"],
                expected["updated_at"],
            ),
        )
    for table_name in (
        "earnapp_logical_nodes",
        "earnapp_account_control_routes",
        "earnapp_account_snapshots",
    ):
        await _rebuild_earnapp_child_table(db, table_name)
    # Keep the stranded source as an audit/recovery archive; never discard the
    # only copy of credentials after an interrupted DDL sequence.
    await db.execute("ALTER TABLE earnapp_accounts_v19 RENAME TO earnapp_accounts_v19_legacy")


async def _migrate_legacy_earnapp_accounts(db: Any, applied: list[str]) -> None:
    """Archive the retired pool and materialize safe, non-assignable records."""
    # Apply additive logical-node hardening before the completion-marker
    # validator runs.  This keeps an already-migrated v19 volume upgradeable
    # without rebuilding or rewriting its identity rows.
    await _ensure_earnapp_logical_node_identity_schema(db, applied)
    await _ensure_earnapp_logical_node_proxy_health_schema(db, applied)
    marker = await _earnapp_migration_marker(db)
    accounts_exists = await _table_exists(db, "earnapp_accounts")
    account_columns = await _table_columns(db, "earnapp_accounts") if accounts_exists else set()
    legacy_accounts_exists = accounts_exists and "profile_key" not in account_columns
    if accounts_exists and "profile_key" in account_columns:
        missing = _EARNAPP_ACCOUNT_REQUIRED_COLUMNS - account_columns
        if missing:
            raise RuntimeError(f"EarnApp canonical schema missing columns: {', '.join(sorted(missing))}")
    if marker == "complete":
        # A completed migration may retain its immutable archive, but a live
        # legacy table or a second stranded source indicates corruption and
        # must not be silently ignored.
        if legacy_accounts_exists or await _table_exists(db, "earnapp_accounts_v19"):
            raise RuntimeError("EarnApp migration marker conflicts with live legacy tables")
        await _validate_completed_earnapp_migration(
            db,
            allowed_missing_tables=frozenset({"earnapp_proxy_reservations"}),
        )
        await _ensure_earnapp_proxy_reservation_schema(db, applied)
        await _validate_completed_earnapp_migration(db)
        return
    if await _table_exists(db, "earnapp_accounts_v19_legacy") and not await _table_exists(db, "earnapp_accounts_v19"):
        # An archive without its completion marker is ambiguous: it may be the
        # only surviving source after a crash, or a source already copied and
        # later edited. Never mark that state complete without an operator-led
        # comparison of every row.
        raise RuntimeError("archived EarnApp v19 source requires recovery review")
    needs_migration = any(
        [
            await _table_exists(db, "earnapp_accounts_legacy_v18"),
            await _table_exists(db, "earnapp_accounts_v19"),
            await _table_exists(db, "earnapp_accounts_v19_legacy"),
            legacy_accounts_exists,
        ]
    )
    if not needs_migration:
        return
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute("PRAGMA defer_foreign_keys=ON")
        await _archive_legacy_earnapp_tables(db)
        await _recover_stranded_earnapp_v19(db)
        await _create_earnapp_current_schema(db)

        # A crash can leave both the v18 archive and a copied v19 source.  The
        # same account ID in both is ambiguous; never choose one silently.
        if await _table_exists(db, "earnapp_accounts_legacy_v18") and await _table_exists(
            db, "earnapp_accounts_v19_legacy"
        ):
            v18_ids = {
                int(row["id"])
                for row in await (await db.execute("SELECT id FROM earnapp_accounts_legacy_v18")).fetchall()
            }
            v19_ids = {
                int(row["id"])
                for row in await (await db.execute("SELECT id FROM earnapp_accounts_v19_legacy")).fetchall()
            }
            overlap = sorted(v18_ids & v19_ids)
            if overlap:
                raise RuntimeError(f"EarnApp migration archives contain duplicate account IDs: {overlap}")

        if await _table_exists(db, "earnapp_accounts_legacy_v18"):
            columns = await _table_columns(db, "earnapp_accounts_legacy_v18")
            if not {"id", "account_name", "cookies_enc", "state"} <= columns:
                raise RuntimeError("Unsupported legacy earnapp_accounts schema")
            cursor = await db.execute(
                """
                SELECT id, account_name, cookies_enc, state, created_at, updated_at
                FROM earnapp_accounts_legacy_v18 ORDER BY id
                """
            )
            for row in await cursor.fetchall():
                encrypted = str(row["cookies_enc"] or "")
                cookies, stored_email, credentials_valid = _decode_legacy_earnapp_credentials(encrypted)
                email = stored_email or str(row["account_name"] or "").strip()
                credentials_enc = (
                    encrypt_value(json.dumps({"cookies": cookies}, sort_keys=True, separators=(",", ":")))
                    if credentials_valid
                    else ""
                )
                expected = {
                    "profile_key": f"legacy-account-{int(row['id'])}",
                    "account_name": str(row["account_name"] or ""),
                    "email": email,
                    "auth_method": "google",
                    "credentials_enc": credentials_enc,
                    "credential_keys_json": json.dumps(sorted(cookies)),
                    "state": _legacy_earnapp_state(row["state"], credentials_valid=credentials_valid),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                existing = await (
                    await db.execute("SELECT * FROM earnapp_accounts WHERE id = ?", (int(row["id"]),))
                ).fetchone()
                if existing:
                    equal = all(
                        (
                            _credential_values_equal(existing["credentials_enc"], expected["credentials_enc"])
                            if key == "credentials_enc"
                            else existing[key] == value
                        )
                        for key, value in expected.items()
                    )
                    if not equal:
                        raise RuntimeError(f"Conflicting canonical EarnApp account row {row['id']}")
                else:
                    await db.execute(
                        """
                        INSERT INTO earnapp_accounts
                            (id, profile_key, account_name, email, auth_method, credentials_enc,
                             credential_keys_json, state, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(row["id"]),
                            expected["profile_key"],
                            expected["account_name"],
                            expected["email"],
                            expected["auth_method"],
                            expected["credentials_enc"],
                            expected["credential_keys_json"],
                            expected["state"],
                            expected["created_at"],
                            expected["updated_at"],
                        ),
                    )

        for table_name in (
            "earnapp_logical_nodes",
            "earnapp_account_control_routes",
            "earnapp_account_snapshots",
        ):
            await _rebuild_earnapp_child_table(db, table_name)
        await _rebuild_earnapp_logical_child_table(db, "earnapp_replacement_tickets")

        if await _table_exists(db, "earnapp_account_leases_legacy_v18"):
            cursor = await db.execute(
                """
            SELECT id, account_id, worker_id, instance_id, state, leased_at,
                   last_heartbeat_at, released_at
            FROM earnapp_account_leases_legacy_v18
            ORDER BY id
            """
            )
            for lease in await cursor.fetchall():
                lease_state = str(lease["state"] or "").strip().upper()
                node_state = "RECOVERABLE" if lease_state == "ACTIVE" and not lease["released_at"] else "RETIRED"
                logical_node_id = f"legacy-earnapp-lease-{int(lease['id'])}"
                expected = {
                    "account_id": int(lease["account_id"]),
                    "state": node_state,
                    "assigned_worker_id": None,
                    "last_worker_id": int(lease["worker_id"]),
                    "last_heartbeat_at": lease["last_heartbeat_at"],
                    "created_at": lease["leased_at"],
                    "updated_at": lease["released_at"] or lease["last_heartbeat_at"] or lease["leased_at"],
                }
                existing = await (
                    await db.execute(
                        "SELECT account_id, state, assigned_worker_id, last_worker_id, last_heartbeat_at, created_at, updated_at "
                        "FROM earnapp_logical_nodes WHERE logical_node_id = ?",
                        (logical_node_id,),
                    )
                ).fetchone()
                if existing:
                    if any(existing[key] != value for key, value in expected.items()):
                        raise RuntimeError(f"Conflicting logical EarnApp node {logical_node_id}")
                else:
                    await db.execute(
                        """
                        INSERT INTO earnapp_logical_nodes
                            (logical_node_id, account_id, state, assigned_worker_id, last_worker_id,
                             last_heartbeat_at, created_at, updated_at)
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                        """,
                        (
                            logical_node_id,
                            expected["account_id"],
                            expected["state"],
                            expected["last_worker_id"],
                            expected["last_heartbeat_at"],
                            expected["created_at"],
                            expected["updated_at"],
                        ),
                    )
        violations = await (await db.execute("PRAGMA foreign_key_check")).fetchall()
        if violations:
            raise RuntimeError("EarnApp migration failed foreign-key validation")
        await _mark_earnapp_migration_complete(db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    applied.append("earnapp_accounts.legacy_v19")


#: What this build's schema looks like. Bumped by hand when a migration is added.
#:
#: REPORTED, NEVER USED AS A GATE. Every migration below is guarded by its own
#: ``PRAGMA table_info`` check, and that stays the source of truth. If this number
#: decided whether migrations ran, a database whose user_version said 10 but was
#: missing a column -- an interrupted upgrade, a restored backup, a hand-edited
#: file -- could never be repaired, because the gate would say there was nothing
#: to do. The guards are idempotent and cheap; the version is for the operator.
SCHEMA_VERSION = 21


async def init_db() -> None:
    """Create tables if they don't exist."""
    db = await _get_db()
    # What actually changed on THIS boot, for the log line at the end. An
    # operator watching `docker logs` during an upgrade could previously not
    # tell a clean start from one that had just rewritten the earnings table.
    applied: list[str] = []
    try:
        await _dedupe_earnings_before_indexing(db)
        await db.executescript(_SCHEMA)
        # Add snapshot payment metadata before the completed-migration validator
        # compares the canonical child schema.
        if await _table_exists(db, "earnapp_account_snapshots"):
            snapshot_cols = {
                row["name"]
                for row in await (await db.execute("PRAGMA table_info(earnapp_account_snapshots)")).fetchall()
            }
            if "payment_json" not in snapshot_cols:
                await db.execute(
                    "ALTER TABLE earnapp_account_snapshots ADD COLUMN payment_json TEXT NOT NULL DEFAULT '{}'"
                )
                applied.append("earnapp_account_snapshots.payment_json")
        await _migrate_legacy_earnapp_accounts(db, applied)
        await db.executescript(_EARNAPP_ACCOUNTS_SCHEMA)
        await _quarantine_synthetic_legacy_accounts(db, applied)
        # Recovery releases the live assignment but keeps its prior owner so
        # another worker still needs a one-time replacement ticket.
        cursor = await db.execute("PRAGMA table_info(earnapp_logical_nodes)")
        earnapp_node_cols = {row["name"] for row in await cursor.fetchall()}
        if "last_worker_id" not in earnapp_node_cols:
            applied.append("earnapp_logical_nodes.last_worker_id")
            await db.execute("ALTER TABLE earnapp_logical_nodes ADD COLUMN last_worker_id INTEGER")
        # Migrate workers table: add client_id (UNIQUE) and apps columns
        cursor = await db.execute("PRAGMA table_info(workers)")
        cols = {row["name"] for row in await cursor.fetchall()}
        if "client_id" not in cols:
            applied.append("workers.client_id")
            # Rebuild table: UNIQUE moves from name → client_id, name becomes display-only.
            # Existing rows get client_id = name for backward compat.
            has_apps = "apps" in cols
            apps_select = "apps" if has_apps else "'[]'"
            _logger.info("Migrating workers table: adding client_id column")
            await db.executescript(f"""
                -- executescript COMMITS PER STATEMENT, so an interruption
                -- between CREATE and RENAME leaves workers_new behind
                -- permanently. The guard above ("client_id" not in cols) is
                -- still true on the next boot, so the rebuild re-runs, the
                -- CREATE fails with "table already exists", init_db raises, and
                -- the app never starts again. Reproduced: a leftover
                -- workers_new plus a pre-client_id workers table bricks startup
                -- on every subsequent restart.
                --
                -- Dropping any leftover first makes the rebuild re-entrant. The
                -- leftover is always disposable: it is only ever a partial copy
                -- of workers, which is still intact until the DROP below.
                DROP TABLE IF EXISTS workers_new;
                CREATE TABLE workers_new (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id       TEXT    NOT NULL UNIQUE,
                    name            TEXT    NOT NULL DEFAULT '',
                    url             TEXT    NOT NULL DEFAULT '',
                    status          TEXT    NOT NULL DEFAULT 'online',
                    containers      TEXT    NOT NULL DEFAULT '[]',
                    apps            TEXT    NOT NULL DEFAULT '[]',
                    system_info     TEXT    NOT NULL DEFAULT '{{}}',
                    last_heartbeat  TEXT,
                    registered_at   TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO workers_new
                    (id, client_id, name, url, status, containers, apps, system_info, last_heartbeat, registered_at)
                SELECT id, name, name, url, status, containers, {apps_select}, system_info, last_heartbeat, registered_at
                FROM workers;
                DROP TABLE workers;
                ALTER TABLE workers_new RENAME TO workers;
                CREATE INDEX IF NOT EXISTS idx_workers_status ON workers (status);
            """)
        elif "apps" not in cols:
            applied.append("workers.apps")
            await db.execute("ALTER TABLE workers ADD COLUMN apps TEXT NOT NULL DEFAULT '[]'")

        # Migrate workers table: add api_key_enc for per-worker fleet keys.
        # (cols is the pre-rebuild snapshot; on a fresh DB the column comes from
        # _SCHEMA so it is already present here and the ALTER is skipped.)
        if "api_key_enc" not in cols:
            applied.append("workers.api_key_enc")
            await db.execute("ALTER TABLE workers ADD COLUMN api_key_enc TEXT")
        if "key_confirmed" not in cols:
            applied.append("workers.key_confirmed")
            await db.execute("ALTER TABLE workers ADD COLUMN key_confirmed INTEGER NOT NULL DEFAULT 0")
        if "key_issued_at" not in cols:
            applied.append("workers.key_issued_at")
            # When the per-worker key was minted, so the window in which the
            # SHARED key still works for that worker can be bounded.
            await db.execute("ALTER TABLE workers ADD COLUMN key_issued_at TEXT")

            # Backfilled to NOW, not to NULL and not to the distant past.
            # Every already-enrolled-but-unconfirmed worker would otherwise be
            # instantly past its window the moment this upgrade lands, and a
            # patch release would take a working fleet offline with no warning.
            # Absent is not expired: these get a full fresh window, and only a
            # worker that still cannot confirm within it is cut off.
            await db.execute(
                "UPDATE workers SET key_issued_at = datetime('now') "
                "WHERE api_key_enc IS NOT NULL AND api_key_enc != '' AND key_confirmed = 0"
            )

        # Migrate earnings table: add fx_rate_usd so a non-USD balance's value at the
        # time it was recorded stays reconstructable (rates are only cached live).
        cursor = await db.execute("PRAGMA table_info(earnings)")
        earnings_cols = {row["name"] for row in await cursor.fetchall()}
        if "fx_rate_usd" not in earnings_cols:
            applied.append("earnings.fx_rate_usd")
            await db.execute("ALTER TABLE earnings ADD COLUMN fx_rate_usd REAL")
        # Add `source`: WHO took the reading. Existing rows were all taken by
        # this server's own collectors, so 'server' is the truthful backfill
        # rather than a placeholder -- there was no other sampler before this.
        if "source" not in earnings_cols:
            applied.append("earnings.source")
            await db.execute("ALTER TABLE earnings ADD COLUMN source TEXT NOT NULL DEFAULT 'server'")
        # Unconditional, and only AFTER the column is guaranteed to exist. This
        # is the ONLY place the index is created, so a fresh install and an
        # upgraded volume take the same path -- declaring it in _SCHEMA instead
        # broke every upgrade, because `CREATE TABLE IF NOT EXISTS` is a no-op
        # there and the index then named a column the ALTER had not yet added.
        #
        # Makes (platform, source, date) the idempotency key, so re-pairing or a
        # retried import overwrites a day rather than appending a second reading
        # for it -- which would difference against itself and read as zero.
        # The LEGACY index must go FIRST. On an upgraded volume
        # idx_earnings_platform_date survives, and it still forbids two sources
        # for one (platform, date) -- so the new index would be created and the
        # old one would quietly keep rejecting exactly the writes this change
        # exists to allow. Creating the replacement is not enough; the old
        # constraint has to be removed. (CodeRabbit, PR #255.)
        await db.execute("DROP INDEX IF EXISTS idx_earnings_platform_date")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_earnings_platform_source_date ON earnings (platform, source, date)"
        )

        # Migrate deployments table: add spec_encrypted so an existing install starts
        # remembering what it deployed. Rows written before this stay empty and fall
        # back to the catalog, exactly as they do today.
        # Migrate alerts table: add the failure-kind category (CashPilot-5bdm).
        cursor = await db.execute("PRAGMA table_info(alerts)")
        alerts_cols = {row["name"] for row in await cursor.fetchall()}
        if "category" not in alerts_cols:
            applied.append("alerts.category")
            # NULL backfill is the truthful one: nothing recorded before this
            # column existed ever knew its failure kind (CashPilot-5bdm).
            await db.execute("ALTER TABLE alerts ADD COLUMN category TEXT")

        cursor = await db.execute("PRAGMA table_info(deployments)")
        deployment_cols = {row["name"] for row in await cursor.fetchall()}
        if "spec_encrypted" not in deployment_cols:
            applied.append("deployments.spec_encrypted")
            await db.execute("ALTER TABLE deployments ADD COLUMN spec_encrypted TEXT NOT NULL DEFAULT ''")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS proxy_provider_masks (
                proxy_id      INTEGER NOT NULL,
                provider_slug TEXT    NOT NULL,
                reason        TEXT    NOT NULL DEFAULT '',
                masked_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY(proxy_id, provider_slug),
                FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_proxy_provider_masks_provider ON proxy_provider_masks(provider_slug, proxy_id)"
        )
        cursor = await db.execute("PRAGMA table_info(proxy_endpoints)")
        proxy_endpoint_cols = {row["name"] for row in await cursor.fetchall()}
        proxy_endpoint_migrations = {
            "country_code": "TEXT NOT NULL DEFAULT ''",
            "country_name": "TEXT NOT NULL DEFAULT ''",
            "geo_source": "TEXT NOT NULL DEFAULT ''",
            "geo_confidence": "TEXT NOT NULL DEFAULT 'unknown'",
            "geo_checked_at": "TEXT",
            "ip_type": "TEXT NOT NULL DEFAULT 'unknown'",
            "ip_type_source": "TEXT NOT NULL DEFAULT ''",
            "ip_type_confidence": "TEXT NOT NULL DEFAULT 'unknown'",
            "ip_type_checked_at": "TEXT",
            "duplicate_egress": "INTEGER NOT NULL DEFAULT 0",
            "canonical_proxy_id": "INTEGER REFERENCES proxy_endpoints(id) ON DELETE SET NULL",
            "duplicate_reason": "TEXT NOT NULL DEFAULT ''",
        }
        for column, declaration in proxy_endpoint_migrations.items():
            if column not in proxy_endpoint_cols:
                applied.append(f"proxy_endpoints.{column}")
                await db.execute(f"ALTER TABLE proxy_endpoints ADD COLUMN {column} {declaration}")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS proxy_probe_results (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_id       INTEGER NOT NULL,
                profile        TEXT    NOT NULL,
                probe_status   TEXT    NOT NULL DEFAULT 'unknown',
                verdict        TEXT    NOT NULL DEFAULT '',
                eligibility    TEXT    NOT NULL DEFAULT 'unknown',
                reason         TEXT    NOT NULL DEFAULT '',
                exit_ip        TEXT    NOT NULL DEFAULT '',
                latency_ms     INTEGER,
                probe_version  TEXT    NOT NULL DEFAULT '',
                evidence_json  TEXT    NOT NULL DEFAULT '{}',
                checked_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_proxy_probe_results_latest
                ON proxy_probe_results(proxy_id, profile, id DESC);
            CREATE INDEX IF NOT EXISTS idx_proxy_endpoints_exit_ip
                ON proxy_endpoints(exit_ip);

            CREATE TABLE IF NOT EXISTS proxy_import_batches (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id    INTEGER,
                source_name    TEXT    NOT NULL DEFAULT 'manual',
                raw_input_enc  TEXT    NOT NULL DEFAULT '',
                parsed_count   INTEGER NOT NULL DEFAULT 0,
                imported_count INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(provider_id) REFERENCES proxy_providers(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS proxy_import_rows (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id       INTEGER NOT NULL,
                row_number     INTEGER NOT NULL,
                proxy_id       INTEGER,
                raw_line_enc   TEXT    NOT NULL DEFAULT '',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(batch_id) REFERENCES proxy_import_batches(id) ON DELETE CASCADE,
                FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL,
                UNIQUE(batch_id, row_number)
            );
            CREATE INDEX IF NOT EXISTS idx_proxy_import_rows_proxy
                ON proxy_import_rows(proxy_id, batch_id);

            CREATE TABLE IF NOT EXISTS provider_proxy_leases (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_slug  TEXT    NOT NULL,
                worker_id      INTEGER NOT NULL,
                instance_id    TEXT    NOT NULL,
                proxy_id       INTEGER NOT NULL,
                exit_ip        TEXT    NOT NULL DEFAULT '',
                leased_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                released_at    TEXT,
                release_reason TEXT    NOT NULL DEFAULT '',
                FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE,
                FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_proxy_leases_active_instance
                ON provider_proxy_leases(provider_slug, worker_id, instance_id)
                WHERE released_at IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_proxy_leases_active_proxy
                ON provider_proxy_leases(proxy_id)
                WHERE released_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_provider_proxy_leases_active_exit
                ON provider_proxy_leases(exit_ip)
                WHERE released_at IS NULL;
            """
        )
        cursor = await db.execute("PRAGMA table_info(proxy_assignments)")
        proxy_assignment_cols = {row["name"] for row in await cursor.fetchall()}
        if "assignment_version" not in proxy_assignment_cols:
            applied.append("proxy_assignments.assignment_version")
            await db.execute("ALTER TABLE proxy_assignments ADD COLUMN assignment_version INTEGER NOT NULL DEFAULT 0")
        # Migrate config table: add updated_at so credential age is knowable.
        # Existing rows are left NULL — see the note on the back-fill below.
        # (This comment used to say they receive the migration time, which is
        # exactly the behaviour that was removed; leaving it would have invited
        # someone to restore the back-fill.)
        cursor = await db.execute("PRAGMA table_info(config)")
        config_cols = {row["name"] for row in await cursor.fetchall()}
        if "updated_at" not in config_cols:
            applied.append("config.updated_at")
            await db.execute("ALTER TABLE config ADD COLUMN updated_at TEXT")
            # Deliberately NOT back-filled with datetime('now').
            #
            # Doing so stamped every credential on an upgraded volume with the
            # moment of the upgrade, so the credential-health page reported all
            # of them "fresh" — including short-lived session cookies that had
            # in fact expired days earlier. An unknown age was rendered as the
            # most favourable known age.
            #
            # NULL is the honest value, and both consumers already handle it:
            # get_config_updated_at filters WHERE updated_at IS NOT NULL, and
            # the health endpoint skips unstamped keys.

        # Migrate users table: add password_changed_at for session invalidation
        cursor = await db.execute("PRAGMA table_info(users)")
        user_cols = {row["name"] for row in await cursor.fetchall()}
        if "password_changed_at" not in user_cols:
            applied.append("users.password_changed_at")
            await db.execute("ALTER TABLE users ADD COLUMN password_changed_at REAL DEFAULT 0")

        # The version the database CLAIMED before this boot. 0 on anything
        # written before this was introduced, including a fully up-to-date one --
        # so the first upgrade reports "was 0" and that is honest rather than
        # alarming.
        cursor = await db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        previous = int(row[0]) if row else 0
        if previous != SCHEMA_VERSION:
            # A literal: PRAGMA does not accept a bound parameter here. Safe
            # because the value is this module's own int constant.
            await db.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")

        if applied:
            _logger.info(
                "Schema now at version %d (was %d). Migrations applied this boot: %s",
                SCHEMA_VERSION,
                previous,
                ", ".join(applied),
            )
        else:
            _logger.info("Schema at version %d; no migration needed this boot.", SCHEMA_VERSION)

        await db.commit()

        # After the schema is settled, so the config table certainly exists.
        await _encrypt_legacy_plaintext_credentials(db)
    finally:
        await db.close()


# --- Earnings ---


async def upsert_earnings(
    platform: str,
    balance: float,
    currency: str = "USD",
    date: str | None = None,
    fx_rate_usd: float | None = None,
    source: str = "server",
) -> None:
    """Insert or update an earnings record for a platform + source + date.

    ``fx_rate_usd`` is the currency -> USD rate at collection time. It is stored
    alongside the balance because exchange rates are only cached live: without it,
    the USD value of a historical non-USD reading cannot be reconstructed later.

    ``source`` is WHO took the reading: ``"server"`` for this server's own
    collectors, or a paired client's worker id. It is part of the key, so two
    machines may report the same platform on the same day -- the normal case once
    a client pushes its history -- while one machine reporting a platform twice
    for a day still upserts. Without this parameter the schema would accept a
    source but nothing could ever write one, so a client's series could not exist.
    """
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    db = await _get_db()
    try:
        # Insert a new reading, or update the existing platform+date row only
        # when the balance changed (we always want the latest reading). The
        # WHERE guard preserves created_at when the balance is unchanged.
        await db.execute(
            """
            INSERT INTO earnings (platform, balance, currency, date, fx_rate_usd, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, source, date) DO UPDATE SET
                balance = excluded.balance,
                currency = excluded.currency,
                -- COALESCE, not a plain assignment: if the rate lookup failed this
                -- cycle (provider outage after a restart cleared the cache) the new
                -- value is NULL, and overwriting a known-good rate with it would
                -- destroy the very data this column exists to preserve.
                fx_rate_usd = COALESCE(excluded.fx_rate_usd, earnings.fx_rate_usd),
                created_at = datetime('now')
            -- The balance guard preserves created_at when nothing changed, but it also
            -- meant a row already stored with a NULL rate (written pre-upgrade, or when
            -- the rate was briefly unavailable) could never be back-filled: for a
            -- service whose balance moves once a day, every later run in that day was
            -- skipped entirely. Allow the update through in that one case.
            WHERE earnings.balance != excluded.balance
               OR earnings.fx_rate_usd IS NULL
            """,
            (platform, balance, currency, date, fx_rate_usd, source),
        )
        await db.commit()
    finally:
        await db.close()


async def upsert_earnings_many(readings: Sequence[Mapping[str, Any]]) -> int:
    """Upsert many readings in ONE transaction. Returns how many were written.

    Same statement and same conflict rules as :func:`upsert_earnings` — this is
    purely about how often the work is committed.

    WHY IT EXISTS
    -------------
    A client importing its pre-pairing history sends up to a thousand readings
    per request, and calling ``upsert_earnings`` in a loop commits once per row.
    Every commit is an fsync, and every one of them takes SQLite's write lock —
    so a single import serialised a thousand disk syncs against the server's own
    collector, and request latency tracked disk sync cost rather than row count.

    (The connection is NOT the problem, despite appearances: ``_get_db`` hands
    out a borrowed handle on a shared per-loop connection whose ``close()`` is a
    documented no-op, so the loop was never opening and closing a thousand
    connections. It was committing a thousand times.)

    ONE TRANSACTION ALSO MEANS ALL-OR-NOTHING, which is the behaviour to want
    here: a failure part-way through leaves the caller's history exactly as it
    was rather than half-applied, and the import is idempotent so retrying costs
    a round trip.
    """
    rows = [
        (
            r["platform"],
            float(r["balance"]),
            (r.get("currency") or "USD"),
            r.get("date") or datetime.now(UTC).strftime("%Y-%m-%d"),
            r.get("fx_rate_usd"),
            (r.get("source") or "server"),
        )
        for r in readings
    ]
    if not rows:
        # No statement, no commit. An empty import is a normal case, and taking
        # the write lock to do nothing would still block the collector.
        return 0

    db = await _get_db()
    try:
        try:
            await db.executemany(
                """
                INSERT INTO earnings (platform, balance, currency, date, fx_rate_usd, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, source, date) DO UPDATE SET
                    balance = excluded.balance,
                    currency = excluded.currency,
                    fx_rate_usd = COALESCE(excluded.fx_rate_usd, earnings.fx_rate_usd),
                    created_at = datetime('now')
                WHERE earnings.balance != excluded.balance
                   OR earnings.fx_rate_usd IS NULL
                """,
                rows,
            )
            await db.commit()
        except Exception:
            # ROLL BACK, do not merely propagate. The connection is SHARED and
            # outlives the request, so an abandoned transaction keeps SQLite's
            # write lock and every later write on this loop -- including this
            # server's own collector -- blocks until it times out. Measured: the
            # next write took twelve seconds before this was added.
            with contextlib.suppress(Exception):
                await db.rollback()
            raise
    finally:
        await db.close()
    return len(rows)


async def get_earnings_summary() -> list[dict[str, Any]]:
    """Return the latest balance for each platform."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            -- fx_rate_usd is selected because the dashboard total needs a
            -- fallback when no LIVE rate is cached. Without it a crypto
            -- balance whose rate lookup is merely stale gets dropped from the
            -- headline figure entirely, even though the rate it was recorded
            -- at is sitting right here in the row.
            SELECT platform, balance, currency, date, fx_rate_usd
            FROM earnings
            -- Deliberately ONE row per platform, not one per source. A
            -- provider reports a single balance for the whole account, so the
            -- newest account reading IS the current balance. Node rows are
            -- auxiliary breakdown only; letting them into this query would
            -- replace the account total with a node fragment.
            WHERE id IN (
                SELECT id FROM earnings e
                WHERE COALESCE(e.source, 'server') NOT LIKE 'node:%'
                  AND e.date = (SELECT MAX(date) FROM earnings WHERE platform = e.platform AND COALESCE(source, 'server') NOT LIKE 'node:%')
                GROUP BY e.platform
                HAVING id = MAX(e.id)
            )
            ORDER BY platform
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_earnings_history(
    period: str = "week",
) -> list[dict[str, Any]]:
    """Return earnings history filtered by period (week, month, year, all)."""
    days_map = {"week": 7, "month": 30, "year": 365}
    days = days_map.get(period)

    db = await _get_db()
    try:
        if days:
            cursor = await db.execute(
                """
                SELECT platform, balance, currency, date
                FROM earnings
                WHERE COALESCE(source, 'server') NOT LIKE 'node:%'
                  AND date >= date('now', ?)
                ORDER BY date DESC, platform
                """,
                (f"-{days} days",),
            )
        else:
            # period="all": defensively cap the result so a very long-lived DB can't
            # return an unbounded row set into a single response/chart. Most-recent
            # first; 50k rows spans years of daily per-service earnings.
            cursor = await db.execute(
                "SELECT platform, balance, currency, date FROM earnings WHERE COALESCE(source, 'server') NOT LIKE 'node:%' ORDER BY date DESC, platform LIMIT 50000"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


def _usd_rate(currency: str, raw: Any) -> float | None:
    """The USD price of one unit, or None when the reading cannot be priced.

    USD is parity BY DEFINITION — trusting a stored rate on a USD row would let
    a bad rate rewrite money the collector reported exactly. For anything else
    only a finite positive number is a price:

    * ``0`` reports the platform as having earned nothing, which is
      indistinguishable from a genuinely flat balance;
    * a negative defeats the payout clamp, which applies to the delta while the
      sign is applied after it, so the total comes out NEGATIVE;
    * ``inf``/``nan`` poison the total outright.

    Anything rejected here is treated as unpriced — excluded and reported —
    rather than believed.
    """
    if currency == "USD":
        return 1.0
    if raw is None:
        return None
    value = float(raw)
    return value if math.isfinite(value) and value > 0 else None


async def _usd_earned_per_date(
    db: Any,
    platforms: set[str] | frozenset[str] | None = None,
    excluded_platforms: set[str] | frozenset[str] | None = None,
) -> tuple[dict[str, float], int]:
    """USD earned per calendar date, summed across platforms.

    ONE implementation behind both the dashboard cards and the trend chart.
    They previously carried separate copies of the arithmetic and both filtered
    ``currency = 'USD'``, so an installation earning MYST or another token saw
    "$0.00 today", "$0.00 this month" and a flat-zero chart while its balances
    climbed — verified against a MystNodes-only fixture, which reported 0.00
    where the correct figure was 0.20.

    Same rules as :func:`get_earned_by_platform`, and deliberately so:

    * the delta is taken in the NATIVE currency and only then priced, because a
      balance is a running total and converting before subtracting puts the
      movement of the exchange rate inside the earnings figure;
    * a platform with no predecessor reading contributes nothing, rather than
      counting its whole opening balance as one day's earnings;
    * a reading that cannot be priced drops the baseline instead of anchoring
      the next delta, so an unpriced stretch is not silently counted whole.
    """
    normalized_platforms = {slug.strip().lower() for slug in platforms} if platforms is not None else None
    normalized_exclusions = (
        {slug.strip().lower() for slug in excluded_platforms} if excluded_platforms is not None else None
    )
    cursor = await db.execute(
        """
        SELECT platform, date, balance, currency, fx_rate_usd, source
        FROM earnings
        WHERE COALESCE(source, 'server') NOT LIKE 'node:%'
        ORDER BY platform, source, date
        """
    )
    per_date: dict[str, float] = {}
    # Keyed by (platform, SOURCE) for the same reason as get_earned_by_platform:
    # two machines sampling one provider account interleave into a series whose
    # deltas are meaningless, and every drop clamps to zero, so the total comes
    # out understated while looking plausible.
    previous: dict[tuple[str, str], tuple[str, float]] = {}
    unpriced = 0
    for row in await cursor.fetchall():
        platform = row["platform"]
        normalized_platform = str(platform or "").strip().lower()
        if normalized_platforms is not None and normalized_platform not in normalized_platforms:
            continue
        if normalized_exclusions is not None and normalized_platform in normalized_exclusions:
            continue
        # Absent source means a row written before the column existed; those
        # were all this server's own, so they join the 'server' series rather
        # than forming a phantom one.
        series = (platform, (row["source"] or "server"))
        currency = (row["currency"] or "USD").upper()
        rate = _usd_rate(currency, row["fx_rate_usd"])
        if rate is None:
            previous.pop(series, None)
            unpriced += 1
            continue
        balance = float(row["balance"] or 0.0)
        before = previous.get(series)
        if before is not None and before[0] == currency:
            # Clamped per platform BEFORE summing: a payout drops one
            # platform's balance, and an unclamped drop would cancel real
            # earnings on another platform in the same day's total.
            gained = max(0.0, balance - before[1]) * rate
            per_date[row["date"]] = per_date.get(row["date"], 0.0) + gained
        previous[series] = (currency, balance)
    return per_date, unpriced


async def get_earnings_dashboard_summary(
    platforms: set[str] | frozenset[str] | None = None,
    *,
    excluded_platforms: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Return aggregated earnings stats for the dashboard."""
    db = await _get_db()
    try:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        first_of_month = datetime.now(UTC).replace(day=1).strftime("%Y-%m-%d")

        normalized_platforms = {slug.strip().lower() for slug in platforms} if platforms is not None else None
        normalized_exclusions = (
            {slug.strip().lower() for slug in excluded_platforms} if excluded_platforms is not None else None
        )

        # Total: sum of latest balance per platform (USD only for now).
        # Filter in Python so callers can exclude retired providers without
        # mutating historical rows or building a variable-length SQL clause.
        cursor = await db.execute(
            """
            SELECT e.platform, e.balance
            FROM earnings e
            INNER JOIN (
                SELECT platform, MAX(date) as max_date
                FROM earnings WHERE currency = 'USD' AND COALESCE(source, 'server') NOT LIKE 'node:%'
                GROUP BY platform
            ) latest ON e.platform = latest.platform AND e.date = latest.max_date
            WHERE e.currency = 'USD'
              AND COALESCE(e.source, 'server') NOT LIKE 'node:%'
            """
        )
        total = sum(
            float(row["balance"] or 0.0)
            for row in await cursor.fetchall()
            if (normalized_platforms is None or str(row["platform"] or "").strip().lower() in normalized_platforms)
            and (
                normalized_exclusions is None or str(row["platform"] or "").strip().lower() not in normalized_exclusions
            )
        )

        # Today, this month and yesterday all come from one priced series.
        # They used to be three separate SQL aggregates that each filtered
        # currency = 'USD', so every non-USD platform was missing from all
        # three at once and the cards read $0.00 while balances climbed.
        per_date, unpriced = await _usd_earned_per_date(db, platforms, excluded_platforms)
        if unpriced:
            _logger.warning(
                "%d earnings reading(s) have no usable USD rate and are left out of the "
                "dashboard totals, which are therefore understated.",
                unpriced,
            )

        today_earned = per_date.get(today, 0.0)
        # The month is the sum of clamped daily deltas rather than one delta
        # from the first of the month, so a mid-month payout counts as zero on
        # its own day instead of erasing the whole month's earnings.
        month_earned = sum(earned for day, earned in per_date.items() if day >= first_of_month)

        yesterday_earned = per_date.get(yesterday, 0.0)

        today_change = 0.0
        if yesterday_earned > 0:
            today_change = ((today_earned - yesterday_earned) / yesterday_earned) * 100

        return {
            "total": round(total, 2),
            "today": round(today_earned, 2),
            "month": round(month_earned, 2),
            "today_change": round(today_change, 1),
            # None, not 0.0. This was a literal that nothing computed, and the
            # dashboard rendered it as "+0.0%" in the positive style forever —
            # a month-over-month figure that had never been measured, presented
            # with the same confidence as one that had.
            "month_change": None,
        }
    finally:
        await db.close()


async def get_earnings_per_service() -> list[dict[str, Any]]:
    """Return per-platform earnings breakdown: latest balance, previous balance, trend."""
    db = await _get_db()
    try:
        # Latest balance per platform
        cursor = await db.execute(
            """
            SELECT
                e.platform,
                e.balance,
                e.currency,
                e.date,
                COALESCE(prev.balance, 0) as prev_balance
            FROM earnings e
            INNER JOIN (
                SELECT platform, MAX(date) as max_date
                FROM earnings
                WHERE COALESCE(source, 'server') NOT LIKE 'node:%'
                GROUP BY platform
            ) latest ON e.platform = latest.platform AND e.date = latest.max_date
            LEFT JOIN (
                SELECT e2.platform, e2.balance
                FROM earnings e2
                INNER JOIN (
                    SELECT platform, MAX(date) as max_date
                    FROM earnings
                    WHERE COALESCE(source, 'server') NOT LIKE 'node:%'
                      AND date < (SELECT MAX(date) FROM earnings e3 WHERE e3.platform = earnings.platform AND COALESCE(e3.source, 'server') NOT LIKE 'node:%')
                    GROUP BY platform
                ) prev_latest ON e2.platform = prev_latest.platform AND e2.date = prev_latest.max_date
                WHERE COALESCE(e2.source, 'server') NOT LIKE 'node:%'
            ) prev ON e.platform = prev.platform
            ORDER BY e.balance DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_daily_earnings(
    days: int = 7,
    platforms: set[str] | frozenset[str] | None = None,
    *,
    excluded_platforms: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Return daily aggregated earnings for charting (delta per day)."""
    db = await _get_db()
    try:
        # Shares the priced series with the dashboard cards, so the chart and
        # the "Today" card can no longer disagree. The previous version built
        # its own per-date balance map filtered to currency = 'USD', which drew
        # a flat-zero line for a fleet earning MYST or another token.
        #
        # It also treated a platform's FIRST-EVER reading as a delta against
        # zero, so a newly added service drew a spike the size of its whole
        # opening balance. The shared helper requires a predecessor.
        per_date, unpriced = await _usd_earned_per_date(db, platforms, excluded_platforms)
        if unpriced:
            _logger.warning(
                "%d earnings reading(s) have no usable USD rate and are left out of the "
                "daily chart, which is therefore understated.",
                unpriced,
            )

        now = datetime.now(UTC)
        result = []
        for i in range(days - 1, -1, -1):
            d = now - timedelta(days=i)
            result.append(
                {
                    "date": d.strftime("%b %d"),
                    "amount": round(per_date.get(d.strftime("%Y-%m-%d"), 0.0), 2),
                }
            )

        return result
    finally:
        await db.close()


# --- Config ---


async def get_config(key: str | None = None) -> dict[str, str] | str | None:
    """Get a single config value (if key given) or all config as a dict.

    Secret values are decrypted transparently.
    """
    db = await _get_db()
    try:
        if key:
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            if not row:
                return None
            val = row["value"]
            return decrypt_value(val) if _is_secret_key(key) else val
        cursor = await db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        return {r["key"]: (decrypt_value(r["value"]) if _is_secret_key(r["key"]) else r["value"]) for r in rows}
    finally:
        await db.close()


async def get_config_masked() -> dict[str, Any]:
    """Return non-secret config values plus a {secret_key: is_set} map.

    Secret values are NEVER decrypted or returned — only their presence is
    reported under the ``_secrets`` key. This is the read path for the UI so
    stored credentials never cross the wire in plaintext.
    """
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        values: dict[str, Any] = {}
        secrets_set: dict[str, bool] = {}
        for r in rows:
            if _is_secret_key(r["key"]):
                secrets_set[r["key"]] = bool(r["value"])
            else:
                values[r["key"]] = r["value"]
        values["_secrets"] = secrets_set
        return values
    finally:
        await db.close()


async def set_config(key: str, value: str) -> None:
    """Upsert a config key-value pair. Secrets are encrypted at rest."""
    stored = encrypt_value(value) if _is_secret_key(key) else value
    db = await _get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, stored),
        )
        await db.commit()
    finally:
        await db.close()


async def set_config_bulk(data: dict[str, str]) -> None:
    """Upsert multiple config entries at once. Secrets are encrypted at rest."""
    pairs = [(k, encrypt_value(v) if _is_secret_key(k) else v) for k, v in data.items()]
    db = await _get_db()
    try:
        await db.executemany(
            "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            pairs,
        )
        await db.commit()
    finally:
        await db.close()


async def get_config_updated_at() -> dict[str, str]:
    """Return {config_key: ISO timestamp of last write}.

    Values are never returned here - only when each key was last set - so this
    is safe to drive a UI that shows credential age without touching secrets.
    """
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT key, updated_at FROM config WHERE updated_at IS NOT NULL")
        return {row["key"]: row["updated_at"] for row in await cursor.fetchall()}
    finally:
        await db.close()


async def delete_config_keys(keys: list[str]) -> None:
    """Delete one or more config entries by key."""
    if not keys:
        return
    db = await _get_db()
    try:
        placeholders = ",".join("?" for _ in keys)
        await db.execute(f"DELETE FROM config WHERE key IN ({placeholders})", keys)
        await db.commit()
    finally:
        await db.close()


# --- EarnApp accounts and logical nodes ---


async def upsert_earnapp_account(
    *,
    profile_key: str,
    account_name: str,
    email: str,
    auth_method: str,
    credentials: Mapping[str, Any],
    credential_keys: Sequence[str],
    token_expires_at: str | None,
    cookie_expires_at: str | None,
) -> int:
    """Insert or refresh one profile-bound EarnApp account."""
    def normalized_email(value: Any) -> str:
        return str(value or "").strip().rstrip(",").strip().lower()

    profile = str(profile_key or "").strip()
    name = str(account_name or "").strip()
    method = str(auth_method or "").strip().lower()
    if not profile or not name:
        raise ValueError("profile_key and account_name are required")
    if method not in {"google", "apple"}:
        raise ValueError("auth_method must be Google or Apple")

    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.executescript(_EARNAPP_ACCOUNTS_SCHEMA)
            await db.execute("BEGIN IMMEDIATE")
            existing = await (
                await db.execute(
                    "SELECT id, profile_key, account_name, auth_method, state FROM earnapp_accounts WHERE profile_key = ?",
                    (profile,),
                )
            ).fetchone()
            duplicate_to_lock: int | None = None
            if existing and normalized_email(email):
                same_email = await (
                    await db.execute(
                        """
                        SELECT a.id, a.profile_key, a.account_name, a.auth_method, a.state,
                               COUNT(n.logical_node_id) AS assigned_nodes
                        FROM earnapp_accounts a
                        LEFT JOIN earnapp_logical_nodes n
                          ON n.account_id = a.id AND n.state != 'RETIRED'
                        WHERE lower(trim(rtrim(a.email, ','))) = ?
                          AND a.state != 'DELETED'
                        GROUP BY a.id
                        ORDER BY assigned_nodes DESC, a.id ASC
                        """,
                        (normalized_email(email),),
                    )
                ).fetchall()
                populated = [row for row in same_email if int(row["assigned_nodes"] or 0) > 0]
                current_has_nodes = any(int(row["id"]) == int(existing["id"]) and int(row["assigned_nodes"] or 0) > 0 for row in same_email)
                if len(populated) > 1:
                    raise ValueError("EarnApp email is bound to multiple populated accounts; manual duplicate review is required")
                if populated and not current_has_nodes and int(populated[0]["id"]) != int(existing["id"]):
                    duplicate_to_lock = int(existing["id"])
                    existing = populated[0]
                    profile = str(existing["profile_key"] or "")
            if not existing and normalized_email(email):
                email_matches = await (
                    await db.execute(
                        """
                        SELECT a.id, a.profile_key, a.account_name, a.auth_method, a.state,
                               COUNT(n.logical_node_id) AS assigned_nodes
                        FROM earnapp_accounts a
                        LEFT JOIN earnapp_logical_nodes n
                          ON n.account_id = a.id AND n.state != 'RETIRED'
                        WHERE lower(trim(rtrim(a.email, ','))) = ?
                          AND a.profile_key NOT LIKE 'legacy-account-%'
                          AND a.state != 'DELETED'
                        GROUP BY a.id
                        ORDER BY assigned_nodes DESC, a.id ASC
                        """,
                        (normalized_email(email),),
                    )
                ).fetchall()
                if len(email_matches) > 1:
                    raise ValueError("EarnApp email is bound to multiple accounts; manual duplicate review is required")
                if email_matches:
                    existing = email_matches[0]
                    profile = str(existing["profile_key"] or "")
            legacy_adoption = bool(existing and str(existing["profile_key"]).startswith("legacy-account-"))
            if not existing:
                existing = await (
                    await db.execute(
                        """
                        SELECT id, profile_key, account_name, auth_method, state
                        FROM earnapp_accounts
                        WHERE profile_key LIKE 'legacy-account-%'
                          AND lower(trim(account_name)) = lower(trim(?))
                          AND state != 'DELETED'
                        ORDER BY id
                        LIMIT 1
                        """,
                        (name,),
                    )
                ).fetchone()
                if existing:
                    await db.execute(
                        "UPDATE earnapp_accounts SET profile_key = ? WHERE id = ?",
                        (profile, int(existing["id"])),
                    )
                    legacy_adoption = True
            if existing and (
                str(existing["account_name"]) != name
                or (not legacy_adoption and str(existing["auth_method"]) != method)
            ):
                raise ValueError("Chrome profile is already bound to a different EarnApp account")
            if existing and str(existing["state"]) == "DELETED":
                raise ValueError("EarnApp account is deleted")
            cursor = await db.execute(
                """
                INSERT INTO earnapp_accounts
                    (profile_key, account_name, email, auth_method, credentials_enc,
                     credential_keys_json, token_expires_at, cookie_expires_at, state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', datetime('now'))
                ON CONFLICT(profile_key) DO UPDATE SET
                    account_name = excluded.account_name,
                    auth_method = excluded.auth_method,
                    email = excluded.email,
                    credentials_enc = excluded.credentials_enc,
                    credential_keys_json = excluded.credential_keys_json,
                    token_expires_at = excluded.token_expires_at,
                    cookie_expires_at = excluded.cookie_expires_at,
                    state = CASE WHEN earnapp_accounts.state = 'ACCOUNT_LOCKED' THEN 'ACCOUNT_LOCKED' ELSE 'ACTIVE' END,
                    updated_at = datetime('now')
                RETURNING id
                """,
                (
                    profile,
                    name,
                    str(email or "").strip(),
                    method,
                    encrypt_value(json.dumps(dict(credentials), sort_keys=True, separators=(",", ":"))),
                    json.dumps(sorted({str(key) for key in credential_keys if str(key)})),
                    token_expires_at,
                    cookie_expires_at,
                ),
            )
            row = await cursor.fetchone()
            if duplicate_to_lock is not None:
                await db.execute(
                    "UPDATE earnapp_accounts SET state = 'ACCOUNT_LOCKED', updated_at = datetime('now') WHERE id = ?",
                    (duplicate_to_lock,),
                )
            await db.commit()
            return int(row["id"])
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def list_earnapp_accounts(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        await db.executescript(_EARNAPP_ACCOUNTS_SCHEMA)
        where = "" if include_deleted else "WHERE a.state != 'DELETED'"
        cursor = await db.execute(
            f"""
            SELECT a.id, a.profile_key, a.account_name, a.email, a.auth_method, a.state,
                   a.credential_keys_json, a.token_expires_at, a.cookie_expires_at,
                   a.created_at, a.updated_at,
                   COUNT(n.logical_node_id) AS assigned_nodes
            FROM earnapp_accounts a
            LEFT JOIN earnapp_logical_nodes n
              ON n.account_id = a.id AND n.state != 'RETIRED'
            {where}
            GROUP BY a.id
            ORDER BY a.id
            """
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def get_earnapp_account_credentials(account_id: int) -> dict[str, Any] | None:
    """Return decrypted credentials to internal callers only."""
    db = await _get_db()
    try:
        await db.executescript(_EARNAPP_ACCOUNTS_SCHEMA)
        row = await (
            await db.execute(
                """
                SELECT id, profile_key, account_name, email, auth_method, state,
                       credentials_enc, token_expires_at, cookie_expires_at
                FROM earnapp_accounts
                WHERE id = ? AND state != 'DELETED'
                """,
                (int(account_id),),
            )
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        encrypted = str(data.pop("credentials_enc") or "")
        try:
            credentials = json.loads(decrypt_value(encrypted)) if encrypted else {}
        except (TypeError, ValueError):
            credentials = {}
        data["credentials"] = credentials if isinstance(credentials, dict) else {}
        return data
    finally:
        await db.close()


async def assign_earnapp_account(logical_node_id: str, *, platform: str = "") -> dict[str, Any]:
    """Bind a stable logical node to the least-assigned active account."""
    node_id = str(logical_node_id or "").strip()
    if not node_id:
        raise ValueError("logical_node_id required")
    if earnapp_policy.is_protected_logical_node(node_id):
        raise ValueError("protected EarnApp node is inspection-only")
    requested_platform = str(platform or "").strip().lower()
    if requested_platform not in {"", "unknown", "macos", "ios", "ubuntu"}:
        raise ValueError("invalid EarnApp platform")
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.executescript(_EARNAPP_ACCOUNTS_SCHEMA)
            await db.execute("BEGIN IMMEDIATE")
            existing = await (
                await db.execute(
                    """
                        SELECT a.*, n.platform AS logical_platform
                    FROM earnapp_logical_nodes n
                    JOIN earnapp_accounts a ON a.id = n.account_id
                    WHERE n.logical_node_id = ? AND n.state != 'RETIRED' AND a.state != 'DELETED'
                    """,
                    (node_id,),
                )
            ).fetchone()
            if existing:
                existing_platform = str(existing["logical_platform"] or "unknown").strip().lower()
                if requested_platform and requested_platform != "unknown":
                    if existing_platform not in {"unknown", requested_platform}:
                        raise ValueError("EarnApp logical node platform is immutable")
                    if existing_platform == "unknown":
                        await db.execute(
                            "UPDATE earnapp_logical_nodes SET platform = ?, updated_at = datetime('now') "
                            "WHERE logical_node_id = ?",
                            (requested_platform, node_id),
                        )
                await db.commit()
                refreshed = await (
                    await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
                ).fetchone()
                # Preserve the established API shape (account row) while
                # exposing the node's immutable platform to newer callers.
                result = dict(existing)
                if refreshed:
                    result["platform"] = str(refreshed["platform"] or "unknown")
                return result

            account = await (
                await db.execute(
                    """
                    SELECT a.*, COUNT(n.logical_node_id) AS assigned_nodes
                    FROM earnapp_accounts a
                    LEFT JOIN earnapp_logical_nodes n
                      ON n.account_id = a.id AND n.state != 'RETIRED'
                    WHERE a.state = 'ACTIVE'
                    GROUP BY a.id
                    ORDER BY assigned_nodes ASC, a.id ASC
                    LIMIT 1
                    """
                )
            ).fetchone()
            if not account:
                raise ValueError("no active EarnApp account available")
            await db.execute(
                """
                INSERT INTO earnapp_logical_nodes (logical_node_id, account_id, platform, state)
                VALUES (?, ?, ?, 'PLANNED')
                """,
                (node_id, int(account["id"]), requested_platform or "unknown"),
            )
            await db.commit()
            result = dict(account)
            result["platform"] = requested_platform or "unknown"
            return result
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def set_earnapp_logical_node_state(logical_node_id: str, state: str) -> bool:
    allowed = {"PLANNED", "ACTIVE", "RECOVERY_HOLD", "RECOVERABLE", "RETIRED"}
    normalized = str(state or "").strip().upper()
    if normalized not in allowed:
        raise ValueError("invalid EarnApp logical-node state")
    if earnapp_policy.is_protected_runtime_reference(logical_node_id):
        return False
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            UPDATE earnapp_logical_nodes
            SET state = ?, updated_at = datetime('now')
            WHERE logical_node_id = ?
            """,
            (normalized, str(logical_node_id or "").strip()),
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def save_earnapp_identity_profile(
    logical_node_id: str,
    *,
    platform: str,
    asset_kind: str,
    device_id: str,
    value: str,
) -> None:
    """Persist one encrypted/opaque identity profile per logical node."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_runtime_reference(node_id):
        raise ValueError("protected EarnApp node is inspection-only")
    selected = str(platform or "").strip().lower()
    kind = str(asset_kind or "").strip().lower()
    if (
        not node_id
        or selected not in {"macos", "ios", "ubuntu"}
        or kind not in {"mac_identity_profile", "ios_identity_profile", "ubuntu_identity_profile"}
        or not str(device_id or "").strip()
        or not str(value or "")
    ):
        raise ValueError("EarnApp identity profile is incomplete")
    payload = json.dumps(
        {"platform": selected, "asset_kind": kind, "device_id": str(device_id), "value": str(value)},
        sort_keys=True,
        separators=(",", ":"),
    )
    await set_config(f"runtime_asset::earnapp::{kind}::{node_id}::secret", payload)


async def get_earnapp_identity_profile(logical_node_id: str) -> dict[str, str] | None:
    node_id = str(logical_node_id or "").strip()
    if not node_id:
        return None
    db = await _get_db()
    try:
        rows = await (
            await db.execute(
                "SELECT key, value FROM config WHERE key LIKE ? ORDER BY key",
                (f"runtime_asset::earnapp::%::{node_id}::secret",),
            )
        ).fetchall()
    finally:
        await db.close()
    profiles: list[dict[str, str]] = []
    for row in rows:
        raw = (
            decrypt_value(str(row["value"] or "")) if _is_secret_key(str(row["key"] or "")) else str(row["value"] or "")
        )
        try:
            item = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(item, dict) and item.get("device_id") and item.get("value"):
            profiles.append({str(key): str(value) for key, value in item.items()})
    if len(profiles) > 1:
        raise RuntimeError("EarnApp logical node has multiple identity profiles")
    return profiles[0] if profiles else None


async def save_earnapp_mac_profile(logical_node_id: str, *, device_id: str, value: str) -> None:
    """Backward-compatible wrapper for the established Mac profile key."""
    await save_earnapp_identity_profile(
        logical_node_id,
        platform="macos",
        asset_kind="mac_identity_profile",
        device_id=device_id,
        value=value,
    )


async def get_earnapp_mac_profile(logical_node_id: str) -> dict[str, str] | None:
    profile = await get_earnapp_identity_profile(logical_node_id)
    if not profile or profile.get("platform") not in {None, "", "macos"}:
        return None
    device_id = str(profile.get("device_id") or "")
    ciphertext = str(profile.get("value") or "")
    return {"device_id": device_id, "value": ciphertext} if device_id and ciphertext else None


async def set_earnapp_account_state(account_id: int, state: str) -> bool:
    allowed = {"ACTIVE", "EXPIRED", "AUTH_FAILED", "ACCOUNT_LOCKED", "DISABLED"}
    normalized = str(state or "").strip().upper()
    if normalized not in allowed:
        raise ValueError("invalid EarnApp account state")
    db = await _get_db()
    try:
        cursor = await db.execute(
            "UPDATE earnapp_accounts SET state = ?, updated_at = datetime('now') WHERE id = ? AND state != 'DELETED'",
            (normalized, int(account_id)),
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def list_earnapp_runtime_bindings(account_id: int) -> list[dict[str, Any]]:
    """List local EarnApp runtimes that must be removed before account deletion.

    The provider-instance row is the server's durable record of a worker-side
    runtime.  An active/recovery node without that row is included as well: a
    partially completed deploy is still unsafe to treat as already removed.
    No encrypted spec or credential is returned from this helper.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT n.logical_node_id, n.account_id, n.platform, n.state AS node_state,
                   n.generation, n.device_id, n.assigned_worker_id, n.last_worker_id,
                   n.current_proxy_id,
                   pi.instance_id, pi.slug, pi.worker_id, pi.mode, pi.container_id,
                   pi.proxy_id, pi.status AS runtime_status, pi.spec_encrypted
            FROM earnapp_logical_nodes n
            LEFT JOIN provider_instances pi
              ON pi.slug = 'earnapp' AND pi.instance_id = n.logical_node_id
            WHERE n.account_id = ?
              AND (
                  pi.instance_id IS NOT NULL
                  OR (
                      n.state IN ('ACTIVE', 'RECOVERY_HOLD', 'RECOVERABLE')
                      OR n.assigned_worker_id IS NOT NULL
                      OR n.last_worker_id IS NOT NULL
                      OR n.current_proxy_id IS NOT NULL
                      OR trim(coalesce(n.device_id, '')) != ''
                  )
              )
            ORDER BY n.logical_node_id
            """,
            (int(account_id),),
        )
        bindings: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            data = dict(row)
            logical_node_id = str(data.get("logical_node_id") or "")
            instance_id = str(data.get("instance_id") or logical_node_id)
            platform = str(data.get("platform") or "unknown").strip().lower()
            worker_id = data.get("worker_id")
            if worker_id is None:
                worker_id = data.get("assigned_worker_id")
            if worker_id is None:
                worker_id = data.get("last_worker_id")
            # EarnApp is Docker-only. Legacy LXD rows remain readable but are
            # never selected as the mutation/deployment backend.
            runtime_backend = ""
            if instance_id and data.get("instance_id"):
                persisted_spec = None
                blob = str(data.get("spec_encrypted") or "")
                if blob:
                    try:
                        raw_spec = decrypt_value(blob)
                        parsed_spec = json.loads(raw_spec) if raw_spec else None
                        persisted_spec = parsed_spec if isinstance(parsed_spec, dict) else None
                    except (ValueError, TypeError, InvalidToken, json.JSONDecodeError):
                        persisted_spec = None
                candidate_backend = str((persisted_spec or {}).get("runtime_backend") or "").strip().lower()
                if candidate_backend == "docker":
                    runtime_backend = candidate_backend
            if not runtime_backend:
                runtime_backend = "docker" if platform in {"macos", "ios", "ubuntu"} else ""
            data.update(
                {
                    "logical_node_id": logical_node_id,
                    "instance_id": instance_id,
                    "worker_id": int(worker_id) if worker_id is not None else None,
                    "platform": platform,
                    "runtime_backend": runtime_backend,
                    "generation": int(data.get("generation") or 0),
                    "device_id": str(data.get("device_id") or ""),
                }
            )
            bindings.append(data)
        return bindings
    finally:
        await db.close()


async def delete_locked_earnapp_account(account_id: int, *, runtime_instance_ids: Sequence[str] | None = None) -> str:
    """Delete local secrets only after locked-account runtimes are gone.

    ``runtime_instance_ids`` is supplied only after the caller has received an
    authoritative removal ACK for every local runtime.  The final transaction
    deletes those bookkeeping rows and re-checks that no account-bound runtime
    remains, closing the race where a deploy is recorded while cleanup is in
    progress.  A missing argument deliberately fails closed when a runtime row
    still exists.
    """
    if any(earnapp_policy.is_protected_runtime_reference(value) for value in (runtime_instance_ids or ())):
        return "PROTECTED_RUNTIME"
    if await _protected_earnapp_account_reference(int(account_id)):
        return "PROTECTED_RUNTIME"
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute("SELECT state FROM earnapp_accounts WHERE id = ?", (int(account_id),))
            ).fetchone()
            if not row:
                await db.rollback()
                return "NOT_FOUND"
            if str(row["state"]) != "ACCOUNT_LOCKED":
                await db.rollback()
                return "NOT_LOCKED"

            cleaned_ids: list[str] = []
            if runtime_instance_ids is not None:
                cleaned_ids = sorted(
                    {str(value or "").strip() for value in runtime_instance_ids if str(value or "").strip()}
                )
                if cleaned_ids:
                    placeholders = ",".join("?" for _ in cleaned_ids)
                    await db.execute(
                        f"""
                        DELETE FROM provider_instances
                        WHERE slug = 'earnapp' AND instance_id IN ({placeholders})
                          AND EXISTS (
                              SELECT 1 FROM earnapp_logical_nodes n
                              WHERE n.account_id = ? AND n.logical_node_id = provider_instances.instance_id
                          )
                        """,
                        [*cleaned_ids, int(account_id)],
                    )

            # Re-check the logical-node table in the same transaction.  A
            # worker can have a live/partially-provisioned node before its
            # provider_instances row is written, so checking that table alone
            # could release credentials and leases while a runtime remains.
            node_exclusion = ""
            node_params: list[Any] = [int(account_id)]
            if cleaned_ids:
                placeholders = ",".join("?" for _ in cleaned_ids)
                node_exclusion = f"AND n.logical_node_id NOT IN ({placeholders})"
                node_params.extend(cleaned_ids)
            remaining_runtime = await (
                await db.execute(
                    f"""
                    SELECT n.logical_node_id
                    FROM earnapp_logical_nodes n
                    LEFT JOIN provider_instances pi
                      ON pi.slug = 'earnapp' AND pi.instance_id = n.logical_node_id
                    WHERE n.account_id = ?
                      {node_exclusion}
                      AND (
                          pi.instance_id IS NOT NULL
                          OR n.state IN ('ACTIVE', 'RECOVERY_HOLD', 'RECOVERABLE')
                          OR n.assigned_worker_id IS NOT NULL
                          OR n.last_worker_id IS NOT NULL
                          OR n.current_proxy_id IS NOT NULL
                          OR trim(coalesce(n.device_id, '')) != ''
                      )
                    LIMIT 1
                    """,
                    node_params,
                )
            ).fetchone()
            if remaining_runtime:
                await db.rollback()
                return "RUNTIME_CLEANUP_REQUIRED"
            await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET state = 'RETIRED', assigned_worker_id = NULL, last_worker_id = NULL,
                    current_proxy_id = NULL, preferred_proxy_id = NULL,
                    updated_at = datetime('now')
                WHERE account_id = ? AND state != 'RETIRED'
                """,
                (int(account_id),),
            )
            await db.execute(
                """
                UPDATE provider_proxy_leases
                SET released_at = datetime('now'), release_reason = 'EARNAPP_ACCOUNT_DELETED'
                WHERE provider_slug = 'earnapp' AND released_at IS NULL
                  AND instance_id IN (
                      SELECT logical_node_id FROM earnapp_logical_nodes WHERE account_id = ?
                  )
                """,
                (int(account_id),),
            )
            await db.execute(
                """
                UPDATE earnapp_account_control_routes
                SET state = 'RELEASED', released_at = datetime('now'),
                    release_reason = 'ACCOUNT_DELETED', updated_at = datetime('now')
                WHERE account_id = ? AND state = 'ACTIVE'
                """,
                (int(account_id),),
            )
            await db.execute(
                """
                UPDATE earnapp_accounts
                SET state = 'DELETED', credentials_enc = '', credential_keys_json = '[]',
                    token_expires_at = NULL, cookie_expires_at = NULL, updated_at = datetime('now')
                WHERE id = ?
                """,
                (int(account_id),),
            )
            await db.commit()
            return "DELETED"
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


def _earnapp_proxy_eligible_sql(alias: str = "pe") -> str:
    return f"""
        lower(coalesce({alias}.status, 'unknown')) = 'alive'
        AND lower(trim(coalesce({alias}.ip_type, ''))) = 'residential'
        AND trim(coalesce({alias}.exit_ip, '')) != ''
        AND length(trim(coalesce({alias}.country_code, ''))) = 2
        AND upper(trim({alias}.country_code)) GLOB '[A-Z][A-Z]'
        AND coalesce({alias}.duplicate_egress, 0) = 0
        AND EXISTS (
            SELECT 1 FROM proxy_probe_results earnapp
            WHERE earnapp.proxy_id = {alias}.id
              AND earnapp.profile = 'earnapp_wss'
              AND earnapp.verdict = 'CID_SET'
              AND earnapp.eligibility = 'eligible'
              AND trim(coalesce(earnapp.exit_ip, '')) != ''
              AND earnapp.exit_ip = {alias}.exit_ip
              AND earnapp.id = (
                  SELECT MAX(latest.id) FROM proxy_probe_results latest
                  WHERE latest.proxy_id = {alias}.id AND latest.profile = 'earnapp_wss'
              )
        )
    """


async def _expire_earnapp_provider_masks(db: Any) -> None:
    """Release EarnApp-only masks after the agreed 48-hour quarantine."""
    await db.execute(
        """
        DELETE FROM proxy_provider_masks
        WHERE provider_slug = 'earnapp' AND updated_at <= datetime('now', '-48 hours')
        """
    )


def _active_earnapp_reservation_exclusion_sql(
    alias: str = "pe", reservation_alias: str = "reservation", reserved_proxy_alias: str = "reserved_proxy"
) -> str:
    """Exclude a proxy held by a live EarnApp rotation reservation.

    Reservations are short-lived staging locks.  They must block every allocator,
    including legacy and non-EarnApp paths, and the comparison is by canonical
    egress as well as endpoint id so duplicate rows cannot bypass the lock.
    """
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM earnapp_proxy_reservations {reservation_alias}
            JOIN proxy_endpoints {reserved_proxy_alias}
              ON {reserved_proxy_alias}.id = {reservation_alias}.proxy_id
            WHERE {reservation_alias}.state = 'ACTIVE'
              AND {reservation_alias}.expires_at > datetime('now')
              AND (
                  {reservation_alias}.proxy_id = {alias}.id
                  OR (
                      trim(coalesce({alias}.exit_ip, '')) != ''
                      AND trim(coalesce({reserved_proxy_alias}.exit_ip, '')) != ''
                      AND {reserved_proxy_alias}.exit_ip = {alias}.exit_ip
                  )
              )
        )
    """


async def _protected_earnapp_proxy_reference(
    db: Any,
    *,
    proxy_ids: Sequence[int] | None = None,
    status: str = "",
) -> str:
    protected_ids = tuple(sorted(earnapp_policy.PROTECTED_LOGICAL_NODE_IDS))
    if not protected_ids:
        return ""
    node_placeholders = ",".join("?" for _ in protected_ids)
    runtime_refs = tuple(sorted(earnapp_policy.protected_runtime_references()))
    runtime_placeholders = ",".join("?" for _ in runtime_refs)
    proxy_clause = ""
    selected_ids = [int(value) for value in (proxy_ids or ()) if int(value) > 0]
    if selected_ids:
        proxy_placeholders = ",".join("?" for _ in selected_ids)
        proxy_clause = f"WHERE pe.id IN ({proxy_placeholders})"
        filter_params: list[Any] = selected_ids
    elif status:
        proxy_clause = "WHERE lower(coalesce(pe.status, '')) = ?"
        filter_params = [str(status).strip().lower()]
    else:
        filter_params = []
    row = await (
        await db.execute(
            f"""
            WITH targets AS (
                SELECT pe.id, pe.exit_ip
                FROM proxy_endpoints pe
                {proxy_clause}
            )
            SELECT n.logical_node_id
            FROM earnapp_logical_nodes n
            JOIN proxy_endpoints source
              ON source.id = n.current_proxy_id OR source.id = n.preferred_proxy_id
            JOIN targets target
              ON target.id = source.id
              OR (
                  trim(coalesce(source.exit_ip, '')) != ''
                  AND target.exit_ip = source.exit_ip
              )
            WHERE n.logical_node_id IN ({node_placeholders})
            UNION ALL
            SELECT l.instance_id AS logical_node_id
            FROM provider_proxy_leases l
            JOIN proxy_endpoints source ON source.id = l.proxy_id
            JOIN targets target
              ON target.id = source.id
              OR (
                  trim(coalesce(source.exit_ip, '')) != ''
                  AND target.exit_ip = source.exit_ip
              )
            WHERE l.provider_slug = 'earnapp'
              AND l.instance_id IN ({runtime_placeholders})
              AND l.released_at IS NULL
            UNION ALL
            SELECT r.logical_node_id
            FROM earnapp_proxy_reservations r
            JOIN proxy_endpoints source ON source.id = r.proxy_id
            JOIN targets target
              ON target.id = source.id
              OR (
                  trim(coalesce(source.exit_ip, '')) != ''
                  AND target.exit_ip = source.exit_ip
              )
            WHERE r.logical_node_id IN ({node_placeholders})
              AND r.state = 'ACTIVE'
            UNION ALL
            SELECT coalesce(nullif(r.assigned_logical_node_id, ''), n.logical_node_id)
            FROM earnapp_account_control_routes r
            JOIN earnapp_logical_nodes n ON n.account_id = r.account_id
            JOIN proxy_endpoints source ON source.id = r.proxy_id
            JOIN targets target
              ON target.id = source.id
              OR (
                  trim(coalesce(source.exit_ip, '')) != ''
                  AND target.exit_ip = source.exit_ip
              )
            WHERE n.logical_node_id IN ({node_placeholders})
              AND r.state IN ('ACTIVE', 'TRANSFERRED')
            UNION ALL
            SELECT pi.instance_id
            FROM provider_instances pi
            JOIN proxy_endpoints source ON source.id = pi.proxy_id
            JOIN targets target
              ON target.id = source.id
              OR (
                  trim(coalesce(source.exit_ip, '')) != ''
                  AND target.exit_ip = source.exit_ip
              )
            WHERE pi.slug = 'earnapp'
              AND pi.instance_id IN ({runtime_placeholders})
            LIMIT 1
            """,
            [
                *filter_params,
                *protected_ids,
                *runtime_refs,
                *protected_ids,
                *protected_ids,
                *runtime_refs,
            ],
        )
    ).fetchone()
    return str(row["logical_node_id"] or "") if row else ""


async def _protected_earnapp_account_reference(account_id: int) -> str:
    protected_ids = tuple(sorted(earnapp_policy.PROTECTED_LOGICAL_NODE_IDS))
    if int(account_id or 0) <= 0 or not protected_ids:
        return ""
    placeholders = ",".join("?" for _ in protected_ids)
    db = await _get_db()
    try:
        row = await (
            await db.execute(
                f"""
                SELECT logical_node_id
                FROM earnapp_logical_nodes
                WHERE account_id = ? AND logical_node_id IN ({placeholders})
                LIMIT 1
                """,
                (int(account_id), *protected_ids),
            )
        ).fetchone()
        return str(row["logical_node_id"] or "") if row else ""
    finally:
        await db.close()


async def get_earnapp_logical_node(logical_node_id: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        row = await (
            await db.execute(
                "SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?",
                (str(logical_node_id or "").strip(),),
            )
        ).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_earnapp_logical_nodes() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM earnapp_logical_nodes ORDER BY logical_node_id")
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def get_active_provider_proxy_lease(
    provider_slug: str, worker_id: int, instance_id: str
) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        row = await (
            await db.execute(
                """
                SELECT * FROM provider_proxy_leases
                WHERE provider_slug = ? AND worker_id = ? AND instance_id = ? AND released_at IS NULL
                LIMIT 1
                """,
                (
                    str(provider_slug or "").strip().lower(),
                    int(worker_id),
                    str(instance_id or "").strip(),
                ),
            )
        ).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_provider_proxy_leases(*, provider_slug: str = "") -> list[dict[str, Any]]:
    """Return lease history for operator/tests without decrypting proxy credentials."""
    slug = str(provider_slug or "").strip().lower()
    db = await _get_db()
    try:
        where = "WHERE provider_slug = ?" if slug else ""
        params: tuple[Any, ...] = (slug,) if slug else ()
        rows = await (
            await db.execute(
                f"SELECT * FROM provider_proxy_leases {where} ORDER BY id",
                params,
            )
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def record_earnapp_proxy_health(
    logical_node_id: str,
    worker_id: int,
    *,
    generation: int,
    proxy_id: int,
    health: str,
    observed_egress_ip: str = "",
    reason: str = "",
) -> bool:
    """Persist worker evidence only when the exact node assignment is current."""
    node_id = str(logical_node_id or "").strip()
    status = str(health or "").strip().lower()
    if status not in {"healthy", "unhealthy", "unknown"}:
        raise ValueError("invalid EarnApp proxy health")
    observed = str(observed_egress_ip or "").strip()[:64]
    safe_reason = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(reason or "").strip())[:160]
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute(
                    """
                    SELECT n.current_proxy_id, pe.exit_ip
                    FROM earnapp_logical_nodes n
                    LEFT JOIN proxy_endpoints pe ON pe.id = n.current_proxy_id
                    WHERE n.logical_node_id = ? AND n.assigned_worker_id = ? AND n.generation = ?
                      AND n.current_proxy_id = ? AND n.state IN ('ACTIVE', 'RECOVERY_HOLD')
                    """,
                    (node_id, int(worker_id), int(generation), int(proxy_id)),
                )
            ).fetchone()
            if not row:
                await db.rollback()
                return False
            cursor = await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET proxy_health = ?, observed_egress_ip = ?, expected_egress_ip = ?,
                    proxy_checked_at = datetime('now'), proxy_health_reason = ?, updated_at = datetime('now')
                WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ? AND current_proxy_id = ?
                """,
                (
                    status,
                    observed,
                    str(row["exit_ip"] or ""),
                    safe_reason,
                    node_id,
                    int(worker_id),
                    int(generation),
                    int(proxy_id),
                ),
            )
            await db.commit()
            return bool(cursor.rowcount)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def find_available_earnapp_proxy_for_node(
    logical_node_id: str,
    worker_id: int,
    *,
    expected_proxy_id: int,
) -> dict[str, Any] | None:
    """Return a read-only rotation candidate for one exact EarnApp assignment."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return None
    if not node_id or int(worker_id or 0) <= 0 or int(expected_proxy_id or 0) <= 0:
        return None
    db = await _get_db()
    try:
        await _expire_earnapp_provider_masks(db)
        await db.commit()
        node = await (
            await db.execute(
                """
                SELECT platform, preferred_proxy_id
                FROM earnapp_logical_nodes
                WHERE logical_node_id = ? AND assigned_worker_id = ?
                  AND current_proxy_id = ? AND state = 'ACTIVE'
                """,
                (node_id, int(worker_id), int(expected_proxy_id)),
            )
        ).fetchone()
        if not node:
            return None
        platform = str(node["platform"] or "").strip().lower()
        if platform in {"macos", "ios"}:
            country_clause = "upper(trim(coalesce(pe.country_code, ''))) = 'VN'"
        elif platform == "ubuntu":
            country_clause = (
                "length(trim(coalesce(pe.country_code, ''))) = 2 "
                "AND upper(trim(pe.country_code)) GLOB '[A-Z][A-Z]' "
                "AND upper(trim(pe.country_code)) != 'VN'"
            )
        else:
            return None
        preferred_proxy_id = int(node["preferred_proxy_id"] or 0)
        row = await (
            await db.execute(
                f"""
                SELECT pe.id AS proxy_id, pe.endpoint, pe.host, pe.port, pe.protocol,
                       pe.username, pe.password_enc, pe.location, pe.exit_ip, pe.ip_type,
                       pe.country_code, pe.country_name
                FROM proxy_endpoints pe
                LEFT JOIN proxy_assignments legacy ON legacy.proxy_id = pe.id
                WHERE pe.id != ? AND legacy.proxy_id IS NULL
                  AND {_earnapp_proxy_eligible_sql("pe")}
                  AND {country_clause}
                  AND NOT EXISTS (
                      SELECT 1 FROM proxy_provider_masks ppm
                      WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = 'earnapp'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM provider_proxy_leases occupied
                      WHERE occupied.released_at IS NULL
                        AND (occupied.proxy_id = pe.id OR (
                            trim(coalesce(occupied.exit_ip, '')) != ''
                            AND occupied.exit_ip = pe.exit_ip
                        ))
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM provider_instances runtime
                      JOIN proxy_endpoints runtime_proxy ON runtime_proxy.id = runtime.proxy_id
                      WHERE runtime.proxy_id = pe.id OR (
                          trim(coalesce(runtime_proxy.exit_ip, '')) != ''
                          AND runtime_proxy.exit_ip = pe.exit_ip
                      )
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM earnapp_account_control_routes control
                      JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                      WHERE control.state = 'ACTIVE'
                        AND (control.proxy_id = pe.id OR (
                            trim(coalesce(control_proxy.exit_ip, '')) != ''
                          AND control_proxy.exit_ip = pe.exit_ip
                        ))
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM earnapp_proxy_reservations reservation
                      JOIN proxy_endpoints reserved_proxy ON reserved_proxy.id = reservation.proxy_id
                      WHERE reservation.state = 'ACTIVE' AND reservation.expires_at > datetime('now')
                        AND (reservation.proxy_id = pe.id OR (
                            trim(coalesce(reserved_proxy.exit_ip, '')) != ''
                            AND reserved_proxy.exit_ip = pe.exit_ip
                        ))
                  )
                ORDER BY CASE WHEN pe.id = ? THEN 0 ELSE 1 END, pe.id
                LIMIT 1
                """,
                (int(expected_proxy_id), preferred_proxy_id),
            )
        ).fetchone()
        if not row:
            return None
        candidate = dict(row)
        encrypted = candidate.pop("password_enc", "") or ""
        if encrypted:
            candidate["password"] = decrypt_value(encrypted)
        return candidate
    finally:
        await db.close()


async def reserve_earnapp_proxy_candidate(
    logical_node_id: str,
    worker_id: int,
    *,
    generation: int,
    expected_proxy_id: int,
    candidate_proxy_id: int,
    binding_version: str,
    ttl_seconds: int = 10 * 60,
) -> dict[str, Any] | None:
    """Reserve one exact rotation candidate before any worker-side staging."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return None
    version = str(binding_version or "").strip()
    ttl = max(60, min(int(ttl_seconds or 0), 60 * 60))
    if (
        not node_id
        or int(worker_id or 0) <= 0
        or int(generation or 0) <= 0
        or int(expected_proxy_id or 0) <= 0
        or int(candidate_proxy_id or 0) <= 0
        or int(candidate_proxy_id) == int(expected_proxy_id)
        or not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", version)
    ):
        return None
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await _expire_earnapp_provider_masks(db)
            await db.execute(
                """
                UPDATE earnapp_proxy_reservations
                SET state = 'EXPIRED', released_at = datetime('now'), release_reason = 'RESERVATION_TTL_EXPIRED'
                WHERE state = 'ACTIVE' AND expires_at <= datetime('now')
                """
            )
            node = await (
                await db.execute(
                    """
                    SELECT platform
                    FROM earnapp_logical_nodes
                    WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ?
                      AND current_proxy_id = ? AND state = 'ACTIVE'
                    """,
                    (node_id, int(worker_id), int(generation), int(expected_proxy_id)),
                )
            ).fetchone()
            if not node:
                await db.rollback()
                return None
            platform = str(node["platform"] or "unknown").strip().lower()
            if platform in {"macos", "ios"}:
                country_clause = "AND upper(trim(coalesce(pe.country_code, ''))) = 'VN'"
            elif platform == "ubuntu":
                country_clause = (
                    "AND length(trim(coalesce(pe.country_code, ''))) = 2 "
                    "AND upper(trim(pe.country_code)) GLOB '[A-Z][A-Z]' "
                    "AND upper(trim(pe.country_code)) != 'VN'"
                )
            else:
                await db.rollback()
                return None
            candidate = await (
                await db.execute(
                    f"""
                    SELECT pe.*
                    FROM proxy_endpoints pe
                    LEFT JOIN proxy_assignments legacy ON legacy.proxy_id = pe.id
                    WHERE pe.id = ? AND legacy.proxy_id IS NULL
                      AND {_earnapp_proxy_eligible_sql("pe")}
                      {country_clause}
                      AND NOT EXISTS (
                          SELECT 1 FROM proxy_provider_masks ppm
                          WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = 'earnapp'
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM provider_proxy_leases occupied
                          WHERE occupied.released_at IS NULL
                            AND (occupied.proxy_id = pe.id OR (
                                trim(coalesce(occupied.exit_ip, '')) != '' AND occupied.exit_ip = pe.exit_ip
                            ))
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM provider_instances runtime
                          JOIN proxy_endpoints runtime_proxy ON runtime_proxy.id = runtime.proxy_id
                          WHERE runtime.proxy_id = pe.id OR (
                              trim(coalesce(runtime_proxy.exit_ip, '')) != ''
                              AND runtime_proxy.exit_ip = pe.exit_ip
                          )
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM earnapp_account_control_routes control
                          JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                          WHERE control.state = 'ACTIVE'
                            AND (control.proxy_id = pe.id OR (
                                trim(coalesce(control_proxy.exit_ip, '')) != '' AND control_proxy.exit_ip = pe.exit_ip
                            ))
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM earnapp_proxy_reservations reservation
                          JOIN proxy_endpoints reserved_proxy ON reserved_proxy.id = reservation.proxy_id
                          WHERE reservation.state = 'ACTIVE' AND reservation.expires_at > datetime('now')
                            AND (reservation.proxy_id = pe.id OR (
                                trim(coalesce(reserved_proxy.exit_ip, '')) != '' AND reserved_proxy.exit_ip = pe.exit_ip
                            ))
                      )
                    LIMIT 1
                    """,
                    (int(candidate_proxy_id),),
                )
            ).fetchone()
            if not candidate:
                await db.rollback()
                return None
            await db.execute(
                """
                INSERT INTO earnapp_proxy_reservations
                    (logical_node_id, worker_id, generation, expected_proxy_id, proxy_id,
                     binding_version, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now', ?))
                """,
                (
                    node_id,
                    int(worker_id),
                    int(generation),
                    int(expected_proxy_id),
                    int(candidate_proxy_id),
                    version,
                    f"+{ttl} seconds",
                ),
            )
            await db.commit()
            data = dict(candidate)
            encrypted = data.pop("password_enc", "") or ""
            if encrypted:
                data["password"] = decrypt_value(encrypted)
            data["proxy_id"] = int(candidate_proxy_id)
            data["binding_version"] = version
            return data
        except aiosqlite.IntegrityError:
            await db.rollback()
            return None
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def get_earnapp_proxy_reservation(logical_node_id: str, *, binding_version: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        row = await (
            await db.execute(
                """
                SELECT * FROM earnapp_proxy_reservations
                WHERE logical_node_id = ? AND binding_version = ?
                ORDER BY id DESC LIMIT 1
                """,
                (str(logical_node_id or "").strip(), str(binding_version or "").strip()),
            )
        ).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def release_earnapp_proxy_reservation(logical_node_id: str, *, binding_version: str, reason: str) -> bool:
    if earnapp_policy.is_protected_logical_node(logical_node_id):
        return False
    safe_reason = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(reason or "").strip())[:160]
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                UPDATE earnapp_proxy_reservations
                SET state = 'RELEASED', released_at = datetime('now'), release_reason = ?
                WHERE logical_node_id = ? AND binding_version = ? AND state = 'ACTIVE'
                """,
                (
                    safe_reason or "EARNAPP_PROXY_RESERVATION_RELEASED",
                    str(logical_node_id or "").strip(),
                    str(binding_version or "").strip(),
                ),
            )
            await db.commit()
            return bool(cursor.rowcount)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def commit_earnapp_proxy_rotation(
    logical_node_id: str,
    worker_id: int,
    *,
    expected_generation: int,
    expected_proxy_id: int,
    new_proxy_id: int,
    binding_version: str = "",
) -> dict[str, Any] | None:
    """CAS-rotate exactly one EarnApp logical node and preserve its identity."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return None
    if not node_id or int(new_proxy_id) <= 0 or int(new_proxy_id) == int(expected_proxy_id):
        return None
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await _expire_earnapp_provider_masks(db)
            node = await (
                await db.execute(
                    """
                    SELECT * FROM earnapp_logical_nodes
                    WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ?
                      AND current_proxy_id = ? AND state = 'ACTIVE'
                    """,
                    (node_id, int(worker_id), int(expected_generation), int(expected_proxy_id)),
                )
            ).fetchone()
            if not node:
                await db.rollback()
                return None

            reservation_version = str(binding_version or "").strip()
            if reservation_version:
                reservation = await (
                    await db.execute(
                        """
                        SELECT id FROM earnapp_proxy_reservations
                        WHERE logical_node_id = ? AND worker_id = ? AND generation = ?
                          AND expected_proxy_id = ? AND proxy_id = ? AND binding_version = ?
                          AND state = 'ACTIVE' AND expires_at > datetime('now')
                        LIMIT 1
                        """,
                        (
                            node_id,
                            int(worker_id),
                            int(expected_generation),
                            int(expected_proxy_id),
                            int(new_proxy_id),
                            reservation_version,
                        ),
                    )
                ).fetchone()
                if not reservation:
                    await db.rollback()
                    return None

            platform = str(node["platform"] or "unknown").strip().lower()
            country_clause = ""
            if platform in {"macos", "ios"}:
                country_clause = "AND upper(trim(coalesce(pe.country_code, ''))) = 'VN'"
            elif platform == "ubuntu":
                country_clause = (
                    "AND length(trim(coalesce(pe.country_code, ''))) = 2 "
                    "AND upper(trim(pe.country_code)) GLOB '[A-Z][A-Z]' "
                    "AND upper(trim(pe.country_code)) != 'VN'"
                )
            else:
                await db.rollback()
                return None
            candidate = await (
                await db.execute(
                    f"""
                    SELECT pe.* FROM proxy_endpoints pe
                    LEFT JOIN proxy_assignments legacy ON legacy.proxy_id = pe.id
                    WHERE pe.id = ? AND legacy.proxy_id IS NULL
                      AND {_earnapp_proxy_eligible_sql("pe")}
                      {country_clause}
                      AND NOT EXISTS (
                          SELECT 1 FROM proxy_provider_masks ppm
                          WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = 'earnapp'
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM provider_proxy_leases occupied
                          WHERE occupied.released_at IS NULL
                            AND NOT (
                                occupied.provider_slug = 'earnapp' AND occupied.worker_id = ?
                                AND occupied.instance_id = ? AND occupied.proxy_id = ?
                            )
                            AND (occupied.proxy_id = pe.id OR (occupied.exit_ip != '' AND occupied.exit_ip = pe.exit_ip))
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM earnapp_account_control_routes control
                          JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                          WHERE control.state = 'ACTIVE'
                            AND (control.proxy_id = pe.id OR (control_proxy.exit_ip != '' AND control_proxy.exit_ip = pe.exit_ip))
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM earnapp_proxy_reservations other_reservation
                          JOIN proxy_endpoints reserved_proxy ON reserved_proxy.id = other_reservation.proxy_id
                          WHERE other_reservation.state = 'ACTIVE'
                            AND NOT (other_reservation.logical_node_id = ? AND other_reservation.binding_version = ?)
                            AND (other_reservation.proxy_id = pe.id OR (
                                reserved_proxy.exit_ip != '' AND reserved_proxy.exit_ip = pe.exit_ip
                            ))
                      )
                    LIMIT 1
                    """,
                    (
                        int(new_proxy_id),
                        int(worker_id),
                        node_id,
                        int(expected_proxy_id),
                        node_id,
                        reservation_version,
                    ),
                )
            ).fetchone()
            if not candidate:
                await db.rollback()
                return None

            released = await db.execute(
                """
                UPDATE provider_proxy_leases
                SET released_at = datetime('now'), release_reason = 'EARNAPP_PROXY_ROTATED'
                WHERE provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?
                  AND proxy_id = ? AND released_at IS NULL
                """,
                (int(worker_id), node_id, int(expected_proxy_id)),
            )
            if int(released.rowcount or 0) != 1:
                await db.rollback()
                return None
            await db.execute(
                """
                INSERT INTO provider_proxy_leases
                    (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                VALUES ('earnapp', ?, ?, ?, ?)
                """,
                (int(worker_id), node_id, int(new_proxy_id), str(candidate["exit_ip"] or "")),
            )
            updated_node = await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET current_proxy_id = ?, preferred_proxy_id = ?, proxy_health = 'unknown',
                    observed_egress_ip = '', expected_egress_ip = ?, proxy_checked_at = NULL,
                    proxy_health_reason = '', updated_at = datetime('now')
                WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ? AND current_proxy_id = ?
                """,
                (
                    int(new_proxy_id),
                    int(expected_proxy_id),
                    str(candidate["exit_ip"] or ""),
                    node_id,
                    int(worker_id),
                    int(expected_generation),
                    int(expected_proxy_id),
                ),
            )
            if int(updated_node.rowcount or 0) != 1:
                await db.rollback()
                return None
            await db.execute(
                """
                UPDATE provider_instances
                SET proxy_id = ?, updated_at = datetime('now')
                WHERE slug = 'earnapp' AND instance_id = ? AND worker_id = ? AND proxy_id = ?
                """,
                (int(new_proxy_id), node_id, int(worker_id), int(expected_proxy_id)),
            )
            updated = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            if reservation_version:
                committed_reservation = await db.execute(
                    """
                    UPDATE earnapp_proxy_reservations
                    SET state = 'COMMITTED', released_at = datetime('now'), release_reason = 'EARNAPP_PROXY_ROTATED'
                    WHERE logical_node_id = ? AND binding_version = ? AND state = 'ACTIVE'
                    """,
                    (node_id, reservation_version),
                )
                if int(committed_reservation.rowcount or 0) != 1:
                    await db.rollback()
                    return None
            await db.commit()
            return dict(updated) if updated else None
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def adopt_earnapp_runtime_proxy(
    logical_node_id: str,
    worker_id: int,
    *,
    expected_generation: int,
    device_id: str,
    expected_database_proxy_id: int,
    runtime_proxy_id: int,
    expected_runtime_egress_ip: str,
    observed_runtime_egress_ip: str,
    container_id: str,
    sidecar_id: str,
) -> dict[str, Any] | None:
    """CAS-adopt a verified live EarnApp route after server/worker split-brain."""
    node_id = str(logical_node_id or "").strip()
    identity = str(device_id or "").strip()
    expected_egress = str(expected_runtime_egress_ip or "").strip()
    observed_egress = str(observed_runtime_egress_ip or "").strip()
    live_container_id = str(container_id or "").strip()
    live_sidecar_id = str(sidecar_id or "").strip()
    database_proxy_id = int(expected_database_proxy_id or 0)
    live_proxy_id = int(runtime_proxy_id or 0)
    if (
        earnapp_policy.is_protected_logical_node(node_id)
        or not node_id
        or int(worker_id or 0) <= 0
        or int(expected_generation or 0) <= 0
        or not re.fullmatch(r"sdk-(?:mac|ios|node)-[A-Za-z0-9-]{4,96}", identity)
        or database_proxy_id <= 0
        or live_proxy_id <= 0
        or not expected_egress
        or observed_egress != expected_egress
        or not live_container_id
        or not live_sidecar_id
    ):
        return None
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            node = await (
                await db.execute(
                    """
                    SELECT * FROM earnapp_logical_nodes
                    WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ?
                      AND device_id = ? AND current_proxy_id = ? AND state = 'ACTIVE'
                    """,
                    (
                        node_id,
                        int(worker_id),
                        int(expected_generation),
                        identity,
                        database_proxy_id,
                    ),
                )
            ).fetchone()
            if not node:
                await db.rollback()
                return None
            platform = str(node["platform"] or "").strip().lower()
            if platform in {"macos", "ios"}:
                country_clause = "upper(trim(coalesce(proxy_endpoints.country_code, ''))) = 'VN'"
            elif platform == "ubuntu":
                country_clause = (
                    "length(trim(coalesce(proxy_endpoints.country_code, ''))) = 2 "
                    "AND upper(trim(proxy_endpoints.country_code)) GLOB '[A-Z][A-Z]' "
                    "AND upper(trim(proxy_endpoints.country_code)) != 'VN'"
                )
            else:
                await db.rollback()
                return None
            proxy = await (
                await db.execute(
                    f"""
                    SELECT proxy_endpoints.id, proxy_endpoints.exit_ip, proxy_endpoints.country_code,
                           proxy_endpoints.ip_type, earnapp.probe_status, earnapp.verdict,
                           earnapp.eligibility, earnapp.reason AS probe_reason
                    FROM proxy_endpoints
                    JOIN proxy_probe_results earnapp ON earnapp.id = (
                        SELECT MAX(latest.id) FROM proxy_probe_results latest
                        WHERE latest.proxy_id = proxy_endpoints.id AND latest.profile = 'earnapp_wss'
                    )
                    WHERE proxy_endpoints.id = ? AND proxy_endpoints.exit_ip = ?
                      AND lower(coalesce(proxy_endpoints.status, 'unknown')) = 'alive'
                      AND lower(trim(coalesce(proxy_endpoints.ip_type, ''))) = 'residential'
                      AND {country_clause}
                      AND coalesce(proxy_endpoints.duplicate_egress, 0) = 0
                      AND trim(coalesce(earnapp.exit_ip, '')) != ''
                      AND earnapp.exit_ip = proxy_endpoints.exit_ip
                    """,
                    (live_proxy_id, expected_egress),
                )
            ).fetchone()
            if not proxy:
                await db.rollback()
                return None
            mask = await (
                await db.execute(
                    """
                    SELECT reason FROM proxy_provider_masks
                    WHERE proxy_id = ? AND provider_slug = 'earnapp'
                    LIMIT 1
                    """,
                    (live_proxy_id,),
                )
            ).fetchone()
            raw_mask_reason = str(mask["reason"] or "").strip() if mask else ""
            probe_alive = str(proxy["probe_status"] or "").strip().lower() == "alive"
            probe_eligible = (
                str(proxy["verdict"] or "").strip().upper() == "CID_SET"
                and str(proxy["eligibility"] or "").strip().lower() == "eligible"
            )
            dashboard_blocked = (
                str(proxy["verdict"] or "").strip().upper() == "BLACKLIST"
                and str(proxy["eligibility"] or "").strip().lower() == "blocked"
                and str(proxy["probe_reason"] or "").strip().lower() == "earnapp_blacklist"
                and raw_mask_reason == "dashboard_ip_block"
            )
            if not probe_alive or not (probe_eligible or dashboard_blocked):
                await db.rollback()
                return None
            mask_reason = raw_mask_reason or ("dashboard_ip_block" if mask else "")
            conflict = await (
                await db.execute(
                    """
                    SELECT 1 FROM provider_proxy_leases
                    WHERE released_at IS NULL
                      AND NOT (provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?)
                      AND (proxy_id = ? OR (trim(coalesce(exit_ip, '')) != '' AND exit_ip = ?))
                    LIMIT 1
                    """,
                    (int(worker_id), node_id, live_proxy_id, expected_egress),
                )
            ).fetchone()
            if conflict:
                await db.rollback()
                return None
            ownership_conflict = await (
                await db.execute(
                    """
                    SELECT 1
                    FROM (
                        SELECT legacy.proxy_id
                        FROM proxy_assignments legacy
                        JOIN proxy_endpoints legacy_proxy ON legacy_proxy.id = legacy.proxy_id
                        WHERE legacy.proxy_id = ?
                           OR (trim(coalesce(legacy_proxy.exit_ip, '')) != '' AND legacy_proxy.exit_ip = ?)
                        UNION ALL
                        SELECT control.proxy_id
                        FROM earnapp_account_control_routes control
                        JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                        WHERE control.state = 'ACTIVE'
                          AND (control.proxy_id = ?
                               OR (trim(coalesce(control_proxy.exit_ip, '')) != '' AND control_proxy.exit_ip = ?))
                        UNION ALL
                        SELECT reservation.proxy_id
                        FROM earnapp_proxy_reservations reservation
                        JOIN proxy_endpoints reserved_proxy ON reserved_proxy.id = reservation.proxy_id
                        WHERE reservation.state = 'ACTIVE' AND reservation.expires_at > datetime('now')
                          AND (reservation.proxy_id = ?
                               OR (trim(coalesce(reserved_proxy.exit_ip, '')) != '' AND reserved_proxy.exit_ip = ?))
                    ) occupied
                    LIMIT 1
                    """,
                    (
                        live_proxy_id,
                        expected_egress,
                        live_proxy_id,
                        expected_egress,
                        live_proxy_id,
                        expected_egress,
                    ),
                )
            ).fetchone()
            if ownership_conflict:
                await db.rollback()
                return None

            own_leases = await (
                await db.execute(
                    """
                    SELECT id, proxy_id, exit_ip FROM provider_proxy_leases
                    WHERE provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?
                      AND released_at IS NULL
                    ORDER BY id
                    """,
                    (int(worker_id), node_id),
                )
            ).fetchall()
            if len(own_leases) != 1:
                await db.rollback()
                return None
            own_lease = own_leases[0]
            if int(own_lease["proxy_id"] or 0) != database_proxy_id:
                await db.rollback()
                return None
            if database_proxy_id != live_proxy_id:
                released = await db.execute(
                    """
                    UPDATE provider_proxy_leases
                    SET released_at = datetime('now'), release_reason = 'EARNAPP_RUNTIME_PROXY_ADOPTED'
                    WHERE id = ? AND released_at IS NULL
                    """,
                    (int(own_lease["id"]),),
                )
                if int(released.rowcount or 0) != 1:
                    await db.rollback()
                    return None
                await db.execute(
                    """
                    INSERT INTO provider_proxy_leases
                        (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                    VALUES ('earnapp', ?, ?, ?, ?)
                    """,
                    (int(worker_id), node_id, live_proxy_id, expected_egress),
                )

            updated_node = await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET current_proxy_id = ?, preferred_proxy_id = ?, proxy_health = ?,
                    observed_egress_ip = ?, expected_egress_ip = ?, proxy_checked_at = datetime('now'),
                    proxy_health_reason = ?, updated_at = datetime('now')
                WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ?
                  AND device_id = ? AND current_proxy_id = ? AND state = 'ACTIVE'
                """,
                (
                    live_proxy_id,
                    database_proxy_id if database_proxy_id != live_proxy_id else int(node["preferred_proxy_id"] or 0),
                    "unhealthy" if mask else "healthy",
                    observed_egress,
                    expected_egress,
                    mask_reason,
                    node_id,
                    int(worker_id),
                    int(expected_generation),
                    identity,
                    database_proxy_id,
                ),
            )
            if int(updated_node.rowcount or 0) != 1:
                await db.rollback()
                return None
            updated_instance = await db.execute(
                """
                UPDATE provider_instances
                SET proxy_id = ?, container_id = ?, sidecar_id = ?, updated_at = datetime('now')
                WHERE slug = 'earnapp' AND instance_id = ? AND worker_id = ? AND proxy_id = ?
                """,
                (
                    live_proxy_id,
                    live_container_id,
                    live_sidecar_id,
                    node_id,
                    int(worker_id),
                    database_proxy_id,
                ),
            )
            if int(updated_instance.rowcount or 0) != 1:
                await db.rollback()
                return None
            updated = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            await db.commit()
            return dict(updated) if updated else None
        except aiosqlite.IntegrityError:
            await db.rollback()
            return None
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def bind_earnapp_node_runtime(
    logical_node_id: str,
    worker_id: int,
    *,
    device_id: str,
    proxy_id: int,
) -> dict[str, Any]:
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        raise ValueError("protected EarnApp node is inspection-only")
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            node = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            if not node:
                raise ValueError("EarnApp logical node not found")
            if node["assigned_worker_id"] is not None and int(node["assigned_worker_id"]) != int(worker_id):
                raise ValueError("EarnApp logical node is already assigned to another worker")
            proxy = await (
                await db.execute(
                    f"""
                    SELECT * FROM proxy_endpoints pe
                    WHERE pe.id = ? AND {_earnapp_proxy_eligible_sql("pe")}
                      AND (
                          {_active_earnapp_reservation_exclusion_sql("pe")}
                          OR EXISTS (
                              SELECT 1 FROM earnapp_proxy_reservations reservation
                              WHERE reservation.logical_node_id = ?
                                AND reservation.worker_id = ?
                                AND reservation.proxy_id = pe.id
                                AND reservation.state = 'ACTIVE'
                                AND reservation.expires_at > datetime('now')
                          )
                      )
                    """,
                    (int(proxy_id), node_id, int(worker_id)),
                )
            ).fetchone()
            if not proxy:
                raise ValueError("EarnApp proxy is not eligible")
            conflict = await (
                await db.execute(
                    """
                    SELECT 1 FROM provider_proxy_leases
                    WHERE released_at IS NULL
                      AND NOT (provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?)
                      AND (proxy_id = ? OR (exit_ip != '' AND exit_ip = ?))
                    LIMIT 1
                    """,
                    (int(worker_id), node_id, int(proxy_id), str(proxy["exit_ip"] or "")),
                )
            ).fetchone()
            if conflict:
                raise ValueError("EarnApp proxy is already leased")
            own_lease = await (
                await db.execute(
                    """
                    SELECT 1 FROM provider_proxy_leases
                    WHERE provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?
                      AND proxy_id = ? AND released_at IS NULL
                    LIMIT 1
                    """,
                    (int(worker_id), node_id, int(proxy_id)),
                )
            ).fetchone()
            if not own_lease:
                await db.execute(
                    """
                    INSERT INTO provider_proxy_leases
                        (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                    VALUES ('earnapp', ?, ?, ?, ?)
                    """,
                    (int(worker_id), node_id, int(proxy_id), str(proxy["exit_ip"] or "")),
                )
            await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET assigned_worker_id = ?, last_worker_id = ?, device_id = ?, current_proxy_id = ?, preferred_proxy_id = ?,
                    proxy_health = 'unknown', observed_egress_ip = '', expected_egress_ip = ?,
                    proxy_checked_at = NULL, proxy_health_reason = '',
                    state = 'ACTIVE', last_heartbeat_at = datetime('now'), recovery_started_at = NULL,
                    recovery_hold_until = NULL, updated_at = datetime('now')
                WHERE logical_node_id = ?
                """,
                (
                    int(worker_id),
                    int(worker_id),
                    str(device_id or ""),
                    int(proxy_id),
                    int(proxy_id),
                    str(proxy["exit_ip"] or ""),
                    node_id,
                ),
            )
            updated = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            await db.commit()
            return dict(updated)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def reserve_earnapp_node_runtime(
    logical_node_id: str,
    worker_id: int,
    *,
    device_id: str = "",
    proxy_id: int,
) -> dict[str, Any]:
    """Reserve an Ubuntu assignment without inventing its runtime UUID."""
    return await bind_earnapp_node_runtime(
        logical_node_id,
        worker_id,
        device_id=str(device_id or ""),
        proxy_id=proxy_id,
    )


async def bind_earnapp_generated_device_id(
    logical_node_id: str,
    worker_id: int,
    *,
    generation: int,
    proxy_id: int,
    device_id: str,
) -> dict[str, Any] | None:
    """CAS-bind the UUID generated inside one fresh Ubuntu runtime volume."""
    node_id = str(logical_node_id or "").strip()
    generated = str(device_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        raise ValueError("protected EarnApp node is inspection-only")
    if not re.fullmatch(r"sdk-node-[0-9a-f]{32}", generated):
        raise ValueError("EarnApp generated device identity is invalid")
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            collision = await (
                await db.execute(
                    "SELECT logical_node_id FROM earnapp_logical_nodes WHERE device_id = ? AND logical_node_id != ?",
                    (generated, node_id),
                )
            ).fetchone()
            if collision:
                await db.rollback()
                raise ValueError("EarnApp generated device identity is already assigned")
            updated = await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET device_id = ?, updated_at = datetime('now')
                WHERE logical_node_id = ? AND platform = 'ubuntu'
                  AND assigned_worker_id = ? AND generation = ? AND current_proxy_id = ?
                  AND (device_id = '' OR device_id = ?)
                """,
                (generated, node_id, int(worker_id), int(generation), int(proxy_id), generated),
            )
            if int(updated.rowcount or 0) != 1:
                await db.rollback()
                return None
            row = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            await db.commit()
            return dict(row) if row else None
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def rollback_earnapp_canary_binding(
    logical_node_id: str,
    worker_id: int,
    *,
    generation: int,
    proxy_id: int,
    reason: str,
) -> bool:
    """CAS rollback for a failed first canary deploy without touching recovery nodes."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return False
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            node = await (
                await db.execute(
                    """
                    SELECT state, assigned_worker_id, generation, current_proxy_id
                    FROM earnapp_logical_nodes WHERE logical_node_id = ?
                    """,
                    (node_id,),
                )
            ).fetchone()
            if not node or (
                str(node["state"] or "") != "ACTIVE"
                or int(node["assigned_worker_id"] or 0) != int(worker_id)
                or int(node["generation"] or 0) != int(generation)
                or int(node["current_proxy_id"] or 0) != int(proxy_id)
            ):
                await db.rollback()
                return False
            await db.execute(
                """
                UPDATE provider_proxy_leases
                SET released_at = datetime('now'), release_reason = ?
                WHERE provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?
                  AND proxy_id = ? AND released_at IS NULL
                """,
                (str(reason or "EARNAPP_CANARY_DEPLOY_FAILED")[:300], int(worker_id), node_id, int(proxy_id)),
            )
            await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET state = 'PLANNED', assigned_worker_id = NULL, last_worker_id = NULL,
                    current_proxy_id = NULL, preferred_proxy_id = NULL, device_id = '',
                    last_heartbeat_at = NULL, updated_at = datetime('now')
                WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ? AND current_proxy_id = ?
                """,
                (node_id, int(worker_id), int(generation), int(proxy_id)),
            )
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def finalize_earnapp_node_removal(
    logical_node_id: str,
    worker_id: int,
    *,
    generation: int,
    device_id: str,
    reason: str = "EARNAPP_NODE_REMOVED",
) -> bool:
    """Release one removed runtime while preserving its reusable identity and proxy affinity."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return False
    expected_device_id = str(device_id or "").strip()
    if not node_id or int(worker_id or 0) <= 0 or int(generation or 0) <= 0 or not expected_device_id:
        return False
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            node = await (
                await db.execute(
                    """
                    SELECT state, assigned_worker_id, generation, device_id, current_proxy_id
                    FROM earnapp_logical_nodes
                    WHERE logical_node_id = ?
                    """,
                    (node_id,),
                )
            ).fetchone()
            if not node or (
                str(node["state"] or "") not in {"ACTIVE", "RECOVERY_HOLD"}
                or int(node["assigned_worker_id"] or 0) != int(worker_id)
                or int(node["generation"] or 0) != int(generation)
                or str(node["device_id"] or "") != expected_device_id
            ):
                await db.rollback()
                return False
            proxy_id = int(node["current_proxy_id"] or 0)
            await db.execute(
                """
                UPDATE provider_proxy_leases
                SET released_at = datetime('now'), release_reason = ?
                WHERE provider_slug = 'earnapp' AND worker_id = ? AND instance_id = ?
                  AND released_at IS NULL
                """,
                (str(reason or "EARNAPP_NODE_REMOVED")[:300], int(worker_id), node_id),
            )
            cursor = await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET state = 'PLANNED', assigned_worker_id = NULL, last_worker_id = ?,
                    current_proxy_id = NULL,
                    preferred_proxy_id = CASE WHEN ? > 0 THEN ? ELSE preferred_proxy_id END,
                    proxy_health = 'unknown', observed_egress_ip = '', expected_egress_ip = '',
                    proxy_checked_at = NULL, proxy_health_reason = '', last_heartbeat_at = NULL,
                    recovery_started_at = NULL, recovery_hold_until = NULL, updated_at = datetime('now')
                WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ? AND device_id = ?
                """,
                (
                    int(worker_id),
                    proxy_id,
                    proxy_id,
                    node_id,
                    int(worker_id),
                    int(generation),
                    expected_device_id,
                ),
            )
            if int(cursor.rowcount or 0) != 1:
                await db.rollback()
                return False
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def begin_earnapp_recovery_hold(logical_node_id: str, *, hold_seconds: int) -> dict[str, Any] | None:
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return None
    seconds = max(1, int(hold_seconds))
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            UPDATE earnapp_logical_nodes
            SET state = 'RECOVERY_HOLD', recovery_started_at = datetime('now'),
                recovery_hold_until = datetime('now', ?), updated_at = datetime('now')
            WHERE logical_node_id = ? AND state = 'ACTIVE'
            """,
            (f"+{seconds} seconds", node_id),
        )
        await db.commit()
        if not cursor.rowcount:
            return None
        return await get_earnapp_logical_node(node_id)
    finally:
        await db.close()


async def sweep_stale_earnapp_nodes(
    *,
    stale_after_seconds: int,
    hold_seconds: int,
    platforms: Sequence[str] | None = None,
    excluded_logical_node_ids: Sequence[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    held: list[dict[str, Any]] = []
    released: list[dict[str, Any]] = []
    selected_platforms = tuple(
        platform
        for platform in (str(value or "").strip().lower() for value in (platforms or ()))
        if platform in {"macos", "ios", "ubuntu"}
    )
    platform_clause = ""
    platform_params: tuple[str, ...] = ()
    if selected_platforms:
        placeholders = ", ".join("?" for _ in selected_platforms)
        platform_clause = f" AND n.platform IN ({placeholders})"
        platform_params = selected_platforms
    excluded_nodes = tuple(
        sorted(
            {
                *earnapp_policy.PROTECTED_LOGICAL_NODE_IDS,
                *(
                    node_id
                    for node_id in (str(value or "").strip() for value in (excluded_logical_node_ids or ()))
                    if node_id
                ),
            }
        )
    )
    excluded_clause = ""
    excluded_params: tuple[str, ...] = ()
    if excluded_nodes:
        placeholders = ", ".join("?" for _ in excluded_nodes)
        excluded_clause = f" AND n.logical_node_id NOT IN ({placeholders})"
        excluded_params = excluded_nodes
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cutoff = f"-{max(1, int(stale_after_seconds))} seconds"
            stale = await (
                await db.execute(
                    f"""
                    SELECT n.*
                    FROM earnapp_logical_nodes n
                    JOIN workers w ON w.id = n.assigned_worker_id
                    WHERE n.state = 'ACTIVE'
                      {platform_clause}
                      {excluded_clause}
                      AND w.last_heartbeat IS NOT NULL
                      AND w.last_heartbeat < datetime('now', ?)
                    ORDER BY n.logical_node_id
                    """,
                    (*platform_params, *excluded_params, cutoff),
                )
            ).fetchall()
            for row in stale:
                await db.execute(
                    """
                    UPDATE earnapp_logical_nodes
                    SET state = 'RECOVERY_HOLD', recovery_started_at = datetime('now'),
                        recovery_hold_until = datetime('now', ?), updated_at = datetime('now')
                    WHERE logical_node_id = ? AND state = 'ACTIVE'
                    """,
                    (f"+{max(1, int(hold_seconds))} seconds", str(row["logical_node_id"])),
                )
                held.append({"logical_node_id": str(row["logical_node_id"])})

            expired = await (
                await db.execute(
                    f"""
                    SELECT * FROM earnapp_logical_nodes
                    WHERE state = 'RECOVERY_HOLD'
                      {platform_clause.replace("n.", "")}
                      {excluded_clause.replace("n.", "")}
                      AND recovery_hold_until IS NOT NULL
                      AND recovery_hold_until <= datetime('now')
                    ORDER BY logical_node_id
                    """,
                    (*platform_params, *excluded_params),
                )
            ).fetchall()
            for row in expired:
                node_id = str(row["logical_node_id"])
                await db.execute(
                    """
                    UPDATE provider_proxy_leases
                    SET released_at = datetime('now'), release_reason = 'EARNAPP_RECOVERY_HOLD_EXPIRED'
                    WHERE provider_slug = 'earnapp' AND instance_id = ? AND released_at IS NULL
                    """,
                    (node_id,),
                )
                await db.execute(
                    """
                    UPDATE earnapp_logical_nodes
                    SET state = 'RECOVERABLE', assigned_worker_id = NULL, current_proxy_id = NULL,
                        updated_at = datetime('now')
                    WHERE logical_node_id = ? AND state = 'RECOVERY_HOLD'
                    """,
                    (node_id,),
                )
                released.append({"logical_node_id": node_id})
            await db.commit()
            return {"held": held, "released": released}
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def create_earnapp_replacement_ticket(
    logical_node_id: str,
    target_worker_id: int,
    *,
    generation: int,
    token_hash: str,
    expires_seconds: int,
) -> str:
    """Create a ticket only while the requested recovery generation is current."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return "protected_node"
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            worker = await (
                await db.execute("SELECT id FROM workers WHERE id = ?", (int(target_worker_id),))
            ).fetchone()
            if not worker:
                await db.rollback()
                return "target_worker_not_found"

            node = await (
                await db.execute(
                    "SELECT generation, state FROM earnapp_logical_nodes WHERE logical_node_id = ?",
                    (node_id,),
                )
            ).fetchone()
            if not node:
                await db.rollback()
                return "node_not_found"
            if int(node["generation"]) != int(generation):
                await db.rollback()
                return "generation_mismatch"
            if str(node["state"] or "") not in {"RECOVERY_HOLD", "RECOVERABLE"}:
                await db.rollback()
                return "node_not_recoverable"

            await db.execute(
                """
                INSERT INTO earnapp_replacement_tickets
                    (logical_node_id, target_worker_id, generation, token_hash, expires_at)
                VALUES (?, ?, ?, ?, datetime('now', ?))
                """,
                (
                    node_id,
                    int(target_worker_id),
                    int(generation),
                    str(token_hash),
                    f"+{max(1, int(expires_seconds))} seconds",
                ),
            )
            await db.commit()
            return "created"
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def claim_earnapp_node(
    logical_node_id: str,
    worker_id: int,
    *,
    expected_generation: int,
    ticket_hash: str = "",
) -> dict[str, Any] | None:
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_logical_node(node_id):
        return None
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await _expire_earnapp_provider_masks(db)
            node = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            if not node or int(node["generation"]) != int(expected_generation):
                await db.rollback()
                return None
            if str(node["state"] or "") not in {"RECOVERY_HOLD", "RECOVERABLE"}:
                await db.rollback()
                return None
            platform = str(node["platform"] or "unknown").strip().lower()
            if platform in {"macos", "ios"}:
                country_clause = "AND upper(trim(coalesce(pe.country_code, ''))) = 'VN'"
            elif platform == "ubuntu":
                country_clause = (
                    "AND length(trim(coalesce(pe.country_code, ''))) = 2 "
                    "AND upper(trim(pe.country_code)) GLOB '[A-Z][A-Z]' "
                    "AND upper(trim(pe.country_code)) != 'VN'"
                )
            else:
                await db.rollback()
                return None
            assigned_worker_id = int(node["assigned_worker_id"] or 0)
            last_worker_id = int(node["last_worker_id"] or assigned_worker_id or 0)
            replacing = bool(
                (assigned_worker_id and assigned_worker_id != int(worker_id))
                or (not assigned_worker_id and last_worker_id and last_worker_id != int(worker_id))
            )
            ticket = None
            if replacing:
                ticket = await (
                    await db.execute(
                        """
                        SELECT id FROM earnapp_replacement_tickets
                        WHERE logical_node_id = ? AND target_worker_id = ? AND generation = ?
                          AND token_hash = ? AND used_at IS NULL AND expires_at > datetime('now')
                        LIMIT 1
                        """,
                        (node_id, int(worker_id), int(expected_generation), str(ticket_hash)),
                    )
                ).fetchone()
                if not ticket:
                    await db.rollback()
                    return None

            proxy_id = int(node["current_proxy_id"] or node["preferred_proxy_id"] or 0)
            preferred = None
            if proxy_id:
                preferred = await (
                    await db.execute(
                        f"""
                        SELECT pe.* FROM proxy_endpoints pe
                        LEFT JOIN proxy_assignments legacy ON legacy.proxy_id = pe.id
                        LEFT JOIN provider_proxy_leases occupied
                          ON occupied.proxy_id = pe.id AND occupied.released_at IS NULL
                         AND NOT (occupied.provider_slug = 'earnapp' AND occupied.instance_id = ?)
                        LEFT JOIN earnapp_account_control_routes control
                          ON control.proxy_id = pe.id AND control.state = 'ACTIVE'
                        WHERE pe.id = ? AND legacy.proxy_id IS NULL AND occupied.id IS NULL
                          AND control.proxy_id IS NULL AND {_earnapp_proxy_eligible_sql("pe")}
                          {country_clause}
                          AND NOT EXISTS (
                              SELECT 1 FROM proxy_assignments used_legacy
                              JOIN proxy_endpoints used_proxy ON used_proxy.id = used_legacy.proxy_id
                              WHERE used_proxy.exit_ip = pe.exit_ip
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM provider_proxy_leases used
                              WHERE used.released_at IS NULL
                                AND NOT (used.provider_slug = 'earnapp' AND used.instance_id = ?)
                                AND used.exit_ip = pe.exit_ip
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM earnapp_account_control_routes used_control
                              JOIN proxy_endpoints control_proxy ON control_proxy.id = used_control.proxy_id
                              WHERE used_control.state = 'ACTIVE' AND control_proxy.exit_ip = pe.exit_ip
                          )
                          AND {_active_earnapp_reservation_exclusion_sql("pe")}
                        LIMIT 1
                        """,
                        (node_id, proxy_id, node_id),
                    )
                ).fetchone()
            if not preferred:
                preferred = await (
                    await db.execute(
                        f"""
                        SELECT pe.* FROM proxy_endpoints pe
                        LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
                        LEFT JOIN provider_proxy_leases occupied ON occupied.proxy_id = pe.id AND occupied.released_at IS NULL
                        WHERE pa.proxy_id IS NULL AND occupied.id IS NULL
                          AND {_earnapp_proxy_eligible_sql("pe")}
                          {country_clause}
                          AND NOT EXISTS (
                              SELECT 1 FROM proxy_assignments used_legacy
                              JOIN proxy_endpoints used_proxy ON used_proxy.id = used_legacy.proxy_id
                              WHERE used_proxy.exit_ip = pe.exit_ip
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM provider_proxy_leases used
                              WHERE used.released_at IS NULL AND used.exit_ip = pe.exit_ip
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM earnapp_account_control_routes used_control
                              JOIN proxy_endpoints control_proxy ON control_proxy.id = used_control.proxy_id
                              WHERE used_control.state = 'ACTIVE' AND control_proxy.exit_ip = pe.exit_ip
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM proxy_provider_masks ppm
                              WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = 'earnapp'
                          )
                          AND {_active_earnapp_reservation_exclusion_sql("pe")}
                        ORDER BY CASE WHEN pe.id = ? THEN 0 ELSE 1 END, pe.id
                        LIMIT 1
                        """,
                        (int(node["preferred_proxy_id"] or 0),),
                    )
                ).fetchone()
            if not preferred:
                await db.rollback()
                return None

            await db.execute(
                """
                UPDATE provider_proxy_leases
                SET released_at = datetime('now'), release_reason = 'EARNAPP_RECOVERED'
                WHERE provider_slug = 'earnapp' AND instance_id = ? AND released_at IS NULL
                """,
                (node_id,),
            )
            await db.execute(
                """
                INSERT INTO provider_proxy_leases
                    (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                VALUES ('earnapp', ?, ?, ?, ?)
                """,
                (int(worker_id), node_id, int(preferred["id"]), str(preferred["exit_ip"] or "")),
            )
            new_generation = int(expected_generation) + (1 if replacing else 0)
            await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET assigned_worker_id = ?, last_worker_id = ?, current_proxy_id = ?, preferred_proxy_id = ?,
                    proxy_health = 'unknown', observed_egress_ip = '', expected_egress_ip = ?,
                    proxy_checked_at = NULL, proxy_health_reason = '',
                    state = 'ACTIVE', generation = ?, last_heartbeat_at = datetime('now'),
                    recovery_started_at = NULL, recovery_hold_until = NULL, updated_at = datetime('now')
                WHERE logical_node_id = ? AND generation = ?
                """,
                (
                    int(worker_id),
                    int(worker_id),
                    int(preferred["id"]),
                    int(preferred["id"]),
                    str(preferred["exit_ip"] or ""),
                    new_generation,
                    node_id,
                    int(expected_generation),
                ),
            )
            if ticket:
                await db.execute(
                    "UPDATE earnapp_replacement_tickets SET used_at = datetime('now') WHERE id = ?",
                    (int(ticket["id"]),),
                )
            updated = await (
                await db.execute("SELECT * FROM earnapp_logical_nodes WHERE logical_node_id = ?", (node_id,))
            ).fetchone()
            await db.commit()
            return dict(updated)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def heartbeat_earnapp_node(
    logical_node_id: str,
    worker_id: int,
    *,
    generation: int,
    device_id: str = "",
    proxy_id: int = 0,
) -> bool:
    node_id = str(logical_node_id or "").strip()
    supplied_device_id = str(device_id or "").strip()
    supplied_proxy_id = int(proxy_id or 0)
    if not node_id or not supplied_device_id or supplied_proxy_id <= 0:
        return False
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                UPDATE earnapp_logical_nodes
                SET state = 'ACTIVE', last_heartbeat_at = datetime('now'), recovery_started_at = NULL,
                    recovery_hold_until = NULL, updated_at = datetime('now')
                WHERE logical_node_id = ? AND assigned_worker_id = ? AND generation = ?
                  AND device_id = ? AND current_proxy_id = ?
                  AND state IN ('ACTIVE', 'RECOVERY_HOLD')
                """,
                (node_id, int(worker_id), int(generation), supplied_device_id, supplied_proxy_id),
            )
            if not cursor.rowcount:
                await db.rollback()
                return False
            await db.execute(
                """
                UPDATE earnapp_replacement_tickets
                SET used_at = datetime('now')
                WHERE logical_node_id = ? AND generation = ? AND used_at IS NULL
                """,
                (node_id, int(generation)),
            )
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def get_earnapp_account_control_route(
    account_id: int, *, include_released: bool = False, healthy_only: bool = False
) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        active = "" if include_released else "AND r.state = 'ACTIVE'"
        eligibility = f"AND {_earnapp_proxy_eligible_sql('pe')}" if healthy_only else ""
        row = await (
            await db.execute(
                f"""
                SELECT r.*, pe.endpoint, pe.host, pe.port, pe.protocol, pe.username,
                       pe.password_enc, pe.exit_ip, pe.status, pe.ip_type, pe.country_code, pe.country_name,
                       pe.last_checked_at
                FROM earnapp_account_control_routes r
                JOIN proxy_endpoints pe ON pe.id = r.proxy_id
                WHERE r.account_id = ? {active} {eligibility}
                LIMIT 1
                """,
                (int(account_id),),
            )
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        encrypted = str(data.pop("password_enc", "") or "")
        if encrypted:
            data["password"] = decrypt_value(encrypted)
        return data
    finally:
        await db.close()


async def update_earnapp_lifecycle(
    logical_node_id: str, decision: Any, *, usage: float | None = None, window_started_at: str | None = None
) -> bool:
    """Persist the pure lifecycle decision without touching identity or leases."""
    db = await _get_db()
    try:
        fields = [
            "lifecycle_action = ?",
            "same_proxy_recreates = ?",
            "rotate_count = ?",
            "updated_at = datetime('now')",
        ]
        values: list[Any] = [str(decision.action), int(decision.same_proxy_recreates), int(decision.rotate_count)]
        if usage is not None:
            fields.append("usage_baseline = ?")
            values.append(float(usage))
        if window_started_at is not None:
            fields.append("window_started_at = ?")
            values.append(str(window_started_at))
        values.append(str(logical_node_id))
        cursor = await db.execute(
            f"UPDATE earnapp_logical_nodes SET {', '.join(fields)} WHERE logical_node_id = ?", values
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def release_earnapp_account_control_route(
    account_id: int,
    *,
    expected_proxy_id: int,
    reason: str,
) -> bool:
    """CAS-release an unhealthy pre-node collector route."""
    if await _protected_earnapp_account_reference(int(account_id)):
        return False
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                UPDATE earnapp_account_control_routes
                SET state = 'RELEASED', released_at = datetime('now'), release_reason = ?,
                    updated_at = datetime('now')
                WHERE account_id = ? AND proxy_id = ? AND state = 'ACTIVE'
                """,
                (str(reason or "EARNAPP_CONTROL_ROUTE_RELEASED")[:300], int(account_id), int(expected_proxy_id)),
            )
            await db.commit()
            return bool(cursor.rowcount)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def get_earnapp_account_node_routes(account_id: int, *, healthy_only: bool = True) -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        eligibility = f"AND {_earnapp_proxy_eligible_sql('pe')}" if healthy_only else ""
        cursor = await db.execute(
            f"""
            SELECT n.logical_node_id, n.state, n.current_proxy_id AS proxy_id,
                   pe.endpoint, pe.host, pe.port, pe.protocol, pe.username, pe.password_enc,
                   pe.exit_ip, pe.status, pe.ip_type, pe.country_code, pe.country_name,
                   pe.last_checked_at
            FROM earnapp_logical_nodes n
            JOIN proxy_endpoints pe ON pe.id = n.current_proxy_id
            WHERE n.account_id = ? AND n.state IN ('ACTIVE', 'RECOVERY_HOLD') {eligibility}
            ORDER BY CASE n.state WHEN 'ACTIVE' THEN 0 ELSE 1 END, n.logical_node_id
            """,
            (int(account_id),),
        )
        rows: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            data = dict(row)
            encrypted = str(data.pop("password_enc", "") or "")
            if encrypted:
                data["password"] = decrypt_value(encrypted)
            rows.append(data)
        return rows
    finally:
        await db.close()


async def lease_earnapp_account_control_proxy(account_id: int) -> dict[str, Any] | None:
    if await _protected_earnapp_account_reference(int(account_id)):
        return None
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            existing = await (
                await db.execute(
                    """
                    SELECT r.*, pe.endpoint, pe.host, pe.port, pe.protocol, pe.username,
                           pe.password_enc, pe.exit_ip, pe.status, pe.ip_type
                    FROM earnapp_account_control_routes r
                    JOIN proxy_endpoints pe ON pe.id = r.proxy_id
                    WHERE r.account_id = ? AND r.state = 'ACTIVE'
                    LIMIT 1
                    """,
                    (int(account_id),),
                )
            ).fetchone()
            if existing:
                await db.commit()
                data = dict(existing)
                encrypted = str(data.pop("password_enc", "") or "")
                if encrypted:
                    data["password"] = decrypt_value(encrypted)
                return data

            has_nodes = await (
                await db.execute(
                    """
                    SELECT 1 FROM earnapp_logical_nodes
                    WHERE account_id = ? AND state != 'RETIRED'
                    LIMIT 1
                    """,
                    (int(account_id),),
                )
            ).fetchone()
            if has_nodes:
                await db.rollback()
                return None
            candidate = await (
                await db.execute(
                    f"""
                    SELECT pe.* FROM proxy_endpoints pe
                    WHERE {_earnapp_proxy_eligible_sql("pe")}
                      AND NOT EXISTS (
                          SELECT 1
                          FROM proxy_assignments legacy
                          JOIN proxy_endpoints legacy_proxy ON legacy_proxy.id = legacy.proxy_id
                          WHERE legacy.proxy_id = pe.id
                            OR (trim(coalesce(pe.exit_ip, '')) != '' AND legacy_proxy.exit_ip = pe.exit_ip)
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM provider_proxy_leases occupied
                          LEFT JOIN proxy_endpoints occupied_proxy ON occupied_proxy.id = occupied.proxy_id
                          WHERE occupied.released_at IS NULL
                            AND (occupied.proxy_id = pe.id
                                 OR (trim(coalesce(pe.exit_ip, '')) != ''
                                     AND (occupied.exit_ip = pe.exit_ip OR occupied_proxy.exit_ip = pe.exit_ip)))
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM earnapp_account_control_routes control
                          JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                          WHERE control.state = 'ACTIVE'
                            AND (control.proxy_id = pe.id
                                 OR (trim(coalesce(pe.exit_ip, '')) != '' AND control_proxy.exit_ip = pe.exit_ip))
                      )
                      AND {_active_earnapp_reservation_exclusion_sql("pe")}
                    ORDER BY pe.id
                    LIMIT 1
                    """
                )
            ).fetchone()
            if not candidate:
                await db.rollback()
                return None
            await db.execute(
                """
                INSERT INTO earnapp_account_control_routes (account_id, proxy_id, state)
                VALUES (?, ?, 'ACTIVE')
                ON CONFLICT(account_id) DO UPDATE SET
                    proxy_id = excluded.proxy_id, state = 'ACTIVE', assigned_logical_node_id = '',
                    leased_at = datetime('now'), released_at = NULL, release_reason = '', updated_at = datetime('now')
                """,
                (int(account_id), int(candidate["id"])),
            )
            await db.commit()
            data = dict(candidate)
            data["account_id"] = int(account_id)
            data["proxy_id"] = int(data["id"])
            encrypted = str(data.pop("password_enc", "") or "")
            if encrypted:
                data["password"] = decrypt_value(encrypted)
            return data
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def transfer_earnapp_control_route_to_node(
    account_id: int, logical_node_id: str, *, worker_id: int, country_code: str = ""
) -> dict[str, Any] | None:
    """Atomically turn an account-control route into the first node's provider lease."""
    node_id = str(logical_node_id or "").strip()
    if earnapp_policy.is_protected_runtime_reference(node_id):
        return None
    if await _protected_earnapp_account_reference(int(account_id)):
        return None
    async with _earnapp_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            requested_country = str(country_code or "").strip().upper()
            control = await (
                await db.execute(
                    """
                    SELECT r.*, pe.exit_ip, pe.country_code
                    FROM earnapp_account_control_routes r
                    JOIN proxy_endpoints pe ON pe.id = r.proxy_id
                    WHERE r.account_id = ? AND r.state = 'ACTIVE'
                    LIMIT 1
                    """,
                    (int(account_id),),
                )
            ).fetchone()
            if not control:
                await db.rollback()
                return None
            if requested_country and str(control["country_code"] or "").strip().upper() != requested_country:
                await db.rollback()
                return None
            await db.execute(
                """
                INSERT INTO provider_proxy_leases
                    (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                VALUES ('earnapp', ?, ?, ?, ?)
                """,
                (int(worker_id), node_id, int(control["proxy_id"]), str(control["exit_ip"] or "")),
            )
            await db.execute(
                """
                UPDATE earnapp_account_control_routes
                SET state = 'TRANSFERRED', assigned_logical_node_id = ?, released_at = datetime('now'),
                    release_reason = 'FIRST_NODE_CREATED', updated_at = datetime('now')
                WHERE account_id = ? AND state = 'ACTIVE'
                """,
                (node_id, int(account_id)),
            )
            await db.commit()
            return {"proxy_id": int(control["proxy_id"]), "exit_ip": str(control["exit_ip"] or "")}
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def save_earnapp_snapshot(account_id: int, snapshot: Mapping[str, Any]) -> int:
    devices = snapshot.get("devices") if isinstance(snapshot, Mapping) else []
    sanitized_devices = list(devices) if isinstance(devices, list) else []
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO earnapp_account_snapshots
                (account_id, money_balance, money_total, online_nodes, offline_nodes, devices_json, payment_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(account_id),
                float(snapshot.get("money_balance") or 0),
                float(snapshot.get("money_total") or 0),
                int(snapshot.get("online_nodes") or 0),
                int(snapshot.get("offline_nodes") or 0),
                json.dumps(sanitized_devices, sort_keys=True, separators=(",", ":")),
                json.dumps(
                    snapshot.get("payment") if isinstance(snapshot.get("payment"), Mapping) else {},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid or 0)
    finally:
        await db.close()


async def get_latest_earnapp_snapshot(account_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        row = await (
            await db.execute(
                """
                SELECT * FROM earnapp_account_snapshots
                WHERE account_id = ? ORDER BY id DESC LIMIT 1
                """,
                (int(account_id),),
            )
        ).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_earnapp_proxy_capacity() -> dict[str, int]:
    """Return residential, canonical, currently free EarnApp capacity."""
    db = await _get_db()
    try:
        eligible_sql = _earnapp_proxy_eligible_sql("pe")
        row = await (
            await db.execute(
                f"""
                SELECT
                    COUNT(DISTINCT pe.exit_ip) AS eligible,
                    COUNT(DISTINCT CASE WHEN NOT EXISTS (
                                  SELECT 1
                                  FROM proxy_assignments legacy
                                  JOIN proxy_endpoints legacy_proxy ON legacy_proxy.id = legacy.proxy_id
                                  WHERE legacy.proxy_id = pe.id
                                    OR (trim(coalesce(pe.exit_ip, '')) != ''
                                        AND legacy_proxy.exit_ip = pe.exit_ip)
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM provider_proxy_leases occupied
                                  LEFT JOIN proxy_endpoints occupied_proxy ON occupied_proxy.id = occupied.proxy_id
                                  WHERE occupied.released_at IS NULL
                                    AND (occupied.proxy_id = pe.id
                                         OR (trim(coalesce(pe.exit_ip, '')) != ''
                                             AND (occupied.exit_ip = pe.exit_ip
                                                  OR occupied_proxy.exit_ip = pe.exit_ip)))
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM earnapp_account_control_routes control
                                  JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                                  WHERE control.state = 'ACTIVE'
                                    AND (control.proxy_id = pe.id
                                         OR (trim(coalesce(pe.exit_ip, '')) != ''
                                             AND control_proxy.exit_ip = pe.exit_ip))
                              )
                              AND {_active_earnapp_reservation_exclusion_sql("pe")}
                         THEN pe.exit_ip END) AS leaseable,
                    COUNT(DISTINCT CASE WHEN EXISTS (
                                  SELECT 1
                                  FROM provider_proxy_leases occupied
                                  LEFT JOIN proxy_endpoints occupied_proxy ON occupied_proxy.id = occupied.proxy_id
                                  WHERE occupied.released_at IS NULL
                                    AND (occupied.proxy_id = pe.id
                                         OR (trim(coalesce(pe.exit_ip, '')) != ''
                                             AND (occupied.exit_ip = pe.exit_ip
                                                  OR occupied_proxy.exit_ip = pe.exit_ip)))
                              ) THEN pe.exit_ip END) AS occupied,
                    COUNT(DISTINCT CASE WHEN EXISTS (
                                  SELECT 1
                                  FROM earnapp_account_control_routes control
                                  JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                                  WHERE control.state = 'ACTIVE'
                                    AND (control.proxy_id = pe.id
                                         OR (trim(coalesce(pe.exit_ip, '')) != ''
                                             AND control_proxy.exit_ip = pe.exit_ip))
                              ) THEN pe.exit_ip END) AS control_routes
                FROM proxy_endpoints pe
                WHERE {eligible_sql}
                """
            )
        ).fetchone()
        nodes = await (
            await db.execute(
                """
                SELECT
                    SUM(state = 'ACTIVE') AS active_nodes,
                    SUM(state = 'RECOVERY_HOLD') AS recovery_hold_nodes
                FROM earnapp_logical_nodes
                WHERE state != 'RETIRED'
                """
            )
        ).fetchone()
        return {
            "eligible": int(row["eligible"] or 0),
            "leaseable": int(row["leaseable"] or 0),
            "ready": int(row["leaseable"] or 0),
            "used": int(row["occupied"] or 0) + int(row["control_routes"] or 0),
            "occupied": int(row["occupied"] or 0),
            "control_routes": int(row["control_routes"] or 0),
            "active_nodes": int(nodes["active_nodes"] or 0),
            "recovery_hold_nodes": int(nodes["recovery_hold_nodes"] or 0),
            "recovery_hold_seconds": 3600,
        }
    finally:
        await db.close()


# --- Deployments ---


async def save_runtime_asset(provider: str, asset_kind: str, value: str) -> None:
    from app import runtime_assets

    await set_config(runtime_assets.config_key(provider, asset_kind), value)


async def get_runtime_asset(provider: str, asset_kind: str) -> str | None:
    from app import runtime_assets

    value = await get_config(runtime_assets.config_key(provider, asset_kind))
    return str(value) if value is not None else None


async def list_runtime_assets() -> list[dict[str, Any]]:
    from app import runtime_assets

    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT key, value FROM config WHERE key LIKE 'runtime_asset::%::secret' ORDER BY key"
        )
        rows = []
        for row in await cursor.fetchall():
            parsed = runtime_assets.parse_config_key(row["key"])
            if not parsed:
                continue
            provider, asset_kind = parsed
            rows.append({"provider": provider, "asset_kind": asset_kind, "is_set": bool(row["value"])})
        return rows
    finally:
        await db.close()


async def save_deployment(
    slug: str,
    container_id: str,
    env_vars_encrypted: str = "",
    status: str = "running",
    spec: dict[str, Any] | None = None,
) -> None:
    """Record a deployment, including the spec that was actually used.

    ``spec`` is serialised and encrypted at rest because it embeds the service's
    environment, which carries credentials. Passing None preserves any spec
    already recorded for this slug rather than blanking it, so a caller that
    only knows the container id (an external service, a status update) cannot
    erase the deployment's memory of itself.
    """
    spec_encrypted = ""
    if spec is not None:
        try:
            spec_encrypted = encrypt_value(json.dumps(spec, sort_keys=True))
        except (TypeError, ValueError):
            # A deploy must not fail because the bookkeeping did. Degrade to
            # today's behaviour - no record, so the next redeploy rebuilds from
            # the catalog - but say so loudly, because that redeploy is then the
            # one that can silently change the container.
            _logger.error(
                "Could not serialise the deployed spec for %s; it will NOT be recorded, "
                "so a later redeploy will fall back to the catalog",
                slug,
                exc_info=True,
            )
    else:
        existing = await get_deployment(slug)
        if existing:
            spec_encrypted = existing.get("spec_encrypted") or ""

    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT OR REPLACE INTO deployments
                (slug, container_id, env_vars_encrypted, spec_encrypted, deployed_at, status)
            VALUES (?, ?, ?, ?, datetime('now'), ?)
            """,
            (slug, container_id, env_vars_encrypted, spec_encrypted, status),
        )
        await db.commit()
    finally:
        await db.close()


async def get_deployment_spec(slug: str) -> dict[str, Any] | None:
    """Return the spec this service was actually deployed with, or None.

    None means "no record" - a deployment made before this existed, or one whose
    stored spec can no longer be decrypted. Callers must fall back to the
    catalog in that case rather than deploying a half-remembered spec, which
    would be worse than deploying a fresh one.
    """
    row = await get_deployment(slug)
    if not row:
        return None
    blob = row.get("spec_encrypted") or ""
    if not blob:
        return None
    raw = decrypt_value(blob)
    if not raw:
        # decrypt_value returns "" on a key mismatch and has already logged it.
        _logger.warning("Recorded spec for %s could not be decrypted; falling back to the catalog", slug)
        return None
    try:
        spec = json.loads(raw)
    except ValueError:
        _logger.warning("Recorded spec for %s is not valid JSON; falling back to the catalog", slug)
        return None
    return spec if isinstance(spec, dict) else None


async def get_deployments() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM deployments ORDER BY slug")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_deployment(slug: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM deployments WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def set_deployment_status(slug: str, status: str) -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE deployments SET status = ? WHERE slug = ?", (status, slug))
        await db.commit()
    finally:
        await db.close()


async def remove_deployment(slug: str) -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM deployments WHERE slug = ?", (slug,))
        await db.commit()
    finally:
        await db.close()


async def save_provider_instance(
    slug: str,
    instance_id: str,
    *,
    worker_id: int | None = None,
    mode: str = "direct",
    container_id: str = "",
    sidecar_id: str = "",
    proxy_id: int | None = None,
    status: str = "planned",
    spec: dict[str, Any] | None = None,
) -> None:
    if str(slug or "").strip().lower() == "earnapp" and earnapp_policy.is_protected_runtime_reference(instance_id):
        raise ValueError("protected EarnApp node is inspection-only")
    spec_encrypted = ""
    if spec is not None:
        try:
            spec_encrypted = encrypt_value(json.dumps(spec, sort_keys=True))
        except (TypeError, ValueError):
            _logger.error("Could not serialise provider instance spec for %s", instance_id, exc_info=True)
    else:
        existing = await get_provider_instance(instance_id)
        if existing:
            spec_encrypted = existing.get("spec_encrypted") or ""

    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO provider_instances
                (instance_id, slug, worker_id, mode, container_id, sidecar_id, proxy_id, status, spec_encrypted, deployed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? != '' THEN datetime('now') ELSE NULL END, datetime('now'))
            ON CONFLICT(instance_id) DO UPDATE SET
                slug = excluded.slug,
                worker_id = excluded.worker_id,
                mode = excluded.mode,
                container_id = excluded.container_id,
                sidecar_id = excluded.sidecar_id,
                proxy_id = excluded.proxy_id,
                status = excluded.status,
                spec_encrypted = excluded.spec_encrypted,
                deployed_at = COALESCE(excluded.deployed_at, provider_instances.deployed_at),
                updated_at = datetime('now')
            """,
            (
                instance_id,
                slug,
                worker_id,
                mode,
                container_id,
                sidecar_id,
                proxy_id,
                status,
                spec_encrypted,
                container_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_provider_instance(instance_id: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM provider_instances WHERE instance_id = ?", (instance_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_provider_instance_spec(instance_id: str) -> dict[str, Any] | None:
    row = await get_provider_instance(instance_id)
    blob = (row or {}).get("spec_encrypted") or ""
    if not blob:
        return None
    raw = decrypt_value(blob)
    if not raw:
        return None
    try:
        spec = json.loads(raw)
    except ValueError:
        return None
    return spec if isinstance(spec, dict) else None


async def list_provider_instances(*, slug: str | None = None, worker_id: int | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if slug is not None:
        clauses.append("slug = ?")
        params.append(slug)
    if worker_id is not None:
        clauses.append("worker_id = ?")
        params.append(worker_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'provider_instances'")
        if not await cursor.fetchone():
            return []
        cursor = await db.execute(
            f"SELECT * FROM provider_instances {where} ORDER BY slug, mode, instance_id",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def remove_provider_instance(instance_id: str) -> bool:
    if earnapp_policy.is_protected_runtime_reference(instance_id):
        return False
    db = await _get_db()
    try:
        cursor = await db.execute("DELETE FROM provider_instances WHERE instance_id = ?", (instance_id,))
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


# --- Users ---


async def has_any_users() -> bool:
    """Check if any user accounts exist (for first-run detection)."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
        row = await cursor.fetchone()
        return row["cnt"] > 0
    finally:
        await db.close()


async def create_user(username: str, hashed_password: str, role: str = "viewer") -> int:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, hashed_password, role),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def create_first_owner(username: str, hashed_password: str) -> int | None:
    """Atomically create the first owner account.

    Returns the new id, or ``None`` if any account already exists (lost the
    first-run race). The ``INSERT ... WHERE NOT EXISTS`` makes the "one owner per
    setup token" guarantee safe against two concurrent first-run registrations,
    which a check-then-act (``has_any_users()`` then ``create_user()``) could not.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO users (username, password, role) SELECT ?, ?, 'owner' WHERE NOT EXISTS (SELECT 1 FROM users)",
            (username, hashed_password),
        )
        await db.commit()
        if cursor.rowcount != 1:
            return None
        return cursor.lastrowid
    finally:
        await db.close()


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_users() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def list_users_with_pwd_epoch() -> list[dict[str, Any]]:
    """Return [{id, password_changed_at}, ...] for warming the auth pwd-epoch cache."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT id, password_changed_at FROM users")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_user_role(user_id: int, role: str) -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        await db.commit()
    finally:
        await db.close()


async def delete_user(user_id: int) -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
    finally:
        await db.close()


# Kept in sync with auth.SESSION_MAX_AGE (30 days); duplicated as a plain constant
# so this module doesn't import auth (which would create a cycle).
_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


async def revoke_user_sessions(user_id: int, revoked_before: float) -> None:
    """Durably invalidate a user's outstanding session cookies.

    Records that any session token for ``user_id`` issued before ``revoked_before``
    must be rejected. This table has no FK to ``users``, so the revocation outlives
    a deleted row and is restored into auth's in-memory epoch cache at startup —
    that is what stops a deleted/demoted account's still-valid 30-day cookie from
    regaining access after a UI restart. The write is monotonic (an older timestamp
    can never lower an existing revocation), and rows whose window has fully elapsed
    are pruned since the tokens they guarded have themselves expired.
    """
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO session_revocations (user_id, revoked_before)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET revoked_before = excluded.revoked_before
            WHERE excluded.revoked_before > session_revocations.revoked_before
            """,
            (user_id, revoked_before),
        )
        await db.execute(
            "DELETE FROM session_revocations WHERE revoked_before < ?",
            (revoked_before - _SESSION_MAX_AGE_SECONDS,),
        )
        await db.commit()
    finally:
        await db.close()


async def list_session_revocations() -> list[dict[str, Any]]:
    """Return [{user_id, revoked_before}, ...] for warming the auth epoch cache."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT user_id, revoked_before FROM session_revocations")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_user_password(user_id: int, hashed_password: str) -> None:
    """Update a user's password and record the change timestamp."""
    import time

    db = await _get_db()
    try:
        await db.execute(
            "UPDATE users SET password = ?, password_changed_at = ? WHERE id = ?",
            (hashed_password, time.time(), user_id),
        )
        await db.commit()
    finally:
        await db.close()


# --- User Preferences ---


async def get_user_preferences(user_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def save_user_preferences(
    user_id: int,
    setup_mode: str = "fresh",
    selected_categories: str = "[]",
    timezone: str = "UTC",
    setup_completed: bool = False,
) -> None:
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO user_preferences
                (user_id, setup_mode, selected_categories, timezone, setup_completed, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                setup_mode = excluded.setup_mode,
                selected_categories = excluded.selected_categories,
                timezone = excluded.timezone,
                setup_completed = excluded.setup_completed,
                updated_at = datetime('now')
            """,
            (user_id, setup_mode, selected_categories, timezone, int(setup_completed)),
        )
        await db.commit()
    finally:
        await db.close()


async def mark_setup_completed(user_id: int) -> None:
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE user_preferences SET setup_completed = 1, updated_at = datetime('now') WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
    finally:
        await db.close()


# --- Workers (Fleet) ---


async def upsert_worker(
    client_id: str,
    name: str = "",
    url: str = "",
    containers: str = "[]",
    apps: str = "[]",
    system_info: str = "{}",
) -> int:
    """Register or update a worker by client_id. Returns the worker ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO workers (client_id, name, url, containers, apps, system_info, status, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?, 'online', datetime('now'))
            ON CONFLICT(client_id) DO UPDATE SET
                -- Never replace a name we already have with a Docker container ID.
                --
                -- Inside a container, socket.gethostname() returns the first 12
                -- hex characters of the container ID, and Docker regenerates that
                -- on every recreate -- which is what an image bump does. So a
                -- worker with no CASHPILOT_WORKER_NAME set reported a brand-new
                -- meaningless name after every upgrade, and the fleet page's
                -- labels churned while the machines had not changed at all.
                -- Observed live: three workers renamed themselves during a
                -- routine 1.10.1 -> 1.11.34 roll.
                --
                -- The worker's IDENTITY is already protected from this
                -- (worker_api._name_is_ephemeral guards client_id); this is the
                -- display name, which was not.
                --
                -- GLOB matches the whole string, so 12 character classes means
                -- exactly 12 hex characters -- the container-ID shape and
                -- nothing else. A real hostname, or anything the user set, is
                -- kept and wins.
                name = CASE
                    WHEN excluded.name GLOB '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]' AND COALESCE(workers.name, '') != ''
                        THEN workers.name
                    ELSE excluded.name
                END,
                url = excluded.url,
                containers = excluded.containers,
                apps = excluded.apps,
                system_info = excluded.system_info,
                status = 'online',
                last_heartbeat = datetime('now')
            """,
            (client_id, name, url, containers, apps, system_info),
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM workers WHERE client_id = ?", (client_id,))
        row = await cursor.fetchone()
        return row["id"]
    finally:
        await db.close()


async def get_worker(worker_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_worker_by_client_id(client_id: str) -> dict[str, Any] | None:
    """Return a worker by its durable client identity."""
    value = str(client_id or "").strip()
    if not value:
        return None
    db = await _get_db()
    try:
        row = await (await db.execute("SELECT * FROM workers WHERE client_id = ?", (value,))).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_workers() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM workers ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def set_worker_status(worker_id: int, status: str) -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE workers SET status = ? WHERE id = ?", (status, worker_id))
        await db.commit()
    finally:
        await db.close()


async def count_worker_heartbeats(worker_id: int, *, healthy_only: bool = True) -> int:
    db = await _get_db()
    try:
        if healthy_only:
            cursor = await db.execute(
                "SELECT COUNT(*) AS cnt FROM workers WHERE id = ? AND status = 'online' AND last_heartbeat IS NOT NULL",
                (worker_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT COUNT(*) AS cnt FROM workers WHERE id = ? AND last_heartbeat IS NOT NULL",
                (worker_id,),
            )
        row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0
    finally:
        await db.close()


async def _protected_earnapp_worker_reference(db: Any, worker_id: int) -> str:
    """Return the protected node/runtime that would be changed by a worker delete."""
    protected_nodes = tuple(sorted(earnapp_policy.PROTECTED_LOGICAL_NODE_IDS))
    protected_runtimes = tuple(sorted(earnapp_policy.protected_runtime_references()))
    if not protected_nodes or not protected_runtimes:
        return ""

    node_placeholders = ",".join("?" for _ in protected_nodes)
    runtime_placeholders = ",".join("?" for _ in protected_runtimes)
    row = await (
        await db.execute(
            f"""
            SELECT n.logical_node_id AS reference
            FROM earnapp_logical_nodes n
            WHERE n.logical_node_id IN ({node_placeholders})
              AND (n.assigned_worker_id = ? OR n.last_worker_id = ?)
            UNION ALL
            SELECT l.instance_id AS reference
            FROM provider_proxy_leases l
            WHERE l.provider_slug = 'earnapp'
              AND l.worker_id = ?
              AND l.instance_id IN ({runtime_placeholders})
              AND l.released_at IS NULL
            UNION ALL
            SELECT pi.instance_id AS reference
            FROM provider_instances pi
            WHERE pi.slug = 'earnapp'
              AND pi.worker_id = ?
              AND pi.instance_id IN ({runtime_placeholders})
            UNION ALL
            SELECT r.logical_node_id AS reference
            FROM earnapp_proxy_reservations r
            WHERE r.worker_id = ?
              AND r.logical_node_id IN ({node_placeholders})
              AND r.state = 'ACTIVE'
            UNION ALL
            SELECT t.logical_node_id AS reference
            FROM earnapp_replacement_tickets t
            WHERE t.target_worker_id = ?
              AND t.logical_node_id IN ({node_placeholders})
              AND t.used_at IS NULL
            LIMIT 1
            """,
            (
                *protected_nodes,
                int(worker_id),
                int(worker_id),
                int(worker_id),
                *protected_runtimes,
                int(worker_id),
                *protected_runtimes,
                int(worker_id),
                *protected_nodes,
                int(worker_id),
                *protected_nodes,
            ),
        )
    ).fetchone()
    return str(row["reference"] or "") if row else ""


async def delete_worker(worker_id: int) -> None:
    async with _nkn_wallet_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            protected_reference = await _protected_earnapp_worker_reference(db, worker_id)
            if protected_reference:
                raise ProtectedEarnAppWorkerReference(
                    f"worker {worker_id} still references protected EarnApp runtime {protected_reference}"
                )
            await _ensure_nkn_wallets_table(db)
            cursor = await db.execute(
                "SELECT 1 FROM nkn_wallets WHERE state = 'LEASED' AND leased_to_worker_id = ? LIMIT 1",
                (worker_id,),
            )
            if await cursor.fetchone():
                raise NknWalletLeaseActive(f"worker {worker_id} still owns an active NKN wallet lease")
            await db.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


# --- Proxy egress ---


async def upsert_proxy_provider(
    name: str,
    type: str,
    *,
    base_url: str = "",
    api_key: str | None = None,
    enabled: bool = True,
) -> int:
    api_key_enc = encrypt_value(api_key.strip()) if api_key is not None and api_key.strip() else ""
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO proxy_providers (name, type, base_url, api_key_enc, enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(type, name) DO UPDATE SET
                base_url = excluded.base_url,
                api_key_enc = CASE WHEN excluded.api_key_enc != '' THEN excluded.api_key_enc ELSE proxy_providers.api_key_enc END,
                enabled = excluded.enabled
            """,
            (name.strip(), type.strip().lower(), base_url.strip(), api_key_enc, 1 if enabled else 0),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id FROM proxy_providers WHERE type = ? AND name = ?",
            (type.strip().lower(), name.strip()),
        )
        row = await cur.fetchone()
        return int(row["id"])
    finally:
        await db.close()


async def list_proxy_providers() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            SELECT id, name, type, base_url, enabled, last_synced_at, created_at,
                   CASE WHEN api_key_enc IS NOT NULL AND api_key_enc != '' THEN 1 ELSE 0 END AS api_key_set
            FROM proxy_providers
            ORDER BY name
            """
        )
        return [
            {
                **dict(row),
                "enabled": bool(row["enabled"]),
                "api_key_set": bool(row["api_key_set"]),
            }
            for row in await cur.fetchall()
        ]
    finally:
        await db.close()


async def get_proxy_provider(provider_id: int, *, include_secret: bool = False) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cur = await db.execute("SELECT * FROM proxy_providers WHERE id = ?", (provider_id,))
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["api_key_set"] = bool(data.get("api_key_enc"))
        if include_secret:
            data["api_key"] = decrypt_value(data.get("api_key_enc") or "")
        data.pop("api_key_enc", None)
        return data
    finally:
        await db.close()


async def upsert_proxy_endpoints_returning_ids(provider_id: int, proxies: Sequence[Mapping[str, Any]]) -> list[int]:
    """Upsert endpoints and return the exact row id for each accepted input row."""
    db = await _get_db()
    try:
        proxy_ids: list[int] = []
        for proxy in proxies:
            protocol = str(proxy.get("protocol") or "socks5").lower()
            if protocol not in {"http", "socks5"}:
                continue
            host = str(proxy.get("host") or "")
            port = int(proxy.get("port") or 0)
            username = str(proxy.get("username") or "")
            endpoint = str(proxy.get("endpoint") or f"{host}:{port}")
            provider_proxy_id = str(proxy.get("provider_proxy_id") or "").strip()
            if not provider_proxy_id:
                provider_proxy_id = f"{protocol}:{host}:{port}:{username}"
            password = str(proxy.get("password") or "")
            await db.execute(
                """
                INSERT INTO proxy_endpoints (
                    provider_id, provider_proxy_id, endpoint, host, port, protocol,
                    username, password_enc, location, status, expiry_date, days_left,
                    hours_left, exit_ip, udp_ok, latency_ms, last_synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(provider_id, provider_proxy_id) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    host = excluded.host,
                    port = excluded.port,
                    protocol = excluded.protocol,
                    username = excluded.username,
                    password_enc = CASE WHEN excluded.password_enc != '' THEN excluded.password_enc ELSE proxy_endpoints.password_enc END,
                    location = CASE WHEN excluded.location != '' THEN excluded.location ELSE proxy_endpoints.location END,
                    status = CASE WHEN excluded.status != 'unknown' THEN excluded.status ELSE proxy_endpoints.status END,
                    expiry_date = excluded.expiry_date,
                    days_left = excluded.days_left,
                    hours_left = excluded.hours_left,
                    exit_ip = CASE WHEN excluded.exit_ip IS NOT NULL AND excluded.exit_ip != '' THEN excluded.exit_ip ELSE proxy_endpoints.exit_ip END,
                    udp_ok = COALESCE(excluded.udp_ok, proxy_endpoints.udp_ok),
                    latency_ms = COALESCE(excluded.latency_ms, proxy_endpoints.latency_ms),
                    last_synced_at = datetime('now')
                """,
                (
                    provider_id,
                    provider_proxy_id,
                    endpoint,
                    host,
                    port,
                    protocol,
                    username,
                    encrypt_value(password) if password else "",
                    str(proxy.get("location") or ""),
                    str(proxy.get("status") or "unknown"),
                    proxy.get("expiry_date"),
                    proxy.get("days_left"),
                    proxy.get("hours_left"),
                    proxy.get("exit_ip"),
                    proxy.get("udp_ok"),
                    proxy.get("latency_ms"),
                ),
            )
            cursor = await db.execute(
                "SELECT id FROM proxy_endpoints WHERE provider_id = ? AND provider_proxy_id = ?",
                (provider_id, provider_proxy_id),
            )
            row = await cursor.fetchone()
            if row:
                proxy_ids.append(int(row["id"]))
        await db.execute("UPDATE proxy_providers SET last_synced_at = datetime('now') WHERE id = ?", (provider_id,))
        await db.commit()
        return proxy_ids
    finally:
        await db.close()


async def upsert_proxy_endpoints(provider_id: int, proxies: Sequence[Mapping[str, Any]]) -> int:
    """Backward-compatible endpoint upsert returning the largest touched id."""
    proxy_ids = await upsert_proxy_endpoints_returning_ids(provider_id, proxies)
    return max(proxy_ids, default=0)


async def create_proxy_import_batch(
    provider_id: int,
    *,
    source_name: str,
    raw_input: str,
    parsed_rows: Sequence[Mapping[str, Any]],
    proxy_ids: Sequence[int],
) -> int:
    """Persist encrypted raw import evidence without exposing it in pool JSON."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO proxy_import_batches
                (provider_id, source_name, raw_input_enc, parsed_count, imported_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(provider_id),
                str(source_name or "manual"),
                encrypt_value(str(raw_input or "")) if raw_input else "",
                len(parsed_rows),
                len(proxy_ids),
            ),
        )
        batch_id = int(cursor.lastrowid or 0)
        for row_number, (parsed, proxy_id) in enumerate(zip(parsed_rows, proxy_ids, strict=False), start=1):
            raw_line = str(parsed.get("_raw_line") or "").strip()
            await db.execute(
                """
                INSERT INTO proxy_import_rows (batch_id, row_number, proxy_id, raw_line_enc)
                VALUES (?, ?, ?, ?)
                """,
                (batch_id, row_number, int(proxy_id), encrypt_value(raw_line) if raw_line else ""),
            )
        await db.commit()
        return batch_id
    finally:
        await db.close()


async def list_proxy_pool() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            SELECT pe.id, pe.provider_id, pp.name AS provider_name, pp.type AS provider_type,
                   pe.provider_proxy_id, pe.endpoint, pe.host, pe.port, pe.protocol,
                   pe.location, pe.status, pe.expiry_date, pe.days_left,
                   pe.hours_left, pe.exit_ip, pe.udp_ok, pe.latency_ms,
                   pe.last_synced_at, pe.last_checked_at,
                   pe.country_code, pe.country_name, pe.geo_source, pe.geo_confidence, pe.geo_checked_at,
                   pe.ip_type, pe.ip_type_source, pe.ip_type_confidence, pe.ip_type_checked_at,
                   pe.duplicate_egress, pe.canonical_proxy_id, pe.duplicate_reason,
                   CASE WHEN pe.password_enc IS NOT NULL AND pe.password_enc != '' THEN 1 ELSE 0 END AS password_set,
                   pa.worker_id AS assigned_worker_id,
                   pawns.reason AS pawns_mask_reason,
                   earnapp.probe_status AS earnapp_probe_status,
                   earnapp.verdict AS earnapp_verdict,
                   earnapp.eligibility AS earnapp_eligibility,
                   earnapp.reason AS earnapp_probe_reason,
                   earnapp.latency_ms AS earnapp_latency_ms,
                   earnapp.checked_at AS earnapp_checked_at,
                   scoped.provider_slug AS scoped_provider_slug,
                   scoped.worker_id AS scoped_worker_id,
                   scoped.instance_id AS scoped_instance_id
            FROM proxy_endpoints pe
            LEFT JOIN proxy_providers pp ON pp.id = pe.provider_id
            LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
            LEFT JOIN proxy_provider_masks pawns ON pawns.proxy_id = pe.id AND pawns.provider_slug = 'iproyal'
            LEFT JOIN proxy_probe_results earnapp ON earnapp.id = (
                SELECT MAX(pr.id) FROM proxy_probe_results pr
                WHERE pr.proxy_id = pe.id AND pr.profile = 'earnapp_wss'
            )
                AND trim(coalesce(earnapp.exit_ip, '')) != ''
                AND earnapp.exit_ip = pe.exit_ip
            LEFT JOIN provider_proxy_leases scoped ON scoped.proxy_id = pe.id AND scoped.released_at IS NULL
            ORDER BY pp.name, pe.endpoint
            """
        )
        rows = []
        for row in await cur.fetchall():
            item = dict(row)
            item["password_set"] = bool(item["password_set"])
            item["duplicate_egress"] = bool(item.get("duplicate_egress"))
            if item.get("udp_ok") is not None:
                item["udp_ok"] = bool(item["udp_ok"])
            rows.append(item)
        return rows
    finally:
        await db.close()


async def list_proxy_pool_page(
    *,
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    provider: str = "",
    location: str = "",
    ip_type: str = "",
    earnapp: str = "",
    duplicate: str = "",
    sort: str = "provider_name",
    direction: str = "asc",
) -> dict[str, Any]:
    """Return one operator page while keeping aggregate inventory context."""
    size = min(100_000, max(1, int(page_size or 20)))
    requested_page = max(1, int(page or 1))
    location_expr = _proxy_location_sql()
    ip_type_expr = """CASE
        WHEN trim(coalesce(pe.exit_ip, '')) = '' AND lower(coalesce(pe.status, '')) = 'dead' THEN 'Generic check failed'
        WHEN trim(coalesce(pe.exit_ip, '')) = '' THEN 'Egress unresolved'
        WHEN trim(coalesce(pe.ip_type, 'unknown')) IN ('', 'unknown') THEN 'Metadata pending'
        ELSE pe.ip_type
    END"""
    earnapp_expr = """CASE
        WHEN lower(coalesce(pe.status, '')) = 'dead' THEN 'skipped'
        WHEN trim(coalesce(earnapp.verdict, '')) = '' THEN 'not checked'
        ELSE coalesce(nullif(trim(earnapp.eligibility), ''), 'unknown')
    END"""
    select_sql = f"""
        SELECT pe.id, pe.provider_id, pp.name AS provider_name, pp.type AS provider_type,
               pe.provider_proxy_id, pe.endpoint, pe.host, pe.port, pe.protocol,
               pe.location, pe.status, pe.expiry_date, pe.days_left,
               pe.hours_left, pe.exit_ip, pe.udp_ok, pe.latency_ms,
               pe.last_synced_at, pe.last_checked_at,
               pe.country_code, pe.country_name, pe.geo_source, pe.geo_confidence, pe.geo_checked_at,
               pe.ip_type, pe.ip_type_source, pe.ip_type_confidence, pe.ip_type_checked_at,
               pe.duplicate_egress, pe.canonical_proxy_id, pe.duplicate_reason,
               CASE WHEN pe.password_enc IS NOT NULL AND pe.password_enc != '' THEN 1 ELSE 0 END AS password_set,
               pa.worker_id AS assigned_worker_id,
               pawns.reason AS pawns_mask_reason,
               earnapp.probe_status AS earnapp_probe_status,
               earnapp.verdict AS earnapp_verdict,
               earnapp.eligibility AS earnapp_eligibility,
               earnapp.reason AS earnapp_probe_reason,
               earnapp.latency_ms AS earnapp_latency_ms,
               earnapp.checked_at AS earnapp_checked_at,
               scoped.provider_slug AS scoped_provider_slug,
               scoped.worker_id AS scoped_worker_id,
               scoped.instance_id AS scoped_instance_id,
               {location_expr} AS display_location,
               {ip_type_expr} AS display_ip_type,
               {earnapp_expr} AS display_earnapp,
               CASE WHEN {_active_earnapp_reservation_exclusion_sql("pe")} THEN 0 ELSE 1 END
                   AS earnapp_reservation_free
        FROM proxy_endpoints pe
        LEFT JOIN proxy_providers pp ON pp.id = pe.provider_id
        LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
        LEFT JOIN proxy_provider_masks pawns ON pawns.proxy_id = pe.id AND pawns.provider_slug = 'iproyal'
        LEFT JOIN proxy_probe_results earnapp ON earnapp.id = (
            SELECT MAX(pr.id) FROM proxy_probe_results pr
            WHERE pr.proxy_id = pe.id AND pr.profile = 'earnapp_wss'
        )
            AND trim(coalesce(earnapp.exit_ip, '')) != ''
            AND earnapp.exit_ip = pe.exit_ip
        LEFT JOIN provider_proxy_leases scoped ON scoped.proxy_id = pe.id AND scoped.released_at IS NULL
    """
    clauses: list[str] = []
    params: list[Any] = []
    query = str(search or "").strip().lower()
    if query:
        pattern = f"%{query}%"
        clauses.append(
            f"""(
                lower(coalesce(pp.name, '')) LIKE ? OR lower(coalesce(pe.endpoint, '')) LIKE ? OR
                lower(coalesce(pe.protocol, '')) LIKE ? OR lower(coalesce(pe.country_code, '')) LIKE ? OR
                lower(coalesce(pe.country_name, '')) LIKE ? OR lower(coalesce(pe.status, '')) LIKE ? OR
                lower(coalesce(earnapp.verdict, '')) LIKE ? OR lower(coalesce(earnapp.reason, '')) LIKE ? OR
                lower(coalesce(pe.duplicate_reason, '')) LIKE ? OR lower(coalesce(pe.expiry_date, '')) LIKE ? OR
                lower(coalesce(CAST(pa.worker_id AS TEXT), '')) LIKE ? OR lower({location_expr}) LIKE ? OR
                lower({ip_type_expr}) LIKE ? OR lower(coalesce(pe.exit_ip, 'Egress unresolved')) LIKE ? OR
                lower({earnapp_expr}) LIKE ?
            )"""
        )
        params.extend([pattern] * 15)
    if str(provider or "").strip():
        clauses.append("pp.name = ?")
        params.append(str(provider).strip())
    location_value = str(location or "").strip()
    if location_value:
        location_code = canonical_proxy_country_code(location_value)
        location_code = location_code or _COUNTRY_CODE_ALIASES.get(location_value.lower(), "")
        if location_code:
            # The code predicate is authoritative; the alias branch preserves
            # compatibility with older rows that have only country_name.
            alias_names = [name for name, code in _COUNTRY_CODE_ALIASES.items() if code == location_code]
            code_names = [location_code]
            if location_code == "GB":
                code_names.append("UK")
            clauses.append(
                "(upper(trim(coalesce(pe.country_code, ''))) IN (" + ",".join("?" for _ in code_names) + ") OR "
                "lower(trim(coalesce(pe.country_name, ''))) IN (" + ",".join("?" for _ in alias_names) + "))"
            )
            params.extend([*code_names, *alias_names])
        else:
            clauses.append(f"{location_expr} = ?")
            params.append(location_value)
    if str(ip_type or "").strip():
        clauses.append(f"{ip_type_expr} = ?")
        params.append(str(ip_type).strip())
    if str(earnapp or "").strip():
        clauses.append(f"{earnapp_expr} = ?")
        params.append(str(earnapp).strip())
    duplicate_value = str(duplicate or "").strip().lower()
    if duplicate_value == "duplicate":
        clauses.append("coalesce(pe.duplicate_egress, 0) = 1")
    elif duplicate_value == "canonical":
        clauses.append("coalesce(pe.duplicate_egress, 0) = 0")
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sort_expressions = {
        "provider_name": "lower(coalesce(pp.name, ''))",
        "endpoint": "lower(coalesce(pe.endpoint, ''))",
        "protocol": "lower(coalesce(pe.protocol, ''))",
        "location": f"lower({location_expr})",
        "ip_type": f"lower({ip_type_expr})",
        "exit_ip": "lower(coalesce(pe.exit_ip, ''))",
        "status": "lower(coalesce(pe.status, ''))",
        "latency_ms": "coalesce(pe.latency_ms, 2147483647)",
        "earnapp_eligibility": f"lower({earnapp_expr})",
        "duplicate_egress": "coalesce(pe.duplicate_egress, 0)",
        "assigned_worker_id": "coalesce(pa.worker_id, scoped.worker_id, 0)",
        "last_checked_at": "coalesce(pe.last_checked_at, '')",
    }
    order_by = sort_expressions.get(str(sort or "").strip(), sort_expressions["provider_name"])
    order_direction = "DESC" if str(direction or "").strip().lower() == "desc" else "ASC"
    db = await _get_db()
    try:
        total = int(
            (await (await db.execute(f"SELECT COUNT(*) AS n FROM ({select_sql}{where_sql})", params)).fetchone())["n"]
        )
        pages = max(1, math.ceil(total / size))
        current_page = min(pages, requested_page)
        offset = (current_page - 1) * size
        item_cursor = await db.execute(
            f"{select_sql}{where_sql} ORDER BY {order_by} {order_direction}, pe.id {order_direction} LIMIT ? OFFSET ?",
            (*params, size, offset),
        )
        items: list[dict[str, Any]] = []
        for row in await item_cursor.fetchall():
            item = dict(row)
            item["location"] = item["display_location"]
            item.pop("display_location", None)
            item.pop("display_ip_type", None)
            item.pop("display_earnapp", None)
            item.pop("earnapp_reservation_free", None)
            item["password_set"] = bool(item.get("password_set"))
            item["duplicate_egress"] = bool(item.get("duplicate_egress"))
            if item.get("udp_ok") is not None:
                item["udp_ok"] = bool(item["udp_ok"])
            items.append(item)
        aggregate = dict(
            await (
                await db.execute(
                    f"""SELECT
                        COUNT(*) AS inventory,
                        SUM(lower(coalesce(status, '')) = 'alive') AS generic_live,
                        SUM(lower(coalesce(status, '')) = 'dead') AS generic_dead,
                        SUM(assigned_worker_id IS NOT NULL) AS legacy_leased,
                        SUM(scoped_provider_slug IS NOT NULL) AS scoped_leased,
                        SUM(assigned_worker_id IS NULL AND scoped_provider_slug IS NULL) AS unassigned_inventory,
                        SUM(coalesce(duplicate_egress, 0) = 1) AS duplicates,
                        SUM(display_earnapp = 'eligible') AS earnapp_eligible,
                        SUM(display_earnapp NOT IN ('not checked', 'skipped')) AS earnapp_checked,
                        SUM(display_earnapp = 'unknown') AS earnapp_unknown,
                        SUM(display_earnapp = 'not checked') AS earnapp_not_checked,
                        SUM(display_earnapp = 'skipped') AS earnapp_skipped,
                        SUM(trim(coalesce(exit_ip, '')) != '') AS egress_known,
                        SUM(trim(coalesce(exit_ip, '')) = '') AS egress_unresolved,
                        SUM(display_location = 'Metadata pending') AS location_pending,
                        SUM(display_ip_type = 'Metadata pending') AS ip_type_pending,
                        SUM(display_location = 'Metadata pending' OR display_ip_type = 'Metadata pending') AS metadata_pending,
                        SUM(lower(coalesce(status, '')) = 'alive' AND trim(coalesce(exit_ip, '')) != '' AND coalesce(duplicate_egress, 0) = 0) AS generic_usable,
                        SUM(lower(coalesce(status, '')) = 'alive' AND trim(coalesce(exit_ip, '')) != '' AND coalesce(duplicate_egress, 0) = 0 AND assigned_worker_id IS NULL AND scoped_provider_slug IS NULL) AS canonical_available,
                        SUM(lower(coalesce(status, '')) = 'alive' AND trim(coalesce(exit_ip, '')) != '' AND coalesce(duplicate_egress, 0) = 0 AND display_earnapp = 'eligible' AND assigned_worker_id IS NULL AND scoped_provider_slug IS NULL AND earnapp_reservation_free = 1) AS earnapp_leaseable
                    FROM ({select_sql})"""
                )
            ).fetchone()
        )
        type_counts = dict(
            await (
                await db.execute(
                    f"""SELECT
                        SUM(lower(coalesce(protocol, '')) = 'http') AS http,
                        SUM(lower(coalesce(protocol, '')) = 'socks5') AS socks5,
                        SUM(ip_type = 'residential') AS residential,
                        SUM(ip_type = 'datacenter') AS datacenter,
                        SUM(ip_type = 'hosting') AS hosting,
                        SUM(ip_type = 'vpn') AS vpn,
                        SUM(ip_type = 'proxy') AS proxy,
                        SUM(coalesce(ip_type, 'unknown') IN ('', 'unknown')) AS unknown
                    FROM ({select_sql})"""
                )
            ).fetchone()
        )

        async def distinct_values(expression: str) -> list[str]:
            cursor = await db.execute(
                f"SELECT DISTINCT value FROM (SELECT {expression} AS value FROM ({select_sql})) WHERE trim(coalesce(value, '')) != '' ORDER BY value"
            )
            return [str(row["value"]) for row in await cursor.fetchall()]

        filters = {
            "providers": await distinct_values("provider_name"),
            "locations": await distinct_values("display_location"),
            "ip_types": await distinct_values("display_ip_type"),
            "earnapp_states": await distinct_values("display_earnapp"),
        }
        return {
            "items": items,
            "page": current_page,
            "page_size": size,
            "total": total,
            "pages": pages,
            "counts": {key: int(value or 0) for key, value in aggregate.items()},
            "type_counts": {key: int(value or 0) for key, value in type_counts.items()},
            "filters": filters,
        }
    finally:
        await db.close()


async def mask_proxy_for_provider(proxy_id: int, provider_slug: str, reason: str = "") -> bool:
    provider_slug = str(provider_slug or "").strip()
    if int(proxy_id or 0) <= 0 or not provider_slug:
        return False
    db = await _get_db()
    try:
        cur = await db.execute("SELECT id FROM proxy_endpoints WHERE id = ?", (int(proxy_id),))
        if not await cur.fetchone():
            return False
        await db.execute(
            """
            INSERT INTO proxy_provider_masks (proxy_id, provider_slug, reason, masked_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(proxy_id, provider_slug) DO UPDATE SET
                reason = excluded.reason,
                updated_at = datetime('now')
            """,
            (int(proxy_id), provider_slug, str(reason or "")),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def unmask_proxy_for_provider(proxy_id: int | Sequence[int], provider_slug: str) -> int:
    provider_slug = str(provider_slug or "").strip()
    ids = [
        int(x)
        for x in (proxy_id if isinstance(proxy_id, Sequence) and not isinstance(proxy_id, (str, bytes)) else [proxy_id])
        if int(x) > 0
    ]
    if not ids or not provider_slug:
        return 0
    db = await _get_db()
    try:
        placeholders = ",".join("?" for _ in ids)
        cursor = await db.execute(
            f"DELETE FROM proxy_provider_masks WHERE provider_slug = ? AND proxy_id IN ({placeholders})",
            [provider_slug, *ids],
        )
        await db.commit()
        return int(cursor.rowcount or 0)
    finally:
        await db.close()


async def proxy_masked_for_provider(proxy_id: int, provider_slug: str) -> bool:
    provider_slug = str(provider_slug or "").strip()
    if int(proxy_id or 0) <= 0 or not provider_slug:
        return False
    db = await _get_db()
    try:
        if provider_slug == "earnapp":
            await _expire_earnapp_provider_masks(db)
            await db.commit()
        cur = await db.execute(
            "SELECT 1 FROM proxy_provider_masks WHERE proxy_id = ? AND provider_slug = ? LIMIT 1",
            (int(proxy_id), provider_slug),
        )
        return bool(await cur.fetchone())
    finally:
        await db.close()


async def delete_proxy_endpoints(proxy_ids: Sequence[int] | None = None, *, status: str | None = None) -> int:
    ids = [int(x) for x in (proxy_ids or []) if int(x) > 0]
    status = str(status or "").strip().lower()
    if not ids and not status:
        return 0
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            protected_node = await _protected_earnapp_proxy_reference(db, proxy_ids=ids, status=status)
            if protected_node:
                await db.rollback()
                raise ProtectedEarnAppProxyError(f"proxy is referenced by protected EarnApp node {protected_node}")
            if ids:
                placeholders = ",".join("?" for _ in ids)
                await db.execute(
                    f"DELETE FROM earnapp_account_control_routes WHERE proxy_id IN ({placeholders})",
                    ids,
                )
                cursor = await db.execute(f"DELETE FROM proxy_endpoints WHERE id IN ({placeholders})", ids)
            else:
                await db.execute(
                    """
                    DELETE FROM earnapp_account_control_routes
                    WHERE proxy_id IN (
                        SELECT id FROM proxy_endpoints WHERE lower(status) = ?
                    )
                    """,
                    (status,),
                )
                cursor = await db.execute("DELETE FROM proxy_endpoints WHERE lower(status) = ?", (status,))
            await db.commit()
            return int(cursor.rowcount or 0)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def _ensure_myst_wallets_table(db: Any) -> None:
    await db.executescript(_MYST_WALLETS_SCHEMA)
    cursor = await db.execute("PRAGMA table_info(myst_wallets)")
    cols = {row["name"] for row in await cursor.fetchall()}
    if "leased_to_client_id" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN leased_to_client_id TEXT NOT NULL DEFAULT ''")
    if "leased_at" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN leased_at TEXT")
    if "release_reason" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN release_reason TEXT NOT NULL DEFAULT ''")
    if "wallet_assignment_version" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN wallet_assignment_version INTEGER NOT NULL DEFAULT 0")
    if "node_identity" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN node_identity TEXT NOT NULL DEFAULT ''")
    if "runtime_status" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN runtime_status TEXT NOT NULL DEFAULT ''")
    if "public_ip" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN public_ip TEXT NOT NULL DEFAULT ''")
    if "last_heartbeat_at" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN last_heartbeat_at TEXT")
    if "evidence_json" not in cols:
        await db.execute("ALTER TABLE myst_wallets ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'")


async def _ensure_nkn_wallets_table(db: Any) -> None:
    await db.executescript(_NKN_WALLETS_SCHEMA)
    cursor = await db.execute("PRAGMA table_info(nkn_wallets)")
    cols = {row["name"] for row in await cursor.fetchall()}
    if "leased_to_client_id" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN leased_to_client_id TEXT NOT NULL DEFAULT ''")
    if "leased_at" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN leased_at TEXT")
    if "release_reason" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN release_reason TEXT NOT NULL DEFAULT ''")
    if "wallet_assignment_version" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN wallet_assignment_version INTEGER NOT NULL DEFAULT 0")
    if "node_identity" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN node_identity TEXT NOT NULL DEFAULT ''")
    if "runtime_status" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN runtime_status TEXT NOT NULL DEFAULT ''")
    if "public_ip" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN public_ip TEXT NOT NULL DEFAULT ''")
    if "last_heartbeat_at" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN last_heartbeat_at TEXT")
    if "evidence_json" not in cols:
        await db.execute("ALTER TABLE nkn_wallets ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'")


async def import_myst_wallets(raw: str) -> int:
    from app.myst_wallets import iter_wallet_records

    rows = list(iter_wallet_records(raw))
    if not rows:
        return 0
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        for row in rows:
            await db.execute(
                """
                INSERT INTO myst_wallets (
                    wallet_fingerprint, raw_wallet_enc, address, state, funding, updated_at
                )
                VALUES (?, ?, ?, 'AVAILABLE', 'FUNDED', datetime('now'))
                ON CONFLICT(wallet_fingerprint) DO UPDATE SET
                    raw_wallet_enc = excluded.raw_wallet_enc,
                    address = excluded.address,
                    updated_at = datetime('now')
                """,
                (
                    row["wallet_fingerprint"],
                    encrypt_value(row["raw_wallet"]),
                    row["address"],
                ),
            )
        await db.commit()
        return len(rows)
    finally:
        await db.close()


async def import_nkn_wallets_from_zip(raw_zip: bytes) -> int:
    from app.nkn_wallets import iter_wallet_records_from_zip

    rows = list(iter_wallet_records_from_zip(raw_zip))
    return await import_nkn_wallet_records(rows)


async def import_nkn_wallet_records(records: Sequence[Mapping[str, Any]]) -> int:
    from app.nkn_wallets import normalize_wallet_record

    rows = [row for record in records if (row := normalize_wallet_record(dict(record)))]
    if not rows:
        return 0
    db = await _get_db()
    try:
        await _ensure_nkn_wallets_table(db)
        for row in rows:
            await db.execute(
                """
                INSERT INTO nkn_wallets (
                    wallet_fingerprint, folder_name, wallet_json_enc, wallet_pswd_enc, address, state, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'AVAILABLE', datetime('now'))
                ON CONFLICT(wallet_fingerprint) DO UPDATE SET
                    folder_name = excluded.folder_name,
                    wallet_json_enc = excluded.wallet_json_enc,
                    wallet_pswd_enc = excluded.wallet_pswd_enc,
                    address = excluded.address,
                    updated_at = datetime('now')
                """,
                (
                    row["wallet_fingerprint"],
                    row["folder_name"],
                    encrypt_value(row["wallet_json"]),
                    encrypt_value(row["wallet_pswd"]),
                    row["address"],
                ),
            )
        await db.commit()
        return len(rows)
    finally:
        await db.close()


async def list_myst_wallets() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        await _repair_myst_wallet_addresses(db)
        cursor = await db.execute(
            """
            SELECT id, wallet_fingerprint, address, state, funding, leased_to_worker_id, leased_to_client_id,
                   release_reason, wallet_assignment_version,
                   node_identity, runtime_status, public_ip, last_heartbeat_at,
                   quarantined_reason, imported_at, updated_at
            FROM myst_wallets
            ORDER BY id DESC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def list_nkn_wallets() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        await _ensure_nkn_wallets_table(db)
        cursor = await db.execute(
            """
            SELECT id, wallet_fingerprint, folder_name, address, state,
                   leased_to_worker_id, leased_to_client_id, release_reason,
                   wallet_assignment_version, node_identity, runtime_status,
                   public_ip, last_heartbeat_at, evidence_json, quarantined_reason,
                   imported_at, updated_at
            FROM nkn_wallets
            ORDER BY id DESC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


def _nkn_slot_from_client_id(client_id: str) -> str:
    value = str(client_id or "").strip()
    marker = ":nkn:"
    slot = value.split(marker, 1)[1] if marker in value else ""
    if not slot.startswith("ipv4-") or not slot[6:].isdigit():
        return ""
    return slot


def _redact_nkn_evidence(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep runtime evidence JSON-safe and prevent accidental secret persistence."""
    secret_fragments = ("wallet", "password", "passwd", "seed", "private", "mnemonic", "secret")

    def clean(value: Any, key: str = "") -> Any:
        lowered = key.lower()
        if any(fragment in lowered for fragment in secret_fragments):
            return "[redacted]"
        if isinstance(value, Mapping):
            return {str(k): clean(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item, key) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    value = clean(dict(evidence or {}))
    return value if isinstance(value, dict) else {}


async def lease_nkn_wallet(
    client_id: str,
    worker_id: int | None = None,
    *,
    public_ip: str = "",
) -> dict[str, Any] | None:
    """Lease one exclusive NKN wallet for a worker/slot client id.

    The compare-and-swap transaction makes retries idempotent and prevents two
    workers from receiving the same wallet or public-IP assignment.
    """
    client_id = str(client_id or "").strip()
    slot_id = _nkn_slot_from_client_id(client_id)
    if not client_id or not slot_id:
        return None
    public_ip = str(public_ip or "").strip()
    async with _nkn_wallet_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await _ensure_nkn_wallets_table(db)
            current_cursor = await db.execute(
                "SELECT * FROM nkn_wallets WHERE state = 'LEASED' AND leased_to_client_id = ? ORDER BY id DESC LIMIT 1",
                (client_id,),
            )
            current = await current_cursor.fetchone()
            if current:
                current_ip = str(current["public_ip"] or "")
                if public_ip and current_ip and current_ip != public_ip:
                    await db.rollback()
                    return None
                if public_ip and not current_ip:
                    await db.execute(
                        "UPDATE nkn_wallets SET public_ip = ?, updated_at = datetime('now') WHERE id = ?",
                        (public_ip, current["id"]),
                    )
                    current = dict(current)
                    current["public_ip"] = public_ip
                else:
                    current = dict(current)
                await db.commit()
                current["wallet_json"] = decrypt_value(current.pop("wallet_json_enc") or "")
                current["wallet_pswd"] = decrypt_value(current.pop("wallet_pswd_enc") or "")
                return current

            if public_ip:
                conflict_cursor = await db.execute(
                    "SELECT id FROM nkn_wallets WHERE state = 'LEASED' AND public_ip = ? LIMIT 1",
                    (public_ip,),
                )
                if await conflict_cursor.fetchone():
                    await db.rollback()
                    return None
            available_cursor = await db.execute(
                "SELECT * FROM nkn_wallets WHERE state = 'AVAILABLE' ORDER BY id LIMIT 1"
            )
            row = await available_cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            next_version = int(row["wallet_assignment_version"] or 0) + 1
            updated = await db.execute(
                """
                UPDATE nkn_wallets
                SET state = 'LEASED', leased_to_worker_id = ?, leased_to_client_id = ?,
                    leased_at = datetime('now'), release_reason = '', public_ip = ?,
                    wallet_assignment_version = ?, updated_at = datetime('now')
                WHERE id = ? AND state = 'AVAILABLE' AND wallet_assignment_version = ?
                """,
                (worker_id, client_id, public_ip, next_version, row["id"], row["wallet_assignment_version"]),
            )
            if int(updated.rowcount or 0) != 1:
                await db.rollback()
                return None
            await db.commit()
            item = dict(row)
            item.update(
                {
                    "state": "LEASED",
                    "leased_to_worker_id": worker_id,
                    "leased_to_client_id": client_id,
                    "leased_at": datetime.now(UTC).isoformat(),
                    "release_reason": "",
                    "public_ip": public_ip,
                    "wallet_assignment_version": next_version,
                    "wallet_json": decrypt_value(item.pop("wallet_json_enc") or ""),
                    "wallet_pswd": decrypt_value(item.pop("wallet_pswd_enc") or ""),
                }
            )
            return item
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def reserve_nkn_publisher_wallet(
    *, public_ip: str, client_id: str = "nkn-chaindb-publisher"
) -> dict[str, Any] | None:
    """Reserve one NKN wallet for the dedicated ChainDB publisher.

    Publisher reservations use a separate state and client-id namespace, so a
    publisher wallet can never be handed to an ordinary worker slot. Repeating
    the same request is idempotent for the same public IP.
    """
    public_ip = str(public_ip or "").strip()
    client_id = str(client_id or "").strip()
    if not public_ip or not client_id.startswith("nkn-chaindb-publisher"):
        return None
    lease_client_id = f"{client_id}:{public_ip}"
    async with _nkn_wallet_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await _ensure_nkn_wallets_table(db)
            current_cursor = await db.execute(
                "SELECT * FROM nkn_wallets WHERE state = 'RESERVED' AND leased_to_client_id = ? LIMIT 1",
                (lease_client_id,),
            )
            current = await current_cursor.fetchone()
            if current:
                item = dict(current)
                item["wallet_json"] = decrypt_value(item.pop("wallet_json_enc") or "")
                item["wallet_pswd"] = decrypt_value(item.pop("wallet_pswd_enc") or "")
                item["reservation_created"] = False
                await db.commit()
                return item
            available_cursor = await db.execute(
                "SELECT * FROM nkn_wallets WHERE state = 'AVAILABLE' ORDER BY id LIMIT 1"
            )
            row = await available_cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            next_version = int(row["wallet_assignment_version"] or 0) + 1
            updated = await db.execute(
                """
                UPDATE nkn_wallets
                SET state = 'RESERVED', leased_to_worker_id = NULL, leased_to_client_id = ?,
                    leased_at = datetime('now'), release_reason = '', public_ip = ?,
                    wallet_assignment_version = ?, updated_at = datetime('now')
                WHERE id = ? AND state = 'AVAILABLE' AND wallet_assignment_version = ?
                """,
                (lease_client_id, public_ip, next_version, row["id"], row["wallet_assignment_version"]),
            )
            if int(updated.rowcount or 0) != 1:
                await db.rollback()
                return None
            await db.commit()
            item = dict(row)
            item.update(
                {
                    "state": "RESERVED",
                    "leased_to_worker_id": None,
                    "leased_to_client_id": lease_client_id,
                    "leased_at": datetime.now(UTC).isoformat(),
                    "public_ip": public_ip,
                    "wallet_assignment_version": next_version,
                    "wallet_json": decrypt_value(item.pop("wallet_json_enc") or ""),
                    "wallet_pswd": decrypt_value(item.pop("wallet_pswd_enc") or ""),
                    "reservation_created": True,
                }
            )
            return item
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def release_nkn_publisher_wallet(
    *, wallet_id: int, public_ip: str, client_id: str = "nkn-chaindb-publisher"
) -> bool:
    """Release only the exact publisher reservation identified by its IP."""
    lease_client_id = f"{str(client_id).strip()}:{str(public_ip).strip()}"
    db = await _open_transaction_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_nkn_wallets_table(db)
        cursor = await db.execute(
            """
            UPDATE nkn_wallets
            SET state = 'AVAILABLE', leased_to_worker_id = NULL, leased_to_client_id = '',
                leased_at = NULL, public_ip = '', release_reason = 'PUBLISHER_RELEASED',
                node_identity = '', runtime_status = '', last_heartbeat_at = NULL, evidence_json = '{}',
                wallet_assignment_version = wallet_assignment_version + 1, updated_at = datetime('now')
            WHERE id = ? AND state = 'RESERVED' AND leased_to_client_id = ?
            """,
            (int(wallet_id), lease_client_id),
        )
        await db.commit()
        return bool(cursor.rowcount)
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_nkn_publisher_reservation(
    *, wallet_id: int, public_ip: str, client_id: str = "nkn-chaindb-publisher"
) -> dict[str, Any] | None:
    """Return only public metadata for the exact publisher reservation."""
    lease_client_id = f"{str(client_id).strip()}:{str(public_ip).strip()}"
    db = await _get_db()
    try:
        await _ensure_nkn_wallets_table(db)
        cursor = await db.execute(
            """
            SELECT id, state, leased_to_client_id, public_ip, wallet_assignment_version,
                   leased_at, updated_at
            FROM nkn_wallets
            WHERE id = ? AND state = 'RESERVED' AND leased_to_client_id = ?
            LIMIT 1
            """,
            (int(wallet_id), lease_client_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def release_nkn_wallet(
    wallet_id: int,
    client_id: str,
    *,
    release_reason: str = "",
    wallet_assignment_version: int | None = None,
) -> bool:
    """Release an NKN wallet only when the lease token still matches."""
    if wallet_assignment_version is None or not _nkn_slot_from_client_id(client_id):
        return False
    db = await _open_transaction_connection()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_nkn_wallets_table(db)
        cursor = await db.execute(
            """
            UPDATE nkn_wallets
            SET state = 'AVAILABLE', leased_to_worker_id = NULL, leased_to_client_id = '',
                leased_at = NULL, public_ip = '', release_reason = ?,
                node_identity = '', runtime_status = '', last_heartbeat_at = NULL, evidence_json = '{}',
                wallet_assignment_version = wallet_assignment_version + 1,
                updated_at = datetime('now')
            WHERE id = ? AND state = 'LEASED' AND leased_to_client_id = ?
              AND wallet_assignment_version = ?
            """,
            (str(release_reason or ""), int(wallet_id), str(client_id), int(wallet_assignment_version)),
        )
        await db.commit()
        return bool(cursor.rowcount)
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def sync_nkn_wallet_runtime(
    wallet_id: int,
    client_id: str,
    *,
    wallet_assignment_version: int,
    node_identity: str = "",
    runtime_status: str = "",
    public_ip: str = "",
    evidence: Mapping[str, Any] | None = None,
) -> bool:
    """CAS-update NKN runtime evidence from an authenticated worker heartbeat."""
    if not _nkn_slot_from_client_id(client_id) or wallet_assignment_version <= 0:
        return False
    evidence_json = json.dumps(_redact_nkn_evidence(evidence), sort_keys=True)
    db = await _get_db()
    try:
        await _ensure_nkn_wallets_table(db)
        cursor = await db.execute(
            """
            UPDATE nkn_wallets
            SET node_identity = ?, runtime_status = ?,
                last_heartbeat_at = datetime('now'), evidence_json = ?, updated_at = datetime('now')
            WHERE id = ? AND state = 'LEASED' AND leased_to_client_id = ?
              AND wallet_assignment_version = ?
              AND (NULLIF(?, '') IS NULL OR public_ip = ?)
            """,
            (
                str(node_identity or "")[:256],
                str(runtime_status or "")[:128],
                evidence_json,
                int(wallet_id),
                str(client_id),
                int(wallet_assignment_version),
                str(public_ip or ""),
                str(public_ip or ""),
            ),
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def reclaim_stale_nkn_wallets(*, stale_after_seconds: int = 900) -> list[dict[str, Any]]:
    """Reclaim leases from offline workers after the 15-minute grace period."""
    threshold = max(900, int(stale_after_seconds))
    db = await _open_transaction_connection()
    reclaimed: list[dict[str, Any]] = []
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_nkn_wallets_table(db)
        cursor = await db.execute(
            """
            SELECT nw.id, nw.wallet_assignment_version, nw.leased_to_client_id,
                   nw.leased_to_worker_id, w.last_heartbeat
            FROM nkn_wallets nw
            JOIN workers w ON w.id = nw.leased_to_worker_id
            WHERE nw.state = 'LEASED' AND w.status = 'offline'
              AND w.last_heartbeat IS NOT NULL
              AND (julianday('now') - julianday(w.last_heartbeat)) * 86400 >= ?
            ORDER BY nw.id
            """,
            (threshold,),
        )
        rows = await cursor.fetchall()
        for row in rows:
            client_id = str(row["leased_to_client_id"] or "")
            slot_id = _nkn_slot_from_client_id(client_id)
            if not slot_id:
                continue
            old_version = int(row["wallet_assignment_version"] or 0)
            updated = await db.execute(
                """
                UPDATE nkn_wallets
                SET state = 'AVAILABLE', leased_to_worker_id = NULL, leased_to_client_id = '',
                    leased_at = NULL, public_ip = '', release_reason = 'WORKER_HEARTBEAT_STALE_15M',
                    node_identity = '', runtime_status = '', last_heartbeat_at = NULL, evidence_json = '{}',
                    wallet_assignment_version = wallet_assignment_version + 1,
                    updated_at = datetime('now')
                WHERE id = ? AND state = 'LEASED' AND leased_to_client_id = ?
                  AND wallet_assignment_version = ?
                """,
                (row["id"], client_id, old_version),
            )
            if int(updated.rowcount or 0) == 1:
                reclaimed.append(
                    {
                        "wallet_id": int(row["id"]),
                        "wallet_assignment_version": old_version + 1,
                        "previous_wallet_assignment_version": old_version,
                        "lease_client_id": client_id,
                        "worker_id": row["leased_to_worker_id"],
                        "slot_id": slot_id,
                    }
                )
        await db.commit()
        return reclaimed
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def export_myst_wallets(*, funding: str | None = None) -> list[str]:
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        query = "SELECT raw_wallet_enc FROM myst_wallets"
        params: list[Any] = []
        if funding:
            query += " WHERE funding = ?"
            params.append(funding.upper())
        query += " ORDER BY id"
        cursor = await db.execute(query, params)
        return [decrypt_value(row["raw_wallet_enc"] or "") for row in await cursor.fetchall()]
    finally:
        await db.close()


async def update_myst_wallet(
    wallet_id: int,
    *,
    state: str | None = None,
    funding: str | None = None,
    quarantined_reason: str | None = None,
    release_reason: str | None = None,
) -> bool:
    allowed_state = {"AVAILABLE", "LEASED", "QUARANTINED"}
    allowed_funding = {"FUNDED", "UNFUNDED"}
    updates: list[str] = []
    params: list[Any] = []
    if state is not None:
        value = state.upper()
        if value not in allowed_state:
            return False
        updates.append("state = ?")
        params.append(value)
    if funding is not None:
        value = funding.upper()
        if value not in allowed_funding:
            return False
        updates.append("funding = ?")
        params.append(value)
    if quarantined_reason is not None:
        updates.append("quarantined_reason = ?")
        params.append(quarantined_reason)
    if release_reason is not None:
        updates.append("release_reason = ?")
        params.append(release_reason)
    if not updates:
        return False
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        updates.append("updated_at = datetime('now')")
        params.append(wallet_id)
        cursor = await db.execute(
            f"UPDATE myst_wallets SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def lease_myst_wallet(
    client_id: str,
    worker_id: int | None = None,
    *,
    public_ip: str = "",
) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        normalized_public_ip = (public_ip or "").strip()
        if normalized_public_ip:
            cursor = await db.execute(
                """
                SELECT id
                FROM myst_wallets
                WHERE state = 'LEASED' AND public_ip = ? AND leased_to_client_id != ?
                LIMIT 1
                """,
                (normalized_public_ip, client_id),
            )
            if await cursor.fetchone():
                raise MystWalletPublicIpInUse(normalized_public_ip)
        cursor = await db.execute(
            """
            SELECT *
            FROM myst_wallets
            WHERE state = 'LEASED' AND leased_to_client_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (client_id,),
        )
        current = await cursor.fetchone()
        if current:
            if normalized_public_ip and not str(current["public_ip"] or "").strip():
                await db.execute(
                    "UPDATE myst_wallets SET public_ip = ?, updated_at = datetime('now') WHERE id = ?",
                    (normalized_public_ip, current["id"]),
                )
                await db.commit()
            item = dict(current)
            item["public_ip"] = normalized_public_ip or item.get("public_ip", "")
            item["raw_wallet"] = decrypt_value(item.pop("raw_wallet_enc") or "")
            return item
        cursor = await db.execute(
            """
            SELECT *
            FROM myst_wallets
            WHERE state = 'AVAILABLE' AND funding = 'FUNDED'
            ORDER BY id
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        if not row:
            return None
        await db.execute(
            """
            UPDATE myst_wallets
            SET state = 'LEASED',
                leased_to_worker_id = ?,
                leased_to_client_id = ?,
                leased_at = datetime('now'),
                release_reason = '',
                public_ip = ?,
                wallet_assignment_version = wallet_assignment_version + 1,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (worker_id, client_id, normalized_public_ip, row["id"]),
        )
        await db.commit()
        item = dict(row)
        item["state"] = "LEASED"
        item["leased_to_worker_id"] = worker_id
        item["leased_to_client_id"] = client_id
        item["leased_at"] = datetime.now(UTC).isoformat()
        item["release_reason"] = ""
        item["public_ip"] = normalized_public_ip
        item["wallet_assignment_version"] = int(item.get("wallet_assignment_version") or 0) + 1
        item["raw_wallet"] = decrypt_value(item.pop("raw_wallet_enc") or "")
        return item
    finally:
        await db.close()


async def release_myst_wallet(
    wallet_id: int,
    client_id: str,
    *,
    release_reason: str = "",
    wallet_assignment_version: int | None = None,
) -> bool:
    if wallet_assignment_version is None:
        return False
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        params: list[Any] = [release_reason, wallet_id, client_id, wallet_assignment_version]
        cursor = await db.execute(
            """
            UPDATE myst_wallets
            SET state = 'AVAILABLE',
                leased_to_worker_id = NULL,
                leased_to_client_id = '',
                leased_at = NULL,
                public_ip = '',
                release_reason = ?,
                updated_at = datetime('now')
            WHERE id = ? AND leased_to_client_id = ? AND wallet_assignment_version = ?
            """,
            params,
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


def _myst_wallet_unfunded(runtime_status: str, evidence: Mapping[str, Any]) -> bool:
    _ = runtime_status
    return str(evidence.get("registration_status") or "").strip().lower() == "unregistered"


def _myst_public_ip(evidence: Mapping[str, Any]) -> str:
    return str(evidence.get("public_ip") or evidence.get("egress_ip") or "").strip()


async def sync_myst_wallet_runtime(
    wallet_id: int,
    client_id: str,
    *,
    wallet_assignment_version: int | None = None,
    node_identity: str = "",
    runtime_status: str = "",
    evidence: Mapping[str, Any] | None = None,
) -> bool:
    evidence = evidence or {}
    unfunded = _myst_wallet_unfunded(runtime_status, evidence)
    public_ip = _myst_public_ip(evidence)
    if wallet_assignment_version is None:
        return False
    db = await _get_db()
    try:
        await _ensure_myst_wallets_table(db)
        if unfunded:
            params: list[Any] = [
                node_identity,
                runtime_status,
                json.dumps(evidence, sort_keys=True),
                wallet_id,
                client_id,
                wallet_assignment_version,
            ]
            cursor = await db.execute(
                """
                UPDATE myst_wallets
                SET state = 'AVAILABLE',
                    funding = 'UNFUNDED',
                    leased_to_worker_id = NULL,
                    leased_to_client_id = '',
                    leased_at = NULL,
                    public_ip = '',
                    release_reason = 'MYST_WALLET_UNFUNDED',
                    node_identity = ?,
                    runtime_status = ?,
                    last_heartbeat_at = datetime('now'),
                    evidence_json = ?,
                    updated_at = datetime('now')
                WHERE id = ? AND leased_to_client_id = ? AND wallet_assignment_version = ?
                """,
                params,
            )
        else:
            params = [
                node_identity,
                runtime_status,
                public_ip,
                json.dumps(evidence, sort_keys=True),
                wallet_id,
                client_id,
                wallet_assignment_version,
            ]
            cursor = await db.execute(
                """
                UPDATE myst_wallets
                SET node_identity = ?,
                    runtime_status = ?,
                    public_ip = ?,
                    last_heartbeat_at = datetime('now'),
                    evidence_json = ?,
                    updated_at = datetime('now')
                WHERE id = ? AND leased_to_client_id = ? AND wallet_assignment_version = ?
                """,
                params,
            )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def set_worker_proxy_assignment(
    worker_id: int, proxy_id: int | None, mode: str = "proxy", fallback: str = "hold"
) -> bool:
    mode = mode if mode in {"proxy", "direct", "auto"} else "proxy"
    fallback = fallback if fallback in {"hold", "rotate"} else "hold"
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT id FROM workers WHERE id = ?", (worker_id,))
            if not await cur.fetchone():
                await db.rollback()
                return False
            if proxy_id is not None:
                cur = await db.execute(
                    "SELECT id, exit_ip, duplicate_egress FROM proxy_endpoints WHERE id = ?", (proxy_id,)
                )
                endpoint = await cur.fetchone()
                if not endpoint or bool(endpoint["duplicate_egress"]):
                    await db.rollback()
                    return False
                cur = await db.execute(
                    "SELECT worker_id FROM proxy_assignments WHERE proxy_id = ? AND worker_id != ? LIMIT 1",
                    (proxy_id, worker_id),
                )
                if await cur.fetchone():
                    await db.rollback()
                    return False
                cur = await db.execute(
                    f"""
                    SELECT 1
                    FROM proxy_endpoints pe
                    WHERE pe.id = ?
                      AND {_active_earnapp_reservation_exclusion_sql("pe")}
                    LIMIT 1
                    """,
                    (int(proxy_id),),
                )
                if not await cur.fetchone():
                    await db.rollback()
                    return False
                exit_ip = str(endpoint["exit_ip"] or "").strip()
                cur = await db.execute(
                    """
                    SELECT 1
                    FROM earnapp_account_control_routes control
                    JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                    WHERE control.state = 'ACTIVE'
                      AND (control.proxy_id = ? OR (control_proxy.exit_ip != '' AND control_proxy.exit_ip = ?))
                    LIMIT 1
                    """,
                    (int(proxy_id), exit_ip),
                )
                if await cur.fetchone():
                    await db.rollback()
                    return False
                if exit_ip:
                    cur = await db.execute(
                        """
                        SELECT 1
                        FROM provider_proxy_leases scoped
                        WHERE scoped.released_at IS NULL AND scoped.exit_ip = ?
                        LIMIT 1
                        """,
                        (exit_ip,),
                    )
                    if await cur.fetchone():
                        await db.rollback()
                        return False
                    cur = await db.execute(
                        """
                        SELECT 1
                        FROM proxy_assignments legacy
                        JOIN proxy_endpoints used ON used.id = legacy.proxy_id
                        WHERE legacy.worker_id != ? AND used.exit_ip = ?
                        LIMIT 1
                        """,
                        (worker_id, exit_ip),
                    )
                    if await cur.fetchone():
                        await db.rollback()
                        return False
            await db.execute(
                """
                INSERT INTO proxy_assignments (worker_id, proxy_id, mode, fallback, assignment_version, applied_at)
                VALUES (?, ?, ?, ?, 1, NULL)
                ON CONFLICT(worker_id) DO UPDATE SET
                    proxy_id = excluded.proxy_id,
                    mode = excluded.mode,
                    fallback = excluded.fallback,
                    assignment_version = proxy_assignments.assignment_version + 1,
                    applied_at = NULL
                """,
                (worker_id, proxy_id, mode, fallback),
            )
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def clear_worker_proxy_assignment(worker_id: int) -> bool:
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            # Keep the row as a tombstone so an in-flight rotation cannot reuse an
            # old assignment version after a clear/re-lease race.
            cursor = await db.execute(
                """
                UPDATE proxy_assignments
                SET proxy_id = NULL,
                    mode = 'direct',
                    fallback = 'hold',
                    assignment_version = assignment_version + 1,
                    applied_at = datetime('now')
                WHERE worker_id = ?
                """,
                (worker_id,),
            )
            await db.commit()
            return bool(cursor.rowcount)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def get_worker_proxy_assignment(worker_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            SELECT pa.worker_id, pa.proxy_id, pa.mode, pa.fallback, pa.assignment_version,
                   pa.applied_at, pa.created_at,
                   pe.endpoint, pe.host, pe.port, pe.protocol, pe.username, pe.location,
                    pe.password_enc, pe.status, pe.udp_ok, pe.exit_ip, pe.ip_type,
                    pe.country_code, pe.country_name, pp.name AS provider_name
            FROM proxy_assignments pa
            LEFT JOIN proxy_endpoints pe ON pe.id = pa.proxy_id
            LEFT JOIN proxy_providers pp ON pp.id = pe.provider_id
            WHERE pa.worker_id = ?
            """,
            (worker_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        enc = data.pop("password_enc", "") or ""
        if enc:
            data["password"] = decrypt_value(enc)
        return data
    finally:
        await db.close()


async def commit_proxy_rotation(
    worker_id: int,
    *,
    expected_proxy_id: int,
    expected_assignment_version: int,
    new_proxy_id: int,
    instance_ids: Sequence[str],
    fallback: str = "rotate",
) -> bool:
    """CAS-commit a worker proxy rotation and its affected instances in one transaction."""
    ids = [str(value or "").strip() for value in instance_ids if str(value or "").strip()]
    if not ids:
        return False
    fallback = fallback if fallback in {"hold", "rotate"} else "rotate"
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT id, exit_ip, duplicate_egress FROM proxy_endpoints WHERE id = ?", (new_proxy_id,)
            )
            candidate = await cursor.fetchone()
            if not candidate or bool(candidate["duplicate_egress"]):
                await db.rollback()
                return False
            cursor = await db.execute(
                """
                SELECT worker_id
                FROM proxy_assignments
                WHERE proxy_id = ? AND worker_id != ?
                LIMIT 1
                """,
                (new_proxy_id, worker_id),
            )
            if await cursor.fetchone():
                # A candidate may have been read before another worker claimed it.
                # Do not create duplicate active leases during the CAS commit.
                await db.rollback()
                return False
            exit_ip = str(candidate["exit_ip"] or "").strip()
            cursor = await db.execute(
                """
                SELECT 1
                FROM earnapp_account_control_routes control
                JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                WHERE control.state = 'ACTIVE'
                  AND (control.proxy_id = ? OR (control_proxy.exit_ip != '' AND control_proxy.exit_ip = ?))
                LIMIT 1
                """,
                (int(new_proxy_id), exit_ip),
            )
            if await cursor.fetchone():
                await db.rollback()
                return False
            cursor = await db.execute(
                f"""
                SELECT 1
                FROM proxy_endpoints pe
                WHERE pe.id = ?
                  AND {_active_earnapp_reservation_exclusion_sql("pe")}
                LIMIT 1
                """,
                (int(new_proxy_id),),
            )
            if not await cursor.fetchone():
                await db.rollback()
                return False
            if exit_ip:
                cursor = await db.execute(
                    "SELECT 1 FROM provider_proxy_leases WHERE released_at IS NULL AND exit_ip = ? LIMIT 1",
                    (exit_ip,),
                )
                if await cursor.fetchone():
                    await db.rollback()
                    return False
                cursor = await db.execute(
                    """
                    SELECT 1
                    FROM proxy_assignments legacy
                    JOIN proxy_endpoints used ON used.id = legacy.proxy_id
                    WHERE legacy.worker_id != ? AND used.exit_ip = ?
                    LIMIT 1
                    """,
                    (worker_id, exit_ip),
                )
                if await cursor.fetchone():
                    await db.rollback()
                    return False
            cursor = await db.execute(
                """
                UPDATE proxy_assignments
                SET proxy_id = ?,
                    mode = 'proxy',
                    fallback = ?,
                    assignment_version = assignment_version + 1,
                    applied_at = datetime('now')
                WHERE worker_id = ?
                  AND proxy_id = ?
                  AND assignment_version = ?
                """,
                (new_proxy_id, fallback, worker_id, expected_proxy_id, expected_assignment_version),
            )
            if int(cursor.rowcount or 0) != 1:
                await db.rollback()
                return False
            placeholders = ",".join("?" for _ in ids)
            cursor = await db.execute(
                f"""
                UPDATE provider_instances
                SET proxy_id = ?, updated_at = datetime('now')
                WHERE worker_id = ?
                  AND mode = 'proxy'
                  AND proxy_id = ?
                  AND instance_id IN ({placeholders})
                """,
                [new_proxy_id, worker_id, expected_proxy_id, *ids],
            )
            if int(cursor.rowcount or 0) != len(ids):
                await db.rollback()
                return False
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def _repair_myst_wallet_addresses(db: aiosqlite.Connection, *, limit: int = 300) -> None:
    from app import myst_wallets

    cursor = await db.execute(
        """
        SELECT id, raw_wallet_enc, address
        FROM myst_wallets
        WHERE length(coalesce(address, '')) != 40
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    )
    changed = 0
    for row in await cursor.fetchall():
        current = str(row["address"] or "")
        raw = decrypt_value(row["raw_wallet_enc"] or "")
        address = myst_wallets.wallet_address_hint(raw)
        if address and address != current and len(address) == 40:
            await db.execute(
                "UPDATE myst_wallets SET address = ?, updated_at = datetime('now') WHERE id = ?",
                (address, int(row["id"])),
            )
            changed += 1
    if changed:
        await db.commit()


async def export_proxy_pool(
    *,
    status: str | None = None,
    provider: str | None = None,
    location: str | None = None,
    protocol: str | None = None,
) -> list[dict[str, Any]]:
    rows = await list_proxy_pool()
    wanted_status = (status or "").strip().lower()
    wanted_provider = (provider or "").strip().lower()
    wanted_location = (location or "").strip().lower()
    wanted_protocol = (protocol or "").strip().lower()
    if wanted_status:
        rows = [row for row in rows if str(row.get("status") or "").strip().lower() == wanted_status]
    if wanted_provider:
        rows = [row for row in rows if str(row.get("provider_name") or "").strip().lower() == wanted_provider]
    if wanted_location:
        rows = [row for row in rows if str(row.get("location") or "").strip().lower() == wanted_location]
    if wanted_protocol:
        rows = [row for row in rows if str(row.get("protocol") or "").strip().lower() == wanted_protocol]
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if not str(item.get("exit_ip") or "").strip():
            item["location"] = (
                "Generic check failed"
                if str(item.get("status") or "").strip().lower() == "dead"
                else "Egress unresolved"
            )
        else:
            item["location"] = (
                canonical_proxy_location(item.get("country_code"), item.get("country_name")) or "Metadata pending"
            )
        normalized_rows.append(item)
    return normalized_rows


async def export_duplicate_proxy_rows(*, raw: bool = False) -> list[dict[str, Any]]:
    """Export duplicate evidence; raw mode is explicit and owner-gated by the route."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT pe.id, pe.endpoint, pe.host, pe.port, pe.protocol, pe.username, pe.password_enc,
                   pe.exit_ip, pe.canonical_proxy_id, pe.duplicate_reason, pp.name AS provider_name,
                   (
                       SELECT latest.raw_line_enc
                       FROM proxy_import_rows latest
                       WHERE latest.proxy_id = pe.id
                       ORDER BY latest.id DESC
                       LIMIT 1
                   ) AS raw_line_enc
            FROM proxy_endpoints pe
            LEFT JOIN proxy_providers pp ON pp.id = pe.provider_id
            WHERE pe.duplicate_egress = 1
            ORDER BY pe.id
            """
        )
        rows: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            data = dict(row)
            raw_line = decrypt_value(data.pop("raw_line_enc", "") or "")
            enc = data.pop("password_enc", "") or ""
            data["password"] = decrypt_value(enc) if raw else ""
            data["username"] = data.get("username", "") if raw else ""
            data["raw_proxy"] = raw_line if raw else ""
            rows.append(data)
        return rows
    finally:
        await db.close()


async def update_proxy_pool_check_results(
    results: Mapping[int, str], *, protocols: Mapping[int, str] | None = None, exit_ips: Mapping[int, str] | None = None
) -> int:
    db = await _get_db()
    try:
        checked = 0
        for proxy_id, status in results.items():
            normalized_status = str(status).lower()
            if normalized_status not in {"alive", "dead"}:
                continue
            protocol = str((protocols or {}).get(proxy_id) or "").lower()
            exit_ip = str((exit_ips or {}).get(proxy_id) or "").strip()
            clear_intelligence = normalized_status == "dead"
            cur = await db.execute(
                """
                UPDATE proxy_endpoints
                SET status = ?,
                    protocol = CASE WHEN ? IN ('http', 'socks5') THEN ? ELSE protocol END,
                    exit_ip = CASE
                        WHEN ? THEN ''
                        WHEN ? != '' THEN ?
                        ELSE exit_ip
                    END,
                    location = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN '' ELSE location END,
                    country_code = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN '' ELSE country_code END,
                    country_name = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN '' ELSE country_name END,
                    geo_source = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN '' ELSE geo_source END,
                    geo_confidence = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN 'unknown' ELSE geo_confidence END,
                    geo_checked_at = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN NULL ELSE geo_checked_at END,
                    ip_type = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN 'unknown' ELSE ip_type END,
                    ip_type_source = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN '' ELSE ip_type_source END,
                    ip_type_confidence = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN 'unknown' ELSE ip_type_confidence END,
                    ip_type_checked_at = CASE WHEN ? OR (? != '' AND ? != exit_ip) THEN NULL ELSE ip_type_checked_at END,
                    last_checked_at = datetime('now')
                WHERE id = ?
                """,
                (
                    normalized_status,
                    protocol,
                    protocol,
                    clear_intelligence,
                    exit_ip,
                    exit_ip,
                    *(value for _field in range(10) for value in (clear_intelligence, exit_ip, exit_ip)),
                    int(proxy_id),
                ),
            )
            checked += int(cur.rowcount or 0)
        await db.commit()
        return checked
    finally:
        await db.close()


async def update_proxy_endpoint_intelligence(proxy_id: int, intelligence: Mapping[str, Any]) -> bool:
    country_code = canonical_proxy_country_code(intelligence.get("country_code"))
    country_name = str(intelligence.get("country_name") or "").strip()
    geo_source = str(intelligence.get("geo_source") or intelligence.get("location_source") or "").strip()
    ip_type = str(intelligence.get("ip_type") or "unknown").strip().lower()
    ip_type_source = str(intelligence.get("ip_type_source") or "").strip()
    has_geo = bool(geo_source and (country_code or country_name))
    has_type = bool(ip_type_source and ip_type != "unknown")
    if not has_geo and not has_type:
        return False
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            UPDATE proxy_endpoints
            SET location = CASE WHEN ? THEN ? ELSE location END,
                country_code = CASE WHEN ? THEN ? ELSE country_code END,
                country_name = CASE WHEN ? THEN ? ELSE country_name END,
                geo_source = CASE WHEN ? THEN ? ELSE geo_source END,
                geo_confidence = CASE WHEN ? THEN ? ELSE geo_confidence END,
                geo_checked_at = CASE WHEN ? THEN datetime('now') ELSE geo_checked_at END,
                ip_type = CASE WHEN ? THEN ? ELSE ip_type END,
                ip_type_source = CASE WHEN ? THEN ? ELSE ip_type_source END,
                ip_type_confidence = CASE WHEN ? THEN ? ELSE ip_type_confidence END,
                ip_type_checked_at = CASE WHEN ? THEN datetime('now') ELSE ip_type_checked_at END
            WHERE id = ?
            """,
            (
                has_geo,
                str(intelligence.get("location") or country_name or country_code),
                has_geo,
                country_code,
                has_geo,
                country_name,
                has_geo,
                geo_source,
                has_geo,
                str(intelligence.get("geo_confidence") or "unknown"),
                has_geo,
                has_type,
                ip_type,
                has_type,
                ip_type_source,
                has_type,
                str(intelligence.get("ip_type_confidence") or "unknown"),
                has_type,
                int(proxy_id),
            ),
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def get_cached_proxy_intelligence(exit_ip: str, *, max_age_hours: int = 168) -> dict[str, Any] | None:
    value = str(exit_ip or "").strip()
    if not value:
        return None
    age = f"-{max(1, int(max_age_hours))} hours"
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT location, country_code, country_name, geo_source, geo_confidence,
                   ip_type, ip_type_source, ip_type_confidence
            FROM proxy_endpoints
            WHERE exit_ip = ?
              AND geo_source != ''
              AND geo_checked_at >= datetime('now', ?)
              AND ip_type_source != ''
              AND ip_type_checked_at >= datetime('now', ?)
            ORDER BY CASE WHEN geo_source != '' AND ip_type_source != '' THEN 0 ELSE 1 END,
                     max(coalesce(geo_checked_at, ''), coalesce(ip_type_checked_at, '')) DESC,
                     id DESC
            LIMIT 1
            """,
            (value, age, age),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def save_proxy_probe_result(
    proxy_id: int,
    *,
    profile: str,
    probe_status: str,
    verdict: str,
    eligibility: str,
    reason: str,
    exit_ip: str,
    latency_ms: int | None,
    probe_version: str,
    evidence: Mapping[str, Any] | None = None,
) -> int:
    """Append probe evidence and refresh only the endpoint fields it proves."""
    observed_exit_ip = str(exit_ip or "").strip()
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO proxy_probe_results
                (proxy_id, profile, probe_status, verdict, eligibility, reason, exit_ip,
                 latency_ms, probe_version, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(proxy_id),
                str(profile or "generic"),
                str(probe_status or "unknown"),
                str(verdict or ""),
                str(eligibility or "unknown"),
                str(reason or "")[:500],
                observed_exit_ip,
                int(latency_ms) if latency_ms is not None else None,
                str(probe_version or ""),
                json.dumps(dict(evidence or {}), separators=(",", ":"), sort_keys=True),
            ),
        )
        is_generic = str(profile or "") == "generic"
        update_status = str(probe_status or "unknown").lower() if is_generic else ""
        if observed_exit_ip:
            await db.execute(
                """
                UPDATE proxy_endpoints
                SET location = '',
                    country_code = '',
                    country_name = '',
                    geo_source = '',
                    geo_confidence = 'unknown',
                    geo_checked_at = NULL,
                    ip_type = 'unknown',
                    ip_type_source = '',
                    ip_type_confidence = 'unknown',
                    ip_type_checked_at = NULL
                WHERE id = ? AND exit_ip != ?
                """,
                (int(proxy_id), observed_exit_ip),
            )
        await db.execute(
            """
            UPDATE proxy_endpoints
            SET exit_ip = CASE WHEN ? != '' THEN ? ELSE exit_ip END,
                latency_ms = CASE WHEN ? AND ? IS NOT NULL THEN ? ELSE latency_ms END,
                status = CASE WHEN ? IN ('alive', 'dead') THEN ? ELSE status END,
                last_checked_at = CASE WHEN ? = 'generic' THEN datetime('now') ELSE last_checked_at END
            WHERE id = ?
            """,
            (
                observed_exit_ip,
                observed_exit_ip,
                is_generic,
                latency_ms,
                latency_ms,
                update_status,
                update_status,
                str(profile or ""),
                int(proxy_id),
            ),
        )
        await db.commit()
        return int(cursor.lastrowid or 0)
    finally:
        await db.close()


async def reconcile_proxy_duplicates() -> int:
    """Choose one canonical endpoint per egress while retaining every raw row.

    Existing assignments are never removed. A bound non-canonical row may still
    be labelled duplicate, but the lease guards prevent every new assignment
    from reusing its egress.
    """
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE proxy_endpoints SET duplicate_egress = 0, canonical_proxy_id = id, duplicate_reason = ''"
        )
        cursor = await db.execute(
            """
            SELECT exit_ip
            FROM proxy_endpoints
            WHERE trim(coalesce(exit_ip, '')) != ''
            GROUP BY exit_ip
            HAVING COUNT(*) > 1
            """
        )
        changed = 0
        for group in await cursor.fetchall():
            exit_ip = str(group["exit_ip"])
            candidates = await (
                await db.execute(
                    """
                    SELECT pe.id, pe.status, pe.latency_ms,
                           CASE WHEN pa.proxy_id IS NOT NULL OR scoped.proxy_id IS NOT NULL THEN 1 ELSE 0 END AS is_bound,
                           CASE WHEN EXISTS (
                               SELECT 1 FROM proxy_probe_results pr
                                WHERE pr.proxy_id = pe.id
                                  AND pr.profile = 'earnapp_wss'
                                  AND pr.verdict = 'CID_SET'
                                  AND pr.eligibility = 'eligible'
                                  AND trim(coalesce(pr.exit_ip, '')) != ''
                                  AND pr.exit_ip = pe.exit_ip
                                  AND pr.id = (
                                     SELECT MAX(latest.id)
                                     FROM proxy_probe_results latest
                                     WHERE latest.proxy_id = pe.id
                                       AND latest.profile = 'earnapp_wss'
                                 )
                           ) THEN 1 ELSE 0 END AS has_earnapp_eligible
                    FROM proxy_endpoints pe
                    LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
                    LEFT JOIN provider_proxy_leases scoped ON scoped.proxy_id = pe.id AND scoped.released_at IS NULL
                    WHERE pe.exit_ip = ?
                    ORDER BY is_bound DESC,
                             has_earnapp_eligible DESC,
                             CASE WHEN lower(pe.status) = 'alive' THEN 0 ELSE 1 END,
                             CASE WHEN pe.latency_ms IS NULL THEN 1 ELSE 0 END,
                             pe.latency_ms,
                             pe.id
                    """,
                    (exit_ip,),
                )
            ).fetchall()
            if not candidates:
                continue
            canonical_id = int(candidates[0]["id"])
            await db.execute(
                "UPDATE proxy_endpoints SET canonical_proxy_id = ? WHERE exit_ip = ?",
                (canonical_id, exit_ip),
            )
            duplicate_ids = [int(row["id"]) for row in candidates[1:]]
            if duplicate_ids:
                placeholders = ",".join("?" for _ in duplicate_ids)
                result = await db.execute(
                    f"""
                    UPDATE proxy_endpoints
                    SET duplicate_egress = 1,
                        canonical_proxy_id = ?,
                        duplicate_reason = 'duplicate egress ' || ?
                    WHERE id IN ({placeholders})
                    """,
                    (canonical_id, exit_ip, *duplicate_ids),
                )
                changed += int(result.rowcount or 0)
        await db.commit()
        return changed
    finally:
        await db.close()


async def lease_proxy_for_provider_instance(
    provider_slug: str,
    worker_id: int,
    instance_id: str,
    *,
    country_code: str = "",
    exclude_country_code: str = "",
) -> dict[str, Any] | None:
    """Lease one canonical egress to a provider instance without touching legacy assignments."""
    slug = str(provider_slug or "").strip().lower()
    instance = str(instance_id or "").strip()
    if slug == "earnapp" and earnapp_policy.is_protected_runtime_reference(instance):
        return None
    if not slug or int(worker_id or 0) <= 0 or not instance:
        return None
    requested_country = str(country_code or "").strip().upper()
    excluded_country = str(exclude_country_code or "").strip().upper()
    if requested_country and not re.fullmatch(r"[A-Z]{2}", requested_country):
        return None
    if excluded_country and not re.fullmatch(r"[A-Z]{2}", excluded_country):
        return None
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            if slug == "earnapp":
                await _expire_earnapp_provider_masks(db)
            cursor = await db.execute(
                """
                SELECT leases.proxy_id, leases.exit_ip, pe.endpoint, pe.host, pe.port, pe.protocol,
                       pe.username, pe.password_enc, pe.location, pe.ip_type, pe.country_code, pe.country_name
                FROM provider_proxy_leases leases
                JOIN proxy_endpoints pe ON pe.id = leases.proxy_id
                WHERE leases.provider_slug = ? AND leases.worker_id = ? AND leases.instance_id = ?
                  AND leases.released_at IS NULL
                LIMIT 1
                """,
                (slug, int(worker_id), instance),
            )
            current = await cursor.fetchone()
            if current:
                if slug == "earnapp":
                    eligible = await (
                        await db.execute(
                            f"SELECT 1 FROM proxy_endpoints pe WHERE pe.id = ? AND {_earnapp_proxy_eligible_sql('pe')}",
                            (int(current["proxy_id"]),),
                        )
                    ).fetchone()
                    current_country = str(current["country_code"] or "").upper()
                    country_matches = (not requested_country or current_country == requested_country) and (
                        not excluded_country or current_country != excluded_country
                    )
                    if not eligible or not country_matches:
                        await db.rollback()
                        return None
                await db.commit()
                data = dict(current)
                encrypted = data.pop("password_enc", "") or ""
                if encrypted:
                    data["password"] = decrypt_value(encrypted)
                data.update(provider_slug=slug, worker_id=int(worker_id), instance_id=instance)
                return data
            preferred_proxy_id = 0
            if slug == "earnapp":
                preferred_row = await (
                    await db.execute(
                        "SELECT preferred_proxy_id FROM earnapp_logical_nodes WHERE logical_node_id = ?",
                        (instance,),
                    )
                ).fetchone()
                preferred_proxy_id = int(preferred_row["preferred_proxy_id"] or 0) if preferred_row else 0
            cursor = await db.execute(
                f"""
                SELECT pe.id AS proxy_id, pe.endpoint, pe.host, pe.port, pe.protocol, pe.username,
                       pe.password_enc, pe.location, pe.exit_ip, pe.ip_type, pe.country_code, pe.country_name
                FROM proxy_endpoints pe
                LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
                LEFT JOIN provider_proxy_leases own ON own.proxy_id = pe.id AND own.released_at IS NULL
                WHERE lower(coalesce(pe.status, 'unknown')) = 'alive'
                  AND trim(coalesce(pe.exit_ip, '')) != ''
                  AND coalesce(pe.duplicate_egress, 0) = 0
                  AND pa.proxy_id IS NULL
                  AND own.proxy_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM proxy_assignments legacy
                      JOIN proxy_endpoints used ON used.id = legacy.proxy_id
                      WHERE trim(coalesce(pe.exit_ip, '')) != '' AND used.exit_ip = pe.exit_ip
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM provider_proxy_leases used
                      WHERE used.released_at IS NULL AND used.exit_ip = pe.exit_ip
                  )
                  AND (
                      ? != 'earnapp'
                      OR NOT EXISTS (
                          SELECT 1 FROM provider_instances runtime
                          JOIN proxy_endpoints runtime_proxy ON runtime_proxy.id = runtime.proxy_id
                          WHERE runtime.proxy_id = pe.id
                             OR (
                                 trim(coalesce(runtime_proxy.exit_ip, '')) != ''
                                 AND runtime_proxy.exit_ip = pe.exit_ip
                             )
                      )
                  )
                   AND NOT EXISTS (
                       SELECT 1 FROM earnapp_account_control_routes control
                       JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                       WHERE control.state = 'ACTIVE'
                         AND (control.proxy_id = pe.id OR control_proxy.exit_ip = pe.exit_ip)
                   )
                   AND {_active_earnapp_reservation_exclusion_sql("pe")}
                   AND NOT EXISTS (
                       SELECT 1 FROM proxy_provider_masks ppm
                       WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = ?
                   )
                  AND (
                      ? != 'earnapp'
                      OR EXISTS (
                          SELECT 1 FROM proxy_probe_results earnapp
                            WHERE earnapp.proxy_id = pe.id
                              AND earnapp.profile = 'earnapp_wss'
                              AND earnapp.verdict = 'CID_SET'
                              AND earnapp.eligibility = 'eligible'
                              AND trim(coalesce(earnapp.exit_ip, '')) != ''
                              AND earnapp.exit_ip = pe.exit_ip
                              AND earnapp.id = (
                                SELECT MAX(latest.id) FROM proxy_probe_results latest
                                WHERE latest.proxy_id = pe.id AND latest.profile = 'earnapp_wss'
                          )
                      )
                  )
                   AND (
                       ? != 'earnapp'
                       OR (
                           lower(trim(coalesce(pe.ip_type, ''))) = 'residential'
                           AND length(trim(coalesce(pe.country_code, ''))) = 2
                           AND upper(trim(pe.country_code)) GLOB '[A-Z][A-Z]'
                       )
                   )
                    AND (? = '' OR upper(trim(coalesce(pe.country_code, ''))) = ?)
                    AND (? = '' OR upper(trim(coalesce(pe.country_code, ''))) != ?)
                ORDER BY CASE WHEN pe.id = ? THEN 0 ELSE 1 END, pe.id
                LIMIT 1
                """,
                (
                    slug,
                    slug,
                    slug,
                    slug,
                    requested_country,
                    requested_country,
                    excluded_country,
                    excluded_country,
                    preferred_proxy_id,
                ),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            data = dict(row)
            await db.execute(
                """
                INSERT INTO provider_proxy_leases
                    (provider_slug, worker_id, instance_id, proxy_id, exit_ip)
                VALUES (?, ?, ?, ?, ?)
                """,
                (slug, int(worker_id), instance, int(data["proxy_id"]), str(data.get("exit_ip") or "")),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
    encrypted = data.pop("password_enc", "") or ""
    if encrypted:
        data["password"] = decrypt_value(encrypted)
    data.update(provider_slug=slug, worker_id=int(worker_id), instance_id=instance)
    return data


async def release_proxy_for_provider_instance(
    provider_slug: str, worker_id: int, instance_id: str, *, reason: str = "released"
) -> bool:
    if str(provider_slug or "").strip().lower() == "earnapp" and earnapp_policy.is_protected_runtime_reference(
        instance_id
    ):
        return False
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            UPDATE provider_proxy_leases
            SET released_at = datetime('now'), release_reason = ?
            WHERE provider_slug = ? AND worker_id = ? AND instance_id = ? AND released_at IS NULL
            """,
            (
                str(reason or "released")[:300],
                str(provider_slug or "").strip().lower(),
                int(worker_id),
                str(instance_id or "").strip(),
            ),
        )
        await db.commit()
        return bool(cursor.rowcount)
    finally:
        await db.close()


async def delete_all_proxy_pool() -> int:
    """Delete every endpoint and every assignment owned by the Proxy Pool."""
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            protected_node = await _protected_earnapp_proxy_reference(db)
            if protected_node:
                await db.rollback()
                raise ProtectedEarnAppProxyError(
                    f"proxy pool contains a proxy referenced by protected EarnApp node {protected_node}"
                )
            await db.execute("DELETE FROM proxy_assignments")
            await db.execute("DELETE FROM earnapp_account_control_routes")
            cursor = await db.execute("DELETE FROM proxy_endpoints")
            await db.execute("DELETE FROM proxy_import_batches")
            await db.commit()
            return int(cursor.rowcount or 0)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()


async def lease_proxy_for_worker(worker_id: int, *, provider_slug: str | None = None) -> dict[str, Any] | None:
    provider_slug = str(provider_slug or "").strip()
    mask_clause = ""
    params: list[Any] = [worker_id]
    if provider_slug:
        mask_clause = """
              AND NOT EXISTS (
                  SELECT 1
                  FROM proxy_provider_masks ppm
                  WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = ?
              )
        """
        params.append(provider_slug)
    async with _proxy_assignment_lock():
        db = await _open_transaction_connection()
        try:
            await db.execute("BEGIN IMMEDIATE")
            if provider_slug == "earnapp":
                await _expire_earnapp_provider_masks(db)
            await db.execute(
                f"""
                INSERT INTO proxy_assignments (worker_id, proxy_id, mode, fallback, assignment_version, applied_at)
                SELECT ?, pe.id, 'proxy', 'hold', 1, datetime('now')
                FROM proxy_endpoints pe
                LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
                WHERE pa.proxy_id IS NULL
                  AND lower(coalesce(pe.status, 'unknown')) = 'alive'
                  AND trim(coalesce(pe.exit_ip, '')) != ''
                  AND coalesce(pe.duplicate_egress, 0) = 0
                   AND NOT EXISTS (
                       SELECT 1 FROM provider_proxy_leases scoped
                       WHERE scoped.released_at IS NULL AND scoped.proxy_id = pe.id
                   )
                   AND NOT EXISTS (
                       SELECT 1
                       FROM earnapp_account_control_routes control
                       JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id
                       WHERE control.state = 'ACTIVE'
                         AND (control.proxy_id = pe.id OR (control_proxy.exit_ip != '' AND control_proxy.exit_ip = pe.exit_ip))
                   )
                   AND {_active_earnapp_reservation_exclusion_sql("pe")}
                   AND (
                       trim(coalesce(pe.exit_ip, '')) = ''
                       OR NOT EXISTS (
                          SELECT 1 FROM proxy_assignments legacy
                          JOIN proxy_endpoints used ON used.id = legacy.proxy_id
                          WHERE used.exit_ip = pe.exit_ip
                      )
                  )
                  AND (
                      trim(coalesce(pe.exit_ip, '')) = ''
                      OR NOT EXISTS (
                          SELECT 1 FROM provider_proxy_leases scoped
                          WHERE scoped.released_at IS NULL AND scoped.exit_ip = pe.exit_ip
                      )
                  )
                {mask_clause}
                ORDER BY pe.id
                LIMIT 1
                ON CONFLICT(worker_id) DO UPDATE SET
                    proxy_id = excluded.proxy_id,
                    mode = excluded.mode,
                    fallback = excluded.fallback,
                    assignment_version = proxy_assignments.assignment_version + 1,
                    applied_at = excluded.applied_at
                """,
                params,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
    assignment = await get_worker_proxy_assignment(worker_id)
    if (
        assignment
        and provider_slug
        and assignment.get("proxy_id")
        and await proxy_masked_for_provider(int(assignment["proxy_id"]), provider_slug)
    ):
        return None
    return assignment


async def find_available_proxy_for_worker(worker_id: int, *, provider_slug: str | None = None) -> dict[str, Any] | None:
    """Read a candidate without mutating the worker assignment.

    Rotation uses this reservation-free lookup so the existing binding remains
    the CAS guard until the worker has applied and acknowledged the candidate.
    """
    provider_slug = str(provider_slug or "").strip()
    clauses = [
        "pa.proxy_id IS NULL",
        "lower(coalesce(pe.status, 'unknown')) = 'alive'",
        "trim(coalesce(pe.exit_ip, '')) != ''",
        "coalesce(pe.duplicate_egress, 0) = 0",
        "NOT EXISTS (SELECT 1 FROM provider_proxy_leases scoped WHERE scoped.released_at IS NULL AND scoped.proxy_id = pe.id)",
        "NOT EXISTS (SELECT 1 FROM earnapp_account_control_routes control JOIN proxy_endpoints control_proxy ON control_proxy.id = control.proxy_id WHERE control.state = 'ACTIVE' AND (control.proxy_id = pe.id OR (control_proxy.exit_ip != '' AND control_proxy.exit_ip = pe.exit_ip)))",
        _active_earnapp_reservation_exclusion_sql("pe"),
        "(trim(coalesce(pe.exit_ip, '')) = '' OR NOT EXISTS (SELECT 1 FROM proxy_assignments legacy JOIN proxy_endpoints used ON used.id = legacy.proxy_id WHERE used.exit_ip = pe.exit_ip))",
        "(trim(coalesce(pe.exit_ip, '')) = '' OR NOT EXISTS (SELECT 1 FROM provider_proxy_leases scoped WHERE scoped.released_at IS NULL AND scoped.exit_ip = pe.exit_ip))",
    ]
    params: list[Any] = []
    if provider_slug:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM proxy_provider_masks ppm WHERE ppm.proxy_id = pe.id AND ppm.provider_slug = ?)"
        )
        params.append(provider_slug)
    db = await _get_db()
    try:
        if provider_slug == "earnapp":
            await _expire_earnapp_provider_masks(db)
            await db.commit()
        cursor = await db.execute(
            f"""
            SELECT pe.id AS proxy_id, pe.endpoint, pe.host, pe.port, pe.protocol,
                   pe.username, pe.location, pe.password_enc, pe.status, pe.udp_ok,
                   pe.exit_ip, pe.ip_type, pe.country_code, pe.country_name,
                   pp.name AS provider_name
            FROM proxy_endpoints pe
            LEFT JOIN proxy_assignments pa ON pa.proxy_id = pe.id
            LEFT JOIN proxy_providers pp ON pp.id = pe.provider_id
            WHERE {" AND ".join(clauses)}
            ORDER BY pe.id
            LIMIT 1
            """,
            params,
        )
        row = await cursor.fetchone()
        if not row:
            return None
        data = dict(row)
        enc = data.pop("password_enc", "") or ""
        if enc:
            data["password"] = decrypt_value(enc)
        return data
    finally:
        await db.close()


async def get_proxy_endpoint(proxy_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cur = await db.execute(
            """
            SELECT pe.*, pp.name AS provider_name, pp.type AS provider_type,
                   CASE WHEN pe.password_enc IS NOT NULL AND pe.password_enc != '' THEN 1 ELSE 0 END AS password_set
            FROM proxy_endpoints pe
            LEFT JOIN proxy_providers pp ON pp.id = pe.provider_id
            WHERE pe.id = ?
            """,
            (proxy_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        enc = data.pop("password_enc", "") or ""
        if enc:
            data["password"] = decrypt_value(enc)
        data["password_set"] = bool(data.get("password_set"))
        return data
    finally:
        await db.close()


# --- Per-worker fleet keys ---
#
# The UI must both VERIFY inbound heartbeats from a worker and, for the full
# cutover, AUTHENTICATE outbound calls TO that worker — so it needs the key
# itself, not just a one-way hash. Keys are therefore stored encrypted at rest
# (Fernet, the same at-rest protection as service credentials) and decrypted on
# demand for comparison and for outbound Authorization headers.


async def set_worker_key(client_id: str, key: str) -> None:
    """Store a worker's per-worker key (encrypted), unconfirmed until the worker
    proves it holds the key by using it on a later heartbeat."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "UPDATE workers SET api_key_enc = ?, key_confirmed = 0, key_issued_at = datetime('now') WHERE client_id = ?",
            (encrypt_value(key), client_id),
        )
        await db.commit()
        if not cursor.rowcount:
            # The worker row must exist first (upsert runs before this); a missing
            # row would silently drop the key and lock the worker out.
            _logger.warning("set_worker_key: no worker row for client_id=%s", client_id)
    finally:
        await db.close()


async def confirm_worker_key(client_id: str) -> None:
    """Mark a worker's key confirmed — it has authenticated with its own key, so the
    shared bootstrap key is refused from now on (the cutover finalizes)."""
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE workers SET key_confirmed = 1 WHERE client_id = ?",
            (client_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_worker_key(client_id: str) -> str | None:
    """Return a worker's per-worker key (decrypted), or None if not yet enrolled."""
    key, _ = await get_worker_key_state(client_id)
    return key


async def get_worker_key_state(client_id: str) -> tuple[str | None, bool]:
    """Return (key, confirmed) for a worker: the decrypted per-worker key (or None
    if unenrolled, or if the stored key can no longer be decrypted) and whether the
    worker has confirmed it by using it."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT api_key_enc, key_confirmed FROM workers WHERE client_id = ?",
            (client_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None, False
        enc = row["api_key_enc"]
        if not enc:
            return None, bool(row["key_confirmed"])
        key = decrypt_value(enc)
        if not key:
            # decrypt_value() returns "" (after logging its own warning) when the
            # CREDENTIAL-ENCRYPTION key can't decrypt this value -- the Fernet key
            # at CASHPILOT_ENCRYPTION_KEY / /data/.fernet_key was rotated, or /data
            # was restored without it. NOT CASHPILOT_SECRET_KEY, which only signs
            # sessions: this message used to name that one, sending the operator
            # after the wrong variable while their whole fleet sat offline.
            #
            # A real per-worker key is always a secrets.token_urlsafe(32) string
            # and can never legitimately be empty, so "" here unambiguously means
            # "undecryptable", not "empty key". Report it as NOT enrolled (None)
            # rather than as a real key that can never match.
            _logger.error(
                "Worker '%s' per-worker key cannot be decrypted. The credential-encryption key "
                "(CASHPILOT_ENCRYPTION_KEY / %s) is not the one it was encrypted with -- this is "
                "NOT CASHPILOT_SECRET_KEY, which only signs sessions. Restore the original key to "
                "recover every stored credential. Until then this worker is treated as unenrolled; "
                "it keeps sending the key it persisted and will 401 for roughly %d heartbeats "
                "before discarding it and re-enrolling on its own. To fix it now, delete "
                "/data/.worker_key on that host and restart its container.",
                client_id,
                _FERNET_KEY_FILE,
                _WORKER_KEY_DISCARD_AFTER,
            )
            return None, False
        return key, bool(row["key_confirmed"])
    finally:
        await db.close()


async def get_worker_key_issued_at(client_id: str) -> str | None:
    """When this worker's per-worker key was minted, or None if not recorded.

    Separate from ``get_worker_key_state`` rather than widening its tuple: that
    function is called on every heartbeat and its 2-tuple contract is relied on
    in several places, while this is only needed on the one branch that decides
    whether the shared key may still be honoured.

    None means UNKNOWN — a row written before this column existed and missed by
    the migration's backfill. Callers must not read it as "long ago"; unknown is
    not expired.
    """
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT key_issued_at FROM workers WHERE client_id = ?", (client_id,))
        row = await cursor.fetchone()
        return row["key_issued_at"] if row else None
    finally:
        await db.close()


# --- Health Events ---


async def record_health_event(slug: str, event: str, detail: str = "") -> None:
    """Record a health event (start, stop, restart, crash, check_ok)."""
    db = await _get_db()
    try:
        await db.execute(
            "INSERT INTO health_events (slug, event, detail) VALUES (?, ?, ?)",
            (slug, event, detail),
        )
        await db.commit()
    finally:
        await db.close()


async def record_health_events(events: list[tuple[str, str, str]]) -> None:
    """Record many health events in ONE transaction/commit.

    The health-check cycle writes one event per deployed service; committing each
    separately fsync'd the WAL up to ~49 times per cycle. One executemany + one commit
    collapses that to a single write — the dominant fix for that path's I/O.
    """
    if not events:
        return
    db = await _get_db()
    try:
        await db.executemany(
            "INSERT INTO health_events (slug, event, detail) VALUES (?, ?, ?)",
            events,
        )
        await db.commit()
    finally:
        await db.close()


# How long a subject stays quiet after alerting. A collector broken for a week must
# not notify every hour: the first failure is news, the 168th is noise.
ALERT_COOLDOWN_HOURS = 24


# A service can be "running" and earning nothing at all - the container is up,
# the collector authenticates, and the balance simply never moves. That gap
# between running and earning is invisible in every other view, because
# everything it touches looks healthy.
FLATLINE_MIN_DAYS = 7


async def get_earned_by_platform(days: int = 30) -> dict[str, float]:
    """USD earned per platform over the trailing window.

    Deliberately NOT the latest balance. A balance is a running total; charging
    a window's electricity against it would subtract 30 days of cost from a
    lifetime of earnings and produce a number that means nothing.

    Deltas are clamped per platform before summing, the same rule the dashboard
    uses (CashPilot-glc): a payout drops a balance, and an unclamped drop would
    read as negative earnings and understate what the service actually paid.

    The delta is taken in the NATIVE currency and only then priced. Converting
    each cumulative balance to USD first and subtracting afterwards would let a
    rate move alone move the earnings figure: 100 MYST at $0.50 followed by 110
    MYST at $0.40 subtracts to a loss and clamps to zero, hiding 10 MYST that
    really was earned, while an unchanged balance at a risen rate invents
    earnings out of nothing.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT platform, date, balance, currency, fx_rate_usd, source
            FROM earnings
            WHERE COALESCE(source, 'server') NOT LIKE 'node:%'
              AND date >= date('now', ?)
            ORDER BY platform, source, date
            """,
            (f"-{max(1, int(days))} days",),
        )
        rows = await cursor.fetchall()

        earned: dict[str, float] = {}
        # Keyed by (platform, SOURCE). Keyed by platform alone, two samplers of
        # one provider account interleave into a single series whose deltas are
        # meaningless: each drop clamps to zero, so the total is understated.
        previous: dict[tuple[str, str], tuple[str, float]] = {}
        unpriced = 0
        for row in rows:
            platform = row["platform"]
            # Absent source means a row written before the column existed, and
            # those were all this server's own. Never invent a distinct source
            # for them: that would split one real series in two.
            series = (platform, (row["source"] or "server"))
            currency = (row["currency"] or "USD").upper()
            balance = float(row["balance"] or 0.0)
            # USD is parity by definition. Trusting a stored rate on a USD row
            # would let a bad rate rewrite money the collector reported exactly.
            rate = _usd_rate(currency, row["fx_rate_usd"])
            earned.setdefault(platform, 0.0)

            if rate is None:
                # No rate means this reading cannot be priced, so it can neither
                # contribute earnings nor anchor the next delta. Dropping the
                # baseline is what stops a later reading from being differenced
                # across the gap and counting the unpriced period twice.
                previous.pop(series, None)
                unpriced += 1
                continue

            before = previous.get(series)
            if before is not None and before[0] == currency:
                # Summed into the PLATFORM, so each source contributes its own
                # earnings and the combination happens after differencing.
                earned[platform] += max(0.0, balance - before[1]) * float(rate)
            previous[series] = (currency, balance)

        if unpriced:
            _logger.warning(
                "%d earnings reading(s) in the last %d days have no USD rate and were left out "
                "of the per-platform totals, which are therefore understated.",
                unpriced,
                days,
            )
        return earned
    finally:
        await db.close()


async def get_flatlined_services(min_days: int = FLATLINE_MIN_DAYS) -> list[dict[str, Any]]:
    """Services whose recorded balance has not moved for at least ``min_days``.

    Deliberately conservative, because a report that cries wolf is a report
    nobody reads:

    * A service with fewer than ``min_days`` of history is NOT reported. A new
      deployment has not had time to earn anything yet.
    * A balance of exactly zero throughout is NOT reported either. That is a
      service that has never paid rather than one that stopped, and it is
      usually a setup problem the user already knows about.
    * The window is measured over distinct recorded days, so a collection outage
      (which records nothing) cannot masquerade as a flat balance.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT platform,
                   COUNT(DISTINCT date) AS days_recorded,
                   MIN(balance)         AS min_balance,
                   MAX(balance)         AS max_balance,
                   MAX(date)            AS last_date
            FROM earnings
            WHERE COALESCE(source, 'server') NOT LIKE 'node:%'
              AND date >= date('now', ?)
            GROUP BY platform
            -- Only platforms that recorded a reading TODAY. A collector that is
            -- failing stops writing rows, but its earlier readings are still
            -- there and are, of course, unchanged - so without this a broken
            -- collector reads as a flatline, and so does a service that was
            -- removed but kept its history. Those are different faults with
            -- different fixes, and reporting them as "running but not earning"
            -- is exactly the crying wolf this feature must avoid.
            HAVING MAX(date) >= date('now')
            """,
            (f"-{min_days} days",),
        )
        rows = await cursor.fetchall()

        flat: list[dict[str, Any]] = []
        for row in rows:
            if row["days_recorded"] < min_days:
                continue  # not enough history to call it a flatline
            if row["max_balance"] != row["min_balance"]:
                continue  # it moved
            if row["max_balance"] == 0:
                continue  # never earned rather than stopped earning
            flat.append(
                {
                    "platform": row["platform"],
                    "days_flat": row["days_recorded"],
                    "balance": row["max_balance"],
                    "last_recorded": row["last_date"],
                }
            )
        return flat
    finally:
        await db.close()


async def record_alert(
    kind: str,
    subject: str,
    message: str,
    *,
    category: str | None = None,
    cooldown_hours: int = ALERT_COOLDOWN_HOURS,
) -> bool:
    """Persist an alert, returning True only when the caller should notify.

    Suppression is by TIME WINDOW per kind+subject, not by message equality. Message
    equality alone is not enough: collectors can alternate between two error
    strings for the same underlying fault (for example an expired-token error
    and a Cloudflare rate-limit depending on which request tripped first), so a
    "changed message means new" rule would notify every single hour and grow the
    table without bound — exactly what this is meant to prevent.

    Nothing is stored while a subject is in cooldown, which keeps the table bounded.
    Call ``clear_alerts`` when a subject recovers so the next failure alerts again
    immediately instead of waiting out the window.
    """
    # A closed enum, enforced at the boundary: `error` is carefully redacted
    # on the line next to this call, and a future collector setting
    # error_kind=str(exc) must not smuggle unredacted exception text (which
    # for several providers IS the credential) into a durable, any-role table.
    if category not in (None, "auth", "transient", "shape"):
        category = None
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM alerts WHERE kind = ? AND subject = ? AND created_at > datetime('now', ?) LIMIT 1",
            (kind, subject, f"-{int(cooldown_hours)} hours"),
        )
        if (row := await cursor.fetchone()) is not None:
            # Refresh what the stored row SAYS while keeping the push
            # suppressed. Without this the first category of a failure window
            # is pinned for 24h: a provider can alternate between an expired-token
            # error (auth) and a Cloudflare rate-limit (transient) with no
            # success in between, so a restart could restore "transient" for a
            # dead credential — rendered muted, with no fix button, as a blip
            # that will never actually heal.
            await db.execute(
                "UPDATE alerts SET category = ?, message = ? WHERE id = ?",
                (category, message, row["id"]),
            )
            await db.commit()
            return False
        await db.execute(
            "INSERT INTO alerts (kind, subject, message, category) VALUES (?, ?, ?, ?)",
            (kind, subject, message, category),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def list_alerts(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent alerts, newest first."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT kind, subject, message, category, created_at FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def get_alert_subjects(kind: str) -> set[str]:
    """Subjects currently holding a stored alert of this kind."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT DISTINCT subject FROM alerts WHERE kind = ?", (kind,))
        return {row["subject"] for row in await cursor.fetchall()}
    finally:
        await db.close()


async def clear_alerts(kind: str | None = None, subject: str | None = None) -> None:
    """Drop stored alerts (all, one kind, or one subject within a kind).

    Called when a subject recovers, so that if it breaks again later the failure
    counts as new and notifies again instead of being deduped into silence.
    """
    clauses, params = [], []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if subject is not None:
        clauses.append("subject = ?")
        params.append(subject)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    db = await _get_db()
    try:
        await db.execute(f"DELETE FROM alerts{where}", tuple(params))  # noqa: S608 - clauses are literals
        await db.commit()
    finally:
        await db.close()


async def get_health_scores(days: int = 7) -> list[dict[str, Any]]:
    """Compute health score per service over the last N days.

    Score formula (0-100):
    - Start at 100
    - -5 per restart
    - -20 per crash
    - Uptime ratio bonus: (running_checks / total_checks) * weight
    """
    db = await _get_db()
    try:
        cutoff = f"-{days} days"
        cursor = await db.execute(
            """
            SELECT
                slug,
                COUNT(*) as total_events,
                SUM(CASE WHEN event = 'restart' THEN 1 ELSE 0 END) as restarts,
                SUM(CASE WHEN event = 'crash' THEN 1 ELSE 0 END) as crashes,
                SUM(CASE WHEN event = 'stop' THEN 1 ELSE 0 END) as stops,
                SUM(CASE WHEN event = 'check_ok' THEN 1 ELSE 0 END) as ok_checks,
                SUM(CASE WHEN event IN ('check_ok', 'check_down') THEN 1 ELSE 0 END) as total_checks,
                MIN(created_at) as first_event,
                MAX(created_at) as last_event
            FROM health_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY slug
            ORDER BY slug
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            score = 100.0
            score -= r["restarts"] * 5
            score -= r["crashes"] * 20
            score -= r["stops"] * 2

            # Uptime ratio
            if r["total_checks"] > 0:
                uptime_ratio = r["ok_checks"] / r["total_checks"]
                score = score * 0.4 + uptime_ratio * 100 * 0.6
            score = max(0.0, min(100.0, score))

            results.append(
                {
                    "slug": r["slug"],
                    "score": round(score, 1),
                    "restarts": r["restarts"],
                    "crashes": r["crashes"],
                    "stops": r["stops"],
                    "uptime_checks": r["ok_checks"],
                    "total_checks": r["total_checks"],
                    "uptime_pct": round(r["ok_checks"] / r["total_checks"] * 100, 1) if r["total_checks"] > 0 else None,
                }
            )
        return results
    finally:
        await db.close()


# --- Data Retention ---

RETENTION_DAYS = 400
# High-frequency uptime samples (check_ok / check_down, one per service every 5
# minutes) are the dominant source of health_events growth, yet get_health_scores
# only ever reads a bounded window. /api/health/scores caps that window at 90 days,
# so we keep samples just past that (95d) — enough that no allowed query can
# out-range its own samples, while still cutting the bulk sample rows ~76% versus
# the 400-day lifecycle-event history (start/stop/restart/crash), which we keep in
# full because those rows are rare and worth the long tail.
HEALTH_CHECK_RETENTION_DAYS = 95
_HEALTH_CHECK_EVENTS = ("check_ok", "check_down")


async def purge_old_data() -> int:
    """Delete data past retention. Returns rows deleted.

    Earnings and lifecycle health events are kept RETENTION_DAYS; the far more
    numerous uptime-sample events are trimmed to HEALTH_CHECK_RETENTION_DAYS.
    """
    db = await _get_db()
    try:
        cutoff = f"-{RETENTION_DAYS} days"
        check_cutoff = f"-{HEALTH_CHECK_RETENTION_DAYS} days"
        c1 = await db.execute(
            "DELETE FROM earnings WHERE created_at < datetime('now', ?)",
            (cutoff,),
        )
        c2 = await db.execute(
            "DELETE FROM health_events WHERE created_at < datetime('now', ?)",
            (cutoff,),
        )
        c3 = await db.execute(
            "DELETE FROM health_events WHERE event IN ('check_ok', 'check_down') AND created_at < datetime('now', ?)",
            (check_cutoff,),
        )
        # Alerts are deduped on write so the table stays small, but a service that
        # was removed long ago should not leave its last failure sitting there forever.
        c4 = await db.execute(
            "DELETE FROM alerts WHERE created_at < datetime('now', ?)",
            (cutoff,),
        )
        await db.commit()
        return (c1.rowcount or 0) + (c2.rowcount or 0) + (c3.rowcount or 0) + (c4.rowcount or 0)
    finally:
        await db.close()


async def vacuum_database() -> None:
    """Reclaim free pages left by retention deletes.

    SQLite never shrinks the file on DELETE alone, so without a periodic VACUUM the
    database keeps its high-water-mark size forever even as old rows are purged.
    Run off-peak (weekly) — VACUUM rewrites the whole file and briefly locks it. We
    commit first because VACUUM cannot run inside an open transaction, and checkpoint
    the WAL afterwards so the freed space is actually returned to the filesystem.
    """
    db = await _get_db()
    try:
        await db.commit()
        await db.execute("VACUUM")
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Payouts (CashPilot-1og)
# ---------------------------------------------------------------------------


async def record_probable_payout(
    platform: str,
    amount: float,
    currency: str = "USD",
    fx_rate_usd: float | None = None,
) -> int | None:
    """Record a balance drop that LOOKS like a payout, unconfirmed.

    Returns the row id, or None when an unconfirmed one is already pending for
    this platform. Without that guard every collection cycle would file another
    copy of the same drop, and the user would face a growing pile of duplicate
    prompts for one event.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM payouts WHERE platform = ? AND confirmed = 0 LIMIT 1",
            (platform,),
        )
        if await cursor.fetchone():
            return None
        cursor = await db.execute(
            "INSERT INTO payouts (platform, amount, currency, fx_rate_usd) VALUES (?, ?, ?, ?)",
            (platform, float(amount), currency, fx_rate_usd),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def confirm_payout(payout_id: int, method: str = "") -> bool:
    """Mark a probable payout as real. Only a human should reach this."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "UPDATE payouts SET confirmed = 1, method = ?, confirmed_at = datetime('now') "
            "WHERE id = ? AND confirmed = 0",
            (method, payout_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def reject_payout(payout_id: int) -> bool:
    """Delete a probable payout the user says was not one.

    Deleted rather than flagged: a rejected guess is not data about earnings,
    and keeping it invites some later query from counting it.
    """
    db = await _get_db()
    try:
        cursor = await db.execute("DELETE FROM payouts WHERE id = ? AND confirmed = 0", (payout_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_payouts(platform: str | None = None, confirmed_only: bool = False) -> list[dict[str, Any]]:
    """Payout rows, newest first."""
    query = "SELECT * FROM payouts"
    clauses: list[str] = []
    params: list[Any] = []
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if confirmed_only:
        clauses.append("confirmed = 1")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY detected_at DESC"

    db = await _get_db()
    try:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_confirmed_payout_totals() -> dict[str, float]:
    """Confirmed payout total per platform, in USD.

    Uses the fx rate recorded when the payout landed, so a token payout keeps
    the value it actually had rather than being restated by today's price.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            # COALESCE(fx_rate_usd, 1.0) would price an unrated token payout at
            # PARITY WITH USD — a 500 MYST payout becomes $500 instead of ~$15.
            # A payout whose rate was never captured is not worth "the same
            # number of dollars"; it is worth an unknown amount, so it is
            # excluded and counted separately rather than silently invented.
            "SELECT platform, "
            "  SUM(CASE WHEN currency = 'USD' THEN amount "
            "           WHEN fx_rate_usd IS NOT NULL THEN amount * fx_rate_usd "
            "           ELSE 0 END) AS total, "
            "  SUM(CASE WHEN currency != 'USD' AND fx_rate_usd IS NULL THEN 1 ELSE 0 END) AS unpriced "
            "FROM payouts WHERE confirmed = 1 GROUP BY platform"
        )
        totals: dict[str, float] = {}
        for row in await cursor.fetchall():
            totals[row["platform"]] = float(row["total"] or 0.0)
            if row["unpriced"]:
                # Say it rather than let the total quietly read low. The
                # alternative — pricing them at parity — reads high by roughly
                # the token's price, which is far worse.
                _logger.warning(
                    "%s: %d confirmed payout(s) have no recorded exchange rate and are "
                    "excluded from the total, which is therefore an UNDERSTATEMENT.",
                    row["platform"],
                    row["unpriced"],
                )
        return totals
    finally:
        await db.close()


async def get_latest_balance(platform: str) -> float | None:
    """The most recent recorded balance for a platform, or None if never seen.

    None matters: a first-ever reading has nothing to compare against, and
    treating an absent history as zero would make every initial collection look
    like a huge gain — or, for payout detection, make the first reading after a
    fresh install look like a drop.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT balance FROM earnings WHERE platform = ? AND COALESCE(source, 'server') NOT LIKE 'node:%' ORDER BY date DESC, id DESC LIMIT 1",
            (platform,),
        )
        row = await cursor.fetchone()
        return float(row["balance"]) if row else None
    finally:
        await db.close()


async def get_balance_history(platform: str, days: int = 30) -> list[dict[str, Any]]:
    """Oldest-first balance readings for a platform, for rate projection."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT date, balance, currency, fx_rate_usd FROM earnings "
            "WHERE platform = ? AND COALESCE(source, 'server') NOT LIKE 'node:%' AND date >= date('now', ?) ORDER BY date ASC",
            (platform, f"-{int(days)} days"),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()
