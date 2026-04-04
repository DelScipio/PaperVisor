from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from papervisor.core.sanitizers import clean_nul
from papervisor.db.models import AppSetting
from sqlalchemy.orm import Session

from papervisor.db.session import get_session, use_session


DEFAULT_SORT_SETTING_KEY = 'default_sort'

# Auth (admin-level)
AUTH_REGISTRATION_ENABLED_KEY = 'auth.registration.enabled'

# Sharing (admin-level)
SHARING_GLOBAL_ENABLED_KEY = 'sharing.global.enabled'
SHARING_GLOBAL_REQUIRES_APPROVAL_KEY = 'sharing.global.requires_approval'

GOOGLE_BOOKS_API_KEY_SETTING_KEY = 'google_books.api_key'

# Book provider priority (admin-level)
#
# Metadata fetch priority (by ISBN). These keys existed first; keep them for compatibility.
BOOK_METADATA_PRIMARY_PROVIDER_SETTING_KEY = 'book.metadata.primary_provider'
BOOK_METADATA_FALLBACK_PROVIDER_SETTING_KEY = 'book.metadata.fallback_provider'

# ISBN discovery priority (by title/author), when ISBN is missing.
BOOK_ISBN_DISCOVERY_PRIMARY_PROVIDER_SETTING_KEY = 'book.isbn_discovery.primary_provider'
BOOK_ISBN_DISCOVERY_FALLBACK_PROVIDER_SETTING_KEY = 'book.isbn_discovery.fallback_provider'

BOOK_METADATA_PROVIDERS_ALLOWED = {'openlibrary', 'google'}

METADATA_PROVIDER_TIMEOUT_SECONDS_KEY = 'metadata.providers.timeout_seconds'
_DEFAULT_METADATA_PROVIDER_TIMEOUT_SECONDS = 6.0
_MIN_METADATA_PROVIDER_TIMEOUT_SECONDS = 2.0
_MAX_METADATA_PROVIDER_TIMEOUT_SECONDS = 60.0

# Password complexity policy (admin-configurable).
PASSWORD_REQUIRE_UPPERCASE_KEY = 'auth.password.require_uppercase'
PASSWORD_REQUIRE_DIGIT_KEY = 'auth.password.require_digit'
PASSWORD_REQUIRE_SPECIAL_KEY = 'auth.password.require_special'
PASSWORD_MIN_LENGTH_KEY = 'auth.password.min_length'

_MAX_SETTING_KEY_LEN = 64
_MAX_SETTING_VALUE_LEN = 2048


# Aliases – keep call-sites unchanged.
_clean_key = clean_nul
_clean_value = clean_nul


def _normalize_provider_pair(*, primary: str, fallback: str) -> list[str]:
    p = str(primary or '').strip().lower()
    f = str(fallback or '').strip().lower()

    if p not in BOOK_METADATA_PROVIDERS_ALLOWED:
        p = 'openlibrary'
    if f not in BOOK_METADATA_PROVIDERS_ALLOWED or f == p:
        f = 'google' if p != 'google' else 'openlibrary'
    return [p, f]


# UI state persistence (admin-level)
#
# Controls how the main page restores the last opened location after refresh.
# - default: 'library' or 'marker'
# - user override: if enabled, users can choose their own preference in Profile
UI_REMEMBER_LOCATION_DEFAULT_KEY = 'ui.remember_location.default'
UI_REMEMBER_LOCATION_USER_OVERRIDE_ALLOWED_KEY = 'ui.remember_location.user_override_allowed'




def _as_bool(value: str) -> bool:
    v = str(value or '').strip().lower()
    return v in {'1', 'true', 'yes', 'on'}


_UI_REMEMBER_LOCATION_ALLOWED = {'dashboard', 'library', 'marker'}


def get_ui_remember_location_default() -> str:
    v = str(get_setting(key=UI_REMEMBER_LOCATION_DEFAULT_KEY, default='library') or '').strip().lower()
    return v if v in _UI_REMEMBER_LOCATION_ALLOWED else 'library'


