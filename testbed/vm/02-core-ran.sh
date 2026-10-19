#!/usr/bin/env bash
# Inside the VM: deploy the Open5GS core (3 slices, 3 UPFs) and the UERANSIM RAN.
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
K8S=~/k8s
CHARTS=oci://registry-1.docker.io/gradiantcharts

kubectl create namespace sixg-core --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace sixg-ran  --dry-run=client -o yaml | kubectl apply -f -

# PFCP services must be headless; clusterIP is immutable, so drop any old non-headless ones.
for s in core-upf-pfcp core-smf-pfcp upf-urllc-pfcp upf-mmtc-pfcp; do
  ip=$(kubectl -n sixg-core get svc $s -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
  [[ -n $ip && $ip != None ]] && kubectl -n sixg-core delete svc $s
done

echo "[core] Open5GS"
helm upgrade --install core $CHARTS/open5gs --version 2.3.4 -n sixg-core -f $K8S/core/values.yaml
echo "[core] URLLC and mMTC UPFs"
helm upgrade --install upf-urllc $CHARTS/open5gs-upf --version 2.3.2 -n sixg-core -f $K8S/core/upf-urllc.yaml
helm upgrade --install upf-mmtc  $CHARTS/open5gs-upf --version 2.3.2 -n sixg-core -f $K8S/core/upf-mmtc.yaml

echo "[core] waiting for all core pods"
kubectl -n sixg-core wait --for=condition=Available deploy --all --timeout=600s

echo "[ran] UERANSIM gNB + UEs"
helm upgrade --install ran $K8S/ran -n sixg-ran
kubectl -n sixg-ran wait --for=condition=Available deploy --all --timeout=300s

kubectl get pods -n sixg-core -o wide
kubectl get pods -n sixg-ran -o wide
