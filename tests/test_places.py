from pathlib import Path

from geonames_sample import SAMPLE, geonames_line

from placefinder.places import PlaceRepository, parse_line


def test_parse_line_reads_columns_and_names() -> None:
    place, names = parse_line(SAMPLE[2])
    assert place.id == 2867714
    assert place.name == "Munich"
    assert (place.latitude, place.longitude) == (48.13743, 11.57549)
    assert (place.country_code, place.feature_code) == ("DE", "PPLA")
    assert place.population == 1260391
    assert place.timezone == "Europe/Berlin"
    assert names == {"Munich", "München", "Muenchen"}


def test_parse_line_without_alternate_names() -> None:
    _, names = parse_line(geonames_line(1, "Nowhere", "", 0.0, 0.0, "PPL", 0))
    assert names == {"Nowhere"}


def test_load_replaces_content(data_file: Path) -> None:
    repo = PlaceRepository()
    repo.load(data_file)
    repo.load(data_file)
    assert len(repo) == len(SAMPLE)
    assert repo.get(2929670) is not None
    assert repo.get(1) is None


def test_search_returns_each_place_once(data_file: Path) -> None:
    repo = PlaceRepository()
    repo.load(data_file)
    # Frankfurt (Oder) matches with three names, Frankfurt am Main with two
    assert [p.id for p in repo.search("frankfurt")] == [2925533, 2925535]
    assert repo.search("   ") == []


def test_search_puts_exact_matches_before_larger_places() -> None:
    repo = PlaceRepository()
    lines = [
        geonames_line(1, "Paris", "", 0.0, 0.0, "PPL", 1000),
        geonames_line(2, "Parish Town", "", 0.0, 0.0, "PPL", 50000),
    ]
    repo.replace(parse_line(line) for line in lines)
    assert [p.id for p in repo.search("paris")] == [1, 2]