def set_ui_remember_location_default(mode: str) -> None:
    m = str(mode or '').strip().lower()
    if m not in _UI_REMEMBER_LOCATION_ALLOWED:
        raise ValueError('Invalid remember-location default (must be dashboard, library, or marker)')
    set_setting(key=UI_REMEMBER_LOCATION_DEFAULT_KEY, value=m)


def get_ui_remember_location_user_override_allowed() -> bool:
    return _as_bool(get_setting(key=UI_REMEMBER_LOCATION_USER_OVERRIDE_ALLOWED_KEY, default='1'))


def set_ui_remember_location_user_override_allowed(*, allowed: bool) -> None:
    set_setting(key=UI_REMEMBER_LOCATION_USER_OVERRIDE_ALLOWED_KEY, value='1' if allowed else '0')




@dataclass(frozen=True)
class SortOption:
    key: str
    label: str


SORT_OPTIONS: list[SortOption] = [
    SortOption(key='recent', label='Recently added'),
    SortOption(key='title_asc', label='Title (A → Z)'),
    SortOption(key='title_desc', label='Title (Z → A)'),
]


def get_setting(*, key: str, default: str = '') -> str:
    cleaned_key = _clean_key(key)
    if not cleaned_key or len(cleaned_key) > _MAX_SETTING_KEY_LEN:
        return default

    try:
        with get_session() as session:
            row = session.get(AppSetting, cleaned_key)
            if row is None:
                return default
            return str(row.value or '')
    except OperationalError:
        # Table might not exist if migrations haven't been applied yet.
        return default


def set_setting(*, key: str, value: str) -> None:
    cleaned_key = _clean_key(key)
    if not cleaned_key:
        raise ValueError('Setting key is required')
    if len(cleaned_key) > _MAX_SETTING_KEY_LEN:
        raise ValueError(f'Setting key is too long (max {_MAX_SETTING_KEY_LEN})')

    cleaned_value = _clean_value(value)
    if len(cleaned_value) > _MAX_SETTING_VALUE_LEN:
        raise ValueError(f'Setting value is too long (max {_MAX_SETTING_VALUE_LEN})')

    try:
        with get_session() as session:
            row = session.get(AppSetting, cleaned_key)
            if row is None:
                row = AppSetting(key=cleaned_key, value=cleaned_value)
                session.add(row)
            else:
                row.value = cleaned_value
            try:
                session.commit()
            except IntegrityError:
                # Concurrent create/update; retry once.
                session.rollback()
                row = session.get(AppSetting, cleaned_key)
                if row is None:
                    row = AppSetting(key=cleaned_key, value=cleaned_value)
                    session.add(row)
                else:
                    row.value = cleaned_value
                session.commit()
    except OperationalError as ex:
        raise ValueError('Database is missing required tables. Run Alembic migrations.') from ex


def settings_available() -> bool:
    """Return True if the app_settings table is available (migrations applied)."""
    try:
        with get_session() as session:
            session.execute(select(AppSetting.key).limit(1)).all()
        return True
    except OperationalError:
        return False


def get_default_sort() -> str:
    value = get_setting(key=DEFAULT_SORT_SETTING_KEY, default='recent')
    allowed = {o.key for o in SORT_OPTIONS}
    return value if value in allowed else 'recent'


def set_default_sort(sort_key: str) -> None:
    allowed = {o.key for o in SORT_OPTIONS}
    cleaned = (sort_key or '').strip()
    if cleaned not in allowed:
        raise ValueError('Invalid sort option')
    set_setting(key=DEFAULT_SORT_SETTING_KEY, value=cleaned)




def get_registration_enabled() -> bool:
    """Return True if self-service registration is enabled.

    Defaults to disabled.
    """

    value = get_setting(key=AUTH_REGISTRATION_ENABLED_KEY, default='0')
    return _as_bool(value)


def set_registration_enabled(*, enabled: bool) -> None:
    set_setting(key=AUTH_REGISTRATION_ENABLED_KEY, value='1' if enabled else '0')


def get_global_sharing_enabled() -> bool:
    """Return True if users are allowed to make their libraries global."""
    value = get_setting(key=SHARING_GLOBAL_ENABLED_KEY, default='1')
    return _as_bool(value)


