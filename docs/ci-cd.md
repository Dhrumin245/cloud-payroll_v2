# CI/CD (GitHub Actions + GitHub Container Registry)

One workflow, `.github/workflows/ci-cd.yml`. **No secrets to configure**: publishing uses the `GITHUB_TOKEN`
that GitHub gives every run.

## What runs when

```
pull request / every push                                         push to main, or a v* tag
┌────────────────────────────────────────────┐
│ services (x4)   lint, tests on SQLite and  │
│                 PostgreSQL, coverage >= 90%│─┐
│                 migrations on PostgreSQL   │ │
├────────────────────────────────────────────┤ │
│ static          Kubernetes manifests,      │ │        ┌───────────────────────┐   ┌─────────────────────────┐
│                 monitoring rules, compose, │─┼──────► │ publish (x4)          │ ► │ manifests               │
│                 Dockerfiles, workflows     │ │        │ build + push image to │   │ kubectl-ready YAML with │
├────────────────────────────────────────────┤ │        │ ghcr.io, SBOM, scan   │   │ the new image tags,     │
│ e2e             builds the 4 images,       │ │        └───────────────────────┘   │ uploaded as an artifact │
│                 deploys to a kind cluster, │─┘                                    └─────────────────────────┘
│                 smoke test, kills pods,    │
│                 smoke test again           │          nothing is published unless ALL three jobs on the left pass
└────────────────────────────────────────────┘
```

| Job | What it proves |
|---|---|
| **services** (one per service) | `ruff` lint; the whole test suite on SQLite *and* PostgreSQL; coverage at least 90%; migrations upgrade, match the models, downgrade, and survive **three copies starting at once** |
| **static** | Kubernetes manifests render (`kustomize`), match the 1.30 schemas (`kubeconform`), are wired correctly (`scripts/check_k8s.py`, itself tested with 25 deliberate breakages) and pass `kube-linter`; Prometheus configs and the alert rules' unit tests pass the official `promtool`; the generated ConfigMaps are in sync; `docker compose config` is valid; Dockerfiles pass `hadolint`; the workflow itself passes `actionlint` |
| **e2e** | The real thing on Kubernetes: images are built, loaded into a throw-away kind cluster, deployed with `scripts/k8s_deploy.py`, then `scripts/smoke_test.py` walks the business flow through the Ingress (employee applies, manager approves, payroll run with loss-of-pay, payslip PDF, bank file, access control, Prometheus sees all 8 pods). Then **one pod of every service is killed** and the smoke test runs again (self-healing) |
| **publish** | Builds each image again with a layer cache and pushes it to `ghcr.io/<owner>/<repo>/<service>` tagged `sha-<commit>` (and `latest` on main; `1.2.3` and `1.2` on a `v1.2.3` tag). Attaches an SBOM and build provenance. Runs a Trivy vulnerability scan (report only) |
| **manifests** | Rewrites the image names in the Kubernetes manifests to the ones just published and uploads the result as the `kubernetes-manifests` artifact |

## First-time setup

