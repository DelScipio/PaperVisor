"""
OPDS Common Utilities

Shared authentication, URL building, and configuration helpers used across OPDS endpoints.
Extracted from opds_api.py to reduce duplication and improve maintainability.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import hashlib
import inspect
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, unquote, urlencode

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from papervisor.core.rate_limit import opds_auth_limiter
from papervisor.services import opds
from papervisor.services.settings import get_setting
from papervisor.services.users import authenticate, authenticate_by_api_key, UserItem
from papervisor.domain import MarkerItem
from papervisor.services.markers import get_markers_for_papers

# HTTP Basic Auth security scheme
security = HTTPBasic(auto_error=False)

logger = logging.getLogger(__name__)

_FORWARDED_HOST_RE = re.compile(r'^[a-z0-9.-]+(?::\d{1,5})?$', re.IGNORECASE)

_SORT_LABELS: dict[str, str] = {
    'newest': 'Newest',
    'oldest': 'Oldest',
    'az': 'A–Z',
    'za': 'Z–A',
    'popular': 'Popular',
    'author': 'Author',
}
_SORT_ORDER: tuple[str, ...] = ('newest', 'oldest', 'az', 'za', 'popular', 'author')

_COLLECTION_FACETS: tuple[tuple[str, str, str], ...] = (
    ('all', 'All Files', 'all'),
    ('papers', 'Academic Papers', 'papers'),
    ('books', 'Books', 'books'),
)


def _normalize_sort(sort_by: str | None) -> str | None:
    if sort_by is None:
        return None
    normalized = str(sort_by).strip().lower()
    return normalized if normalized in _SORT_LABELS else None


def _allow_query_api_key() -> bool:
    """Return ``True`` when OPDS ``?key=...`` auth is allowed.

    Controlled by ``PAPERVISOR_OPDS_ALLOW_QUERY_KEY``.
    Defaults to **True** so profile-provided OPDS URLs work out of the box.
    """
    val = str(os.environ.get('PAPERVISOR_OPDS_ALLOW_QUERY_KEY', '1')).strip().lower()
    return val in {'1', 'true', 'yes', 'on'}


def _client_ip_for_rate_limit(request: Request) -> str:
    """Resolve client IP for rate-limiting, honoring trusted forwarded headers."""
    fallback = request.client.host if request.client else 'unknown'
    if not _trust_forwarded_headers():
        return fallback

    raw = str(request.headers.get('X-Forwarded-For', '') or '').strip()
    if not raw:
        return fallback

    # Use the first hop (original client) from a trusted proxy chain.
    ip = raw.split(',', 1)[0].strip()
    return ip or fallback


def _opds_auth_rate_limit_key(
    *,
    request: Request,
    credentials: Optional[HTTPBasicCredentials],
    query_key: str | None,
) -> str:
    """Build a limiter key that reduces proxy-wide collateral throttling."""
    client_ip = _client_ip_for_rate_limit(request)
    username = str(getattr(credentials, 'username', '') or '').strip().lower()
    if username:
        return f'{client_ip}|u:{username}'
    if query_key:
        key_digest = hashlib.sha256(query_key.encode('utf-8')).hexdigest()[:16]
        return f'{client_ip}|k:{key_digest}'
    return client_ip


def _opds_auth_global_rate_limit_key(*, request: Request) -> str:
    """Build a global per-IP limiter key used to cap aggregate abuse."""
    return _client_ip_for_rate_limit(request)


def get_authenticated_user(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
    key: Optional[str] = Query(None, description="OPDS API key for authentication"),
) -> UserItem:
    """Authenticate user via HTTP Basic Auth or API key parameter."""

    # Disabled OPDS surface should always return 404 before any auth checks.
    check_enabled()

    principal_rate_key = _opds_auth_rate_limit_key(
        request=request,
        credentials=credentials,
        query_key=key,
    )
    global_rate_key = _opds_auth_global_rate_limit_key(request=request)

    allow_query_key = _allow_query_api_key()

    # Try API key first (for Boox and other devices that don't support auth)
    if allow_query_key and key:
        user_item = authenticate_by_api_key(key)
        if user_item:
            opds_auth_limiter.reset(principal_rate_key)
            return user_item

    # Fall back to HTTP Basic Auth
    if credentials:
        user_item = authenticate(username=credentials.username, password=credentials.password)
        if user_item:
            opds_auth_limiter.reset(principal_rate_key)
            return user_item

    # Auth failed: enforce both global IP budget and principal-specific budget.
    if not opds_auth_limiter.check(global_rate_key):
        raise HTTPException(
            status_code=429,
            detail='Too many authentication attempts. Please try again later.',
        )
    if principal_rate_key != global_rate_key and not opds_auth_limiter.check(principal_rate_key):
        raise HTTPException(
            status_code=429,
            detail='Too many authentication attempts. Please try again later.',
        )

    # No valid authentication provided
    detail = 'Authentication required. Use HTTP Basic Auth or add ?key=YOUR_API_KEY to the URL.'
    if not allow_query_key:
        detail = 'Authentication required. Use HTTP Basic Auth.'

    raise HTTPException(
        status_code=401,
        detail=detail,
        headers={'WWW-Authenticate': 'Basic realm="PaperVisor OPDS"'},
    )


def _trust_forwarded_headers() -> bool:
    """Return ``True`` if ``X-Forwarded-*`` headers should be honoured.

    Controlled by the ``PAPERVISOR_TRUST_FORWARDED`` environment variable.
    Defaults to **False** (safe by default). Set to ``1`` / ``true`` / ``yes``
    when PaperVisor runs behind a trusted reverse proxy (nginx, Caddy, etc.).
    """
    val = str(os.environ.get('PAPERVISOR_TRUST_FORWARDED', '')).strip().lower()
    return val in {'1', 'true', 'yes', 'on'}


def _allowed_forwarded_hosts() -> set[str]:
    raw = str(os.environ.get('PAPERVISOR_ALLOWED_FORWARDED_HOSTS', '') or '').strip()
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(',') if item.strip()}


def _sanitize_forwarded_proto(raw: str | None, fallback: str) -> str:
    proto = str(raw or '').strip().lower()
    if proto in {'http', 'https'}:
        return proto
    return fallback


def _sanitize_forwarded_host(raw: str | None, fallback: str) -> str:
    host = str(raw or '').strip().lower()
    if ',' in host:
        host = host.split(',', 1)[0].strip()
    if '/' in host or '\\' in host:
        logger.warning('Ignoring malformed X-Forwarded-Host value: %r', raw)
        return fallback
    if not host:
        return fallback
    if not _FORWARDED_HOST_RE.match(host):
        logger.warning('Ignoring invalid X-Forwarded-Host value: %r', raw)
        return fallback

    allowed = _allowed_forwarded_hosts()
    if allowed and host not in allowed:
        logger.warning('Ignoring untrusted X-Forwarded-Host value: %r', raw)
        return fallback

    return host


def get_base_url(request: Request) -> str:
    """Get base URL from settings or request, respecting proxy headers."""
    configured = get_setting(key='opds_api_directory', default='').strip()
    if configured:
        return configured.rstrip('/')

    prefix = ''
    if _trust_forwarded_headers():
        proto = _sanitize_forwarded_proto(
            request.headers.get('X-Forwarded-Proto'),
            request.url.scheme,
        )
        host = _sanitize_forwarded_host(
            request.headers.get('X-Forwarded-Host'),
            request.url.netloc,
        )
        forwarded_prefix = str(request.headers.get('X-Forwarded-Prefix', '') or '').strip()
        if forwarded_prefix:
            if not forwarded_prefix.startswith('/'):
                forwarded_prefix = f'/{forwarded_prefix}'
            prefix = forwarded_prefix.rstrip('/')
    else:
        proto = request.url.scheme
        host = request.url.netloc

    if not prefix:
        root_path = str(request.scope.get('root_path') or '').strip()
        if root_path:
            if not root_path.startswith('/'):
                root_path = f'/{root_path}'
            prefix = root_path.rstrip('/')

    if '/' in host:
        host = host.split('/')[0]
    base = f'{proto}://{host}{prefix}'
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            'OPDS base_url resolved: configured=%r proto=%s host_header=%r request_netloc=%s prefix=%r final=%s trust_fwd=%s',
            configured,
            proto,
            request.headers.get('X-Forwarded-Host'),
            request.url.netloc,
            prefix,
            base,
            _trust_forwarded_headers(),
        )
    return base


def get_api_key(request: Request) -> Optional[str]:
    """Get API key from request query params if present."""
    if not _allow_query_api_key():
        return None
    key = request.query_params.get('key')
    return key.strip() if key else None


def get_api_key_param(api_key: str | None) -> str:
    """Build API key query string for feeds (e.g. '?key=xxx')."""
    if not api_key:
        return ''
    return f'?key={api_key}'


class OPDSUrlBuilder:
    """Build OPDS URLs with consistent query params and API key support."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key if _allow_query_api_key() else None

    def build(self, path: str = '', **params: object) -> str:
        clean_path = path.lstrip('/')
        if self.base_url.endswith('/opds'):
            url = f'{self.base_url}/{clean_path}' if clean_path else self.base_url
        else:
            url = f'{self.base_url}/opds/{clean_path}'
        query_params: dict[str, object] = {key: value for key, value in params.items() if value is not None}
        if self.api_key:
            query_params['key'] = self.api_key
        if query_params:
            url = f'{url}?{urlencode(query_params, doseq=True)}'
        return url