def set_global_sharing_enabled(*, enabled: bool) -> None:
    set_setting(key=SHARING_GLOBAL_ENABLED_KEY, value='1' if enabled else '0')


def get_global_sharing_requires_approval() -> bool:
    """Return True if making a library global requires admin approval."""
    value = get_setting(key=SHARING_GLOBAL_REQUIRES_APPROVAL_KEY, default='1')
    return _as_bool(value)


def set_global_sharing_requires_approval(*, requires_approval: bool) -> None:
    set_setting(key=SHARING_GLOBAL_REQUIRES_APPROVAL_KEY, value='1' if requires_approval else '0')


def get_google_books_api_key() -> str:
    return get_setting(key=GOOGLE_BOOKS_API_KEY_SETTING_KEY, default='')


def set_google_books_api_key(api_key: str) -> None:
    # Allow clearing by passing an empty string.
    set_setting(key=GOOGLE_BOOKS_API_KEY_SETTING_KEY, value=str(api_key or '').strip())


def get_metadata_provider_timeout_seconds() -> float:
    raw = get_setting(
        key=METADATA_PROVIDER_TIMEOUT_SECONDS_KEY,
        default=str(_DEFAULT_METADATA_PROVIDER_TIMEOUT_SECONDS),
    )
    try:
        val = float(raw)
    except (ValueError, TypeError):
        val = _DEFAULT_METADATA_PROVIDER_TIMEOUT_SECONDS
    if val < _MIN_METADATA_PROVIDER_TIMEOUT_SECONDS:
        return _MIN_METADATA_PROVIDER_TIMEOUT_SECONDS
    if val > _MAX_METADATA_PROVIDER_TIMEOUT_SECONDS:
        return _MAX_METADATA_PROVIDER_TIMEOUT_SECONDS
    return val


def set_metadata_provider_timeout_seconds(timeout_s: float) -> None:
    val = float(timeout_s)
    if val < _MIN_METADATA_PROVIDER_TIMEOUT_SECONDS or val > _MAX_METADATA_PROVIDER_TIMEOUT_SECONDS:
        raise ValueError(
            f'Metadata provider timeout must be between '
            f'{_MIN_METADATA_PROVIDER_TIMEOUT_SECONDS:g} and {_MAX_METADATA_PROVIDER_TIMEOUT_SECONDS:g} seconds'
        )
    set_setting(key=METADATA_PROVIDER_TIMEOUT_SECONDS_KEY, value=f'{val:g}')


def get_book_metadata_providers() -> list[str]:
    """Backward-compatible alias for metadata fetch priority (by ISBN)."""

    return get_book_metadata_fetch_providers()


def set_book_metadata_providers(*, primary: str, fallback: str) -> None:
    """Backward-compatible alias for metadata fetch priority (by ISBN)."""

    set_book_metadata_fetch_providers(primary=primary, fallback=fallback)


def get_book_metadata_fetch_providers() -> list[str]:
    """Return providers (priority order) for fetching BOOK metadata by ISBN.

    Allowed providers: openlibrary, google
    Default: openlibrary -> google
    """

    primary = get_setting(key=BOOK_METADATA_PRIMARY_PROVIDER_SETTING_KEY, default='openlibrary')
    fallback = get_setting(key=BOOK_METADATA_FALLBACK_PROVIDER_SETTING_KEY, default='google')
    return _normalize_provider_pair(primary=primary, fallback=fallback)


def set_book_metadata_fetch_providers(*, primary: str, fallback: str) -> None:
    p = str(primary or '').strip().lower()
    f = str(fallback or '').strip().lower()

    if p not in BOOK_METADATA_PROVIDERS_ALLOWED:
        raise ValueError('Invalid primary provider')
    if f not in BOOK_METADATA_PROVIDERS_ALLOWED:
        raise ValueError('Invalid fallback provider')
    if f == p:
        raise ValueError('Fallback provider must differ from primary')

    set_setting(key=BOOK_METADATA_PRIMARY_PROVIDER_SETTING_KEY, value=p)
    set_setting(key=BOOK_METADATA_FALLBACK_PROVIDER_SETTING_KEY, value=f)


