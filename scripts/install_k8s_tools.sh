#!/usr/bin/env bash
# Install kustomize, kubeconform and kube-linter (Linux amd64) into a directory.
# Versions are pinned and every download is verified against a SHA-256 checksum, so a
# tampered release asset fails the build instead of running.
#
#   scripts/install_k8s_tools.sh [DEST_DIR]      # default: $HOME/.local/bin
#
# To upgrade a tool: change its version and URL, download the new file once, run
# `sha256sum` on it, and paste the new checksum below.
set -euo pipefail

DEST="${1:-$HOME/.local/bin}"
mkdir -p "$DEST"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

install_tool() { # name url sha256 file-inside-archive
  local name="$1" url="$2" sha="$3" member="$4"
  curl -fsSL --retry 3 -o "$tmp/$name.tgz" "$url"
  if ! echo "$sha  $tmp/$name.tgz" | sha256sum -c - >/dev/null 2>&1; then
    echo "CHECKSUM MISMATCH for $name ($url): refusing to install" >&2
    exit 1
  fi
  tar -xzf "$tmp/$name.tgz" -C "$tmp" "$member"
  install -m 0755 "$tmp/$member" "$DEST/$name"
  echo "installed $name"
}

install_tool kustomize \
  "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.4.3/kustomize_v5.4.3_linux_amd64.tar.gz" \
  3669470b454d865c8184d6bce78df05e977c9aea31c30df3c669317d43bcc7a7 kustomize
install_tool kubeconform \
  "https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-linux-amd64.tar.gz" \
  95f14e87aa28c09d5941f11bd024c1d02fdc0303ccaa23f61cef67bc92619d73 kubeconform
install_tool kube-linter \
  "https://github.com/stackrox/kube-linter/releases/download/v0.7.2/kube-linter-linux.tar.gz" \
  8a0f8ba6c28910acd4886cc4d501ed32f3d404a53ac5e72c45a0dd893fcadb03 kube-linter