def check_enabled() -> None:
    """Check if OPDS is enabled, raise 404 if not."""
    enabled = get_setting(key='protocols_enabled', default='1') == '1'
    if not enabled:
        raise HTTPException(status_code=404, detail='OPDS is disabled')


# ---------------------------------------------------------------------------
# OPDSContext – shared per-request dependency
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OPDSContext:
    """Computed once per request; injected via ``Depends(opds_context)``."""

    user: UserItem
    base_url: str
    api_key: str | None
    key_param: str
    url: OPDSUrlBuilder
    sort_by: str | None


def opds_context(
    request: Request,
    user: UserItem = Depends(get_authenticated_user),
) -> OPDSContext:
    """FastAPI dependency that checks OPDS is enabled and assembles context."""
    check_enabled()
    base_url = get_base_url(request)
    api_key = get_api_key(request)
    key_param = get_api_key_param(api_key)
    raw_sort = request.query_params.get('sort')
    sort_by = _normalize_sort(raw_sort)
    url_builder = OPDSUrlBuilder(base_url, api_key)
    return OPDSContext(
        user=user,
        base_url=base_url,
        api_key=api_key,
        key_param=key_param,
        url=url_builder,
        sort_by=sort_by,
    )


def _supports_fetcher_sort(fetcher: Callable[..., list]) -> bool:
    try:
        return 'sort_by' in inspect.signature(fetcher).parameters
    except (TypeError, ValueError):
        return False