def get_book_isbn_discovery_providers() -> list[str]:
    """Return providers (priority order) for discovering ISBN by title/author.

    Allowed providers: openlibrary, google
    Default: openlibrary -> google
    """

    primary = get_setting(key=BOOK_ISBN_DISCOVERY_PRIMARY_PROVIDER_SETTING_KEY, default='openlibrary')
    fallback = get_setting(key=BOOK_ISBN_DISCOVERY_FALLBACK_PROVIDER_SETTING_KEY, default='google')
    return _normalize_provider_pair(primary=primary, fallback=fallback)


def set_book_isbn_discovery_providers(*, primary: str, fallback: str) -> None:
    p = str(primary or '').strip().lower()
    f = str(fallback or '').strip().lower()

    if p not in BOOK_METADATA_PROVIDERS_ALLOWED:
        raise ValueError('Invalid primary provider')
    if f not in BOOK_METADATA_PROVIDERS_ALLOWED:
        raise ValueError('Invalid fallback provider')
    if f == p:
        raise ValueError('Fallback provider must differ from primary')

    set_setting(key=BOOK_ISBN_DISCOVERY_PRIMARY_PROVIDER_SETTING_KEY, value=p)
    set_setting(key=BOOK_ISBN_DISCOVERY_FALLBACK_PROVIDER_SETTING_KEY, value=f)


# ── Password complexity policy ──────────────────────────────────────────


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int
    require_uppercase: bool
    require_digit: bool
    require_special: bool


_DEFAULT_PASSWORD_MIN_LENGTH = 8
_SPECIAL_CHARS = set('!@#$%^&*()-_=+[]{}|;:\'",.<>?/`~')


def get_password_policy() -> PasswordPolicy:
    """Return the admin-configured password complexity policy."""
    min_len_raw = get_setting(key=PASSWORD_MIN_LENGTH_KEY, default=str(_DEFAULT_PASSWORD_MIN_LENGTH))
    try:
        min_len = max(4, min(128, int(min_len_raw)))
    except (ValueError, TypeError):
        min_len = _DEFAULT_PASSWORD_MIN_LENGTH

    return PasswordPolicy(
        min_length=min_len,
        require_uppercase=_as_bool(get_setting(key=PASSWORD_REQUIRE_UPPERCASE_KEY, default='0')),
        require_digit=_as_bool(get_setting(key=PASSWORD_REQUIRE_DIGIT_KEY, default='0')),
        require_special=_as_bool(get_setting(key=PASSWORD_REQUIRE_SPECIAL_KEY, default='0')),
    )


def set_password_policy(
    *,
    min_length: int | None = None,
    require_uppercase: bool | None = None,
    require_digit: bool | None = None,
    require_special: bool | None = None,
) -> None:
    """Update password complexity rules (admin-only)."""
    if min_length is not None:
        clamped = max(4, min(128, int(min_length)))
        set_setting(key=PASSWORD_MIN_LENGTH_KEY, value=str(clamped))
    if require_uppercase is not None:
        set_setting(key=PASSWORD_REQUIRE_UPPERCASE_KEY, value='1' if require_uppercase else '0')
    if require_digit is not None:
        set_setting(key=PASSWORD_REQUIRE_DIGIT_KEY, value='1' if require_digit else '0')
    if require_special is not None:
        set_setting(key=PASSWORD_REQUIRE_SPECIAL_KEY, value='1' if require_special else '0')


def validate_password_policy(password: str) -> str | None:
    """Validate *password* against the current policy.

    Returns ``None`` if the password is acceptable, or an error message string.
    """
    policy = get_password_policy()

    if len(password) < policy.min_length:
        return f'Password too short (min {policy.min_length} characters)'
    if policy.require_uppercase and not any(c.isupper() for c in password):
        return 'Password must contain at least one uppercase letter'
    if policy.require_digit and not any(c.isdigit() for c in password):
        return 'Password must contain at least one digit'
    if policy.require_special and not any(c in _SPECIAL_CHARS for c in password):
        return 'Password must contain at least one special character'
    return None
