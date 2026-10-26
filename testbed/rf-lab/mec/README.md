# MEC on sl04: edge UPF and MEC server

MEC traffic breaks out locally on sl04 instead of travelling to the core: the SMF in the testbed VM
controls a second UPF on sl04 over N4, and UEs that ask for DNN `mec` get a PDU session on it.
Their user plane never leaves sl04, and the MEC server sees real UE addresses (no NAT).

```
UE -> O-DU -> O-CU (CU-UP) --N3 127.0.20.1--> edge UPF --ogsmec 10.48/16--> MEC server 10.0.3.10 (br-mec)
                  |  N2 to AMF (VM)                ^ N4 (PFCP 192.168.2.14:8805) from SMF (VM)
```

| Item | Value |
|---|---|
| DNN / slice | `mec` on eMBB (SST 1, SD 000001) |
| UE pool | 10.48.0.0/16, gateway 10.48.0.1 (`ogsmec` on sl04) |
| Edge UPF | Open5GS 2.7 (PPA), host network; N4 192.168.2.14:8805, N3 127.0.20.1:2152 |
| MEC server | 10.0.3.10 on `br-mec`: http :80, ssh/sftp :2222 (user `mec`, password `mec-lab`), mqtt :1883, rtsp :8554, rtmp :1935, srt udp/8890, hls :8888 |
| CPUs | 12-15 for the whole stack (the O-DU, O-CU and srsUE stay on 4-11) |
| Test subscriber | 999700000000404, DNN mec (in `k8s/core/values.yaml`) |

UEs on `mec` reach only the MEC server: `host-setup.sh` drops their traffic to sl04 itself, the LAN
and the internet, so attacks cannot touch the RIC, the O-DU or anything else.

## Bring-up (each step checked before the next)

1. **Edge UPF and server on sl04**
   ```bash
   cd ~/O-RanSec && git pull
   cd testbed/rf-lab/mec
   docker compose up -d --build
   sudo ./host-setup.sh
   docker compose logs edge-upf | tail      # "PFCP Server" on 192.168.2.14:8805, "GTP-U Server" on 127.0.20.1
   ip -br addr show ogsmec                   # 10.48.0.1/16, UP
   ```
2. **SMF and subscriber** (Pop!_OS, `~/Project6G/testbed`, after `git pull`)
   ```bash
   ./6g snapshot before-mec
   cat k8s/core/values.yaml | ./6g ssh 'cat > ~/k8s/core/values.yaml'
   ./6g ssh "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; helm upgrade core oci://registry-1.docker.io/gradiantcharts/open5gs --version 2.3.4 -n sixg-core -f ~/k8s/core/values.yaml"
   ./6g ssh "sudo k3s kubectl -n sixg-core logs deploy/core-smf --since=2m | grep -iE 'pfcp|associat|192.168.2.14'"
   ```
   The SMF log should show a PFCP association with 192.168.2.14; the edge UPF log shows the same.
3. **UE on the MEC** (sl04): start CU, then DU, then
   ```bash
   cd ~/oran/srsRAN_4G/build/srsue/src && sudo taskset -c 4-11 ./srsue ~/O-RanSec/testbed/rf-lab/sl04/ue_testbed_mec.conf
   ```
   srsUE should report `PDU Session Establishment successful. IP: 10.48.0.x`. Then
   ```bash
   sudo ip netns exec ue1 ip route add default dev tun_srsue
   sudo ip netns exec ue1 ping -c 3 10.0.3.10
   sudo ip netns exec ue1 curl -s http://10.0.3.10/ | head -3
   sudo ip netns exec ue1 ping -c 2 8.8.8.8      # expected to fail: MEC UEs reach only the MEC
   ```
4. **Server sees the UE's own address**
   ```bash
   docker compose logs httpd | tail -2           # requests from 10.48.0.x
   ```

## Notes from bring-up

- Docker 27 or later is needed: the server network is created in `routed` gateway mode, otherwise Docker
  drops routed traffic to containers (`iptables -t raw -S PREROUTING` shows a DROP for 10.0.3.10).
- N4 must not be NATed. `./6g start` adds these rules (`ranlink_up`); to add them by hand:
  ```bash
  ./6g ssh "sudo iptables -t nat -I POSTROUTING 1 -s 10.42.0.0/16 -d 192.168.2.14 -j RETURN"
  sudo iptables -t nat -I POSTROUTING 1 -s 10.166.0.0/24 -d 192.168.2.14 -j RETURN
  sudo iptables -t nat -I POSTROUTING 1 -s 10.42.0.0/16 -d 192.168.2.14 -j RETURN
  ```
  With NAT, the edge UPF sees the SMF at two addresses and PFCP replies are lost: the session is set up,
  the Session Modification times out and the UE gets an RRC Release after about 8 s.
- After restarting the SMF, restart the AMF too (`rollout restart deploy/core-amf`) and re-attach the RAN:
  otherwise the AMF keeps stale session contexts and releases the UE (`Cause[Group:1 Cause:14]`).
- After restarting the edge UPF (including `docker compose down`/`up`), re-attach the UEs: restart the
  O-DU and srsUE. The SMF re-installs the sessions on the UPF, but they no longer match the O-CU's tunnels.

## Capturing MEC traffic

N3 for `mec` sessions stays on sl04's loopback: `sudo tcpdump -ni lo udp port 2152`.
The UE side of the edge UPF (inner packets, no GTP): `sudo tcpdump -ni ogsmec`.
The testbed's flowmon only sees N4 for this traffic, by design.

## After a reboot of sl04

`docker compose up -d` restarts the stack (restart policy `unless-stopped`); run `sudo ./host-setup.sh` again.