def _fetcher_default_sort(fetcher: Callable[..., list]) -> str | None:
    try:
        param = inspect.signature(fetcher).parameters.get('sort_by')
    except (TypeError, ValueError):
        return None
    if param is None or param.default is inspect._empty:
        return None
    return _normalize_sort(str(param.default))


def _fetch_papers_with_optional_sort(
    *,
    fetcher: Callable[..., list],
    user_id: int,
    sort_by: str | None,
    positional_args: tuple[object, ...] = (),
    **kwargs: object,
) -> tuple[list, bool, str | None]:
    supports_sort = _supports_fetcher_sort(fetcher)
    call_kwargs = dict(kwargs)
    if supports_sort and sort_by:
        call_kwargs['sort_by'] = sort_by
    papers = fetcher(user_id, *positional_args, **call_kwargs)
    return papers, supports_sort, _fetcher_default_sort(fetcher)


def _build_sort_facets(
    *,
    ctx: OPDSContext,
    path: str,
    active_sort: str,
    params: dict[str, object] | None = None,
) -> list[opds.OPDSFacetLink]:
    base_params = dict(params or {})
    facets: list[opds.OPDSFacetLink] = []
    for sort_key in _SORT_ORDER:
        facet_params = dict(base_params)
        facet_params['sort'] = sort_key
        facets.append(
            opds.OPDSFacetLink(
                href=ctx.url.build(path, **facet_params),
                title=_SORT_LABELS[sort_key],
                active=(active_sort == sort_key),
            )
        )
    return facets


