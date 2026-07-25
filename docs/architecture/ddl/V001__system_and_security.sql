-- APPROVED_FOR_IMPLEMENTATION. Never apply directly to data/warehouse.db.
-- Owner modules: infrastructure, bootstrap/application, users, security.
PRAGMA foreign_keys = ON;
PRAGMA application_id = 0x4F444531;

BEGIN IMMEDIATE;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum BLOB NOT NULL CHECK (length(checksum) = 32),
    applied_at_us INTEGER NOT NULL CHECK (applied_at_us > 0),
    applied_by TEXT NOT NULL CHECK (length(trim(applied_by)) > 0),
    application_version TEXT NOT NULL CHECK (length(trim(application_version)) > 0)
) STRICT;

CREATE TABLE app_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    balance_state TEXT NOT NULL CHECK (
        balance_state IN ('NOT_INITIALIZED', 'ACTIVE', 'INCONSISTENT')
    ),
    active_snapshot_id INTEGER REFERENCES inventory_snapshots(snapshot_id),
    active_projection_version_id INTEGER
        REFERENCES balance_projection_versions(projection_version_id),
    last_ledger_sequence INTEGER NOT NULL DEFAULT 0
        CHECK (last_ledger_sequence >= 0),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us > 0),
    CHECK (
        (balance_state = 'NOT_INITIALIZED'
            AND active_snapshot_id IS NULL
            AND active_projection_version_id IS NULL
            AND last_ledger_sequence = 0)
        OR
        (balance_state IN ('ACTIVE', 'INCONSISTENT')
            AND active_snapshot_id IS NOT NULL
            AND active_projection_version_id IS NOT NULL)
    )
) STRICT;

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE CHECK (length(public_id) BETWEEN 32 AND 40),
    login_key TEXT NOT NULL UNIQUE CHECK (length(trim(login_key)) > 0),
    email_raw TEXT,
    email_key TEXT,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    password_hash TEXT NOT NULL CHECK (
        length(password_hash) >= 30 AND password_hash GLOB '$argon2id$*'
    ),
    status TEXT NOT NULL CHECK (
        status IN ('INVITED', 'ACTIVE', 'LOCKED', 'DISABLED')
    ),
    must_change_password INTEGER NOT NULL DEFAULT 1
        CHECK (must_change_password IN (0, 1)),
    credential_version INTEGER NOT NULL DEFAULT 1
        CHECK (credential_version >= 1),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    updated_at_us INTEGER NOT NULL CHECK (updated_at_us >= created_at_us)
) STRICT;

CREATE UNIQUE INDEX ux_users_email_key
ON users(email_key)
WHERE email_key IS NOT NULL AND length(email_key) > 0;

CREATE INDEX ix_users_status_login
ON users(status, login_key, user_id);

CREATE TABLE roles (
    role_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (code IN ('operator', 'admin', 'auditor')),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0)
) STRICT;

CREATE TABLE permissions (
    permission_code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    risk_level TEXT NOT NULL CHECK (
        risk_level IN ('READ', 'STANDARD', 'SENSITIVE')
    ),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0)
) STRICT;

CREATE TABLE user_roles (
    user_role_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    role_id INTEGER NOT NULL REFERENCES roles(role_id),
    assigned_by_user_id INTEGER REFERENCES users(user_id),
    assigned_at_us INTEGER NOT NULL CHECK (assigned_at_us > 0),
    revoked_at_us INTEGER CHECK (
        revoked_at_us IS NULL OR revoked_at_us >= assigned_at_us
    )
) STRICT;

CREATE UNIQUE INDEX ux_user_roles_active
ON user_roles(user_id, role_id)
WHERE revoked_at_us IS NULL;

CREATE INDEX ix_user_roles_role_active
ON user_roles(role_id, user_id)
WHERE revoked_at_us IS NULL;

CREATE TABLE role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(role_id),
    permission_code TEXT NOT NULL REFERENCES permissions(permission_code),
    granted_at_us INTEGER NOT NULL CHECK (granted_at_us > 0),
    granted_by_user_id INTEGER REFERENCES users(user_id),
    PRIMARY KEY (role_id, permission_code)
) STRICT, WITHOUT ROWID;

CREATE INDEX ix_role_permissions_permission
ON role_permissions(permission_code, role_id);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY CHECK (length(session_id) BETWEEN 32 AND 40),
    token_hash BLOB NOT NULL UNIQUE CHECK (length(token_hash) = 32),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    credential_version INTEGER NOT NULL CHECK (credential_version >= 1),
    csrf_secret_hash BLOB NOT NULL CHECK (length(csrf_secret_hash) = 32),
    created_at_us INTEGER NOT NULL CHECK (created_at_us > 0),
    last_seen_at_us INTEGER NOT NULL CHECK (last_seen_at_us >= created_at_us),
    idle_expires_at_us INTEGER NOT NULL CHECK (idle_expires_at_us > created_at_us),
    absolute_expires_at_us INTEGER NOT NULL
        CHECK (absolute_expires_at_us >= idle_expires_at_us),
    revoked_at_us INTEGER,
    revoke_reason TEXT,
    ip_hash BLOB CHECK (ip_hash IS NULL OR length(ip_hash) = 32),
    user_agent_family TEXT,
    CHECK (
        (revoked_at_us IS NULL AND revoke_reason IS NULL)
        OR
        (revoked_at_us IS NOT NULL
            AND revoked_at_us >= created_at_us
            AND length(trim(revoke_reason)) > 0)
    )
) STRICT;

CREATE INDEX ix_sessions_user_active
ON sessions(user_id, absolute_expires_at_us, session_id)
WHERE revoked_at_us IS NULL;

CREATE INDEX ix_sessions_expiry
ON sessions(absolute_expires_at_us, session_id);

CREATE TRIGGER trg_users_no_delete
BEFORE DELETE ON users
BEGIN
    SELECT RAISE(ABORT, 'users are deactivated, not deleted');
END;

COMMIT;
PRAGMA user_version = 1;
