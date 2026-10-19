# PlaceFinder

Beispielanwendung des Kurses „Cloud Computing“: ein Dienst zur Ortssuche auf Basis von GeoNames, später ergänzt um OpenStreetMap. PlaceFinder wächst von Termin zu Termin; jeder Stand ist als Git-Tag verfügbar.

**Stand v0 (Tags `t01` bis `t03`):** eine FastAPI-Anwendung, die beim Start die GeoNames-Datei `cities15000` (alle Orte ab 15.000 Einwohnern, rund 34.000) in den Speicher lädt und nach Namen durchsucht. Ab `t02` gibt es dazu ein Container-Image und eine `compose.yaml`, die PlaceFinder zusammen mit einem kleinen Übungsdienst startet (Abschnitt [Container](#container)). Ab `t03` liegen unter `deploy/` Manifeste für Kubernetes und ein Helm-Chart (Abschnitt [Kubernetes](#kubernetes)).

**Stand v1 (Tag `t05`, Version 0.5.0):** eine REST-API unter `/v1` mit GeoJSON, Suche nach Name, Umkreis, Bounding Box und Land, Cursor-Paginierung, Caching-Headern, ETags und Fehlern nach RFC 9457 (Abschnitt [REST-API v1](#rest-api-v1)), dazu eine Karte mit MapLibre GL JS (Abschnitt [Karte](#karte)). Die Endpunkte von v0 bleiben vorerst erreichbar, sind aber als veraltet markiert.

**Stand mit Datenbank (Tag `t06`, Version 0.6.0):** Ist `DATABASE_URL` gesetzt, liest PlaceFinder die Orte aus PostgreSQL mit PostGIS statt aus der Datei im Speicher – dieselbe API, dieselben Antworten (Abschnitt [Datenbank](#datenbank)). `compose.yaml` enthält dafür den Dienst `db`. Ohne `DATABASE_URL` arbeitet PlaceFinder wie bisher mit der Datei.

**Stand mit Cache und eigenen Kacheln (Tag `t07`, Version 0.7.0):** Ist `VALKEY_URL` gesetzt, hält PlaceFinder die Antworten der Suche einige Minuten in Valkey (Abschnitt [Cache](#cache)). Die Karte liest ihre Basiskarte auf Wunsch aus einer einzigen PMTiles-Datei im Object Storage (Abschnitt [Eigene Kacheln](#eigene-kacheln-pmtiles)). `compose.yaml` enthält dafür die Dienste `valkey` und `seaweedfs`.

## Einrichtung

Voraussetzung ist der Dev Container eines Übungs-Repositorys (`cloud-labs-aws`, `cloud-labs-azure` oder `cloud-labs-gcp`, siehe dessen README). Ohne Dev Container genügt die Ubuntu-Shell in WSL: `start.sh` installiert [uv](https://docs.astral.sh/uv/) bei Bedarf, uv lädt ein passendes Python.

1. **Forken:** Das Repository auf GitHub forken; eigene Pipelines und das Abschlussprojekt laufen im Fork. Beim Forken **„Copy the master branch only“ abwählen** – sonst fehlen im Fork die Tags der Ausbaustufen, die die Übungen verwenden.
2. **Klonen:** in Ubuntu (WSL) neben das Übungs-Repository:
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
| `GET /health` | Status und Zahl der geladenen Orte, z. B. für Health Checks |
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

```bash
cd /workspaces/cloud-labs-<anbieter>/t07-objektspeicher
./make-tiles.sh                                      # Ausschnitt um Erfurt aus dem Protomaps-Build, wenige MB
uv run local-s3.py upload ../.state/data/erfurt.pmtiles tiles/erfurt.pmtiles   # in SeaweedFS
uv run local-s3.py map tiles/erfurt.pmtiles          # gibt die Adresse der Karte mit ?tiles=… aus
```

- **URL:** meist eine Pre-Signed URL – der Bucket bleibt privat, die URL gilt eine begrenzte Zeit. Als Parameter muss sie URL-kodiert sein; `local-s3.py map` und die Skripte für die Anbieter erledigen das.
- **CORS:** Der Bucket muss Anfragen der Herkunft `http://localhost:5173` mit dem Header `Range` erlauben und `ETag` sowie `Content-Range` freigeben.
- **Ausschnitt:** Die Karte zoomt beim Start auf die Bounding Box aus dem Kopf der Datei.
- **Daten:** © OpenStreetMap-Mitwirkende (ODbL), Kacheln und Stil von Protomaps; die Karte nennt beides unten rechts.

## Datenbank

Ab Tag `t06`. Musterlösung zu Termin 6: `src/placefinder/db.py` liest die Orte aus der Tabelle `places` in PostgreSQL mit PostGIS. Die Tabelle legt `load-cities.sh` aus dem Übungs-Repository an (`t06-datenbank`): die Spalten der GeoNames-Datei, die Spalte `geom` vom Typ `geography` mit GiST-Index und Trigramm-Indizes für die Namen.

```bash
cd /workspaces/placefinder
docker compose up --detach db                          # PostGIS lokal, Port 5432 nur auf diesem Rechner
export DATABASE_URL=postgresql://pf:pf@localhost:5432/pf
../cloud-labs-<anbieter>/t06-datenbank/load-cities.sh  # Tabelle places mit cities15000
uv run fastapi dev src/placefinder/main.py             # meldet: Using PostGIS at localhost:5432/pf
```

Dieselbe Variable mit der Verbindungszeichenkette aus `create-db.sh` verbindet PlaceFinder mit der Datenbank beim eigenen Anbieter; `t06-datenbank/test-api.sh` startet PlaceFinder so und prüft die API mit dem Smoke-Test aus Termin 5.

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

**Tests gegen PostGIS:** Mit `TEST_DATABASE_URL` laufen alle API-Tests ein zweites Mal gegen PostGIS. Die Tests legen ein eigenes Schema mit den Beispielorten an und löschen es danach.

```bash
TEST_DATABASE_URL=postgresql://pf:pf@localhost:5432/pf uv run pytest
```

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

## Konfiguration

| Umgebungsvariable | Standard | Bedeutung |
|---|---|---|
| `DATABASE_URL` | – | ab `t06`: PostgreSQL mit PostGIS statt der Datei, z. B. `postgresql://pf:pf@localhost:5432/pf` |
| `DATA_FILE` | `data/cities15000.txt` (relativ zum Arbeitsverzeichnis) | GeoNames-Datei, die beim Start geladen wird, wenn `DATABASE_URL` fehlt |
| `VALKEY_URL` | – | ab `t07`: Cache für Suchen in Valkey, z. B. `valkey://localhost:6379/0` |
| `CACHE_TTL` | `300` | ab `t07`: Sekunden, die eine Suche im Cache bleibt |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning` oder `error`; mit `debug` erscheint jede Suche im Log |
| `CORS_ORIGINS` | `http://localhost:5173` | Herkünfte (Schema, Host, Port) von Webseiten, die die API im Browser aufrufen dürfen, durch Kommas getrennt; leer: keine |

Fehlt die Datei, bricht der Start mit einer Meldung ab. `data/download.sh` lädt auch andere GeoNames-Dateien, z. B. `data/download.sh cities5000` (Orte ab 5.000 Einwohnern) oder `data/download.sh DE` (alle Einträge für Deutschland, auch Berge, Gewässer usw.); dann `DATA_FILE=data/DE.txt uv run fastapi dev src/placefinder/main.py` oder kurz `./start.sh --data DE`. Größere Dateien brauchen entsprechend mehr Speicher und Startzeit. Mit `cities15000` belegt PlaceFinder rund 130 MB Arbeitsspeicher und startet in etwa einer Sekunde.

**Betrieb ohne Entwicklungsserver** (so richtet cloud-init in Termin 2 die VM ein):

```bash
uv sync --frozen --no-dev                     # ohne Entwicklungswerkzeuge
DATA_FILE=/pfad/zu/cities15000.txt .venv/bin/uvicorn placefinder.main:app --host 0.0.0.0 --port 8000
```

## Container

Ab Tag `t02`. Alle Befehle im Terminal des Dev Containers, im Verzeichnis `/workspaces/placefinder`.

**Zwei Docker-Instanzen:** Der Dev Container hat eine eigene Docker Engine (Docker in Docker). Images, die dort gebaut werden, sieht Docker in der Ubuntu-Shell von WSL nicht, und umgekehrt. Im Kurs laufen alle Container-Übungen im Dev Container. Auch eine Anmeldung bei Docker Hub gilt nur für die Instanz, in der sie ausgeführt wurde (siehe nächster Abschnitt).

### Docker Hub: anmelden oder nicht?

Die Images `python:3.14-slim` und `busybox` kommen von Docker Hub. Docker Hub begrenzt die Downloads (Pulls) innerhalb von 6 Stunden:

| Zugriff | Pulls je 6 Stunden | gezählt je |
|---|---|---|
| ohne Anmeldung | 100 | öffentliche IP-Adresse (IPv4) bzw. IPv6-/64-Netz |
| mit kostenlosem Docker-Konto | 200 | Konto |

Ein Pull ist ein Image (ein Manifest), nicht jede Schicht; bei Images für mehrere Architekturen zählt jede geladene Architektur. Das aktuelle Limit steht unter [Docker Hub pull usage and limits](https://docs.docker.com/docker-hub/usage/pulls/).

**Entscheidungshilfe:** Wer zu Hause über einen eigenen Anschluss arbeitet, kommt ohne Anmeldung aus. In einem Hochschul- oder Firmennetz teilen sich dagegen oft alle Rechner eine öffentliche IP-Adresse; dann zählen die Pulls aller zusammen, und das anonyme Limit ist schnell erreicht. Dort lohnt die Anmeldung.

**Anmelden** (kostenloses Konto auf [hub.docker.com](https://hub.docker.com)), im Terminal des Dev Containers:

```bash
docker login      # Bestätigung im Browser oder Benutzername und Zugangstoken
docker logout     # Anmeldung wieder entfernen
```

Die Zugangsdaten speichert Docker unverschlüsselt in `~/.docker/config.json` des Containers. Wer Benutzername und Token eingibt, legt dafür auf Docker Hub ein Personal Access Token mit der Berechtigung *Public Repo Read-only* an, nicht das Passwort. Nach einem Neubau des Dev Containers ist die Anmeldung zu wiederholen; die Images selbst bleiben erhalten.

**Fehler `toomanyrequests`:** Die Meldung beim Bauen oder Starten bedeutet, dass das Limit erreicht ist.

- Anmelden und den Befehl wiederholen; ab dann zählt das eigene Kontingent.
- Oder warten: Das Limit bezieht sich auf die letzten 6 Stunden, frühere Pulls fallen nach und nach heraus.
- Bereits geladene Images bleiben in der Docker Engine des Dev Containers (`docker images`). Befehle, die ausdrücklich neu laden (`docker build --pull`, `docker compose pull`), bis dahin vermeiden.

Wie viele Pulls noch übrig sind, zeigt eine Abfrage, die selbst nicht mitzählt (ohne Anmeldung: Kontingent der eigenen IP-Adresse):

```bash
token=$(curl --silent "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq --raw-output .token)
curl --silent --head --header "Authorization: Bearer $token" \
  https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest | grep --ignore-case ratelimit
```

`ratelimit-limit: 100;w=21600` heißt 100 Pulls in 21600 Sekunden (6 Stunden), `ratelimit-remaining` ist der Rest. Fehlen diese Zeilen, gilt für die Adresse kein Limit.

### Image bauen und starten

```bash
docker build --tag placefinder:0.7.0 .       # Image bauen (erster Build einige Minuten)
docker history placefinder:0.7.0             # Schichten mit Größe
docker run --rm --publish 8000:8000 placefinder:0.7.0
curl "http://localhost:8000/v1/places?q=Erfurt"  # in einem zweiten Terminal
```

Das `Dockerfile` hat drei Stufen:

| Stufe | Aufgabe |
|---|---|
| `data` | lädt die GeoNames-Datei (`cities15000`) und entpackt sie nach `/data` |
| `build` | installiert mit uv die Abhängigkeiten genau nach `uv.lock`, dann PlaceFinder selbst als Paket |
| Runtime | übernimmt nur die virtuelle Umgebung und die Daten, entfernt pip, läuft als Benutzer `app` ohne root |

Die Daten gehören damit zum Image (rund 8 MB). So startet der Container überall ohne Download, auch auf den Serverless-Container-Diensten in Termin 3; aktuelle Daten gibt es mit einem neuen Build. Ab `t06` liest der Container die Orte stattdessen aus der Datenbank, wenn `DATABASE_URL` gesetzt ist; die Datei im Image bleibt dann ungenutzt. Eine andere Datei wählt `--build-arg GEONAMES_FILE=cities5000`. `.dockerignore` hält `.git`, `.venv`, `data/`, `tests/`, ab `t03` auch `deploy/` und ab `t05` `frontend/` aus dem Build-Kontext heraus.

Ändert sich nur der Code unter `src/`, baut Docker nur die letzten Schichten neu; ändert sich `uv.lock`, auch die Abhängigkeiten.

### Image verkleinern und prüfen

Zum Vergleich ein Image mit nur einer Stufe auf Basis von `python:3.14` bauen (ohne Daten, nur für den Größenvergleich):

```bash
docker build --tag placefinder:single --file - . <<'EOF'
FROM python:3.14
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
WORKDIR /app
COPY . .
RUN uv sync --locked --no-dev
CMD [".venv/bin/uvicorn", "placefinder.main:app", "--host", "0.0.0.0"]
EOF
docker images placefinder                                       # Größen vergleichen
trivy image --severity HIGH,CRITICAL placefinder:0.7.0          # Schwachstellen
trivy image --severity HIGH,CRITICAL placefinder:single
```

Fehlt `trivy` im Dev Container, geht es auch mit dem Image von Trivy:
`docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0 image --severity HIGH,CRITICAL placefinder:0.7.0`
(feste Version: Einige Trivy-Images vom März 2026 waren manipuliert, deshalb nie ohne Tag)

### Trivy-Bericht lesen

Trivy listet die Funde je Ziel: die Pakete des Betriebssystems (`debian`) und Python-Pakete (`python-pkg`). Wichtig sind die Spalten *Status* und *Fixed Version*:

| Status | Bedeutung | Was tun? |
|---|---|---|
| `fixed` | Es gibt eine korrigierte Version (*Fixed Version*). | Paket bzw. Base-Image aktualisieren und neu bauen |
| `affected` | Betroffen, aber noch keine Korrektur verfügbar. | abwarten; später mit `docker build --pull` neu bauen |
| `fix_deferred` | Die Distribution hat die Korrektur zurückgestellt, meist wegen geringer Auswirkung. | prüfen, ob die Anwendung das Paket überhaupt nutzt |

Bei PlaceFinder (Stand `t02`) sind alle Python-Pakete der virtuellen Umgebung ohne Befund. Die Funde im Debian-Teil des Base-Images (z. B. `util-linux`, `ncurses`, `systemd`) haben keine *Fixed Version*. PlaceFinder nutzt diese Programme nicht, und der Container läuft ohne root – die Funde sind vorhanden, aber praktisch nicht erreichbar.

Die Python-Funde des Base-Images (`msgpack`, `urllib3`, `setuptools`) stammen aus pip, das diese Pakete in sich mitbringt. Im laufenden Container wird pip nicht gebraucht; die Runtime-Stufe entfernt es deshalb. Prüfen lässt sich die Herkunft eines Funds über den Pfad im JSON-Bericht:

```bash
trivy image --format json placefinder:0.7.0 \
  | jq --raw-output '.Results[] | .Vulnerabilities[]? | "\(.PkgName) \(.InstalledVersion) \(.PkgPath // "-")"'
```

Nur Funde mit verfügbarer Korrektur zeigt `trivy image --ignore-unfixed …` – so wird in CI-Pipelines oft geprüft (Termin 8). Weniger Funde haben Base-Images mit weniger Paketen, etwa Distroless-Images.

### Image in die GitHub Container Registry laden

Optional in Termin 2, nötig ab Termin 3 (die Container-Dienste laden das Image von dort). Ab Termin 3 erledigt das `t03-container/build-image.sh --push` im Übungs-Repository; von Hand:

```bash
gh auth login                                 # einmalig, falls noch nicht angemeldet
gh auth refresh --scopes write:packages       # Recht zum Hochladen von Paketen
gh auth token | docker login ghcr.io --username <github-user> --password-stdin
docker tag placefinder:0.7.0 ghcr.io/<github-user>/placefinder:t07
docker push ghcr.io/<github-user>/placefinder:t07
```

Ein neues Paket ist zunächst privat. Für Termin 3 auf GitHub unter *Packages* → *placefinder* → *Package settings* → *Change visibility* auf **Public** stellen.

### Compose: zwei Dienste

`compose.yaml` startet zwei Dienste: PlaceFinder (`api`) und `web`, einen winzigen Webserver aus dem offiziellen Image `busybox` (rund 2 MB). Ab `t06` kommt als dritter Dienst die Datenbank `db` dazu (Abschnitt [Datenbank](#datenbank)), ab `t07` der Cache `valkey` und der Object Storage `seaweedfs` mit S3-API auf Port 8333 (Abschnitte [Cache](#cache) und [Eigene Kacheln](#eigene-kacheln-pmtiles)).

> **Warum ein zweiter Dienst, der nichts mit PlaceFinder zu tun hat?**
> Mit nur einem Dienst wäre `compose.yaml` ein längerer `docker run`-Befehl. Erst mit zwei Diensten zeigt sich, was Compose leistet:
> ein gemeinsames Netz, in dem der Dienstname zugleich der Hostname ist; eine Startreihenfolge mit Healthcheck; ein benanntes Volume, das Daten über `docker compose down` hinaus hält.
> `web` ist dafür bewusst klein und unabhängig – PlaceFinder ruft ihn nicht auf. Eine Datenbank bekommt PlaceFinder erst in Termin 6: PostgreSQL mit PostGIS, dann als weiterer Dienst in dieser `compose.yaml`.

```bash
cd /workspaces/placefinder                    # compose.yaml liegt hier
docker ps                                     # läuft noch ein Container auf Port 8000? stoppen
docker compose up --detach                    # bauen (falls nötig) und starten
docker compose ps                             # web: healthy, api: running (ab t06 auch db, ab t07 valkey, seaweedfs)
curl http://localhost:8080/                   # Startseite von web, liegt im Volume
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://web:8080/').read().decode())"
docker compose exec web sh -c 'echo "Changed" > /www/index.html'
docker compose down                           # Container und Netz weg, das Volume www bleibt
docker compose up --detach
curl http://localhost:8080/                   # zeigt weiter "Changed"
docker compose down --volumes                 # zusätzlich das Volume löschen
```

- **Netz:** Der Aufruf aus `api` erreicht `web` über den Dienstnamen als Hostnamen (`http://web:8080/`); Port 8080 auf dem Rechner braucht er dafür nicht.
- **Reihenfolge:** `api` startet erst, wenn `web` den Healthcheck besteht (`wget` auf die Startseite), ab `t06` auch `db` (`pg_isready`), ab `t07` auch `valkey` (`valkey-cli ping`).
- **Volume:** `web` legt die Startseite beim ersten Start im Volume `www` an. Änderungen überstehen `docker compose down`; erst `down --volumes` löscht sie.

Häufige Fehler:

| Meldung | Ursache | Abhilfe |
|---|---|---|
| `no configuration file provided: not found` | Das Terminal steht nicht im Verzeichnis mit `compose.yaml` (neue Terminals öffnen im Übungs-Repository). | `cd /workspaces/placefinder` |
| `Bind for 0.0.0.0:8000 failed: port is already allocated` | Ein anderer Container belegt Port 8000, meist der aus `docker run` der Übung. | `docker ps`, den Container mit `docker stop <name>` beenden, dann `docker compose up --detach` |
| `Temporary failure in name resolution` beim Aufruf von `web` | Der Container `api` hat nach einem fehlgeschlagenen Start kein vollständiges Netz. | `docker compose down`, dann `docker compose up --detach` |

## Kubernetes

Ab Tag `t03`. Der Cluster läuft lokal mit k3d im Dev Container. Anlegen, Image bauen und Löschen übernehmen Skripte im Übungs-Repository unter `t03-container`: `cluster-up.sh`, `build-image.sh` und `cluster-down.sh` (Anleitung im README dort).

| Datei | Inhalt |
|---|---|
| `deploy/k8s/placefinder.yaml` | Deployment mit drei Replikaten, Probes, Requests und Limit; Service; ConfigMap – Musterlösung der Übung |
| `deploy/hpa.yaml` | Horizontal Pod Autoscaler (Zusatzaufgabe) |
| `deploy/helm/placefinder/` | Helm-Chart mit denselben drei Objekten |
| `deploy/helm/values-dev.yaml`, `values-prod.yaml` | Werte je Umgebung für das Chart |

### Manifest anwenden

```bash
cd /workspaces/placefinder
kubectl apply --filename deploy/k8s/
kubectl get pods --output wide                 # drei Pods, verteilt auf die Nodes
kubectl port-forward svc/placefinder 8000:80   # läuft weiter; zweites Terminal öffnen
curl "http://localhost:8000/v1/places?q=Erfurt"
```

`port-forward` verbindet mit genau einem Pod. Wird dieser Pod ersetzt (Update, Löschen), bricht die Verbindung ab; dann den Befehl erneut starten.

### Neue Version ausrollen

```bash
uv version 0.7.1 --no-sync                          # Version in pyproject.toml und uv.lock
../cloud-labs-<anbieter>/t03-container/build-image.sh   # baut placefinder:0.7.1, lädt es in den Cluster
kubectl set image deployment/placefinder api=placefinder:0.7.1
kubectl rollout status deployment/placefinder
curl http://localhost:8000/                         # "version": "0.7.1"
kubectl rollout undo deployment/placefinder         # zurück zu 0.7.0
git restore pyproject.toml uv.lock                  # Version im Repository wieder 0.7.0
```

### Konfiguration ändern

Die ConfigMap liefert `LOG_LEVEL` und `DATA_FILE` als Umgebungsvariablen. PlaceFinder liest sie nur beim Start, deshalb startet `rollout restart` die Pods neu:

```bash
# in deploy/k8s/placefinder.yaml: LOG_LEVEL: debug
kubectl apply --filename deploy/k8s/
kubectl rollout restart deployment/placefinder
kubectl logs deployment/placefinder --follow       # nach einer Suche: "Search q=Erfurt: …"
```

### Helm

Das Chart erzeugt dieselben Objekte, benannt nach dem Release: Release `pf` → `pf-placefinder`. Es stört das Manifest aus `deploy/k8s/` deshalb nicht.

```bash
helm lint deploy/helm/placefinder
helm template pf deploy/helm/placefinder --values deploy/helm/values-dev.yaml   # nur anzeigen
helm upgrade --install pf deploy/helm/placefinder --values deploy/helm/values-dev.yaml
helm upgrade --install pf deploy/helm/placefinder --values deploy/helm/values-prod.yaml
helm history pf                                     # zwei Revisionen
helm rollback pf 1                                  # zurück zu den dev-Werten
helm uninstall pf
```

Die Annotation `checksum/config` im Deployment ändert sich mit der ConfigMap; deshalb startet `helm upgrade` die Pods neu, wenn sich nur die Konfiguration ändert. Mit `--set image.repository=ghcr.io/<github-user>/placefinder` laden die Nodes das Image aus der GitHub Container Registry statt des importierten.

### Autoscaler (Zusatz)

```bash
kubectl apply --filename deploy/hpa.yaml
kubectl get hpa --watch                             # zweites Terminal
kubectl run load --rm --stdin --tty --image=busybox:1.37 -- \
  sh -c 'while true; do wget --quiet --output-document /dev/null "http://placefinder/v1/places?q=B"; done'
```

Mit Last steigt die Zahl der Replikate auf bis zu sechs; nach dem Ende der Last (Ctrl+C) sinkt sie nach etwa fünf Minuten wieder auf zwei. Achtung: Ein erneutes `kubectl apply --filename deploy/k8s/` setzt die Replikate zunächst auf drei zurück, danach regelt der HPA wieder. Entfernen: `kubectl delete --filename deploy/hpa.yaml`.

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
                            # Valkey and SeaweedFS (from t07)
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

Termin 4 (Netzwerke) ändert PlaceFinder nicht und hat keinen eigenen Tag. Die weiteren Stände folgen als Tags `t08`, `t09` usw. `git tag` listet die vorhandenen, `git switch --detach t01` wechselt zu einem Stand.

## Daten und Lizenz

Die Ortsdaten stammen von [GeoNames](https://www.geonames.org) und stehen unter der Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die Lizenz verlangt eine Quellenangabe; PlaceFinder gibt sie unter `/` und in der API-Dokumentation aus. Die Daten werden nicht eingecheckt, sondern mit `data/download.sh` bzw. beim Bau des Images geladen.
