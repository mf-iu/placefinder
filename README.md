# PlaceFinder

Beispielanwendung des Kurses „Cloud Computing“: ein Dienst zur Ortssuche auf Basis von GeoNames, später ergänzt um OpenStreetMap. PlaceFinder wächst von Termin zu Termin; jeder Stand ist als Git-Tag verfügbar.

**Stand v0 (Tags `t01` bis `t03`):** eine FastAPI-Anwendung, die beim Start die GeoNames-Datei `cities15000` (alle Orte ab 15.000 Einwohnern, rund 34.000) in den Speicher lädt und nach Namen durchsucht. Ab `t02` gibt es dazu ein Container-Image und eine `compose.yaml`, die PlaceFinder zusammen mit einem kleinen Übungsdienst startet (Abschnitt [Container](#container)). Ab `t03` liegen unter `deploy/` Manifeste für Kubernetes und ein Helm-Chart (Abschnitt [Kubernetes](#kubernetes)).

**Stand v1 (Tag `t05`, Version 0.5.0):** eine REST-API unter `/v1` mit GeoJSON, Suche nach Name, Umkreis, Bounding Box und Land, Cursor-Paginierung, Caching-Headern, ETags und Fehlern nach RFC 9457 (Abschnitt [REST-API v1](#rest-api-v1)), dazu eine Karte mit MapLibre GL JS (Abschnitt [Karte](#karte)). Die Endpunkte von v0 bleiben vorerst erreichbar, sind aber als veraltet markiert.

**Stand mit Datenbank (Tag `t06`, Version 0.6.0):** Ist `DATABASE_URL` gesetzt, liest PlaceFinder die Orte aus PostgreSQL mit PostGIS statt aus der Datei im Speicher – dieselbe API, dieselben Antworten (Abschnitt [Datenbank](#datenbank)). `compose.yaml` enthält dafür den Dienst `db`. Ohne `DATABASE_URL` arbeitet PlaceFinder wie bisher mit der Datei.

**Stand mit Cache und eigenen Kacheln (Tag `t07`, Version 0.7.0):** Ist `VALKEY_URL` gesetzt, hält PlaceFinder die Antworten der Suche einige Minuten in Valkey (Abschnitt [Cache](#cache)). Die Karte liest ihre Basiskarte auf Wunsch aus einer einzigen PMTiles-Datei im Object Storage (Abschnitt [Eigene Kacheln](#eigene-kacheln-pmtiles)). `compose.yaml` enthält dafür die Dienste `valkey` und `seaweedfs`.

**Stand mit Pipeline und Telemetrie (Tag `t08`, Version 0.8.0):** Eine CI-Pipeline mit GitHub Actions prüft jeden Push, baut das Image, scannt es, lädt es mit SBOM in die GitHub Container Registry und signiert es (Abschnitt [Pipeline](#pipeline)). Ist `OTEL_EXPORTER_OTLP_ENDPOINT` gesetzt, sendet PlaceFinder Traces und Metriken mit OpenTelemetry (Abschnitt [Beobachtbarkeit](#beobachtbarkeit)). Mit `DATABASE_INIT=true` füllt PlaceFinder eine leere Datenbank selbst – nötig, wenn die Datenbank in einem privaten Netz liegt (Abschnitt [Datenbank selbst füllen](#datenbank-selbst-füllen)).

## Einrichtung

Voraussetzung ist der Dev Container der Übungs-Repositories; die Einrichtung beschreibt [cloud-labs-local/00-setup](https://github.com/mf-iu/cloud-labs-local/tree/master/00-setup). Ohne Dev Container genügt die Ubuntu-Shell in WSL: `start.sh` installiert [uv](https://docs.astral.sh/uv/) bei Bedarf, uv lädt ein passendes Python.

1. **Forken:** Das Repository auf GitHub forken; eigene Pipelines und das Abschlussprojekt laufen im Fork. Beim Forken **„Copy the master branch only“ abwählen** – sonst fehlen im Fork die Tags der Ausbaustufen, die die Übungen verwenden.
2. **Klonen:** in Ubuntu (WSL) neben `cloud-labs-local`:
   ```bash
   cd ~/kurs
   git clone https://github.com/<github-user>/placefinder.git
   ```
   Im Dev Container liegt das Repository dann unter `/workspaces/placefinder`.
3. **Starten:** im Terminal des Dev Containers
   ```bash
   cd /workspaces/placefinder
   ./start.sh
   ```
   oder in der Ubuntu-Shell von WSL
   ```bash
   cd ~/kurs/placefinder
   ./start.sh
   ```
   `start.sh` lädt beim ersten Aufruf die GeoNames-Datei `cities15000` nach `data/` und startet den Entwicklungsserver auf Port 8000. Beim ersten Start legt uv eine virtuelle Umgebung an und installiert die Abhängigkeiten genau in den Versionen aus `uv.lock`: im Dev Container unter `.venv`, in WSL unter `~/.cache/placefinder/venv`, damit sich beide Umgebungen nicht gegenseitig überschreiben. `fastapi dev` lädt die Anwendung bei jeder Änderung am Code neu.

   | Aufruf | Wirkung |
   |---|---|
   | `./start.sh --data cities5000` | andere GeoNames-Datei laden und verwenden |
   | `./start.sh --port 8001` | anderer Port, z. B. wenn schon ein Server auf 8000 läuft |
   | `./start.sh --prod` | ohne Neuladen und ohne Entwicklungswerkzeuge, wie auf der VM in Termin 2 |
   | `./start.sh --help` | alle Optionen |

   Von Hand geht es so (im Dev Container):
   ```bash
   data/download.sh                             # GeoNames cities15000 nach data/
   uv run fastapi dev src/placefinder/main.py   # Entwicklungsserver auf Port 8000
   ```

## Ausprobieren

In einem zweiten Terminal:

```bash
curl "http://localhost:8000/v1/places?q=Erfurt"
```

```json
{"type":"FeatureCollection","features":[{"type":"Feature","id":2929670,"geometry":{"type":"Point","coordinates":[11.03536,50.97734]},"properties":{"name":"Erfurt","country_code":"DE","population":218793,"feature_code":"PPLA","timezone":"Europe/Berlin"},"links":[{"rel":"self","type":"application/geo+json","href":"/v1/places/2929670"}]}],"links":[{"rel":"self","type":"application/geo+json","href":"/v1/places?q=Erfurt"}]}
```

Die Werte hängen vom Stand der GeoNames-Daten ab. VS Code leitet den Port aus dem Dev Container weiter; die interaktive API-Dokumentation steht unter http://localhost:8000/docs.

| Methode und Pfad | Antwort |
|---|---|
| `GET /v1/places` | Orte als GeoJSON-FeatureCollection, gefiltert und seitenweise (Abschnitt [REST-API v1](#rest-api-v1)) |
| `GET /v1/places/{id}` | ein Ort als GeoJSON-Feature mit ETag; 404, wenn es ihn nicht gibt |
| `GET /health` | Status und Zahl der geladenen Orte; fragt Datenbank und Cache – für Health Checks und die Readiness Probe |
| `GET /livez` | nur `{"status": "ok"}`, ohne Datenbank und Cache – für die Liveness Probe |
| `GET /` | Name, Version und Quellenangabe der Daten |
| `GET /docs`, `GET /openapi.json` | von FastAPI erzeugte Dokumentation (OpenAPI) |
| `GET /places?q=…&limit=…`, `GET /places/{id}` | Version 0, veraltet: Liste einfacher JSON-Objekte. Die Antworten tragen die Header `Deprecation` und `Sunset` (01.01.2027) und verweisen mit `Link` auf `/v1/places`. |

Alternative Namen machen auch deutsche Namen auffindbar: GeoNames führt München als „Munich“, `q=München` findet es trotzdem.

## REST-API v1

Ab Tag `t05`. Musterlösung zu Termin 5; der Code steht in `src/placefinder/api.py` (Endpunkte, GeoJSON), `problems.py` (Fehlerformat) und `geo.py` (Bounding Box, Abstände).

### Suche: `GET /v1/places`

| Parameter | Bedeutung |
|---|---|
| `q` | Name oder Anfang eines Namens, auch alternative Namen |
| `lon`, `lat`, `radius` | Umkreis um einen Punkt; `radius` in Metern, 1 bis 50.000, Standard 10.000. Die Antwort enthält dann `distance` in Metern. |
| `bbox` | `minLon,minLat,maxLon,maxLat`, z. B. `10.9,50.9,11.2,51.1` – Länge vor Breite wie in GeoJSON |
| `country` | Ländercode nach ISO 3166, z. B. `DE` |
| `sort` | `relevance` (Standard mit `q`), `distance` (Standard mit `lon`/`lat`), `-population` (sonst Standard), `name` |
| `limit` | 1 bis 100, Standard 20 |
| `cursor` | Position aus dem Link `next` der vorigen Seite |

Alle Filter lassen sich kombinieren. Gibt es weitere Treffer, enthält die Antwort einen Link `next` im Body und im Header `Link` (RFC 8288). Der Cursor ist undurchsichtig: Er enthält Sortierung und Sortierschlüssel des letzten Orts, Base64-kodiert. Der Link `next` wiederholt alle übrigen Parameter.

```bash
curl "http://localhost:8000/v1/places?lon=11.03&lat=50.98&radius=25000"           # Umkreis um Erfurt
curl "http://localhost:8000/v1/places?bbox=10.9,50.9,11.2,51.1&sort=-population"   # Kartenausschnitt
curl --include "http://localhost:8000/v1/places?country=DE&limit=2"                # Header Link: …; rel="next"
```

### Ein Ort: `GET /v1/places/{id}`

Die Antwort trägt ein `ETag` (Hash des Inhalts) und `Cache-Control: public, max-age=3600`. Mit `If-None-Match` antwortet die API mit `304 Not Modified` ohne Inhalt, solange sich der Ort nicht geändert hat:

```bash
curl --include http://localhost:8000/v1/places/2929670                     # ETag kopieren
curl --include --header 'If-None-Match: "<etag>"' http://localhost:8000/v1/places/2929670
```

Die Suche liefert `Cache-Control: public, max-age=60, stale-while-revalidate=300`.

### Fehler nach RFC 9457

Alle Fehler, auch unbekannte Pfade und ungültige Parameter, kommen als `application/problem+json`:

```bash
curl --include "http://localhost:8000/v1/places?bbox=11.0,50.9"
```

```json
{"type":"https://placefinder.test/problems/invalid-bbox","title":"Invalid bounding box","status":422,"detail":"bbox needs 4 numbers, got 2","instance":"/v1/places","parameter":"bbox"}
```

| Fall | Status | `type` (unter `https://placefinder.test/problems/`) |
|---|---|---|
| Ort unbekannt | 404 | `place-not-found` |
| `bbox` falsch aufgebaut oder außerhalb der Wertebereiche | 422 | `invalid-bbox` |
| übrige ungültige Parameter, z. B. `limit=500`, `lon` ohne `lat` | 422 | `invalid-parameters` (mit Liste `errors`, wenn FastAPI prüft) |
| Cursor ungültig oder zu einer anderen Sortierung | 422 | `invalid-cursor` |
| unbekannter Pfad, falsche Methode | 404, 405 | `about:blank` |

### Tests

```bash
uv run pytest                                  # Unit- und API-Tests, auch für v1
uvx schemathesis run http://localhost:8000/openapi.json \
  --exclude-checks positive_data_acceptance    # Vertragstest gegen den laufenden Server
```

Schemathesis erzeugt aus der OpenAPI-Beschreibung Hunderte von Anfragen und prüft Statuscodes, Medientypen und Schemas der Antworten. Die Prüfung `positive_data_acceptance` erwartet, dass jede Anfrage, die zum Schema passt, angenommen wird. Ein beliebiger `cursor` passt zum Schema, ist aber kein gültiger Cursor – die API lehnt ihn zu Recht mit 422 ab. Deshalb ist diese Prüfung ausgeschlossen. Mit `--checks all` laufen zusätzlich alle übrigen Prüfungen.

## Karte

Ab Tag `t05`. `frontend/index.html` zeigt die Orte im sichtbaren Ausschnitt auf einer Karte (MapLibre GL JS 6, Basiskarte von OpenFreeMap). Bei jeder Bewegung lädt die Seite `GET /v1/places?bbox=…&sort=-population&limit=100` neu.

```bash
uv run fastapi dev src/placefinder/main.py              # Terminal 1: API auf Port 8000
python3 -m http.server 5173 --directory frontend        # Terminal 2: Karte auf Port 5173
```

Im Browser http://localhost:5173 öffnen. Karte und API haben verschiedene Herkünfte (Port 5173 und 8000); die API erlaubt die Karte über CORS (`CORS_ORIGINS`). Mit `?api=https://…` zeigt die Karte die Daten einer anderen Instanz, etwa des Dienstes beim eigenen Anbieter.

### Eigene Kacheln (PMTiles)

Ab Tag `t07`. Mit `?tiles=<URL>` zeichnet die Karte ihre Basiskarte aus einer einzigen [PMTiles](https://docs.protomaps.com/pmtiles/)-Datei statt aus den Kacheln von OpenFreeMap. Die Datei liegt im Object Storage; einen Kachelserver braucht es nicht. Die Bibliothek `pmtiles` liest zuerst Kopf und Verzeichnis der Datei und dann jede Kachel mit einem HTTP-Range-Request (`Range: bytes=…`, Antwort `206 Partial Content`). Der Stil kommt von Protomaps (`@protomaps/basemaps`, Variante `light`, Beschriftung auf Deutsch).

Kacheldatei schneiden, in den Object Storage laden und die Adresse der Karte erzeugen: [cloud-labs-local/07-cache-and-storage](https://github.com/mf-iu/cloud-labs-local/tree/master/07-cache-and-storage) (lokal mit SeaweedFS), Schritt `05-storage` im Anbieter-Repository (beim Anbieter).

- **URL:** meist eine Pre-Signed URL – der Bucket bleibt privat, die URL gilt eine begrenzte Zeit. Als Parameter muss sie URL-kodiert sein; die Skripte der Übungen erledigen das.
- **CORS:** Der Bucket muss Anfragen der Herkunft `http://localhost:5173` mit dem Header `Range` erlauben und `ETag` sowie `Content-Range` freigeben.
- **Ausschnitt:** Die Karte zoomt beim Start auf die Bounding Box aus dem Kopf der Datei.
- **Daten:** © OpenStreetMap-Mitwirkende (ODbL), Kacheln und Stil von Protomaps; die Karte nennt beides unten rechts.

## Datenbank

Ab Tag `t06`. Musterlösung zu Termin 6: `src/placefinder/db.py` liest die Orte aus der Tabelle `places` in PostgreSQL mit PostGIS. Die Tabelle legt `load-cities.sh` aus [cloud-labs-local/06-postgis](https://github.com/mf-iu/cloud-labs-local/tree/master/06-postgis) an: die Spalten der GeoNames-Datei, die Spalte `geom` vom Typ `geography` mit GiST-Index und Trigramm-Indizes für die Namen.

```bash
cd /workspaces/placefinder
docker compose up --detach db                          # PostGIS lokal, Port 5432 nur auf diesem Rechner
export DATABASE_URL=postgresql://pf:pf@localhost:5432/pf
../cloud-labs-local/06-postgis/load-cities.sh         # Tabelle places mit cities15000
uv run fastapi dev src/placefinder/main.py             # meldet: Using PostGIS at localhost:5432/pf
```

Dieselbe Variable mit der Verbindungszeichenkette einer Datenbank beim Anbieter verbindet PlaceFinder mit dieser; `06-postgis/test-api.sh` in `cloud-labs-local` startet PlaceFinder so und prüft die API mit dem Smoke-Test.

| Parameter | Abfrage in PostGIS | Index |
|---|---|---|
| `lon`, `lat`, `radius` | `ST_DWithin(geom, punkt, radius)`, Abstand mit `ST_Distance` | GiST auf `geom` |
| `q` | alle Namen in einem Text, `LIKE '%,erf%'`; ein gleicher Name zählt vor einem Präfix | Trigramme auf allen Namen (`places_all_names_trgm_idx`) |
| `bbox` | `longitude BETWEEN … AND latitude BETWEEN …` – ein Rechteck in Grad, keine Großkreise | keiner |
| `country` | `country_code = …` | keiner |
| `cursor` | Zeilenvergleich `(k0, k1) > (…)` mit dem Sortierschlüssel des letzten Orts | – |

- **Repository:** `api.py` fragt eine Schnittstelle (`repository.py`): `find`, `get` und `count`. `PlaceRepository` (`places.py`) erfüllt sie im Speicher, `PostgisRepository` (`db.py`) in der Datenbank. Die Wahl trifft `main.py` beim Start.
- **Verbindungen:** psycopg 3 mit einem Pool aus bis zu vier Verbindungen; geöffnet und geschlossen in der Lifespan-Funktion. Fehlen Datenbank oder Tabelle, bricht der Start mit einer Meldung ab. Antwortet die Datenbank später nicht, liefert die API `503` mit `Retry-After` als Problem Details.
- **Parameter:** Alle Werte gehen als Platzhalter (`%(name)s`) getrennt vom SQL-Text an den Server – Schutz vor SQL-Injection.
- **`/health`:** meldet die geschätzte Zahl der Orte (`reltuples`); ein `count(*)` läse bei jedem Health Check die ganze Tabelle.

**Tests gegen PostGIS:** Mit `TEST_DATABASE_URL` laufen alle API-Tests ein zweites Mal gegen PostGIS. Die Tests legen ein eigenes Schema mit den Beispielorten an und löschen es danach; die Tests zum Laden (`tests/test_load.py`) legen je eine eigene Datenbank an.

```bash
TEST_DATABASE_URL=postgresql://pf:pf@localhost:5432/pf uv run pytest
```

### Datenbank selbst füllen

Ab Tag `t08`. In Termin 6 lädt `load-cities.sh` die Orte vom eigenen Rechner aus in die Datenbank. Liegt die Datenbank wie in Termin 8 in einem privaten Netz, ist sie vom eigenen Rechner aus nicht erreichbar. Das Image enthält die GeoNames-Datei aber schon (`DATA_FILE`), also kann PlaceFinder die Tabelle selbst anlegen – mit denselben Schritten wie `load-cities.sh` (`src/placefinder/load.py`):

```bash
docker compose up --detach db
export DATABASE_URL=postgresql://pf:pf@localhost:5432/pf
uv run placefinder-load data/cities15000.txt            # einmal laden; --replace lädt neu
DATABASE_INIT=true uv run fastapi dev src/placefinder/main.py   # oder: beim Start laden, wenn die Tabelle fehlt
docker compose exec api placefinder-load                 # im Container, mit der Datei aus dem Image
```

- **Eine Transaktion:** Tabelle, `COPY` und Indizes entstehen zusammen; bricht das Laden ab, bleibt nichts zurück.
- **Advisory Lock:** Starten mehrere Instanzen gleichzeitig mit `DATABASE_INIT=true`, lädt nur die erste; die anderen warten und finden danach die Tabelle.
- **Im Kurs eine Vereinfachung:** In Produktion gehört das Schema in versionierte Migrationen (z. B. Alembic), die die Pipeline einmal vor dem Ausrollen ausführt – nicht jede Instanz beim Start.

## Cache

Ab Tag `t07`. Musterlösung zu Termin 7: `src/placefinder/cache.py` hält die Antworten von `GET /v1/places` in Valkey, dem quelloffenen Nachfolger von Redis (BSD-Lizenz). Die Orte ändern sich selten, die Suchen wiederholen sich ständig – die Karte fragt dieselben Ausschnitte immer wieder.

```bash
cd /workspaces/placefinder
docker compose up --detach valkey                      # Valkey lokal, Port 6379 nur auf diesem Rechner
export VALKEY_URL=valkey://localhost:6379/0
uv run fastapi dev src/placefinder/main.py             # meldet: Caching searches in Valkey at localhost:6379/0 for 300 s
curl --include "http://localhost:8000/v1/places?q=Erfurt" | grep --ignore-case cache-status   # fwd=uri-miss; stored
curl --include "http://localhost:8000/v1/places?q=Erfurt" | grep --ignore-case cache-status   # hit
docker compose exec valkey valkey-cli --scan --pattern 'placefinder:*'   # die Schlüssel
docker compose exec valkey valkey-cli ttl 'placefinder:v1:/v1/places?q=Erfurt'   # Sekunden bis zum Ablauf
```

- **Cache-aside:** zuerst im Cache nachsehen; bei einem Treffer antwortet PlaceFinder ohne Datenbank. Sonst fragt es das Repository und legt die Antwort mit einer Lebensdauer (TTL, `CACHE_TTL`, Standard 300 s) ab. Danach löscht Valkey sie selbst.
- **Schlüssel:** Pfad und Query-String genau wie gesendet, z. B. `placefinder:v1:/v1/places?q=Erfurt`. `?a=1&b=2` und `?b=2&a=1` sind zwei Schlüssel; Fehlerantworten werden nicht gespeichert.
- **`Cache-Status`** (RFC 9211): `PlaceFinder; hit` oder `PlaceFinder; fwd=uri-miss; stored`. Ohne `VALKEY_URL` fehlt der Header.
- **Zwei Caches:** `Cache-Control: public, max-age=60` erlaubt Browsern und CDNs, die Antwort eine Minute zu behalten (Termin 5); Valkey hält sie fünf Minuten für alle Clients.
- **Veraltete Antworten:** Nach einem neuen `load-cities.sh` liefert der Cache bis zum Ablauf der TTL die alten Antworten. Sofort leeren: `docker compose exec valkey valkey-cli flushdb`.
- **Fail open:** Antwortet Valkey nicht, fragt PlaceFinder die Datenbank und schreibt einmal eine Warnung ins Log; `/health` meldet `"cache": "unavailable"`. Ein Cache darf den Dienst schneller machen, nie unerreichbar. Kurze Timeouts (0,2 s) verhindern, dass ein hängender Cache jede Anfrage bremst.
- **Speicher:** `compose.yaml` begrenzt Valkey auf 64 MB; ist der Speicher voll, verdrängt `allkeys-lru` die am längsten nicht genutzten Schlüssel. Gespeichert wird nichts auf der Platte – ein Cache lässt sich jederzeit neu füllen.

**Tests mit Valkey:** Die Tests nutzen eine kleine Attrappe des Valkey-Clients; mit `TEST_VALKEY_URL` läuft ein Test zusätzlich gegen ein echtes Valkey (Datenbank 15, nur eigene Schlüssel).

```bash
TEST_VALKEY_URL=valkey://localhost:6379/15 uv run pytest
```

## Pipeline

Ab Tag `t08`. Musterlösung zu Termin 8: `.github/workflows/ci.yml` läuft bei jedem Push und jedem Pull Request.

| Job | Schritte |
|---|---|
| `test` | `uv sync --locked`, `ruff check`, `ruff format --check`, `pytest` – auch gegen PostGIS und Valkey, die als Service-Container des Jobs laufen |
| `image` | Image bauen, mit Trivy scannen (bricht bei behebbaren Schwachstellen HIGH oder CRITICAL ab); auf `master` und bei Tags: in die GitHub Container Registry laden mit SBOM und Provenance, mit cosign signieren |

- **Images:** `ghcr.io/<github-user>/placefinder:<commit>` und `:<branch oder tag>`, z. B. `:master` oder nach `git push origin t08` das Image `:t08`. Pull Requests werden gebaut und gescannt, aber nicht hochgeladen.
- **Ohne gespeicherte Geheimnisse:** Das Hochladen erlaubt der `GITHUB_TOKEN` des Laufs (`packages: write`), das Signieren ein kurzlebiges Zertifikat von Sigstore für den OIDC-Token des Workflows (`id-token: write`). Ausrollen beim Anbieter: `06-infrastructure-as-code/deploy.example.yml` im Anbieter-Repository, ebenfalls ohne gespeicherte Schlüssel.
- **Gepinnte Actions:** Jede Action ist auf den Commit eines Releases festgelegt, nicht auf einen Tag wie `v7` – ein Tag lässt sich später auf anderen Code umhängen, so geschehen im März 2026 mit `trivy-action`. Dependabot (`.github/dependabot.yml`) schlägt wöchentlich neue Versionen der Actions, der Python-Pakete und der Basis-Images vor.
- **Im eigenen Fork:** Unter *Actions* die Workflows einmal aktivieren. Ein neues Paket ist privat; für die Cloud-Dienste auf **Public** stellen (*Packages* → *placefinder* → *Package settings* → *Change visibility*). Schritt für Schritt: [cloud-labs-local/08-iac-and-operations](https://github.com/mf-iu/cloud-labs-local/tree/master/08-iac-and-operations).

Signatur, SBOM und Provenance prüfen (im Dev Container, mit dem Digest aus der Zusammenfassung des Laufs):

```bash
image=ghcr.io/<github-user>/placefinder@sha256:<digest>
cosign verify "$image" \
  --certificate-identity-regexp 'https://github.com/<github-user>/placefinder/.github/workflows/ci.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect "$image" --format '{{json .SBOM}}' | head --bytes 600
docker buildx imagetools inspect "$image" --format '{{json .Provenance}}' | head --bytes 600
```

## Beobachtbarkeit

Ab Tag `t08`. `src/placefinder/telemetry.py` sendet Traces und Metriken mit [OpenTelemetry](https://opentelemetry.io) über OTLP, sobald `OTEL_EXPORTER_OTLP_ENDPOINT` gesetzt ist; ohne die Variable ist alles aus.

- **Traces:** ein Span je Anfrage (FastAPI) mit einem Kind-Span je SQL-Anweisung (psycopg). Health Checks erzeugen keine Spans.
- **Metriken:** die Dauer jeder Anfrage als Histogramm nach Route und Statuscode (`http.server.request.duration`, in Prometheus `http_server_request_duration_seconds`) – daraus folgen Rate, Fehler und Dauer (RED) – und die Zugriffe auf den Cache nach Ergebnis (`placefinder.cache.lookups`, in Prometheus `placefinder_cache_lookups_total`).
- **Backend:** Der Dienst `lgtm` in `compose.yaml` (Image `grafana/otel-lgtm`) bündelt OpenTelemetry Collector, Prometheus, Tempo, Loki und Grafana in einem Container – nur für Entwicklung und Demos.

```bash
cd /workspaces/placefinder
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up --detach --build
for i in $(seq 300); do                                  # Last erzeugen
  curl --silent --output /dev/null "http://localhost:8000/v1/places?q=Erf&limit=$(( i % 50 + 1 ))"
done
```

Grafana unter http://localhost:3000 (ohne Anmeldung); Dashboards, Traces und Abfragen für SLIs: [cloud-labs-local/08-iac-and-operations](https://github.com/mf-iu/cloud-labs-local/tree/master/08-iac-and-operations#beobachtbarkeit-lokal).

Weitere Einstellungen kommen aus den Standardvariablen des OpenTelemetry-SDK, z. B. `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` oder `OTEL_TRACES_SAMPLER`. Derselbe Code sendet so an jedes Backend, das OTLP versteht – auch an die Dienste der Cloud-Anbieter.

## Konfiguration

| Umgebungsvariable | Standard | Bedeutung |
|---|---|---|
| `DATABASE_URL` | – | ab `t06`: PostgreSQL mit PostGIS statt der Datei, z. B. `postgresql://pf:pf@localhost:5432/pf` |
| `DATA_FILE` | `data/cities15000.txt` (relativ zum Arbeitsverzeichnis) | GeoNames-Datei, die beim Start geladen wird, wenn `DATABASE_URL` fehlt |
| `VALKEY_URL` | – | ab `t07`: Cache für Suchen in Valkey, z. B. `valkey://localhost:6379/0` |
| `CACHE_TTL` | `300` | ab `t07`: Sekunden, die eine Suche im Cache bleibt |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning` oder `error`; mit `debug` erscheint jede Suche im Log |
| `CORS_ORIGINS` | `http://localhost:5173` | Herkünfte (Schema, Host, Port) von Webseiten, die die API im Browser aufrufen dürfen, durch Kommas getrennt; leer: keine |
| `DATABASE_INIT` | `false` | ab `t08`: mit `true` legt PlaceFinder beim Start die Tabelle `places` an und lädt `DATA_FILE`, wenn die Tabelle fehlt |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | – | ab `t08`: Ziel für Traces und Metriken über OTLP/HTTP, z. B. `http://localhost:4318`; leer: keine Telemetrie |
| `OTEL_SERVICE_NAME` | `placefinder` | ab `t08`: Name des Dienstes in Traces und Metriken |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | ab `t08`: Millisekunden zwischen zwei Sendungen der Metriken |

Fehlt die Datei, bricht der Start mit einer Meldung ab. `data/download.sh` lädt auch andere GeoNames-Dateien, z. B. `data/download.sh cities5000` (Orte ab 5.000 Einwohnern) oder `data/download.sh DE` (alle Einträge für Deutschland, auch Berge, Gewässer usw.); dann `DATA_FILE=data/DE.txt uv run fastapi dev src/placefinder/main.py` oder kurz `./start.sh --data DE`. Größere Dateien brauchen entsprechend mehr Speicher und Startzeit. Mit `cities15000` belegt PlaceFinder rund 130 MB Arbeitsspeicher und startet in etwa einer Sekunde.

**Betrieb ohne Entwicklungsserver** (so richtet cloud-init in Termin 2 die VM ein):

```bash
uv sync --frozen --no-dev                     # ohne Entwicklungswerkzeuge
DATA_FILE=/pfad/zu/cities15000.txt .venv/bin/uvicorn placefinder.main:app --host 0.0.0.0 --port 8000
```

## Container

Ab Tag `t02`. Übungen dazu – Image bauen, Schichten, Trivy und Syft, Compose, Hochladen nach ghcr.io, Docker Hub und seine Limits: [cloud-labs-local/02-container](https://github.com/mf-iu/cloud-labs-local/tree/master/02-container).

```bash
docker build --tag placefinder:0.8.0 .
docker run --rm --publish 8000:8000 placefinder:0.8.0
```

Das `Dockerfile` hat drei Stufen:

| Stufe | Aufgabe |
|---|---|
| `data` | lädt die GeoNames-Datei (`cities15000`) und entpackt sie nach `/data` |
| `build` | installiert mit uv die Abhängigkeiten genau nach `uv.lock`, dann PlaceFinder selbst als Paket |
| Runtime | übernimmt nur die virtuelle Umgebung und die Daten, entfernt pip, läuft als Benutzer `app` ohne root |

Die Daten gehören damit zum Image (rund 8 MB). So startet der Container überall ohne Download, auch auf den Serverless-Container-Diensten in Termin 3; aktuelle Daten gibt es mit einem neuen Build. Ab `t06` liest der Container die Orte stattdessen aus der Datenbank, wenn `DATABASE_URL` gesetzt ist; die Datei im Image bleibt dann ungenutzt. Eine andere Datei wählt `--build-arg GEONAMES_FILE=cities5000`. `.dockerignore` hält `.git`, `.venv`, `data/`, `tests/`, ab `t03` auch `deploy/` und ab `t05` `frontend/` aus dem Build-Kontext heraus.

`compose.yaml` startet PlaceFinder (`api`) mit einem kleinen Übungsdienst `web`, ab `t06` mit der Datenbank `db`, ab `t07` mit dem Cache `valkey` und dem Object Storage `seaweedfs`, ab `t08` auf Wunsch mit dem Backend für Telemetrie `lgtm` (Profil `observability`).

## Kubernetes

Ab Tag `t03`. Cluster anlegen, Manifest anwenden, neue Version ausrollen, Konfiguration ändern, Helm und Autoscaler: [cloud-labs-local/03-kubernetes](https://github.com/mf-iu/cloud-labs-local/tree/master/03-kubernetes); HTTPS mit der Gateway API: [cloud-labs-local/04-cluster-network](https://github.com/mf-iu/cloud-labs-local/tree/master/04-cluster-network).

| Datei | Inhalt |
|---|---|
| `deploy/k8s/placefinder.yaml` | Deployment mit drei Replikaten, Probes, Requests und Limit; Service; ConfigMap – Musterlösung der Übung |
| `deploy/hpa.yaml` | Horizontal Pod Autoscaler (Zusatzaufgabe) |
| `deploy/helm/placefinder/` | Helm-Chart mit denselben drei Objekten |
| `deploy/helm/values-dev.yaml`, `values-prod.yaml` | Werte je Umgebung für das Chart |

**Probes:** Die Readiness Probe fragt `/health`. Ist die Datenbank nicht erreichbar, bekommt der Pod keine Anfragen mehr, bleibt aber am Leben. Die Liveness Probe fragt `/livez`, das nur den Prozess prüft: Ein Ausfall der Datenbank soll nicht alle Pods gleichzeitig neu starten. Bis Tag `t08` fragten beide Probes `/health`.

## Entwicklung

```bash
uv run pytest           # Tests
uv run ruff check       # Linter
uv run ruff format      # Formatierung
```

```
start.sh                    # starts the server locally (WSL or dev container)
Dockerfile, .dockerignore   # container image with the GeoNames data (from t02)
compose.yaml                # PlaceFinder, a small practice service (from t02), PostGIS (from t06),
                            # Valkey and SeaweedFS (from t07), OpenTelemetry backend (from t08)
deploy/k8s/                 # Kubernetes manifests (from t03)
deploy/hpa.yaml             # Horizontal Pod Autoscaler (from t03)
deploy/helm/                # Helm chart and values per environment (from t03)
src/placefinder/main.py     # FastAPI app: loading the data at startup, CORS, v0 endpoints
src/placefinder/api.py      # REST API v1: GeoJSON, filters, cursor pagination, ETags (from t05)
src/placefinder/problems.py # errors as problem details, RFC 9457 (from t05)
src/placefinder/geo.py      # bounding boxes and distances (from t05)
src/placefinder/repository.py # Place, search query and the interface of a place store (from t06)
src/placefinder/places.py   # GeoNames parser, in-memory repository with name index
src/placefinder/db.py       # repository in PostgreSQL with PostGIS (from t06)
src/placefinder/cache.py    # cache-aside for searches in Valkey (from t07)
src/placefinder/load.py     # creates and loads the table places, placefinder-load (from t08)
src/placefinder/telemetry.py # traces and metrics with OpenTelemetry (from t08)
.github/workflows/ci.yml    # CI pipeline: tests, image, scan, SBOM, signature (from t08)
.github/dependabot.yml      # weekly updates of actions, packages and base images (from t08)
frontend/index.html         # map with MapLibre GL JS (from t05), own PMTiles base map (from t07)
data/download.sh            # downloads GeoNames dumps; data files are not committed
tests/                      # pytest tests with a small sample of GeoNames lines
```

Code, Kommentare und Commit-Messages sind auf Englisch.

## Ausbaustufen

| Tag | Stand |
|---|---|
| `t01` | v0: Ortssuche über `cities15000` im Speicher (`/places?q=…`, `/places/{id}`) |
| `t02` | v0 als Container-Image (`Dockerfile` mit den GeoNames-Daten), `compose.yaml` mit einem Übungsdienst |
| `t03` | Kubernetes-Manifeste, Autoscaler und Helm-Chart unter `deploy/`; Log-Level über `LOG_LEVEL` |
| `t05` | v1: REST-API unter `/v1` mit GeoJSON, Filtern, Cursor-Paginierung, ETags und Problem Details; Karte unter `frontend/`; v0 veraltet (Version 0.5.0) |
| `t06` | Orte aus PostgreSQL mit PostGIS, wenn `DATABASE_URL` gesetzt ist; Dienst `db` in `compose.yaml` (Version 0.6.0) |
| `t07` | Cache für Suchen in Valkey (`VALKEY_URL`, `Cache-Status`); Karte mit eigener Basiskarte aus PMTiles (`?tiles=`); Dienste `valkey` und `seaweedfs` in `compose.yaml` (Version 0.7.0) |
| `t08` | CI-Pipeline mit GitHub Actions (Tests, Image, Trivy, SBOM, cosign); Traces und Metriken mit OpenTelemetry; `placefinder-load` und `DATABASE_INIT`; Dienst `lgtm` in `compose.yaml` (Version 0.8.0) |

Termin 4 (Netzwerke) ändert PlaceFinder nicht und hat keinen eigenen Tag. Die weiteren Stände folgen als Tags `t09`, `t10` usw. `git tag` listet die vorhandenen, `git switch --detach t01` wechselt zu einem Stand.

## Daten und Lizenz

Die Ortsdaten stammen von [GeoNames](https://www.geonames.org) und stehen unter der Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die Lizenz verlangt eine Quellenangabe; PlaceFinder gibt sie unter `/` und in der API-Dokumentation aus. Die Daten werden nicht eingecheckt, sondern mit `data/download.sh` bzw. beim Bau des Images geladen.
