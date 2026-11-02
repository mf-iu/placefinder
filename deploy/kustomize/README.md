# Kustomize-Variante für PlaceFinder

Dieselben drei Objekte wie [`deploy/k8s/placefinder.yaml`](../k8s/placefinder.yaml) – Deployment, Service, ConfigMap –, aufbereitet für zwei Umgebungen mit Kustomize. Es löst dieselbe Aufgabe wie das [Helm-Chart](../helm/README.md), aber umgekehrt: keine Vorlagen mit Platzhaltern, sondern gewöhnliches YAML als **Basis** und je Umgebung ein **Overlay**, das nur die Unterschiede beschreibt. Kustomize ist in `kubectl` eingebaut; es braucht kein weiteres Werkzeug.

**Gehört zu:** [cloud-labs-local/03-kubernetes](https://github.com/mf-iu/cloud-labs-local/tree/master/03-kubernetes) (Termin 3), als Vergleich zum Helm-Chart · **Stand:** PlaceFinder 0.8.0 (Tag `t08`) · **Voraussetzung:** Cluster `pf` aus `cluster-up.sh` und das Image aus `load-image.sh`

## Aufbau

```text
deploy/kustomize/
├── base/
│   ├── kustomization.yaml     lists the objects, generates the ConfigMap, adds a label
│   ├── deployment.yaml        same Deployment as in deploy/k8s/placefinder.yaml
│   └── service.yaml           same Service as in deploy/k8s/placefinder.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml namespace placefinder-dev, 1 pod, LOG_LEVEL=debug
    │   └── namespace.yaml
    └── prod/
        ├── kustomization.yaml namespace placefinder-prod, 3 pods, LOG_LEVEL=warning
        └── namespace.yaml
```

Jede Datei `kustomization.yaml` sagt, woraus ein Ergebnis besteht (`resources`) und was daran zu ändern ist. Ein Overlay nennt die Basis als Ressource (`../../base`) und ändert sie; die Basis weiß nichts von ihren Overlays.

## Wie die Overlays die Basis ändern

| Feld in `kustomization.yaml` | Wo | Wirkung |
|---|---|---|
| `configMapGenerator` | Basis | erzeugt die ConfigMap aus `LOG_LEVEL` und `DATA_FILE` und hängt eine Prüfsumme des Inhalts an den Namen: `placefinder-config-<hash>`. Den Verweis im Deployment passt Kustomize an. |
| `labels` | Basis | schreibt `app.kubernetes.io/managed-by: kustomize` in die Metadaten aller Objekte, nicht in die Selektoren |
| `namespace` | Overlays | legt alle Objekte in `placefinder-dev` bzw. `placefinder-prod`; die Namen bleiben `placefinder` |
| `replicas` | Overlays | setzt die Zahl der Pods im Deployment `placefinder` |
| `configMapGenerator` mit `behavior: merge` | Overlays | ändert `LOG_LEVEL`, behält `DATA_FILE` aus der Basis |
| `images` (auskommentiert) | Overlay prod | ersetzt Name oder Tag des Images, z. B. durch `ghcr.io/<github-user>/placefinder` |

**Neustart bei neuer Konfiguration:** Ändert sich ein Wert der ConfigMap, ändert sich ihr Name und damit der Verweis im Pod-Template – das Deployment rollt neue Pods aus. Das Helm-Chart erreicht dasselbe mit der Annotation `checksum/config`, die man dort selbst schreibt.

**Namespaces statt Namen:** Das Helm-Chart trennt Releases durch den Release-Namen im Objektnamen (`pf-placefinder`). Die Overlays trennen durch Namespaces: Die Objekte heißen überall `placefinder`, im Cluster also `placefinder.placefinder-dev` und `placefinder.placefinder-prod`. So laufen beide Overlays und das Manifest aus `deploy/k8s/` (im Namespace `default`) nebeneinander, ohne dass sich Selektoren überschneiden.

## Befehle

Im Ordner `placefinder`, mit dem Cluster `pf` als aktuellem Kontext:

```bash
kubectl kustomize deploy/kustomize/overlays/dev                 # show the result only
kubectl apply --kustomize deploy/kustomize/overlays/dev
kubectl get all --namespace placefinder-dev                     # 1 pod
kubectl logs deployment/placefinder --namespace placefinder-dev --follow   # debug: every search

kubectl diff --kustomize deploy/kustomize/overlays/prod         # what apply would change
kubectl apply --kustomize deploy/kustomize/overlays/prod
kubectl get pods --namespace placefinder-prod                   # 3 pods

kubectl delete --kustomize deploy/kustomize/overlays/dev        # removes the namespace with everything in it
kubectl delete --kustomize deploy/kustomize/overlays/prod
```

`kubectl kustomize` gibt nur YAML aus und ändert nichts – der beste Weg, ein Overlay zu verstehen. Den Service erreicht man ohne Gateway über eine Portweiterleitung:

```bash
kubectl port-forward service/placefinder 8080:80 --namespace placefinder-dev
curl "http://localhost:8080/v1/places?q=Erfurt"
```

Den Autoscaler aus [`deploy/hpa.yaml`](../hpa.yaml) kann man in einen der Namespaces legen, weil das Deployment dort ebenfalls `placefinder` heißt: `kubectl apply --filename deploy/hpa.yaml --namespace placefinder-prod`. Jedes erneute `kubectl apply --kustomize` setzt die Zahl der Pods allerdings wieder auf den Wert aus `replicas`.

## Helm oder Kustomize?

| | Helm-Chart (`deploy/helm/`) | Kustomize (`deploy/kustomize/`) |
|---|---|---|
| Quelle | Vorlagen mit Go-Template-Syntax, kein gültiges YAML | gewöhnliches YAML |
| Je Umgebung | Wertedatei (`values-dev.yaml`) | Overlay mit Patches und Transformern |
| Werkzeug | `helm` | in `kubectl` eingebaut (`-k`), auch als eigenes Programm `kustomize` |
| Installation | Release mit Revisionen, `helm rollback`, `helm uninstall` | `kubectl apply`; keine Revisionen – die Historie liegt in Git |
| Konfiguration ändern → neue Pods | Annotation `checksum/config` von Hand | `configMapGenerator` mit Prüfsumme im Namen |
| Weitergeben | Chart als Paket in einem Repository, mit Werten für alle Fälle | für das eigene Projekt; wenig geeignet zum Verteilen |
| Typisch für | fremde Software: Traefik, cert-manager, Datenbanken | eigene Anwendungen mit kleinen Unterschieden je Umgebung, GitOps mit Argo CD oder Flux |

Beide lassen sich kombinieren: Kustomize kann ein Helm-Chart rendern (`helmCharts` in `kustomization.yaml`, mit `kustomize build --enable-helm`) und das Ergebnis weiter anpassen – üblich, um fremde Charts zu ändern, ohne sie zu kopieren.

## Pflege

- `base/deployment.yaml` und `base/service.yaml` sind Kopien der Objekte aus `deploy/k8s/placefinder.yaml`. Eine Basis kann nicht auf eine Datei außerhalb ihres Ordners verweisen, und `deploy/k8s/` bleibt ein Ordner für `kubectl apply --filename`, den die Übungen und Skripte von `cloud-labs-local` so verwenden. Ändert sich das Manifest, die Kopien mitändern.
- Eine neue Version von PlaceFinder ändert den Image-Tag an drei Stellen: im Manifest, in `base/deployment.yaml` und als `appVersion` im Helm-Chart.

## Typische Probleme

| Meldung | Ursache | Abhilfe |
|---|---|---|
| `no matches for kind "Kustomization"` | `kubectl apply --filename` auf einen Ordner mit `kustomization.yaml` | `--kustomize` (kurz `-k`) statt `--filename` |
| `security; file '…' is not in or below '…'` | eine Ressource außerhalb des Ordners der `kustomization.yaml` | nur Dateien im eigenen Ordner oder andere Kustomizations als Ordner (`../../base`) einbinden |
| Pods in `ErrImagePull` oder `ImagePullBackOff` | Das Image `placefinder:0.8.0` ist nicht in den Nodes. | `../cloud-labs-local/03-kubernetes/load-image.sh` |
| alte ConfigMaps `placefinder-config-<hash>` bleiben liegen | `kubectl apply` löscht nichts, was nicht mehr im Ergebnis vorkommt | von Hand löschen oder das Overlay mit `delete --kustomize` entfernen und neu anwenden |