def _build_collection_facets(
    *,
    ctx: OPDSContext,
    active_collection: str,
    sort_by: str | None,
) -> list[opds.OPDSFacetLink]:
    facets: list[opds.OPDSFacetLink] = []
    for collection_key, label, path in _COLLECTION_FACETS:
        params: dict[str, object] = {}
        if sort_by:
            params['sort'] = sort_by
        facets.append(
            opds.OPDSFacetLink(
                href=ctx.url.build(path, **params),
                title=label,
                facet_group='Collection',
                active=(collection_key == active_collection),
            )
        )
    return facets


def clamp_per_page(per_page: int, *, maximum: int = 200) -> int:
    """Clamp per_page to a safe range."""
    return max(1, min(per_page, maximum))


def _validate_page(page: int) -> int:
    if page < 1:
        raise HTTPException(status_code=422, detail='Page must be >= 1')
    return page


def acquisition_feed_response(
    *,
    ctx: OPDSContext,
    feed_id: str,
    title: str,
    papers: list,
    path: str,
    page: int,
    per_page: int,
    subtitle: str | None = None,
    up_href: str | None = None,
    query_params: dict[str, object] | None = None,
    paper_markers_map: dict[str, list[MarkerItem]] | None = None,
    supports_sort: bool = False,
    default_sort: str = 'az',
    include_collection_facets: bool = False,
    collection_key: str | None = None,
    is_complete_feed: bool = False,
) -> Response:
    """Build a standard paginated acquisition-feed response."""
    extra = dict(query_params or {})
    self_href = ctx.url.build(path, page=page, per_page=per_page, **extra)
    next_href = ctx.url.build(path, page=page + 1, per_page=per_page, **extra) if len(papers) == per_page else None
    prev_href = ctx.url.build(path, page=page - 1, per_page=per_page, **extra) if page > 1 else None

    effective_sort = _normalize_sort(ctx.sort_by or default_sort) or default_sort
    if effective_sort not in _SORT_LABELS:
        effective_sort = default_sort if default_sort in _SORT_LABELS else 'az'

    facets: list[opds.OPDSFacetLink] = []
    if supports_sort:
        facets.extend(
            _build_sort_facets(
                ctx=ctx,
                path=path,
                active_sort=effective_sort,
                params={
                    'page': page,
                    'per_page': per_page,
                    **extra,
                },
            )
        )
    if include_collection_facets and collection_key:
        facets.extend(
            _build_collection_facets(
                ctx=ctx,
                active_collection=collection_key,
                sort_by=effective_sort,
            )
        )

    feed_xml = opds.generate_acquisition_feed(
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
        papers=papers,
        base_url=ctx.base_url,
        self_href=self_href,
        next_href=next_href,
        prev_href=prev_href,
        up_href=up_href,
        key_param=ctx.key_param,
        paper_markers_map=paper_markers_map,
        crawlable_href=ctx.url.build('all'),
        facets=facets or None,
        is_complete_feed=is_complete_feed,
    )
    return Response(content=feed_xml, media_type='application/atom+xml;charset=utf-8')


def navigation_feed_response(
    *,
    ctx: OPDSContext,
    feed_id: str,
    title: str,
    entries: list,
    path: str,
    subtitle: str | None = None,
    up_href: str | None = None,
) -> Response:
    """Build a standard navigation-feed response."""
    feed_xml = opds.generate_navigation_feed(
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
        entries=entries,
        base_url=ctx.base_url,
        self_href=ctx.url.build(path),
        up_href=up_href,
        key_param=ctx.key_param,
        crawlable_href=ctx.url.build('all'),
    )
    return Response(content=feed_xml, media_type='application/atom+xml;charset=utf-8')


def _named_count_nav_entries(
    *,
    ctx: OPDSContext,
    items: Iterable[tuple[str, int]],
    id_prefix: str,
    href_prefix: str,
    content_template: str,
    encode_id: bool = True,
    encode_href: bool = True,
    feed_kind: str = 'acquisition',
) -> list[opds.OPDSNavEntry]:
    entries: list[opds.OPDSNavEntry] = []
    for raw_name, count in items:
        name = str(raw_name)
        id_name = quote(name) if encode_id else name
        href_name = quote(name) if encode_href else name
        entries.append(
            opds.OPDSNavEntry(
                id=f'{id_prefix}{id_name}',
                title=name,
                href=ctx.url.build(f'{href_prefix}{href_name}'),
                content=content_template.format(name=name, count=count),
                count=count,
                feed_kind=feed_kind,
            )
        )
    return entries