1. Create a GitHub repository and push this project to it (branch `main`). Actions is on by default.
2. The first run starts by itself. Watch it under the **Actions** tab. Pull requests run everything except *publish*/*manifests*.
3. After the first push to `main`, your images appear under your profile or organisation → **Packages**.
4. *(Recommended)* Under Settings → Branches add a rule for `main` that requires the status checks `services`, `static` and `e2e` to pass before merging.
5. *(Optional)* Badge for the README: `[![CI/CD](https://github.com/<owner>/<repo>/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/<owner>/<repo>/actions/workflows/ci-cd.yml)`

## Releasing

```bash
git tag v1.0.0 && git push origin v1.0.0
```
The pipeline runs on the tag and publishes the images as `1.0.0`, `1.0` and `sha-<commit>`.

## Deploying what CI published (minikube)

CI cannot reach your laptop's minikube, so the last step is a deliberate manual one: download the
**`kubernetes-manifests`** artifact from the run's page (a file `cloud-payroll-sha-xxxxxxx.yaml`) and:

```bash
python scripts/init_env.py                                   # once
python scripts/k8s_deploy.py --manifest cloud-payroll-sha-xxxxxxx.yaml
```

Newly published packages are **private** by default, so the cluster needs permission to pull them. Pick one:

* **Make the packages public** (simplest for a demo): GitHub → your profile → Packages → each of the 4 packages → Package settings → *Change visibility* → Public.
* **Or give the cluster a pull secret** (create a personal access token with the `read:packages` scope):
  ```bash
  kubectl -n cloud-payroll create secret docker-registry ghcr-pull \
    --docker-server=ghcr.io --docker-username=<github-user> --docker-password=<token>
  kubectl -n cloud-payroll patch serviceaccount default \
    -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}'
  ```
  (run these after the namespace exists, i.e. after the first `k8s_deploy.py` run; then `kubectl -n cloud-payroll rollout restart deployment --all`).

**Roll back** by deploying an older run's manifest the same way, or with `kubectl -n cloud-payroll rollout undo deployment/<service>`.

## Run the same checks on your own machine

```bash
cd services/auth-service && pytest --cov=app && ruff check .          # per service
scripts/install_k8s_tools.sh ~/.local/bin                             # kustomize, kubeconform, kube-linter (checksum-verified)
python scripts/sync_k8s_configs.py --check
kustomize build k8s > rendered.yaml && kubeconform -strict rendered.yaml \
  && python scripts/check_k8s.py rendered.yaml && kube-linter lint rendered.yaml
docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro" --entrypoint promtool \
  prom/prometheus:v2.55.1 test rules /etc/prometheus/alerts_test.yml
docker compose up --build -d && python scripts/seed_demo.py && python scripts/smoke_test.py   # against compose
```
The same `smoke_test.py` works against docker-compose, minikube and kind: only the URL changes.

## Security choices

* **Actions are pinned to commit SHAs**, not movable tags; **Dependabot** (`.github/dependabot.yml`) proposes updates weekly for the actions, the Python dependencies and the base images.
* **Downloaded tools are checksum-verified** (`scripts/install_k8s_tools.sh`); a changed release asset fails the build.
* **Least privilege:** the workflow defaults to read-only; only the *publish* job gets `packages: write`. Pull requests (including from forks) can never publish.
* **No long-lived secrets** anywhere; the CI values for `JWT_SECRET` and the test encryption key are throw-away constants that protect nothing.
* Images carry an SBOM and provenance attestation; Trivy reports HIGH/CRITICAL findings that have a fix. It is non-blocking so a base-image CVE you cannot fix does not freeze delivery; set `exit-code: "1"` in the workflow to make it a gate.

## Limits and honest notes

* **Not run on GitHub yet.** The workflow and every script it calls were checked with `actionlint` (including shellcheck on the inline shell), and each job's commands were executed step by step here, but a real run on GitHub's runners is the first true test. If a step fails, the log names it; the *Diagnostics on failure* step in `e2e` prints pods, events and logs.
* **Docker Hub pulls in `e2e`** (Postgres, Prometheus, Grafana) can hit anonymous rate limits on busy shared runners; re-running the job fixes it.
* **Images are `linux/amd64` only.** On an Apple Silicon Mac, build locally (`python scripts/k8s_deploy.py --build`) instead of pulling the published images, or add `platforms: linux/amd64,linux/arm64` to the publish step (slower, needs QEMU).
* **No automatic deployment to a cluster:** there is no cloud cluster in this project. The `e2e` job proves the manifests deploy and work on Kubernetes; applying them to your minikube is the manual step above.
* The self-healing step needs the second replica to keep serving while one pod is replaced. If you set a service to a single replica, that step will (correctly) fail.
