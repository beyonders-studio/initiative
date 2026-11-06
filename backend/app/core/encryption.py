import base64
import hmac as _hmac
import hashlib as _hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from app.core.config import settings

# Each logical secret type gets its own HKDF salt so a compromised key
# for one field cannot decrypt another.  Never change an existing salt
# value — doing so changes the derived key and breaks decryption of all
# ciphertext produced with the old key.
#
# To add a new encrypted field: pick a descriptive salt string, add it
# here, and use encrypt_field / decrypt_field with that constant. A stored
# value declares it on its column's ``info`` (``FERNET_SALT``, below), which is
# how the SECRET_KEY rotation finds it.
SALT_OIDC_REFRESH_TOKEN = b"oidc-refresh-token"  # legacy name, do not rename
SALT_OIDC_CLIENT_SECRET = b"oidc-client-secret"
SALT_OIDC_FLOW_STATE = b"oidc-flow-state"  # transient login-flow state (never stored)
SALT_SMTP_PASSWORD = b"smtp-password"
SALT_AI_API_KEY = b"ai-api-key"
SALT_S3_SECRET_KEY = b"s3-secret-key"
SALT_CAPTCHA_SECRET_KEY = b"captcha-secret-key"
SALT_FCM_SERVICE_ACCOUNT = b"fcm-service-account"
# The key this server sends to the push relay with, issued when it registered.
SALT_PUSH_RELAY_KEY = b"push-relay-key"
SALT_EMAIL = b"email"
SALT_EVENT_PUBLISHER_PAYLOAD = b"event-publisher-payload"
# Values a guild (or one of its members) supplies to an installed plug-in's
# connection form. Held per key inside a JSONB map rather than in a column of
# its own, because one install can hold several.
SALT_PLUGIN_CONFIG = b"app-config"  # stored value, do not change
# What an operator supplies for a plug-in's vendor client (its secret, its
# signing key), one ciphertext per field on the plug-in's registration.
SALT_PLUGIN_VENDOR = b"app-vendor"  # stored value, do not change
# The plug-in platform's signing key, when this deployment generated its own
# rather than being given one in PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM.
SALT_PLUGIN_PLATFORM_SIGNING_KEY = (
    b"app-platform-signing-key"  # stored value, do not change
)
# The state a plug-in connection's vendor flow carries through the vendor and
# back. Transient: it lives ten minutes and is never stored.
SALT_PLUGIN_CONNECTION_FLOW = b"app-connection-flow"  # stored value, do not change
# The base32 seed behind an account's authenticator-app factor.
SALT_TOTP_SECRET = b"totp-secret"
# An account's date of birth, kept so a plug-in's minimum age can be checked
# against it. Read on the system engine only, and never sent back to anyone.
SALT_BIRTHDATE = b"birthdate"  # stored value, do not change
# The access tokens the plug-in platform's token endpoint issues. Transient: a
# token lives ten minutes and is never stored, so a key rotation ends the ones
# in flight and their plug-ins ask again.
SALT_PLUGIN_ACCESS_TOKEN = b"app-access-token"  # stored value, do not change
# Where a page of a plug-in's installs ends, handed to the plug-in to ask for the next
# one. Transient: never stored.
SALT_PLUGIN_INSTALLS_CURSOR = b"app-installs-cursor"  # stored value, do not change
# A sign-in finished in the phone's browser, on its way back to the app that
# began it. Transient: it lives two minutes and is spent once.
SALT_NATIVE_HANDOFF = b"native-handoff"
# The state a plug-in vendor's own setup carries through the vendor and back.
# Transient: it lives an hour and is spent once.
SALT_PLUGIN_VENDOR_SETUP = b"app-vendor-setup"  # stored value, do not change
# The value a job needs to read a foreign site. Kept under its original
# name so values written before the job carried it still decrypt.
SALT_IMPORT_CREDENTIAL = b"import-credential"
# What a community or platform moderator wrote when placing a hold: who asked
# for it, a reference number. Read only by the platform.
SALT_HOLD_NOTE = b"hold-note"
# The words a moderator took down, kept in the community's moderation log so
# a removal can be put back.
SALT_MODERATION_SNAPSHOT = b"moderation-snapshot"
# A community's storage key, where the deployment roots it in SECRET_KEY
# (STORAGE_ENCRYPTION=local). Every object the community keeps is encrypted
# under it (app.services.storage_keys).
SALT_STORAGE_KEY = b"storage-key"
# The API token one import job uses to read a foreign site. Held for the
# length of that job and deleted with it.

