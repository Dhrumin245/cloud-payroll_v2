#!/usr/bin/env python3
"""Deploy the whole system to the current Kubernetes cluster (minikube). Standard library only.

    python scripts/k8s_deploy.py --build     # first time: build the 4 images inside minikube, then deploy
    python scripts/k8s_deploy.py             # deploy / update (images already built)
    python scripts/k8s_deploy.py --skip-wait # apply and return immediately
    python scripts/k8s_deploy.py --manifest cloud-payroll-sha-1a2b3c4.yaml
                                             # deploy the images CI published (the manifest is a CI artifact)

Needs: kubectl, a running cluster (minikube start), and a .env file (python scripts/init_env.py).
It is safe to run repeatedly. Every command it runs is printed, so you can also run them by hand.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NS = "cloud-payroll"
SERVICES = ["auth-service", "employee-service", "leave-service", "payroll-service"]


def show(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd), flush=True)


def run(cmd: list[str], *, input_text: str | None = None, check: bool = True, capture: bool = False):
    show(cmd)
    result = subprocess.run(cmd, input=input_text, text=True, capture_output=capture, cwd=ROOT)
    if check and result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(f"\nFailed (exit {result.returncode}): {' '.join(cmd)}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", action="store_true", help="build the service images inside minikube first")
    ap.add_argument("--skip-wait", action="store_true", help="do not wait for everything to become ready")
    ap.add_argument(
        "--manifest",
        help="apply this pre-rendered manifest (the 'kubernetes-manifests' CI artifact) instead of k8s/",
    )
    ap.add_argument("--context", help="kubectl context to use (default: the current one)")
    args = ap.parse_args()

    kubectl = ["kubectl"] + (["--context", args.context] if args.context else [])
    if args.manifest and args.build:
        sys.exit("--manifest uses images from a registry, so it cannot be combined with --build")
    if args.manifest and not Path(args.manifest).exists():
        sys.exit(f"Manifest not found: {args.manifest}")
    if shutil.which("kubectl") is None:
        sys.exit("kubectl not found. Install it (https://kubernetes.io/docs/tasks/tools/) and retry.")
    if not (ROOT / ".env").exists():
        sys.exit("No .env file. Run:  python scripts/init_env.py")

    print("[1/6] checking the cluster")
    run([*kubectl, "cluster-info"], capture=True)
    ingress = run([*kubectl, "get", "namespace", "ingress-nginx"], check=False, capture=True)
    if ingress.returncode != 0:
        print("  note: no ingress controller found. On minikube run:  minikube addons enable ingress")

    if args.build:
        if shutil.which("minikube") is None:
            sys.exit("--build needs minikube on the PATH (it builds the images inside the minikube VM)")
        print("[2/6] building images inside minikube (a few minutes the first time)")
        for svc in SERVICES:
            run(["minikube", "image", "build", "-t", f"cloud-payroll/{svc}:local", f"services/{svc}"])
    else:
        print("[2/6] skipping image build (use --build the first time)")

    print("[3/6] namespace and secrets")
    run([*kubectl, "apply", "-f", "k8s/namespace.yaml"])
    manifest = run(
        [
            *kubectl,
            "-n",
            NS,
            "create",
            "secret",
            "generic",
            "app-secrets",
            "--from-env-file=.env",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        capture=True,
    ).stdout
    run([*kubectl, "-n", NS, "apply", "-f", "-"], input_text=manifest)

    print("[4/6] applying manifests")
    # A finished Job cannot be updated in place; it is idempotent, so just recreate it.
    run([*kubectl, "-n", NS, "delete", "job", "auth-bootstrap-admin", "--ignore-not-found"])
    if args.manifest:
        run([*kubectl, "apply", "-f", args.manifest])
    else:
        run([*kubectl, "apply", "-k", "k8s"])

    if args.skip_wait:
        print("[5/6] not waiting (--skip-wait)")
    else:
        print("[5/6] waiting for everything to become ready (first start: 2-4 minutes)")
        run([*kubectl, "-n", NS, "rollout", "status", "statefulset/postgres", "--timeout=300s"])
        for name in [*SERVICES, "prometheus", "grafana"]:
            run([*kubectl, "-n", NS, "rollout", "status", f"deployment/{name}", "--timeout=300s"])
        run(
            [
                *kubectl,
                "-n",
                NS,
                "wait",
                "--for=condition=complete",
                "job/auth-bootstrap-admin",
                "--timeout=300s",
            ]
        )

    print("[6/6] done\n")
    print("Reach the API (keep this running in its own terminal):")
    print("  kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80")
    print("  then:  curl http://localhost:8080/auth/me   (401 means the gateway reaches auth-service)")
    print("         python scripts/seed_demo.py")
    print("Monitoring (each in its own terminal):")
    print(f"  kubectl -n {NS} port-forward svc/grafana 3000:3000")
    print(f"  kubectl -n {NS} port-forward svc/prometheus 9090:9090")
    return 0


if __name__ == "__main__":
    sys.exit(main())
