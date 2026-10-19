#!/usr/bin/env bash
# Inside the VM: deploy the srsRAN + FlexRIC O-RAN pair, flowmon, the edge device hub and the dashboard.
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K8S=~/k8s

for ns in sixg-ran sixg-ric sixg-edge; do
  kubectl create namespace $ns --dry-run=client -o yaml | kubectl apply -f -
done

echo "[oran] srsRAN gNB + srsUE and FlexRIC"
helm upgrade --install oran $K8S/oran -n sixg-ran
echo "[obs] flowmon"
kubectl apply -f $K8S/obs/flowmon.yaml
echo "[edge] device hub, MQTT, video server"
kubectl apply -f $K8S/edge/device-hub.yaml
echo "[control] dashboard"
kubectl apply -f $K8S/control/dashboard.yaml

kubectl -n sixg-ran  wait --for=condition=Available deploy --all --timeout=600s
kubectl -n sixg-ric  wait --for=condition=Available deploy --all --timeout=600s
kubectl -n sixg-edge wait --for=condition=Available deploy --all --timeout=300s
kubectl -n sixg-obs  rollout status daemonset/flowmon --timeout=300s
kubectl -n sixg-control wait --for=condition=Available deploy --all --timeout=300s
kubectl get pods -A