# Keys of a model column's ``info`` that declare what it stores encrypted, read
# by the SECRET_KEY rotation (app.db.secret_key_rotation).
#
# ``FERNET_SALT``: the salt the column's ciphertext is sealed under — the whole
# value of a text column, or every string leaf of a JSON column.
# ``FERNET_PATHS``: on a JSON column, the only leaves that hold ciphertext,
# each a tuple of keys; the rest of the document is plain.
# ``EMAIL_HASH_COLUMN``: the column beside it holding ``hash_email`` of the
# same plaintext, recomputed in the statement that re-encrypts it.
FERNET_SALT = "fernet_salt"
FERNET_PATHS = "fernet_paths"
EMAIL_HASH_COLUMN = "email_hash_column"


def _resolve_secret_key(secret_key: str | None) -> str:
    """The explicit key when given, else the live SECRET_KEY. Lets the rotation
    sweep (app.db.secret_key_rotation) decrypt under the old key and re-encrypt
    under the new one without mutating global settings; default callers are
    unaffected."""
    return secret_key if secret_key is not None else settings.SECRET_KEY


def _derive_fernet_key(salt: bytes, secret_key: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"fernet-key",
    )
    raw = hkdf.derive(secret_key.encode())
    return base64.urlsafe_b64encode(raw)


# Cached per (secret_key, salt): rotation derives Fernets for two distinct keys, so
# the cache key must include the secret or the second key would collide with the first.
_fernets: dict[tuple[str, bytes], Fernet] = {}


def _get_fernet(salt: bytes, secret_key: str) -> Fernet:
    cache_key = (secret_key, salt)
    if cache_key not in _fernets:
        _fernets[cache_key] = Fernet(_derive_fernet_key(salt, secret_key))
    return _fernets[cache_key]


def normalize_email(email: str) -> str:
    """The form an address is compared, hashed and stored in."""
    return email.lower().strip()


def hash_email(email: str, *, secret_key: str | None = None) -> str:
    """Deterministic HMAC-SHA256 of the normalized email, keyed with SECRET_KEY.

    Used for equality lookups (WHERE email_hash = ?) and unique constraints. Pass
    ``secret_key`` to hash under a specific key (the rotation sweep recomputes hashes
    under the new key); default uses the live SECRET_KEY.
    """
    return _hmac.new(
        _resolve_secret_key(secret_key).encode(),
        normalize_email(email).encode(),
        _hashlib.sha256,
    ).hexdigest()


def encrypt_field(plaintext: str, salt: bytes, *, secret_key: str | None = None) -> str:
    return (
        _get_fernet(salt, _resolve_secret_key(secret_key))
        .encrypt(plaintext.encode())
        .decode()
    )


def decrypt_field(
    ciphertext: str,
    salt: bytes,
    *,
    secret_key: str | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Decrypt ``ciphertext``. With ``ttl_seconds``, a token older than the TTL
    (per its authenticated Fernet timestamp) is rejected as invalid — used for
    transient values like the OIDC flow state."""
    return (
        _get_fernet(salt, _resolve_secret_key(secret_key))
        .decrypt(ciphertext.encode(), ttl=ttl_seconds)
        .decode()
    )


# The accessors for the oidc_refresh_token_encrypted column, whose salt
# predates per-field keys and cannot be renamed.
def encrypt_token(plaintext: str) -> str:
    return encrypt_field(plaintext, SALT_OIDC_REFRESH_TOKEN)


def decrypt_token(ciphertext: str) -> str:
    return decrypt_field(ciphertext, SALT_OIDC_REFRESH_TOKEN)
