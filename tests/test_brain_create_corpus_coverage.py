"""Transparent structural v2 coverage roster; it is not a semantic oracle.

The frozen production references are deliberately never read here.  These
thirty rows encode only the user-visible structural vocabulary that the ten
four-message journeys require at their Draft-producing stages.
"""

from __future__ import annotations

STRUCTURAL_COVERAGE_10X3 = (
    ("similar_cinema", "T2", ("map.attach/v1:base", "matrix.attach/v1:similarity")),
    (
        "similar_cinema",
        "T3",
        (
            "matrix.attach/v1:main+4-variants",
            "quota.distribute/v1:10",
            "map.set/v1:similarity",
            "map.set/v1:order",
        ),
    ),
    (
        "similar_cinema",
        "T4",
        ("map.attach/v1:fallback", "matrix.attach/v1:alternatives", "map.set/v1:limit24"),
    ),
    ("similar_serie", "T2", ("map.attach/v1:seed", "map.set/v1:recent24")),
    (
        "similar_serie",
        "T3",
        ("matrix.attach/v1:3-variants", "quota.distribute/v1:9", "map.attach/v1:recent+similarity"),
    ),
    ("similar_serie", "T4", ("matrix.attach/v1:fallback", "map.set/v1:24x2", "map.set/v1:shuffle")),
    ("filtered_search", "T2", ("map.set/v1:page-default50", "map.attach/v1:shared-search")),
    ("filtered_search", "T3", ("matrix.attach/v1:7-variants", "matrix.attach/v1:alternatives")),
    ("filtered_search", "T4", ("matrix.attach/v1:view-all", "map.attach/v1:fallbacks")),
    (
        "search.detail",
        "T2",
        ("matrix.attach/v1:inputs", "matrix.attach/v1:3-attributes", "map.attach/v1:block"),
    ),
    (
        "search.detail",
        "T3",
        ("matrix.attach/v1:3-blocks", "quota.distribute/v1:9", "map.set/v1:dedup"),
    ),
    ("search.detail", "T4", ("matrix.attach/v1:9-variants", "matrix.attach/v1:metadata")),
    ("compleanno", "T2", ("matrix.attach/v1:multi-catalog-context", "quota.distribute/v1:roles")),
    (
        "compleanno",
        "T3",
        ("matrix.attach/v1:11-roles", "quota.distribute/v1:26", "matrix.attach/v1:viewall+order"),
    ),
    (
        "compleanno",
        "T4",
        ("matrix.attach/v1:fallbacks", "matrix.attach/v1:variants", "map.set/v1:caps"),
    ),
    ("titoli_momento", "T2", ("matrix.attach/v1:film+series", "map.set/v1:total30")),
    (
        "titoli_momento",
        "T3",
        ("matrix.attach/v1:10-blocks", "quota.distribute/v1:27", "matrix.attach/v1:viewall"),
    ),
    (
        "titoli_momento",
        "T4",
        ("map.set/v1:pipeline", "matrix.attach/v1:2-variants", "map.attach/v1:fallback"),
    ),
    ("tvod", "T2", ("matrix.attach/v1:matrix11", "map.attach/v1:context-row")),
    ("tvod", "T3", ("map.set/v1:order", "map.attach/v1:error-fallback")),
    ("tvod", "T4", ("map.set/v1:snapshot+viewall",)),
    ("4k", "T2", ("matrix.attach/v1:paired20x50", "map.attach/v1:parameter-block")),
    (
        "4k",
        "T3",
        ("quota.distribute/v1:6", "matrix.attach/v1:matrix4", "matrix.attach/v1:viewall+year"),
    ),
    ("4k", "T4", ("map.set/v1:empty", "map.attach/v1:seriesdocs", "map.set/v1:affinity")),
    ("inf_film_serie", "T2", ("matrix.attach/v1:4-parameter-blocks", "matrix.attach/v1:matrix12")),
    ("inf_film_serie", "T3", ("matrix.attach/v1:viewall", "map.set/v1:smart-order")),
    ("inf_film_serie", "T4", ("map.set/v1:refinement",)),
    ("similar_intrat", "T2", ("matrix.attach/v1:4-pools50", "map.set/v1:windows+group")),
    (
        "similar_intrat",
        "T3",
        ("matrix.attach/v1:take4x24", "matrix.attach/v1:alternatives+promotion"),
    ),
    ("similar_intrat", "T4", ("map.set/v1:dedup+limit24", "map.attach/v1:append-fallback")),
)


def test_structural_coverage_roster_is_complete_without_claiming_semantic_accuracy() -> None:
    assert len(STRUCTURAL_COVERAGE_10X3) == 30
    assert len(set(STRUCTURAL_COVERAGE_10X3)) == 30
    journeys = {
        "similar_cinema",
        "similar_serie",
        "filtered_search",
        "search.detail",
        "compleanno",
        "titoli_momento",
        "tvod",
        "4k",
        "inf_film_serie",
        "similar_intrat",
    }
    expected = {(journey, stage) for journey in journeys for stage in ("T2", "T3", "T4")}
    actual = {(journey, stage) for journey, stage, _ in STRUCTURAL_COVERAGE_10X3}
    assert actual == expected
    print("in=30 out=30 distinct=30 gaps=0")


def test_coverage_is_limited_to_generic_v2_operations_and_combinator_surface() -> None:
    allowed = {
        "map.attach/v1",
        "map.set/v1",
        "matrix.attach/v1",
        "quota.distribute/v1",
    }
    for _, _, vocabulary in STRUCTURAL_COVERAGE_10X3:
        assert {item.split(":", 1)[0] for item in vocabulary} <= allowed
