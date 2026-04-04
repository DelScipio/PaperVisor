# OPDS FIX

## Goal
Implement a clean, workable OPDS 1.2 facet model for reorder/filtering and remove legacy compatibility paths.

## Contract (new)

### Reorder (`facetGroup=Reorder`)
Canonical `sort` values:
- `newest`
- `oldest`
- `az`
- `za`
- `popular`
- `author`

Legacy values removed:
- `title`

### Filter (`facetGroup=Collection`)
Collection feed facets:
- `all`
- `papers`
- `books`

## Checklist
- [x] Centralize sort/facet metadata in one place
- [x] Remove old `title` sort alias handling
- [x] Reuse shared sort facet builder in complete feed
- [x] Add collection filter facets to acquisition feeds
- [x] Update OPDS XML tests for canonical facets/groups
- [x] Run OPDS tests
- [x] Update docs (README + OPDS Spec)

## Notes
- Keep implementation minimal and OPDS-client friendly.
- Preserve existing endpoint URLs.
- Test run: `python -m pytest -q tests/test_opds_mock.py tests/test_opds_api_routes.py` → `8 passed`.
