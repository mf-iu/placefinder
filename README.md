# PlaceFinder

Beispielanwendung des Kurses „Cloud Computing“: ein Dienst zur Ortssuche auf Basis von GeoNames, später ergänzt um OpenStreetMap. PlaceFinder wächst von Termin zu Termin; jeder Stand ist als Git-Tag verfügbar.

**Stand v0 (Tag `t01`):** eine FastAPI-Anwendung, die beim Start die GeoNames-Datei `cities15000` (alle Orte ab 15.000 Einwohnern, rund 34.000) in den Speicher lädt und nach Namen durchsucht.

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
curl "http://localhost:8000/places?q=Erfurt"
```

```json
[{"id":2929670,"name":"Erfurt","latitude":50.97734,"longitude":11.03536,"country_code":"DE","population":218793,"feature_code":"PPLA","timezone":"Europe/Berlin"}]
```

Die Werte hängen vom Stand der GeoNames-Daten ab. VS Code leitet den Port aus dem Dev Container weiter; die interaktive API-Dokumentation steht unter http://localhost:8000/docs.

| Methode und Pfad | Antwort |
|---|---|
| `GET /places?q=…&limit=…` | Orte, deren Name, ASCII-Name oder alternativer Name mit `q` beginnt, ohne Unterschied zwischen Groß- und Kleinschreibung. Genaue Treffer zuerst, dann nach Einwohnerzahl. `limit` 1–100, Standard 10. |
| `GET /places/{id}` | ein Ort nach GeoNames-ID; 404, wenn es ihn nicht gibt |
| `GET /health` | Status und Zahl der geladenen Orte, z. B. für Health Checks |
| `GET /` | Name, Version und Quellenangabe der Daten |
| `GET /docs`, `GET /openapi.json` | von FastAPI erzeugte Dokumentation (OpenAPI) |

Alternative Namen machen auch deutsche Namen auffindbar: GeoNames führt München als „Munich“, `q=München` findet es trotzdem.

## Konfiguration

| Umgebungsvariable | Standard | Bedeutung |
|---|---|---|
| `DATA_FILE` | `data/cities15000.txt` (relativ zum Arbeitsverzeichnis) | GeoNames-Datei, die beim Start geladen wird |

Fehlt die Datei, bricht der Start mit einer Meldung ab. `data/download.sh` lädt auch andere GeoNames-Dateien, z. B. `data/download.sh cities5000` (Orte ab 5.000 Einwohnern) oder `data/download.sh DE` (alle Einträge für Deutschland, auch Berge, Gewässer usw.); dann `DATA_FILE=data/DE.txt uv run fastapi dev src/placefinder/main.py` oder kurz `./start.sh --data DE`. Größere Dateien brauchen entsprechend mehr Speicher und Startzeit. Mit `cities15000` belegt PlaceFinder rund 130 MB Arbeitsspeicher und startet in etwa einer Sekunde.

**Betrieb ohne Entwicklungsserver** (so richtet cloud-init in Termin 2 die VM ein):

```bash
uv sync --frozen --no-dev                     # ohne Entwicklungswerkzeuge
DATA_FILE=/pfad/zu/cities15000.txt .venv/bin/uvicorn placefinder.main:app --host 0.0.0.0 --port 8000
```

## Entwicklung

```bash
uv run pytest           # Tests
uv run ruff check       # Linter
uv run ruff format      # Formatierung
```

```
start.sh                    # starts the server locally (WSL or dev container)
src/placefinder/main.py     # FastAPI app: endpoints, loading the data at startup
src/placefinder/places.py   # Place, GeoNames parser, in-memory repository with name index
data/download.sh            # downloads GeoNames dumps; data files are not committed
tests/                      # pytest tests with a small sample of GeoNames lines
```

Code, Kommentare und Commit-Messages sind auf Englisch.

## Ausbaustufen

| Tag | Stand |
|---|---|
| `t01` | v0: Ortssuche über `cities15000` im Speicher (`/places?q=…`, `/places/{id}`) |

Die weiteren Stände folgen als Tags `t02`, `t03` usw. `git tag` listet die vorhandenen, `git switch --detach t01` wechselt zu einem Stand.

## Daten und Lizenz

Die Ortsdaten stammen von [GeoNames](https://www.geonames.org) und stehen unter der Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die Lizenz verlangt eine Quellenangabe; PlaceFinder gibt sie unter `/` und in der API-Dokumentation aus. Die Daten werden nicht eingecheckt, sondern mit `data/download.sh` geladen.
