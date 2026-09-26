"""Application security utilities.

This module provides centralized security configuration handling including:
- Secure loading of API credentials from environment variables
- Master key management for stream decryption
- Path validation and containment utilities
- Log redaction helpers

Security-critical values should be provided via environment variables rather
than being hardcoded in source code. This module provides safe loading functions
with appropriate fallback behavior and validation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Environment variable names for security-sensitive configuration
ENV_TIDAL_CLIENT_ID = "TIDAL_DL_CLIENT_ID"
ENV_TIDAL_CLIENT_SECRET = "TIDAL_DL_CLIENT_SECRET"
ENV_TIDAL_API_KEYS_GIST_HASH = "TIDAL_DL_GIST_HASH"
ENV_DECRYPTION_MASTER_KEY = "TIDAL_DL_MASTER_KEY"
ENV_WEB_API_KEY = "TIDAL_DL_PRO_WEB_API_KEY"
ENV_WEB_RATE_LIMIT_PER_MIN = "TIDAL_DL_PRO_WEB_RATE_LIMIT"
ENV_CUSTOM_CA_PATH = "TIDAL_DL_CUSTOM_CA_PATH"
ENV_SECURE_TOKEN_KEY = "TIDAL_DL_TOKEN_ENCRYPTION_KEY"

# Known SHA-256 hash of the TIDAL API keys Gist content.
# This pin prevents supply-chain attacks if the Gist owner's account is compromised.
# This hash corresponds to a specific version of the API keys JSON.
KNOWN_KEYS_GIST_HASH = os.environ.get(
    ENV_TIDAL_API_KEYS_GIST_HASH,
    "",  # Empty means verification is disabled; set this to enable verification
)

# Placeholder values used when credentials are not provided via environment.
# These are intentionally non-functional and must be overridden by the user.
PLACEHOLDER_CLIENT_ID = "NOT_CONFIGURED"
PLACEHOLDER_CLIENT_SECRET = "NOT_CONFIGURED"

# Default master key (legacy key). This should be overridden via environment.
# NOTE: This is provided for backward compatibility with existing downloads.
LEGACY_MASTER_KEY = "UIlTTEMmmLfGowo/UC60x2H45W6MdGgTRfo/umg4754="


def get_env(var_name: str, default: str = "") -> str:
    """Safely read an environment variable.

    Args:
        var_name: The environment variable name.
        default: The default value to return if the variable is not set.

    Returns:
        The environment variable value or the default.
    """
    return os.environ.get(var_name, default).strip()


def get_api_client_id() -> str:
    """Get the TIDAL API client ID securely.

    Returns:
        The client ID from environment or a placeholder.

    Warning:
        If the environment variable is not set, a non-functional placeholder is
        returned. Users must set ``TIDAL_DL_CLIENT_ID`` for the application to work.
    """
    client_id = get_env(ENV_TIDAL_CLIENT_ID, PLACEHOLDER_CLIENT_ID)
    if client_id == PLACEHOLDER_CLIENT_ID:
        logger.warning("TIDAL API client ID not configured via %s", ENV_TIDAL_CLIENT_ID)
        # Fallback to built-in key for backward compatibility (if compiled into release)
        # This is a known key that may not work; users should configure their own.
        fallback_id = _safe_builtin_key("OmDtrzFgyVVL6uW56OnFA2COiabqm")
        if fallback_id:
            return fallback_id
    return client_id


def get_api_client_secret() -> str:
    """Get the TIDAL API client secret securely.

    Returns:
        The client secret from environment or a placeholder.
    """
    secret = get_env(ENV_TIDAL_CLIENT_SECRET, PLACEHOLDER_CLIENT_SECRET)
    if secret == PLACEHOLDER_CLIENT_SECRET:
        logger.warning("TIDAL API client secret not configured via %s", ENV_TIDAL_CLIENT_SECRET)
        fallback_secret = _safe_builtin_key("zxen1r3pO0hgtOC7j6twMo9UAqngGrmRiWpV7QC1zJ8=")
        if fallback_secret:
            return fallback_secret
    return secret


def _safe_builtin_key(key: str) -> str:
    """Retrieve a built-in key only if explicitly enabled.

    In production builds, built-in keys should be disabled to prevent key leakage.
    Set ``TIDAL_DL_ALLOW_BUILTIN_KEYS=1`` to enable them.

    Args:
        key: The key string to return if allowed.

    Returns:
        The key if allowed, otherwise empty string.
    """
    if os.environ.get("TIDAL_DL_ALLOW_BUILTIN_KEYS", "0") == "1":
        return key
    return ""


def get_decryption_master_key() -> bytes:
    """Get the stream decryption master key.

    Returns:
        The base64-decoded master key bytes.

    Warning:
        The default key is provided for backward compatibility. For security,
        set ``TIDAL_DL_MASTER_KEY`` to a custom key.
    """
    env_key = get_env(ENV_DECRYPTION_MASTER_KEY, "")
    key_b64 = env_key if env_key else LEGACY_MASTER_KEY
    try:
        return base64.b64decode(key_b64)
    except (ValueError, TypeError):
        logger.error("Invalid master key format; using legacy key")
        return base64.b64decode(LEGACY_MASTER_KEY)


def verify_gist_content(content: str, expected_hash: str | None = None) -> bool:
    """Verify that Gist content matches an expected SHA-256 hash.

    Args:
        content: The content string from the Gist response.
        expected_hash: The expected SHA-256 hash. If None, uses the configured hash.

    Returns:
        True if hash matches, False otherwise.
    """
    hash_to_check = expected_hash or KNOWN_KEYS_GIST_HASH
    if not hash_to_check:
        logger.warning("No Gist hash configured; content integrity cannot be verified")
        return True  # Allow if no hash configured (legacy behavior)

    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual_hash, hash_to_check)


def validate_path_within_base(path: Path, base: Path) -> bool:
    """Validate that a path stays within a base directory.

    Prevents path traversal attacks via crafted media metadata.

    Args:
        path: The candidate path to validate.
        base: The base directory that path must be within.

    Returns:
        True if path is within base, False otherwise.
    """
    try:
        resolved_path = path.resolve()
        resolved_base = base.resolve()
        resolved_path.relative_to(resolved_base)
        return True
    except (ValueError, OSError):
        return False


def sanitize_log_message(message: str) -> str:
    """Sanitize log messages to remove sensitive data.

    Redacts:
    - OAuth tokens (access/refresh tokens)
    - API keys and secrets
    - Authorization headers
    - Encryption keys

    Args:
        message: The log message to sanitize.

    Returns:
        The sanitized message.
    """
    # Redact OAuth tokens (typically 12-500 char alphanumeric strings)
    message = re.sub(r"(access[_-]?token[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9._-]+)", r"\1[REDACTED]", message,
                     flags=re.IGNORECASE)
    message = re.sub(r"(refresh[_-]?token[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9._-]+)", r"\1[REDACTED]", message,
                     flags=re.IGNORECASE)
    message = re.sub(r"(token[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9._-]{10,})", r"\1[REDACTED]", message,
                     flags=re.IGNORECASE)
    # Redact API keys/secrets
    message = re.sub(r"(secret[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9+/=_-]+)", r"\1[REDACTED]", message,
                     flags=re.IGNORECASE)
    message = re.sub(r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9+/=_-]+)", r"\1[REDACTED]", message,
                     flags=re.IGNORECASE)
    message = re.sub(r"(client[_-]?secret[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9+/=_-]+)", r"\1[REDACTED]", message,
                     flags=re.IGNORECASE)
    # Redact Authorization headers
    message = re.sub(r"(Authorization[\"']?\s*[:=]\s*[\"']?(Bearer|Basic)\s+)[A-Za-z0-9+/=_-]+",
                     r"\1[REDACTED]", message, flags=re.IGNORECASE)
    return message


def get_web_api_key() -> str:
    """Get the API key required for web UI authentication.

    Returns:
        The configured API key or a randomly generated one.

    Note:
        If not configured via ``TIDAL_DL_PRO_WEB_API_KEY``, a random key is
        generated and displayed in logs on first startup.
    """
    key = get_env(ENV_WEB_API_KEY, "")
    if not key:
        key = secrets.token_urlsafe(32)
        logger.info(
            "No WEB API key configured. Generated ephemeral key: %s. "
            "Set %s to persist a key.",
            key,
            ENV_WEB_API_KEY,
        )
    return key


def get_custom_ca_path() -> Path | None:
    """Get a custom CA certificate path if configured.

    Returns:
        The CA path if configured and exists, None otherwise.
    """
    ca_path_env = get_env(ENV_CUSTOM_CA_PATH, "")
    if not ca_path_env:
        return None
    ca_path = Path(ca_path_env).expanduser()
    if ca_path.is_file():
        return ca_path
    logger.warning("Configured custom CA path does not exist: %s", ca_path)
    return None


def get_token_encryption_key() -> bytes:
    """Get or generate an encryption key for OAuth tokens at rest.

    Returns:
        A 32-byte encryption key.

    Note:
        If ``TIDAL_DL_TOKEN_ENCRYPTION_KEY`` is not set, a random key is
        generated and cached. Set the environment variable to persist the key
        across restarts.
    """
    env_key = get_env(ENV_SECURE_TOKEN_KEY, "")
    if env_key:
        try:
            decoded = base64.b64decode(env_key)
            if len(decoded) == 32:
                return decoded
        except (ValueError, TypeError):
            logger.error("Invalid token encryption key format")
    # Generate a random key (will not persist across restarts)
    return secrets.token_bytes(32)


def get_request_timeout() -> int:
    """Get the configured HTTP request timeout.

    Returns:
        The timeout in seconds.
    """
    try:
        return int(get_env("TIDAL_DL_REQUEST_TIMEOUT", "45"))
    except ValueError:
        return 45


def get_rate_limit_per_minute() -> int:
    """Get the web API rate limit per minute.

    Returns:
        The rate limit value (default 120).
    """
    try:
        return max(1, int(get_env(ENV_WEB_RATE_LIMIT_PER_MIN, "120")))
    except ValueError:
        return 120


def validate_ffmpeg_path(path_str: str) -> bool:
    """Validate that a configured FFmpeg path points to a valid executable.

    Args:
        path_str: The configured FFmpeg path string.

    Returns:
        True if valid, False otherwise.
    """
    if not path_str:
        return True  # Empty means use system FFmpeg
    path = Path(path_str).expanduser()
    if not path.is_file():
        return False
    if not os.access(path, os.X_OK):
        return False
    return True


def validate_config_path(path_str: str) -> bool:
    """Validate a config file path for safety.

    Prevents command injection via file paths.

    Args:
        path_str: The file path string.

    Returns:
        True if the path is safe for editor launching, False otherwise.
    """
    path = Path(path_str).expanduser().resolve()
    # Reject paths with shell metacharacters or control characters
    unsafe_chars = re.compile(r"[\x00-\x1f\x7f;|&`$<>\\'\"]")
    if unsafe_chars.search(str(path)):
        return False
    # Only allow regular files
    if not path.is_file():
        return False
    return True