def _entity_count_nav_entries(
    *,
    ctx: OPDSContext,
    items: Iterable[tuple[object, int]],
    id_prefix: str,
    href_prefix: str,
    default_content_template: str,
    content_attr: str | None = None,
    feed_kind: str = 'acquisition',
) -> list[opds.OPDSNavEntry]:
    entries: list[opds.OPDSNavEntry] = []
    for entity, count in items:
        entity_id = str(getattr(entity, 'id', '') or '')
        raw_name = str(getattr(entity, 'name', '') or '').strip()
        name = raw_name or 'Unnamed'

        content = ''
        if content_attr:
            content = str(getattr(entity, content_attr, '') or '').strip()
        if not content:
            content = default_content_template.format(name=name, count=count)

        entries.append(
            opds.OPDSNavEntry(
                id=f'{id_prefix}{entity_id}',
                title=name,
                href=ctx.url.build(f'{href_prefix}{quote(entity_id)}'),
                content=content,
                count=count,
                feed_kind=feed_kind,
            )
        )
    return entries


def _nav_entry(
    *,
    ctx: OPDSContext,
    id: str,
    title: str,
    path: str,
    content: str,
    count: int | None = None,
    feed_kind: str = 'acquisition',
) -> opds.OPDSNavEntry:
    return opds.OPDSNavEntry(
        id=id,
        title=title,
        href=ctx.url.build(path),
        content=content,
        count=count,
        feed_kind=feed_kind,
    )


def _nav_entries_from_specs(
    *,
    ctx: OPDSContext,
    specs: Iterable[dict[str, object]],
) -> list[opds.OPDSNavEntry]:
    entries: list[opds.OPDSNavEntry] = []
    for spec in specs:
        entries.append(
            _nav_entry(
                ctx=ctx,
                id=str(spec['id']),
                title=str(spec['title']),
                path=str(spec['path']),
                content=str(spec.get('content', '') or ''),
                count=(int(spec['count']) if spec.get('count') is not None else None),
                feed_kind=str(spec.get('feed_kind', 'acquisition') or 'acquisition'),
            )
        )
    return entries


def _author_filtered_acquisition_response(
    *,
    ctx: OPDSContext,
    author: str,
    page: int,
    per_page: int,
    file_type: str,
    feed_id_prefix: str,
    title_prefix: str,
    path_prefix: str,
    up_path: str,
) -> Response:
    valid_page = _validate_page(page)
    clean_author = unquote(author)
    clamped_per_page = clamp_per_page(per_page)
    offset = (valid_page - 1) * clamped_per_page

    all_papers, supports_sort, fetcher_default_sort = _fetch_papers_with_optional_sort(
        fetcher=opds.get_papers_by_author,
        user_id=ctx.user.id,
        sort_by=ctx.sort_by,
        positional_args=(clean_author,),
        limit=clamped_per_page,
        offset=offset,
    )
    papers = [paper for paper in all_papers if paper.file_type == file_type]
    
    paper_ids = [str(p.id) for p in papers]
    paper_markers_map = get_markers_for_papers(user_id=ctx.user.id, paper_ids=paper_ids) if papers else {}

    return acquisition_feed_response(
        ctx=ctx,
        feed_id=f'{feed_id_prefix}{clean_author}',
        title=f'{title_prefix} {clean_author}',
        papers=papers,
        path=f'{path_prefix}{quote(clean_author)}',
        page=valid_page,
        per_page=clamped_per_page,
        up_href=ctx.url.build(up_path),
        query_params={'sort': ctx.sort_by} if (supports_sort and ctx.sort_by) else None,
        paper_markers_map=paper_markers_map,
        supports_sort=supports_sort,
        default_sort=fetcher_default_sort or 'az',
    )


