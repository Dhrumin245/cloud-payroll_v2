# Monitoring

Prometheus + Grafana are part of `docker compose up` (and of the Kubernetes deployment, see [`k8s/README.md`](../k8s/README.md): same alert rules and dashboard, but `prometheus/prometheus-k8s.yml` discovers pods instead of using fixed targets). Both listen on **127.0.0.1 only** (never through the public gateway).

| | URL | Login |
|---|---|---|
| Grafana | http://localhost:3000 | `admin` / `GRAFANA_ADMIN_PASSWORD` from `.env` (printed by `scripts/init_env.py`) |
| Prometheus | http://localhost:9090 (targets: `/targets`, alerts: `/alerts`) | none |

Grafana opens on the **Cloud Payroll** dashboard (provisioned from `grafana/dashboards/cloud-payroll.json`, so it is in git and identical on every machine).

## What is collected

Prometheus scrapes `/metrics` of the four services every 15s, directly on the internal network
(`prometheus/prometheus.yml`). Retention is 7 days.

| Metric | From | Meaning |
|---|---|---|
| `http_requests_total{handler,method,status}` | all | requests by endpoint and status class (`2xx`..`5xx`); `/health`, `/ready`, `/metrics` are excluded |
| `http_request_duration_highr_seconds` | all | latency histogram (used for p50/p95) |
| `auth_logins_total{result}` | auth | `success`, `failure`, `rate_limited` |
| `leave_requests_total{event}` | leave | `created`, `approved`, `rejected`, `cancelled` |
| `employee_salary_changes_total`, `employee_bank_reveals_total` | employee | sensitive actions (reveals are also audit-logged) |
| `payroll_runs_total{outcome}`, `payroll_bank_files_total` | payroll | `completed` / `rejected` runs, bank files generated |
| `payroll_last_run_employees`, `payroll_last_run_net_pay_total` | payroll | latest run (resets to 0 on a restart until the next run) |
| `downstream_calls_total{target,outcome}` | leave, payroll | calls to employee-service / leave-service, `ok` or `error` |
| `up{service,pod}` | Prometheus | whether the service (Kubernetes: each pod) could be scraped |

## Dashboard

*Platform health:* services up/down, firing alerts, request rate, 5xx ratio, p50/p95 latency, status classes, busiest endpoints.
*Business activity:* logins by result, leave events, payroll runs (completed / rejected / last run), bank reveals and other sensitive actions, calls between services.

## Alerts (`prometheus/alerts.yml`)

| Alert | Fires when | Severity |
|---|---|---|
| `ServiceDown` | a service (or one replica) cannot be scraped for 1 min | critical |
| `ServiceMissing` | a service has **no** scrape target at all, e.g. every pod gone (Kubernetes; `up == 0` cannot see this) | critical |
| `HighErrorRate` | >5% of a service's requests are 5xx for 5 min (ignored under ~1 request/min) | critical |
| `HighLatencyP95` | p95 latency >2s for 10 min | warning |
| `DownstreamCallsFailing` | leave/payroll cannot reach employee/leave service for 2 min | warning |
| `LoginFailureSpike` | >30 failed logins/min for 5 min | warning |
| `LoginRateLimited` | >10 rate-limited logins in 5 min | warning |
| `BankDetailsRevealSpike` | >100 account numbers revealed in an hour | warning |

The rules have unit tests (including "must not fire" cases):

```bash
promtool test rules monitoring/prometheus/alerts_test.yml     # promtool ships with Prometheus
# or, without installing anything:
docker run --rm -v "$PWD/monitoring/prometheus:/p" --entrypoint promtool prom/prometheus:v2.55.1 test rules /p/alerts_test.yml
```

## Logs

Every service and the gateway write one JSON object per line to stdout:
`docker compose logs -f payroll-service`. Services log `request_id`, `method`, `path`, `status`, `duration_ms`
and business events (`leave_approved`, `payroll_completed`, `bank_revealed`, `dep_down` ...). The gateway's `X-Request-ID` is
passed to the services, so one request can be followed across the gateway and service logs.

## Known limits (and the next steps)

- **No Alertmanager:** alerts are visible in Prometheus and on the dashboard but nothing is emailed. Add an Alertmanager with a receiver to get notifications.
- **Not collected:** gateway (nginx) metrics, PostgreSQL metrics. Add `nginx-prometheus-exporter` and `postgres_exporter` as extra scrape targets.
- **Counters appear on first use:** a per-endpoint series only exists after its first request, so the very first request after a start does not show as a rate.
- **Gauges are per process:** with several replicas `payroll_last_run_*` reflects whichever replica Prometheus saw (the dashboard takes the max).
