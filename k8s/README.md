# Kubernetes (minikube)

The same system as `docker-compose.yml`, on Kubernetes: 2 replicas of each service, health probes,
rolling updates, an Ingress, Prometheus and Grafana. Written and checked for **minikube**.

## Quick start

Needs Docker (as the minikube driver), [minikube](https://minikube.sigs.k8s.io/), `kubectl` and Python 3.

```bash
minikube start --cpus=2 --memory=4096
minikube addons enable ingress

python scripts/init_env.py            # once: .env with random secrets (also used for the Kubernetes Secret)
python scripts/k8s_deploy.py --build  # builds the 4 images INSIDE minikube, applies everything, waits until ready
```

Then, in a second terminal (leave it running), open the gateway on the same address as docker-compose:

```bash
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80
```

```bash
curl http://localhost:8080/auth/me     # 401 "Not authenticated" = the Ingress reaches auth-service
python scripts/seed_demo.py            # demo leave types, 3 employees, 3 logins (asha / priya / karan)
```

Monitoring (each in its own terminal; nothing is exposed publicly):

```bash
kubectl -n cloud-payroll port-forward svc/grafana 3000:3000        # http://localhost:3000, user admin
kubectl -n cloud-payroll port-forward svc/prometheus 9090:9090     # http://localhost:9090
```
The Grafana password is `GRAFANA_ADMIN_PASSWORD` in `.env`.

To deploy the images that CI published to GitHub Container Registry instead of building locally, see [`docs/ci-cd.md`](../docs/ci-cd.md)
(`python scripts/k8s_deploy.py --manifest <file from the CI artifact>`).

Prefer to run the steps yourself? `k8s_deploy.py` prints every command it runs. In short:
`kubectl apply -f k8s/namespace.yaml`, then `kubectl -n cloud-payroll create secret generic app-secrets --from-env-file=.env`,
then `kubectl apply -k k8s`.

## What gets deployed (namespace `cloud-payroll`)

| Object | Count | Notes |
|---|---|---|
| `auth-service`, `employee-service`, `leave-service`, `payroll-service` Deployments | 2 replicas each | rolling update with `maxUnavailable: 0`; startup / readiness (`/ready`) / liveness (`/health`) probes; CPU+memory requests and limits |
| `postgres` StatefulSet + 2 Gi volume | 1 | creates a database **and a login role** per service on first start |
| `auth-bootstrap-admin` Job | 1 | creates the first admin (idempotent) |
| `prometheus` (+ RBAC, 2 Gi volume), `grafana` | 1 each | pod discovery; same alert rules and dashboard as docker-compose |
| `gateway` Ingress | 1 | same routes as the compose nginx gateway; `/metrics`, `/docs`, `/ready` are not routed |
| `app-config` ConfigMap, `app-secrets` Secret | | secrets are created from `.env`, never stored in git |

Each service pod starts with two init containers: `wait-for-db`, then `migrate` (`alembic upgrade head`).
That is safe with several replicas starting together because migrations take a PostgreSQL advisory lock
(without it, 8 of 8 simultaneous first starts crashed in testing).

## Things to show in a demo

```bash
kubectl -n cloud-payroll get pods                       # 2 pods per service, all Ready
```

**Self-healing.** Delete a pod while requests keep working (the other replica serves them):
```bash
kubectl -n cloud-payroll delete pod -l app=leave-service
kubectl -n cloud-payroll get pods -w                    # a replacement appears
```

**Scaling.**
```bash
kubectl -n cloud-payroll scale deployment/payroll-service --replicas=4
kubectl -n cloud-payroll get pods -l app=payroll-service
```
(Prometheus discovers the new pods by itself; Grafana's request-rate panel sums all of them.)

**Rolling update and rollback** (zero downtime: a new pod must be Ready before an old one is removed):
```bash
# edit COMPANY_NAME in k8s/config.yaml, then:
kubectl apply -k k8s
kubectl -n cloud-payroll rollout restart deployment/payroll-service   # ConfigMap changes need a restart
kubectl -n cloud-payroll rollout status deployment/payroll-service
kubectl -n cloud-payroll rollout undo deployment/payroll-service      # roll back
```

**Readiness vs liveness.** Stop the database and watch the services drop out of the load balancer
*without* being restarted; they recover on their own:
```bash
kubectl -n cloud-payroll scale statefulset/postgres --replicas=0
kubectl -n cloud-payroll get pods                       # 0/1 READY, RESTARTS stays 0
kubectl -n cloud-payroll scale statefulset/postgres --replicas=1
```

**Autoscaling** (optional):
```bash
minikube addons enable metrics-server
kubectl apply -n cloud-payroll -f k8s/optional/hpa.yaml
kubectl -n cloud-payroll get hpa -w
# generate load from inside the cluster:
kubectl -n cloud-payroll run load --rm -it --image=busybox:1.36 --restart=Never -- \
  sh -c 'while true; do wget -q -O- http://auth-service:8000/health >/dev/null; done'
```

**Monitoring.** In Grafana the *Cloud Payroll* dashboard opens by default. `http://localhost:9090/alerts`
lists the 8 alert rules. Scale a service to zero to see `ServiceMissing` fire after about a minute:
`kubectl -n cloud-payroll scale deployment/leave-service --replicas=0`.

## Compose vs Kubernetes

| docker-compose | Kubernetes |
|---|---|
| nginx `gateway` container | Ingress (ingress-nginx addon) |
| `*-migrate` one-shot containers | `migrate` init container in every pod |
| `auth-bootstrap-admin` container | `auth-bootstrap-admin` Job |
| `.env` read by compose | `.env` becomes the `app-secrets` Secret |
| static Prometheus targets | Prometheus pod discovery (`monitoring/prometheus/prometheus-k8s.yml`) |
| `depends_on: service_healthy` | init containers + readiness probes |

## Behaviour to know about

- **Login rate limit is per pod.** With 2 replicas the effective limit is about 10 attempts a minute per client (the in-memory limiter of each pod counts separately). Use Redis if you need an exact global limit.
- **Client IP:** ingress-nginx overwrites `X-Forwarded-For` with the real client address, so `TRUST_FORWARDED_FOR=true` on auth-service is safe. Behind another proxy or load balancer, check this again.
- **Changing config:** edit `k8s/config.yaml`, `kubectl apply -k k8s`, then `kubectl rollout restart` the deployments (ConfigMaps are not hot-reloaded).
- **Single source of truth:** the Postgres init script, Prometheus config, alert rules and the dashboard live in `infra/` and `monitoring/` and are copied into `k8s/generated/` by `python scripts/sync_k8s_configs.py`. Never edit `k8s/generated/` by hand (`--check` fails in CI if it is stale).
- **Images** are built into minikube with `minikube image build` and tagged `:local`. To use a registry instead, change the `images:` block in `k8s/kustomization.yaml`.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `ErrImagePull` / `ImagePullBackOff` on a service | Images were not built inside minikube. Run `python scripts/k8s_deploy.py --build` |
| Pod stuck in `Init:0/2` | Postgres is not ready yet (`kubectl -n cloud-payroll logs <pod> -c wait-for-db`); give it a minute, or check `kubectl -n cloud-payroll describe pod postgres-0` |
| `Init:Error` / `CrashLoopBackOff` in `migrate` | `kubectl -n cloud-payroll logs <pod> -c migrate`. A wrong DB password usually means the volume was created with older passwords: `kubectl -n cloud-payroll delete pvc data-postgres-0` (deletes the data) and redeploy |
| `Pending` pods | Not enough CPU/memory: `minikube start --cpus=2 --memory=4096` or stop other workloads |
| `curl localhost:8080` refuses the connection | The `port-forward` terminal is not running |
| `404 ... default backend` from the Ingress | The path is intentionally not routed (e.g. `/metrics`, `/docs`) |
| Changed `.env` secrets but pods still use the old ones | `python scripts/k8s_deploy.py` then `kubectl -n cloud-payroll rollout restart deployment --all` |
| Everything gone after `minikube delete` | Expected; volumes live inside minikube |

Remove everything: `kubectl delete namespace cloud-payroll` (also deletes the data).

## How this was checked (and what was not)

Checked automatically, no cluster needed:
`kustomize build k8s` renders 26 objects; `kubeconform -strict` validates them against the Kubernetes 1.30 schemas;
`scripts/check_k8s.py` verifies the wiring (Service selectors, ports, Secret keys, env-variable order, ConfigMap keys, probes,
volumes, DB names against the init script; it catches all 25 deliberate breakages it was tested with); `kube-linter` reports
nothing; the Prometheus config and alert rules pass the official `promtool` of the deployed version, including unit tests.
The migration lock was tested against a real PostgreSQL, and the service code was run with a read-only root filesystem.

**Not run on a real cluster.** This was prepared without access to Docker or minikube, so the first `k8s_deploy.py --build` on your machine is the
first true run. If something fails, `kubectl -n cloud-payroll get pods` and the `logs` / `describe` commands above show why.

## Hardening that would come next

- Run PostgreSQL as a non-root user with a read-only filesystem (the official image starts as root and drops privileges itself; kept as is here because it could not be tested).
- NetworkPolicies (needs a CNI that enforces them, e.g. `minikube start --cni=calico`), TLS on the Ingress, an external secret manager, an Alertmanager for notifications.