def _named_browse_acquisition_response(
    *,
    ctx: OPDSContext,
    name: str,
    page: int,
    per_page: int,
    fetcher: Callable[..., list],
    feed_id_prefix: str,
    title_prefix: str,
    path_prefix: str,
    up_path: str,
    encode_path_component: bool = True,
) -> Response:
    return _named_entity_acquisition_response(
        ctx=ctx,
        value=name,
        page=page,
        per_page=per_page,
        fetcher=fetcher,
        feed_id_prefix=feed_id_prefix,
        title_prefix=title_prefix,
        path_prefix=path_prefix,
        encode_path_component=encode_path_component,
        up_path=up_path,
    )


def _named_entity_acquisition_response(
    *,
    ctx: OPDSContext,
    value: str,
    page: int,
    per_page: int,
    fetcher: Callable[..., list],
    feed_id_prefix: str,
    title_prefix: str,
    path_prefix: str,
    raise_on_empty_first_page: bool = False,
    not_found_detail: str = 'No items found',
    encode_path_component: bool = True,
    up_path: str | None = None,
    title_value: str | None = None,
) -> Response:
    valid_page = _validate_page(page)
    clean_value = unquote(value)
    clean_title_value = unquote(title_value) if title_value is not None else clean_value
    clamped_per_page = clamp_per_page(per_page)
    offset = (valid_page - 1) * clamped_per_page

    papers, supports_sort, fetcher_default_sort = _fetch_papers_with_optional_sort(
        fetcher=fetcher,
        user_id=ctx.user.id,
        sort_by=ctx.sort_by,
        positional_args=(clean_value,),
        limit=clamped_per_page,
        offset=offset,
    )
    if raise_on_empty_first_page and valid_page == 1 and not papers:
        raise HTTPException(status_code=404, detail=not_found_detail)

    path_component = quote(clean_value) if encode_path_component else clean_value
    
    paper_ids = [str(p.id) for p in papers]
    paper_markers_map = get_markers_for_papers(user_id=ctx.user.id, paper_ids=paper_ids) if papers else {}

    return acquisition_feed_response(
        ctx=ctx,
        feed_id=f'{feed_id_prefix}{clean_value}',
        title=f'{title_prefix} {clean_title_value}',
        papers=papers,
        path=f'{path_prefix}{path_component}',
        page=valid_page,
        per_page=clamped_per_page,
        query_params={'sort': ctx.sort_by} if (supports_sort and ctx.sort_by) else None,
        up_href=(ctx.url.build(up_path) if up_path else None),
        paper_markers_map=paper_markers_map,
        supports_sort=supports_sort,
        default_sort=fetcher_default_sort or 'az',
    )


def _paginated_acquisition(
    *,
    ctx: OPDSContext,
    page: int,
    per_page: int,
    fetcher: Callable[..., list],
    feed_id: str,
    title: str,
    path: str,
    subtitle: str | None = None,
    subtitle_builder: Callable[[list], str | None] | None = None,
    query_params: dict[str, object] | None = None,
    default_sort: str = 'az',
    include_collection_facets: bool = False,
    collection_key: str | None = None,
    **fetcher_kwargs: object,
) -> Response:
    valid_page = _validate_page(page)
    clamped_per_page = clamp_per_page(per_page)
    offset = (valid_page - 1) * clamped_per_page
    papers, supports_sort, fetcher_default_sort = _fetch_papers_with_optional_sort(
        fetcher=fetcher,
        user_id=ctx.user.id,
        sort_by=ctx.sort_by,
        limit=clamped_per_page,
        offset=offset,
        **fetcher_kwargs,
    )
    resolved_subtitle = subtitle_builder(papers) if subtitle_builder is not None else subtitle
    
    paper_ids = [str(p.id) for p in papers]
    paper_markers_map = get_markers_for_papers(user_id=ctx.user.id, paper_ids=paper_ids) if papers else {}

    merged_query_params = dict(query_params or {})
    if supports_sort and ctx.sort_by:
        merged_query_params['sort'] = ctx.sort_by

    return acquisition_feed_response(
        ctx=ctx,
        feed_id=feed_id,
        title=title,
        subtitle=resolved_subtitle,
        papers=papers,
        path=path,
        page=valid_page,
        per_page=clamped_per_page,
        query_params=merged_query_params or None,
        paper_markers_map=paper_markers_map,
        supports_sort=supports_sort,
        default_sort=fetcher_default_sort or default_sort,
        include_collection_facets=include_collection_facets,
        collection_key=collection_key,
    )


