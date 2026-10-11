"""Mutation tests for scripts/check_k8s.py: a checker that never fails proves nothing.

Renders the manifests with kustomize, breaks them in 25 different ways, and asserts that
check_k8s.py reports a problem for every one. Run:  pytest scripts/test_check_k8s.py
(skipped when kustomize is not installed).
"""

import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("kustomize") is None, reason="kustomize not installed")


@pytest.fixture(scope="module")
def docs():
    out = subprocess.run(["kustomize", "build", "k8s"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def check(documents):
    r = subprocess.run(
        [sys.executable, "scripts/check_k8s.py"],
        input=yaml.safe_dump_all(documents),
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return r.returncode, r.stdout


def get(ds, kind, name):
    return next(d for d in ds if d["kind"] == kind and d["metadata"]["name"] == name)


def app(ds, svc):
    spec = get(ds, "Deployment", svc)["spec"]["template"]["spec"]
    return next(c for c in spec["containers"] if c["name"] == "app")


def test_unmodified_manifests_pass(docs):
    code, out = check(docs)
    assert code == 0, out


def _swap_env_order(ds):
    env = app(ds, "auth-service")["env"]
    names = [e["name"] for e in env]
    i, j = names.index("DATABASE_URL"), names.index("AUTH_DB_PASSWORD")
    env[i], env[j] = env[j], env[i]


def _db_url(ds):
    env = app(ds, "leave-service")["env"]
    next(e for e in env if e["name"] == "DATABASE_URL")["value"] = (
        "postgresql+psycopg://leave_svc:$(LEAVE_DB_PASSWORD)@postgres:5432/auth_db"
    )


MUTATIONS = {
    "service selector typo": lambda ds: get(ds, "Service", "auth-service")["spec"]["selector"].update(
        app="auth-servce"
    ),
    "secret key typo": lambda ds: app(ds, "auth-service")["env"][1]["valueFrom"]["secretKeyRef"].update(
        key="AUTH_DB_PASWORD"
    ),
    "probe uses unnamed port": lambda ds: app(ds, "leave-service")["readinessProbe"]["httpGet"].update(port="web"),
    "ingress to missing service": lambda ds: get(ds, "Ingress", "gateway")["spec"]["rules"][0]["http"]["paths"][3][
        "backend"
    ]["service"].update(name="leave-servis"),
    "ingress to unexposed port": lambda ds: get(ds, "Ingress", "gateway")["spec"]["rules"][0]["http"]["paths"][0][
        "backend"
    ]["service"]["port"].update(number=9000),
    "DATABASE_URL wrong database": _db_url,
    "only one replica": lambda ds: get(ds, "Deployment", "payroll-service")["spec"].update(replicas=1),
    "scrape annotation off": lambda ds: get(ds, "Deployment", "employee-service")["spec"]["template"]["metadata"][
        "annotations"
    ].update({"prometheus.io/scrape": "false"}),
    "envFrom secretRef": lambda ds: app(ds, "auth-service")["envFrom"].append({"secretRef": {"name": "app-secrets"}}),
    "limits removed": lambda ds: app(ds, "payroll-service")["resources"].pop("limits"),
    "configmap key wrong": lambda ds: get(ds, "Deployment", "grafana")["spec"]["template"]["spec"]["volumes"][3][
        "configMap"
    ]["items"][0].update(key="datasources.yml"),
    "bootstrap job not idempotent": lambda ds: get(ds, "Job", "auth-bootstrap-admin")["spec"]["template"]["spec"][
        "containers"
    ][0]["command"].remove("--if-not-exists"),
    "unpinned image": lambda ds: get(ds, "Deployment", "grafana")["spec"]["template"]["spec"]["containers"][0].update(
        image="grafana/grafana:latest"
    ),
    "wrong namespace": lambda ds: get(ds, "ServiceAccount", "prometheus")["metadata"].update(namespace="default"),
    "env used before defined": _swap_env_order,
    "init containers reordered": lambda ds: get(ds, "Deployment", "leave-service")["spec"]["template"]["spec"][
        "initContainers"
    ].reverse(),
    "rolling update may drop pods": lambda ds: get(ds, "Deployment", "auth-service")["spec"]["strategy"][
        "rollingUpdate"
    ].update(maxUnavailable=1),
    "liveness checks the database": lambda ds: app(ds, "auth-service")["livenessProbe"]["httpGet"].update(
        path="/ready"
    ),
    "pullPolicy Always": lambda ds: app(ds, "auth-service").update(imagePullPolicy="Always"),
    "capabilities kept": lambda ds: app(ds, "employee-service")["securityContext"].pop("capabilities"),
    "volumeMount without volume": lambda ds: app(ds, "auth-service")["volumeMounts"][0].update(name="scratch"),
    "duplicate env var": lambda ds: app(ds, "auth-service")["env"].append(dict(app(ds, "auth-service")["env"][0])),
    "missing PVC": lambda ds: get(ds, "Deployment", "prometheus")["spec"]["template"]["spec"]["volumes"][1][
        "persistentVolumeClaim"
    ].update(claimName="nope"),
    "Prometheus cannot list pods": lambda ds: get(ds, "Role", "prometheus")["rules"][0].update(resources=["services"]),
    "postgres init password missing": lambda ds: get(ds, "StatefulSet", "postgres")["spec"]["template"]["spec"][
        "containers"
    ][0]["env"].__delitem__(
        [
            e["name"] for e in get(ds, "StatefulSet", "postgres")["spec"]["template"]["spec"]["containers"][0]["env"]
        ].index("EMPLOYEE_DB_PASSWORD")
    ),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_checker_catches(docs, name):
    broken = copy.deepcopy(docs)
    MUTATIONS[name](broken)
    assert broken != docs, "the mutation changed nothing, so the test would prove nothing"
    code, out = check(broken)
    assert code != 0, f"check_k8s.py did not notice: {name}\n{out}"
