#!/usr/bin/env bash
# Inside the VM: Prometheus + Grafana + Alertmanager (kube-prometheus-stack), Loki, Alloy.
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K8S=~/k8s/obs
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null
kubectl create namespace sixg-obs --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install loki  grafana/loki  --version 7.3.0 -n sixg-obs -f $K8S/loki.yaml
helm upgrade --install kps   prometheus-community/kube-prometheus-stack --version 91.8.1 -n sixg-obs -f $K8S/kps.yaml
helm upgrade --install alloy grafana/alloy --version 1.13.0 -n sixg-obs -f $K8S/alloy.yaml

kubectl -n sixg-obs rollout status statefulset/loki --timeout=600s
kubectl -n sixg-obs wait --for=condition=Available deploy --all --timeout=600s
kubectl -n sixg-obs rollout status daemonset/alloy --timeout=300s
kubectl -n sixg-obs get pods
