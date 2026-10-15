#!/usr/bin/env bash
# Download a GeoNames dump into this directory as <name>.txt.
# Usage: data/download.sh [name]
#   name: cities15000 (default), cities5000, cities1000, DE, allCountries ...
#   (list: https://download.geonames.org/export/dump/)
# GeoNames data is licensed under CC BY 4.0: https://www.geonames.org
set -o errexit -o nounset -o pipefail

name="${1:-cities15000}"
cd "$(dirname "$0")"

echo "Downloading $name.zip from GeoNames ..."
curl --fail --silent --show-error --location --output "$name.zip" "https://download.geonames.org/export/dump/$name.zip"
python3 -m zipfile --extract "$name.zip" .
rm "$name.zip"
echo "Done: data/$name.txt with $(wc --lines <"$name.txt") places"
