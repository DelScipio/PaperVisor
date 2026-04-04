from papervisor.ui.dialogs.marker_dialogs import (
    MAX_QUERY_CHILDREN,
    MAX_QUERY_DEPTH,
    _ensure_v2_query,
)


def _max_group_depth(node: dict[str, object], depth: int = 0) -> int:
    children = node.get('children')
    if not isinstance(children, list) or not children:
        return depth
    max_depth = depth
    for child in children:
        if isinstance(child, dict) and str(child.get('type') or '') == 'group':
            max_depth = max(max_depth, _max_group_depth(child, depth + 1))
    return max_depth


def test_ensure_v2_query_defaults_to_single_rule() -> None:
    query = _ensure_v2_query(None)

    assert query['version'] == 2
    root = query['root']
    assert root['type'] == 'group'
    assert root['op'] == 'and'
    assert isinstance(root['children'], list)
    assert len(root['children']) == 1

    rule = root['children'][0]
    assert rule['type'] == 'rule'
    assert rule['field'] == 'title'
    assert rule['operator'] == 'equals'
    assert rule['value'] == ''


def test_ensure_v2_query_sanitizes_legacy_rule_payload() -> None:
    query = _ensure_v2_query({'field': 'Tags', 'operator': 'includes_any', 'value': 'AI'})

    root = query['root']
    assert root['type'] == 'group'
    assert len(root['children']) == 1

    rule = root['children'][0]
    assert rule['field'] == 'tags'
    assert rule['operator'] == 'includes_any'
    assert rule['value'] == ['AI']


def test_ensure_v2_query_sanitizes_legacy_marker_rule_payload() -> None:
    query = _ensure_v2_query({'field': 'Markers', 'operator': 'includes_any', 'value': 'marker-1'})

    root = query['root']
    assert root['type'] == 'group'
    assert len(root['children']) == 1

    rule = root['children'][0]
    assert rule['field'] == 'markers'
    assert rule['operator'] == 'includes_any'
    assert rule['value'] == ['marker-1']


def test_ensure_v2_query_empty_operator_resets_marker_value() -> None:
    query = _ensure_v2_query(
        {
            'version': 2,
            'root': {
                'type': 'group',
                'children': [
                    {
                        'type': 'rule',
                        'field': 'markers',
                        'operator': 'empty',
                        'value': ['marker-1', 'marker-2'],
                    }
                ],
            },
        }
    )

    rule = query['root']['children'][0]
    assert rule['field'] == 'markers'
    assert rule['operator'] == 'empty'
    assert rule['value'] == []


def test_ensure_v2_query_normalizes_invalid_field_and_operator() -> None:
    query = _ensure_v2_query(
        {
            'version': 2,
            'root': {
                'type': 'group',
                'op': 'invalid',
                'children': [
                    {'type': 'rule', 'field': 'unknown_field', 'operator': 'invalid_op', 'value': {'bad': 'value'}},
                ],
            },
        }
    )

    root = query['root']
    assert root['op'] == 'and'
    rule = root['children'][0]
    assert rule['field'] == 'title'
    assert rule['operator'] == 'equals'
    assert rule['value'] == ''


def test_ensure_v2_query_deduplicates_tag_values_case_insensitive() -> None:
    query = _ensure_v2_query(
        {
            'version': 2,
            'root': {
                'type': 'group',
                'children': [
                    {
                        'type': 'rule',
                        'field': 'tags',
                        'operator': 'includes_all',
                        'value': ['AI', 'ai', '  ', 'ML', 'ml'],
                    }
                ],
            },
        }
    )

    rule = query['root']['children'][0]
    assert rule['field'] == 'tags'
    assert rule['value'] == ['AI', 'ML']


def test_ensure_v2_query_limits_number_of_children() -> None:
    many_rules = [
        {'type': 'rule', 'field': 'title', 'operator': 'contains', 'value': f'paper-{i}'}
        for i in range(MAX_QUERY_CHILDREN + 10)
    ]

    query = _ensure_v2_query({'version': 2, 'root': {'type': 'group', 'children': many_rules}})

    assert len(query['root']['children']) == MAX_QUERY_CHILDREN


def test_ensure_v2_query_limits_group_depth() -> None:
    root: dict[str, object] = {'type': 'group', 'op': 'and', 'children': []}
    cursor = root

    for _ in range(MAX_QUERY_DEPTH + 5):
        child: dict[str, object] = {'type': 'group', 'op': 'and', 'children': []}
        cursor['children'] = [child]
        cursor = child

    cursor['children'] = [{'type': 'rule', 'field': 'title', 'operator': 'contains', 'value': 'deep'}]

    query = _ensure_v2_query({'version': 2, 'root': root})

    assert _max_group_depth(query['root']) <= MAX_QUERY_DEPTH
