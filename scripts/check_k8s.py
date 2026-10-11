#!/usr/bin/env python3
"""Check the WIRING of the rendered Kubernetes manifests (needs PyYAML).

    kustomize build k8s | python scripts/check_k8s.py
    python scripts/check_k8s.py rendered.yaml

Schema validators (kubeconform) cannot see mistakes such as a Service whose selector matches no pod,
a Secret key that is not in .env, or an env variable used before it is defined. This script does.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "cloud-payroll"
SERVICES = {
    # service: (db role, database, password key)
    "auth-service": ("auth_svc", "auth_db", "AUTH_DB_PASSWORD"),
    "employee-service": ("employee_svc", "employee_db", "EMPLOYEE_DB_PASSWORD"),
    "leave-service": ("leave_svc", "leave_db", "LEAVE_DB_PASSWORD"),
    "payroll-service": ("payroll_svc", "payroll_db", "PAYROLL_DB_PASSWORD"),
}
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def load(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def pod_spec(doc: dict) -> dict | None:
    if doc["kind"] in ("Deployment", "StatefulSet"):
        return doc["spec"]["template"]["spec"]
    if doc["kind"] == "Job":
        return doc["spec"]["template"]["spec"]
    return None


def pod_labels(doc: dict) -> dict:
    return doc["spec"]["template"]["metadata"].get("labels", {})


def containers(doc: dict):
    spec = pod_spec(doc)
    for kind in ("initContainers", "containers"):
        for c in spec.get(kind, []):
            yield kind, c


def check(docs: list[dict]) -> None:
    by_kind: dict[str, dict[str, dict]] = {}
    for d in docs:
        by_kind.setdefault(d["kind"], {})[d["metadata"]["name"]] = d
    workloads = {**by_kind.get("Deployment", {}), **by_kind.get("StatefulSet", {}), **by_kind.get("Job", {})}
    configmaps = by_kind.get("ConfigMap", {})
    env_keys = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    # every namespaced object is in our namespace
    for d in docs:
        if d["kind"] != "Namespace" and d["metadata"].get("namespace") != NAMESPACE:
            err(f"{d['kind']}/{d['metadata']['name']}: namespace is {d['metadata'].get('namespace')!r}")

    # Services -> pods -> named ports
    for name, svc in by_kind.get("Service", {}).items():
        sel = svc["spec"]["selector"]
        matching = [w for w in workloads.values() if sel.items() <= pod_labels(w).items()]
        if not matching:
            err(f"Service/{name}: selector {sel} matches no workload")
            continue
        for port in svc["spec"]["ports"]:
            target = port["targetPort"]
            declared = {
                p["name"]: p["containerPort"] for w in matching for _, c in containers(w) for p in c.get("ports", [])
            }
            if isinstance(target, str) and target not in declared:
                err(f"Service/{name}: targetPort {target!r} is not a named container port ({sorted(declared)})")

    # Ingress backends
    services = by_kind.get("Service", {})
    for ing in by_kind.get("Ingress", {}).values():
        for rule in ing["spec"]["rules"]:
            for p in rule["http"]["paths"]:
                be = p["backend"]["service"]
                svc = services.get(be["name"])
                if svc is None:
                    err(f"Ingress path {p['path']}: service {be['name']!r} does not exist")
                elif be["port"]["number"] not in [sp["port"] for sp in svc["spec"]["ports"]]:
                    err(f"Ingress path {p['path']}: port {be['port']['number']} not exposed by {be['name']}")

    # per container: env ordering, refs, probes, volumes, resources, security
    for wname, w in workloads.items():
        spec = pod_spec(w)
        volume_names = {v["name"] for v in spec.get("volumes", [])} | {
            t["metadata"]["name"] for t in w["spec"].get("volumeClaimTemplates", [])
        }
        for v in spec.get("volumes", []):
            if "configMap" in v:
                cm = configmaps.get(v["configMap"]["name"])
                if cm is None:
                    err(f"{wname}: volume {v['name']} uses missing ConfigMap {v['configMap']['name']!r}")
                else:
                    for item in v["configMap"].get("items", []):
                        if item["key"] not in cm["data"]:
                            err(f"{wname}: ConfigMap {cm['metadata']['name']} has no key {item['key']!r}")
            if "persistentVolumeClaim" in v and v["persistentVolumeClaim"]["claimName"] not in by_kind.get(
                "PersistentVolumeClaim", {}
            ):
                err(f"{wname}: PVC {v['persistentVolumeClaim']['claimName']!r} is not defined")
        if spec.get("serviceAccountName") and spec["serviceAccountName"] not in by_kind.get("ServiceAccount", {}):
            err(f"{wname}: ServiceAccount {spec['serviceAccountName']!r} is not defined")

        for kind, c in containers(w):
            where = f"{wname}/{c['name']}"
            defined: list[str] = []
            for e in c.get("env", []):
                if e["name"] in defined:
                    err(f"{where}: env {e['name']} defined twice")
                for ref in re.findall(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", e.get("value", "")):
                    if ref not in defined:
                        err(f"{where}: env {e['name']} uses $({ref}) before it is defined")
                sk = e.get("valueFrom", {}).get("secretKeyRef")
                if sk:
                    if sk["name"] != "app-secrets":
                        err(f"{where}: unexpected secret {sk['name']!r}")
                    if sk["key"] not in env_keys:
                        err(f"{where}: secret key {sk['key']!r} is not produced by .env.example")
                ck = e.get("valueFrom", {}).get("configMapKeyRef")
                if ck and ck["key"] not in configmaps.get(ck["name"], {}).get("data", {}):
                    err(f"{where}: configMapKeyRef {ck['name']}/{ck['key']} missing")
                defined.append(e["name"])
            for ef in c.get("envFrom", []):
                if "configMapRef" in ef and ef["configMapRef"]["name"] not in configmaps:
                    err(f"{where}: envFrom ConfigMap {ef['configMapRef']['name']!r} missing")
                if "secretRef" in ef:
                    err(f"{where}: envFrom secretRef would inject EVERY secret; use secretKeyRef")
            for arg in [*c.get("command", []), *c.get("args", [])]:
                for ref in re.findall(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", arg):
                    if ref not in defined:
                        err(f"{where}: command uses $({ref}) which is not an env var")
            for m in c.get("volumeMounts", []):
                if m["name"] not in volume_names:
                    err(f"{where}: volumeMount {m['name']!r} has no volume")
            ports = {p["name"] for p in c.get("ports", [])}
            for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
                port = c.get(probe, {}).get("httpGet", {}).get("port")
                if isinstance(port, str) and port not in ports:
                    err(f"{where}: {probe} port {port!r} is not a named container port")
            res = c.get("resources", {})
            if not res.get("requests") or not res.get("limits"):
                err(f"{where}: needs resource requests AND limits")
            sc = c.get("securityContext", {})
            if wname != "postgres" and (
                sc.get("allowPrivilegeEscalation") is not False or sc.get("capabilities", {}).get("drop") != ["ALL"]
            ):
                err(f"{where}: must drop all capabilities and forbid privilege escalation")
            image = c["image"]
            if image.startswith("cloud-payroll/") and c.get("imagePullPolicy") != "IfNotPresent":
                err(f"{where}: locally built image needs imagePullPolicy IfNotPresent")
            if image.endswith(":latest") or ":" not in image:
                err(f"{where}: image {image!r} must have a pinned tag")

    # the four services: replicas, scrape annotations, migrations and DB wiring
    for svc, (role, db, pw_key) in SERVICES.items():
        dep = by_kind.get("Deployment", {}).get(svc)
        if dep is None:
            err(f"Deployment/{svc} missing")
            continue
        if dep["spec"]["replicas"] < 2:
            err(f"{svc}: needs at least 2 replicas")
        ann = dep["spec"]["template"]["metadata"].get("annotations", {})
        if ann.get("prometheus.io/scrape") != "true" or ann.get("prometheus.io/port") != "8000":
            err(f"{svc}: missing Prometheus scrape annotations")
        spec = dep["spec"]["template"]["spec"]
        if [c["name"] for c in spec.get("initContainers", [])] != ["wait-for-db", "migrate"]:
            err(f"{svc}: initContainers must be wait-for-db then migrate")
        if dep["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] != 0:
            err(f"{svc}: rolling update must keep maxUnavailable 0")
        app = next(c for c in spec["containers"] if c["name"] == "app")
        env = {e["name"]: e for e in app["env"]}
        want = f"postgresql+psycopg://{role}:$({pw_key})@postgres:5432/{db}"
        if env.get("DATABASE_URL", {}).get("value") != want:
            err(f"{svc}: DATABASE_URL should be {want}")
        if app["readinessProbe"]["httpGet"]["path"] != "/ready" or app["livenessProbe"]["httpGet"]["path"] != "/health":
            err(f"{svc}: readiness must be /ready and liveness /health")
    init_script = (ROOT / "infra/postgres/init-databases.sh").read_text()
    for svc, (role, db, pw_key) in SERVICES.items():
        if not re.search(rf"create_service_db\s+{role}\s+{db}\s+\"\${{{pw_key}:-}}\"", init_script):
            err(f"init-databases.sh does not create {role}/{db} with {pw_key}")
    if "EMPLOYEE_DB_PASSWORD" not in {
        e["name"] for e in by_kind["StatefulSet"]["postgres"]["spec"]["template"]["spec"]["containers"][0]["env"]
    }:
        err("postgres: init script passwords are not passed to the container")

    # HPA / RBAC / bootstrap job
    job = by_kind.get("Job", {}).get("auth-bootstrap-admin")
    if job is None or "--if-not-exists" not in job["spec"]["template"]["spec"]["containers"][0]["command"]:
        err("auth-bootstrap-admin job must exist and be idempotent (--if-not-exists)")
    role = by_kind.get("Role", {}).get("prometheus")
    if role is None or "pods" not in role["rules"][0]["resources"]:
        err("Role/prometheus must be able to list pods (pod discovery)")


def main() -> int:
    text = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()
    docs = load(text)
    check(docs)
    # optional HPA file, if present, must point at real deployments
    hpa = ROOT / "k8s/optional/hpa.yaml"
    deployments = {d["metadata"]["name"] for d in docs if d["kind"] == "Deployment"}
    if hpa.exists():
        for d in load(hpa.read_text()):
            if d["spec"]["scaleTargetRef"]["name"] not in deployments:
                err(f"HPA/{d['metadata']['name']}: target deployment missing")
    if errors:
        print(f"{len(errors)} problem(s):")
        for e in errors:
            print("  -", e)
        return 1
    print(f"OK: {len(docs)} objects, wiring consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
