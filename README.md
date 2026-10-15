# PlaceFinder

Beispielanwendung des Kurses „Cloud Computing“: ein Dienst zur Ortssuche auf Basis von GeoNames, später ergänzt um OpenStreetMap. PlaceFinder wächst von Termin zu Termin; jeder Stand ist als Git-Tag verfügbar.

**Stand v0 (Tags `t01` und `t02`):** eine FastAPI-Anwendung, die beim Start die GeoNames-Datei `cities15000` (alle Orte ab 15.000 Einwohnern, rund 34.000) in den Speicher lädt und nach Namen durchsucht. Ab `t02` gibt es dazu ein Container-Image und eine `compose.yaml` mit PostGIS (Abschnitt [Container](#container)).

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

## Container

Ab Tag `t02`. Alle Befehle im Terminal des Dev Containers, im Verzeichnis `/workspaces/placefinder`.

**Zwei Docker-Instanzen:** Der Dev Container hat eine eigene Docker Engine (Docker in Docker). Images, die dort gebaut werden, sieht Docker in der Ubuntu-Shell von WSL nicht, und umgekehrt. Im Kurs laufen alle Container-Übungen im Dev Container. Auch eine Anmeldung bei Docker Hub gilt nur für die Instanz, in der sie ausgeführt wurde (siehe nächster Abschnitt).

### Docker Hub: anmelden oder nicht?

Die Basis-Images (`python:3.14-slim`, `postgis/postgis`) kommen von Docker Hub. Docker Hub begrenzt die Downloads (Pulls) innerhalb von 6 Stunden:

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
token=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq -r .token)
curl -s --head -H "Authorization: Bearer $token" \
  https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest | grep -i ratelimit
```

`ratelimit-limit: 100;w=21600` heißt 100 Pulls in 21600 Sekunden (6 Stunden), `ratelimit-remaining` ist der Rest. Fehlen diese Zeilen, gilt für die Adresse kein Limit.

### Image bauen und starten

```bash
docker build -t placefinder:0.1.0 .          # Image bauen (erster Build einige Minuten)
docker history placefinder:0.1.0             # Schichten mit Größe
docker run --rm -p 8000:8000 placefinder:0.1.0
curl "http://localhost:8000/places?q=Erfurt" # in einem zweiten Terminal
```

Das `Dockerfile` hat drei Stufen:

| Stufe | Aufgabe |
|---|---|
| `data` | lädt die GeoNames-Datei (`cities15000`) und entpackt sie nach `/data` |
| `build` | installiert mit uv die Abhängigkeiten genau nach `uv.lock`, dann PlaceFinder selbst als Paket |
| Runtime | übernimmt nur die virtuelle Umgebung und die Daten, entfernt pip, läuft als Benutzer `app` ohne root |

Die Daten gehören damit zum Image (rund 8 MB). So startet der Container überall ohne Download, auch auf den Serverless-Container-Diensten in Termin 3; aktuelle Daten gibt es mit einem neuen Build. Eine andere Datei wählt `--build-arg GEONAMES_FILE=cities5000`. `.dockerignore` hält `.git`, `.venv`, `data/` und `tests/` aus dem Build-Kontext heraus.

Ändert sich nur der Code unter `src/`, baut Docker nur die letzten Schichten neu; ändert sich `uv.lock`, auch die Abhängigkeiten.

### Image verkleinern und prüfen

Zum Vergleich ein Image mit nur einer Stufe auf Basis von `python:3.14` bauen (ohne Daten, nur für den Größenvergleich):

```bash
docker build -t placefinder:single -f - . <<'EOF'
FROM python:3.14
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
WORKDIR /app
COPY . .
RUN uv sync --locked --no-dev
CMD [".venv/bin/uvicorn", "placefinder.main:app", "--host", "0.0.0.0"]
EOF
docker images placefinder                                       # Größen vergleichen
trivy image --severity HIGH,CRITICAL placefinder:0.1.0          # Schwachstellen
trivy image --severity HIGH,CRITICAL placefinder:single
```

Fehlt `trivy` im Dev Container, geht es auch mit dem Image von Trivy:
`docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0 image --severity HIGH,CRITICAL placefinder:0.1.0`
(feste Version: Einige Trivy-Images vom März 2026 waren manipuliert, deshalb nie ohne Tag)

### Trivy-Bericht lesen

Trivy listet die Funde je Ziel: die Pakete des Betriebssystems (`debian`) und Python-Pakete (`python-pkg`). Wichtig sind die Spalten *Status* und *Fixed Version*:

| Status | Bedeutung | Was tun? |
|---|---|---|
| `fixed` | Es gibt eine korrigierte Version (*Fixed Version*). | Paket bzw. Basis-Image aktualisieren und neu bauen |
| `affected` | Betroffen, aber noch keine Korrektur verfügbar. | abwarten; später mit `docker build --pull` neu bauen |
| `fix_deferred` | Die Distribution hat die Korrektur zurückgestellt, meist wegen geringer Auswirkung. | prüfen, ob die Anwendung das Paket überhaupt nutzt |

Bei PlaceFinder (Stand `t02`) sind alle Python-Pakete der virtuellen Umgebung ohne Befund. Die Funde im Debian-Teil des Basis-Images (z. B. `util-linux`, `ncurses`, `systemd`) haben keine *Fixed Version*. PlaceFinder nutzt diese Programme nicht, und der Container läuft ohne root – die Funde sind vorhanden, aber praktisch nicht erreichbar.

Die Python-Funde des Basis-Images (`msgpack`, `urllib3`, `setuptools`) stammen aus pip, das diese Pakete in sich mitbringt. Zur Laufzeit wird pip nicht gebraucht; die Runtime-Stufe entfernt es deshalb. Prüfen lässt sich die Herkunft eines Funds über den Pfad im JSON-Bericht:

```bash
trivy image --format json placefinder:0.1.0 \
  | jq -r '.Results[] | .Vulnerabilities[]? | "\(.PkgName) \(.InstalledVersion) \(.PkgPath // "-")"'
```

Nur Funde mit verfügbarer Korrektur zeigt `trivy image --ignore-unfixed …` – so wird in CI-Pipelines oft geprüft (Termin 8). Weniger Funde haben Basis-Images mit weniger Paketen, etwa Distroless-Images.

### Image in die GitHub Container Registry laden

Optional in Termin 2, nötig ab Termin 3 (die Container-Dienste laden das Image von dort):

```bash
gh auth login                                 # einmalig, falls noch nicht angemeldet
gh auth refresh -s write:packages             # Recht zum Hochladen von Paketen
gh auth token | docker login ghcr.io -u <github-user> --password-stdin
docker tag placefinder:0.1.0 ghcr.io/<github-user>/placefinder:t02
docker push ghcr.io/<github-user>/placefinder:t02
```

Ein neues Paket ist zunächst privat. Für Termin 3 auf GitHub unter *Packages* → *placefinder* → *Package settings* → *Change visibility* auf **Public** stellen.

### Compose: PlaceFinder mit PostGIS

`compose.yaml` startet PlaceFinder (`api`) und eine PostGIS-Datenbank (`db`). PlaceFinder v0 nutzt die Datenbank noch nicht; die Datenhaltung folgt in Termin 6. Hier geht es darum, dass beide Container laufen und sich über das gemeinsame Netz erreichen.

```bash
cd /workspaces/placefinder                    # compose.yaml liegt hier
docker ps                                     # läuft noch ein Container auf Port 8000? stoppen
docker compose up -d                          # bauen (falls nötig) und starten
docker compose ps                             # db: healthy, api: running
docker compose logs -f api
docker compose exec api python -c "import socket; socket.create_connection(('db', 5432)); print('db reachable')"
docker compose down                           # stoppen; die Datenbank bleibt im Volume pgdata
docker compose down -v                        # zusätzlich das Volume löschen
```

`api` startet erst, wenn `db` den Healthcheck (`pg_isready`) besteht. Der Dienstname `db` ist im Netz des Stacks zugleich der Hostname der Datenbank.

Häufige Fehler:

| Meldung | Ursache | Abhilfe |
|---|---|---|
| `no configuration file provided: not found` | Das Terminal steht nicht im Verzeichnis mit `compose.yaml` (neue Terminals öffnen im Übungs-Repository). | `cd /workspaces/placefinder` |
| `Bind for 0.0.0.0:8000 failed: port is already allocated` | Ein anderer Container belegt Port 8000, meist der aus `docker run` der Übung. | `docker ps`, den Container mit `docker stop <name>` beenden, dann `docker compose up -d` |
| `Temporary failure in name resolution` beim Verbindungstest | Der Container `api` hat nach einem fehlgeschlagenen Start kein vollständiges Netz. | `docker compose down`, dann `docker compose up -d` |

## Entwicklung

```bash
uv run pytest           # Tests
uv run ruff check       # Linter
uv run ruff format      # Formatierung
```

```
start.sh                    # starts the server locally (WSL or dev container)
Dockerfile, .dockerignore   # container image with the GeoNames data (from t02)
compose.yaml                # PlaceFinder with PostGIS for local development (from t02)
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
| `t02` | v0 als Container-Image (`Dockerfile` mit den GeoNames-Daten), `compose.yaml` mit PostGIS |

Die weiteren Stände folgen als Tags `t03`, `t04` usw. `git tag` listet die vorhandenen, `git switch --detach t01` wechselt zu einem Stand.

## Daten und Lizenz

Die Ortsdaten stammen von [GeoNames](https://www.geonames.org) und stehen unter der Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die Lizenz verlangt eine Quellenangabe; PlaceFinder gibt sie unter `/` und in der API-Dokumentation aus. Die Daten werden nicht eingecheckt, sondern mit `data/download.sh` bzw. beim Bau des Images geladen.
