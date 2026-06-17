#!/usr/bin/env bash
set -euo pipefail

DOCKER_VERSION="${DOCKER_VERSION:-5:29.2.1-1~ubuntu.22.04~jammy}"
CONTAINERD_VERSION="${CONTAINERD_VERSION:-2.2.1-1~ubuntu.22.04~jammy}"
BUILDX_VERSION="${BUILDX_VERSION:-0.31.1-1~ubuntu.22.04~jammy}"
COMPOSE_VERSION="${COMPOSE_VERSION:-5.0.2-1~ubuntu.22.04~jammy}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "run with sudo: sudo bash scripts/setup_docker_jetson.sh" >&2
  exit 2
fi

install_docker_repo() {
  if [[ -f /etc/apt/sources.list.d/docker.list ]]; then
    return
  fi
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  arch="$(dpkg --print-architecture)"
  echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
}

install_docker_repo
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  "containerd.io=${CONTAINERD_VERSION}" \
  "docker-ce=${DOCKER_VERSION}" \
  "docker-ce-cli=${DOCKER_VERSION}" \
  "docker-ce-rootless-extras=${DOCKER_VERSION}" \
  "docker-buildx-plugin=${BUILDX_VERSION}" \
  "docker-compose-plugin=${COMPOSE_VERSION}"

if command -v nvidia-ctk >/dev/null 2>&1; then
  nvidia-ctk runtime configure --runtime=docker
else
  echo "warning: nvidia-ctk not found; install NVIDIA container toolkit before GPU containers" >&2
fi

usermod -aG docker "${SUDO_USER:-doit}" || true
systemctl enable --now docker
systemctl restart docker

docker --version
docker compose version
docker info --format 'Runtimes={{range $k,$v := .Runtimes}}{{$k}} {{end}}'
