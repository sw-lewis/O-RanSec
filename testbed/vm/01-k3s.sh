#!/usr/bin/env bash
# Inside the VM: install single-node k3s (the O-Cloud layer) and Helm.
# k3s ships with Flannel, CoreDNS, Traefik ingress and a NetworkPolicy controller.
set -euo pipefail

K3S_VERSION=v1.33.13+k3s2
HELM_VERSION=v3.22.0

if ! command -v k3s >/dev/null; then
  echo "[k3s] installing $K3S_VERSION"
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - \
    --write-kubeconfig-mode 0640 \
    --write-kubeconfig-group sixg \
    --disable-cloud-controller
fi

mkdir -p ~/.kube
ln -sf /etc/rancher/k3s/k3s.yaml ~/.kube/config
grep -q KUBECONFIG ~/.bashrc || echo 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml' >> ~/.bashrc

if ! command -v helm >/dev/null || [[ $(helm version --short) != ${HELM_VERSION}* ]]; then
  echo "[helm] installing $HELM_VERSION"
  curl -sfL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" | tar -xz -C /tmp
  sudo install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm
fi

echo "[k3s] waiting for the node to be Ready"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
until kubectl get node -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q True; do
  sleep 3
done
until [[ $(kubectl get deploy -n kube-system --no-headers 2>/dev/null | wc -l) -ge 4 ]]; do sleep 3; done
kubectl wait -n kube-system --for=condition=Available deploy --all --timeout=300s
kubectl get nodes -o wide
