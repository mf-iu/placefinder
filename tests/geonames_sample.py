"""Sample places in the format of a GeoNames dump, shared by the tests."""


def geonames_line(
    place_id: int,
    name: str,
    alternates: str,
    lat: float,
    lon: float,
    feature_code: str,
    population: int,
    country: str = "DE",
    timezone: str = "Europe/Berlin",
) -> str:
    """Build one line with the 19 tab-separated columns of a GeoNames dump."""
    columns = [""] * 19
    columns[0] = str(place_id)
    columns[1] = columns[2] = name  # name and ASCII name
    columns[3] = alternates
    columns[4], columns[5] = str(lat), str(lon)
    columns[6], columns[7] = "P", feature_code  # feature class and code
    columns[8] = country  # ISO 3166 country code
    columns[14] = str(population)
    columns[17] = timezone
    return "\t".join(columns) + "\n"


# a few places as in cities15000.txt, alternate names shortened
SAMPLE = [
    geonames_line(2929670, "Erfurt", "ERF,Erfordia,Ehrfurt", 50.97734, 11.03536, "PPLA", 218793),
    geonames_line(2929567, "Erlangen", "Erlanga", 49.59099, 11.00783, "PPLA3", 116562),
    geonames_line(2867714, "Munich", "München,Muenchen", 48.13743, 11.57549, "PPLA", 1260391),
    geonames_line(2925533, "Frankfurt am Main", "Frankfurt", 50.11552, 8.68417, "PPLA2", 763380),
    geonames_line(
        2925535,
        "Frankfurt (Oder)",
        "Frankfurt,Frankfurt an der Oder",
        52.34714,
        14.55062,
        "PPLA3",
        57873,
    ),
    geonames_line(2812482, "Weimar", "Veimar", 50.9803, 11.32903, "PPLA3", 65090),
    geonames_line(
        2761369, "Vienna", "Wien", 48.20849, 16.37208, "PPLC", 1691468, "AT", "Europe/Vienna"
    ),
]
