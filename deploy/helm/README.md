# Helm-Chart für PlaceFinder

Das Chart beschreibt dieselben drei Objekte wie das Manifest [`deploy/k8s/placefinder.yaml`](../k8s/placefinder.yaml) – Deployment, Service und ConfigMap –, aber als Vorlagen mit Werten. Statt die YAML-Datei für jede Umgebung zu kopieren, setzt man nur andere Werte ein: ein Pod und ausführliche Logs zum Entwickeln, drei Pods und knappe Logs für den Betrieb. Helm merkt sich jede Installation als Revision und kann zu einer früheren zurückkehren. Dieselbe Aufgabe löst [`deploy/kustomize/`](../kustomize/README.md) mit Kustomize; dort steht auch ein Vergleich der beiden.

**Übung:** [cloud-labs-local/03-kubernetes](https://github.com/mf-iu/cloud-labs-local/tree/master/03-kubernetes), Abschnitt „Helm“ (Termin 3) · **Stand:** Chart 0.5.0 für PlaceFinder 0.8.0 (Tag `t08`) · **Voraussetzung:** Cluster `pf` aus `cluster-up.sh` und das Image aus `load-image.sh`

## Aufbau

```text
deploy/helm/
├── placefinder/               the chart
│   ├── Chart.yaml             name, chart version, appVersion (= default image tag)
│   ├── values.yaml            default values
│   ├── .helmignore            files that helm package leaves out
│   └── templates/
│       ├── _helpers.tpl       name and labels, used by all templates
│       ├── deployment.yaml    pods with probes, resources and the ConfigMap as environment
│       ├── service.yaml       port 80 in front of port 8000 of the pods
│       └── configmap.yaml     LOG_LEVEL and DATA_FILE
├── values-dev.yaml            development: one pod, log level debug
└── values-prod.yaml           production: three pods, log level warning
```

Die beiden Wertedateien liegen bewusst neben dem Chart, nicht darin: Das Chart ist für alle gleich, die Werte gehören zur Umgebung.

## Was Helm aus den Vorlagen macht

`helm template` zeigt das Ergebnis, ohne etwas zu installieren. Im Vergleich zum Manifest aus `deploy/k8s/` ändert sich Folgendes:

| | Manifest `deploy/k8s/` | Chart, Release `pf` |
|---|---|---|
| Namen | `placefinder`, `placefinder-config` | `pf-placefinder`, `pf-placefinder-config` – Release-Name vor dem Chart-Namen (`placefinder.fullname` in `_helpers.tpl`) |
| Labels | `app: placefinder` | die empfohlenen Labels `app.kubernetes.io/name`, `…/instance`, `…/version`, `…/managed-by` und `helm.sh/chart` |
| Selektor | `app: placefinder` | nur `app.kubernetes.io/name` und `…/instance`: So wählt der Service nur die Pods seines Release |
| Image | `placefinder:0.8.0` fest | `image.repository` und `image.tag`; ohne Tag die `appVersion` aus `Chart.yaml` |
| Neustart bei neuer Konfiguration | von Hand: `kubectl rollout restart` | automatisch über die Annotation `checksum/config` |

**Warum zwei Releases sich nicht stören:** Durch den Release-Namen in Namen und Selektor können das Manifest und mehrere Releases (z. B. `pf` und `pf-test`) im selben Namespace nebeneinander laufen.

**Die Annotation `checksum/config`:** Die Pods lesen die ConfigMap nur beim Start als Umgebungsvariablen. Ändert sich nur `logLevel`, bliebe das Deployment gleich, und Kubernetes hätte keinen Grund für neue Pods. Die Vorlage schreibt deshalb die Prüfsumme der fertigen ConfigMap in die Annotationen des Pod-Templates. Ändert sich die ConfigMap, ändert sich die Prüfsumme, also das Pod-Template – und `helm upgrade` löst ein Rolling Update aus.

**Probes:** Die Readiness Probe fragt `/health`, die Liveness Probe `/livez`, wie im Manifest; Begründung im [README von PlaceFinder](../../README.md#kubernetes), Abschnitt „Kubernetes“.

## Werte

| Wert | Vorgabe | Bedeutung |
|---|---|---|
| `replicaCount` | `3` | Zahl der Pods |
| `image.repository` | `placefinder` | Image, das `load-image.sh` in die Nodes von k3d importiert hat; oder `ghcr.io/<github-user>/placefinder` |
| `image.tag` | `""` | leer: `appVersion` aus `Chart.yaml`, z. B. `0.8.0` |
| `image.pullPolicy` | `IfNotPresent` | ein vorhandenes Image nicht neu laden – nötig für das importierte Image, das in keiner Registry liegt |
| `logLevel` | `info` | `LOG_LEVEL` in der ConfigMap: `debug`, `info`, `warning`, `error` |
| `dataFile` | `/data/cities15000.txt` | `DATA_FILE` in der ConfigMap; die Datei ist ins Image eingebaut |
| `service.port` | `80` | Port des Service im Cluster |
| `resources` | Request 100m CPU und 128 MiB, Limit 256 MiB | wie im Manifest |

**Reihenfolge:** `values.yaml` im Chart, dann jede Datei aus `--values` in der angegebenen Reihenfolge, zuletzt `--set`. Was später kommt, gewinnt. `helm upgrade` beginnt jedes Mal wieder bei `values.yaml`: Werte einer früheren Revision gelten nur, wenn man sie erneut angibt (oder `--reuse-values` setzt).

## Befehle

Im Ordner `placefinder`, mit dem Cluster `pf` als aktuellem Kontext:

```bash
helm lint deploy/helm/placefinder                                                 # check the chart
helm template pf deploy/helm/placefinder --values deploy/helm/values-dev.yaml     # show the objects only
helm upgrade --install pf deploy/helm/placefinder --values deploy/helm/values-dev.yaml
kubectl get deployments,pods,services --selector app.kubernetes.io/instance=pf
helm upgrade --install pf deploy/helm/placefinder --values deploy/helm/values-prod.yaml
helm history pf                                                                   # two revisions
helm get values pf                                                                # values of the current revision
helm rollback pf 1                                                                # back to the dev values
helm uninstall pf                                                                 # removes all three objects
```

`upgrade --install` installiert beim ersten Mal und aktualisiert danach; derselbe Befehl passt also immer. Einen einzelnen Wert ändert `--set`, z. B. `--set replicaCount=2` oder `--set image.repository=ghcr.io/<github-user>/placefinder`.

Den Service erreicht man ohne Gateway nur im Cluster oder über eine Portweiterleitung:

```bash
kubectl port-forward service/pf-placefinder 8080:80
curl "http://localhost:8080/v1/places?q=Erfurt"
```

## Was das Chart nicht enthält

Die Werte des Charts decken die Konfiguration von Termin 3 ab: PlaceFinder mit den Orten aus der Datei im Image.

- **Datenbank, Cache, Telemetrie:** keine Werte für `DATABASE_URL`, `VALKEY_URL`, `CORS_ORIGINS` oder `OTEL_*`. Wer sie braucht, ergänzt sie in `configmap.yaml` und `values.yaml`; Passwörter gehören in ein Secret, nicht in die ConfigMap.
- **Autoscaler:** [`deploy/hpa.yaml`](../hpa.yaml) gilt für das Deployment `placefinder` aus dem Manifest. Für ein Release müsste `scaleTargetRef.name` auf `pf-placefinder` zeigen. Außerdem setzt jedes `helm upgrade` die Zahl der Pods wieder auf `replicaCount` zurück; Charts mit Autoscaler lassen `replicas` deshalb weg, sobald der Autoscaler aktiv ist.
- **Zugang von außen:** Gateway, HTTPRoute und Zertifikate richtet [cloud-labs-local/04-cluster-network](https://github.com/mf-iu/cloud-labs-local/tree/master/04-cluster-network) ein, für das Deployment aus dem Manifest.

## Versionen

`version` in `Chart.yaml` ist die Version des Charts, `appVersion` die von PlaceFinder. Beide steigen unabhängig voneinander: eine neue Version von PlaceFinder erhöht `appVersion` (und damit den Image-Tag), eine geänderte Vorlage erhöht `version`. Mit jedem Tag von PlaceFinder steigen beide; das Image muss dann mit dem neuen Tag importiert sein (`load-image.sh`).

## Typische Probleme

| Meldung | Ursache | Abhilfe |
|---|---|---|
| Pods in `ErrImagePull` oder `ImagePullBackOff` | Das Image mit dem Tag aus `appVersion` ist nicht in den Nodes. | `../cloud-labs-local/03-kubernetes/load-image.sh` oder `--set image.tag=<vorhandener Tag>` |
| `Error: INSTALLATION FAILED: cannot re-use a name that is still in use` | `helm install` für ein vorhandenes Release | `helm upgrade --install` verwenden |
| Fehler beim Rendern, z. B. `nil pointer evaluating` | Wert fehlt oder ist falsch geschrieben | `helm template … --debug` zeigt die Stelle |
| doppelt so viele Pods wie erwartet | Manifest und Release laufen nebeneinander | eines entfernen: `kubectl delete --filename deploy/k8s/` oder `helm uninstall pf` |