def _browse_named_count_list_response(
    *,
    ctx: OPDSContext,
    items: list[tuple[str, int]],
    id_prefix: str,
    href_prefix: str,
    content_template: str,
    feed_id: str,
    title: str,
    path: str,
    subtitle_suffix: str,
    encode_id: bool = True,
    encode_href: bool = True,
) -> Response:
    return _named_count_navigation_feed_response(
        ctx=ctx,
        items=items,
        id_prefix=id_prefix,
        href_prefix=href_prefix,
        content_template=content_template,
        feed_id=feed_id,
        title=title,
        subtitle=f'{len(items)} {subtitle_suffix}',
        path=path,
        up_href=ctx.url.build('browse'),
        encode_id=encode_id,
        encode_href=encode_href,
    )


def _browse_author_acquisition_response(
    *,
    ctx: OPDSContext,
    author: str,
    page: int,
    per_page: int,
    file_type: str,
    feed_id_prefix: str,
    title_prefix: str,
    path_prefix: str,
    up_path: str,
) -> Response:
    return _author_filtered_acquisition_response(
        ctx=ctx,
        author=author,
        page=page,
        per_page=per_page,
        file_type=file_type,
        feed_id_prefix=feed_id_prefix,
        title_prefix=title_prefix,
        path_prefix=path_prefix,
        up_path=up_path,
    )


def _browse_named_acquisition_response(
    *,
    ctx: OPDSContext,
    name: str,
    page: int,
    per_page: int,
    fetcher: Callable[..., list],
    feed_id_prefix: str,
    title_prefix: str,
    path_prefix: str,
    up_path: str,
    encode_path_component: bool = True,
) -> Response:
    return _named_browse_acquisition_response(
        ctx=ctx,
        name=name,
        page=page,
        per_page=per_page,
        fetcher=fetcher,
        feed_id_prefix=feed_id_prefix,
        title_prefix=title_prefix,
        path_prefix=path_prefix,
        up_path=up_path,
        encode_path_component=encode_path_component,
    )


def _named_count_navigation_feed_response(
    *,
    ctx: OPDSContext,
    items: Iterable[tuple[str, int]],
    id_prefix: str,
    href_prefix: str,
    content_template: str,
    feed_id: str,
    title: str,
    subtitle: str,
    path: str,
    up_href: str | None = None,
    encode_id: bool = True,
    encode_href: bool = True,
) -> Response:
    entries = _named_count_nav_entries(
        ctx=ctx,
        items=items,
        id_prefix=id_prefix,
        href_prefix=href_prefix,
        content_template=content_template,
        encode_id=encode_id,
        encode_href=encode_href,
    )
    return navigation_feed_response(
        ctx=ctx,
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
        entries=entries,
        path=path,
        up_href=up_href,
    )


def _entity_count_navigation_feed_response(
    *,
    ctx: OPDSContext,
    items: Iterable[tuple[object, int]],
    id_prefix: str,
    href_prefix: str,
    default_content_template: str,
    feed_id: str,
    title: str,
    subtitle: str,
    path: str,
    content_attr: str | None = None,
    up_href: str | None = None,
) -> Response:
    entries = _entity_count_nav_entries(
        ctx=ctx,
        items=items,
        id_prefix=id_prefix,
        href_prefix=href_prefix,
        default_content_template=default_content_template,
        content_attr=content_attr,
    )
    return navigation_feed_response(
        ctx=ctx,
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
        entries=entries,
        path=path,
        up_href=up_href,
    )


def _static_menu_navigation_feed_response(
    *,
    ctx: OPDSContext,
    entries: list[opds.OPDSNavEntry],
    feed_id: str,
    title: str,
    subtitle: str,
    path: str,
    up_href: str | None = None,
) -> Response:
    return navigation_feed_response(
        ctx=ctx,
        feed_id=feed_id,
        title=title,
        subtitle=subtitle,
        entries=entries,
        path=path,
        up_href=up_href,
    )
