"""References of a document, a group or a selection: grouped, deduplicated, or addresses only."""

import pytest
from fastapi.testclient import TestClient

from annals.api import mk_app
from annals.auth import no_auth
from annals.references import (
    combine_references,
    reference_entries,
    reference_sections,
    urls_of,
)
from annals.store import DocStore

BEES = """# Bees

Hives [1] and pollen [2].

## REFERENCES

Accessed 2026-10-30.

1. [Hive life](https://bees.org/hive). 2024.
2. Smith J. Pollen,
   wrapped line. <https://pollen.net/a>

## Appendix

https://not-a-reference.org
"""
WASPS = """# Wasps

```md
## References
1. inside a code fence: https://fenced.org
```

### References
[1] [Hive life again](https://BEES.org/hive/#top)
[2] [Paper wasp](https://en.wikipedia.org/wiki/Polistes_(genus)).
"""


def test_sections_entries_and_addresses():
    (bees,) = reference_sections(BEES)
    assert bees.startswith("Accessed") and "not-a-reference" not in bees
    assert reference_entries(bees) == [
        "1. [Hive life](https://bees.org/hive). 2024.",
        "2. Smith J. Pollen, wrapped line. <https://pollen.net/a>",
    ]
    (wasps,) = reference_sections(WASPS)  # the fenced heading is not a section
    assert "fenced.org" not in wasps
    assert urls_of(wasps) == [
        "https://BEES.org/hive/#top",
        "https://en.wikipedia.org/wiki/Polistes_(genus)",
    ]


def test_three_forms():
    items = [("Bees", [BEES]), ("Wasps", [WASPS]), ("Ants", ["# Ants\n\nno refs"])]
    grouped = combine_references(items, title="Insects")
    assert grouped.startswith("## References for Insects\n\n### Bees\n\nAccessed")
    assert "### Wasps" in grouped and "### Ants" not in grouped
    assert "1. [Hive life]" in grouped  # as they are, numbers kept
    deduped = combine_references(items, title="Insects", form="deduped")
    assert deduped.splitlines()[2:] == [
        "- [Hive life](https://bees.org/hive). 2024.",
        "- Smith J. Pollen, wrapped line. <https://pollen.net/a>",
        "- [Paper wasp](https://en.wikipedia.org/wiki/Polistes_(genus)).",
    ]
    assert combine_references(items, title="Insects", form="urls").splitlines() == [
        "https://bees.org/hive",
        "https://pollen.net/a",
        "https://en.wikipedia.org/wiki/Polistes_(genus)",
    ]
    assert combine_references([("Ants", ["none"])], title="x") == ""
    with pytest.raises(ValueError):
        combine_references(items, title="x", form="nope")


@pytest.fixture
def setup(tmp_path):
    store = DocStore(tmp_path / "data")
    bees = store.publish(text=BEES, title="Bees", filename="bees.md")
    wasps = store.publish(text=WASPS, title="Wasps", filename="wasps.md")
    ants = store.publish(text="# Ants", title="Ants", filename="ants.md")
    g = store.make_group("Insects", [bees["id"], wasps["id"], ants["id"]])
    client = TestClient(mk_app(store=store, authorizer=no_auth))
    return client, store, g, bees, wasps, ants


def test_references_endpoint(setup):
    client, store, g, bees, wasps, ants = setup
    url = "/annals/api/references"
    r = client.get(url, params={"group": g["id"]})
    assert r.status_code == 200 and r.text.startswith("## References for Insects")
    assert (r.headers["x-annals-items"], r.headers["x-annals-without"]) == ("2", "1")
    assert r.headers["x-annals-count"] == "4"
    some = client.get(
        url, params={"group": g["id"], "doc": [wasps["id"]], "form": "urls"}
    )
    assert some.text.splitlines() == [
        "https://BEES.org/hive/#top",
        "https://en.wikipedia.org/wiki/Polistes_(genus)",
    ]
    loose = client.get(
        url, params={"doc": [bees["id"], wasps["id"]], "form": "deduped"}
    )
    assert (
        loose.text.startswith("## References for 2 documents")
        and loose.headers["x-annals-count"] == "3"
    )
    one = client.get(url, params={"doc": [bees["id"]]})
    assert one.text.startswith("## References for Bees")
    saved = client.get(url, params={"doc": [bees["id"]], "form": "urls", "download": 1})
    assert saved.headers["content-type"].startswith("text/plain")
    assert ".txt" in saved.headers["content-disposition"]
    assert client.get(url, params={"doc": [ants["id"]]}).status_code == 404
    assert client.get(url).status_code == 422
    assert client.get(url, params={"group": g["id"], "form": "x"}).status_code == 422
    assert (
        client.get(
            url, params={"group": g["id"], "doc": ["20200101-000000-nope-0000"]}
        ).status_code
        == 422
    )
    store.trash(wasps["id"])
    assert client.get(url, params={"group": g["id"]}).headers["x-annals-items"] == "1"
