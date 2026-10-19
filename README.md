# 6G Security Testbed

A complete 5G/6G network that runs inside **one virtual machine** on a normal Linux PC.

It is a safe playground (a "cyber-range") for testing network security. Students can run their own AI attacker agents against it, and real devices like drones and phones can connect to it. Everything is built from real open-source software. Nothing is faked.

You control everything from a **web dashboard** in your browser.

---

## Table of contents

1. [What is inside](#1-what-is-inside)
2. [How it works](#2-how-it-works)
3. [What you need](#3-what-you-need)
4. [Folder layout](#4-folder-layout)
5. [First-time setup](#5-first-time-setup)
6. [Daily use](#6-daily-use)
7. [The dashboard: user manual](#7-the-dashboard-user-manual)
8. [Connecting real devices](#8-connecting-real-devices)
9. [Snapshots and reset](#9-snapshots-and-reset)
10. [All commands](#10-all-commands)
11. [Troubleshooting](#11-troubleshooting)
12. [Safety and isolation](#12-safety-and-isolation)
13. [Known limits](#13-known-limits)

---

## 1. What is inside

| Part | Software | What it does |
|---|---|---|
| 5G Core | Open5GS 2.7.5 | The "brain" of the mobile network (AMF, SMF, UPF, AUSF, UDM, NRF, PCF, NSSF + MongoDB) |
| 3 network slices | Open5GS, 3 UPFs | eMBB (fast data), URLLC (low delay), mMTC (many small IoT devices) |
| Simulated radio | UERANSIM 3.2.6 | Simulated base station (gNB) and 9 simulated phones (UEs) |
| Software radio | srsRAN 25.10 (ZMQ) | A more realistic gNB + phone pair. Radio signals are passed as data, so no antennas are needed |
| O-RAN RIC | FlexRIC | A lightweight RAN Intelligent Controller with a monitoring xApp (reads live radio stats over E2) |
| Edge (MEC) | Device Hub, Mosquitto, MediaMTX | Receives drone telemetry, MQTT sensor data and live video from devices |
| Simulated devices | ArduPilot SITL, ffmpeg | A simulated drone that really flies a route, a simulated phone camera, IoT sensors |
| Monitoring | Prometheus, Grafana, Loki, Alloy | Metrics, charts, and every log from every component |
| Traffic meter | flowmon (own code) | Measures live traffic on each network link (N2, N3, N4, N6, E2 ...) |
| Cloud layer | k3s (Kubernetes) | Runs every part as a container, restarts broken parts by itself |
| Control panel | Dashboard (React + FastAPI) | One web page to see and control everything |

> **About "6G":** there is no open-source 6G core yet. So the base layer is a real 5G Standalone network, and 6G ideas (slicing, O-RAN intelligence, edge computing, AI-driven testing) are built on top of it.

---

## 2. How it works

```
 Your PC (Ubuntu)
 ┌─────────────────────────────────────────────────────────────┐
 │  Browser ──► http://127.0.0.1:8660  (SSH tunnel)            │
 │                     │                                       │
 │  ┌──────────────────▼────────────────────────────────────┐  │
 │  │ Isolated VM "sixg-testbed" (10.166.0.10)              │  │
 │  │  k3s Kubernetes                                       │  │
 │  │   ├─ sixg-core     Open5GS core + 3 UPFs + MongoDB    │  │
 │  │   ├─ sixg-ran      UERANSIM gNB + UEs, srsRAN pair    │  │
 │  │   ├─ sixg-ric      FlexRIC + xApp                     │  │
 │  │   ├─ sixg-edge     Device Hub, MQTT, video server     │  │
 │  │   ├─ sixg-devices  one gateway per connected device   │  │
 │  │   ├─ sixg-obs      Prometheus, Grafana, Loki, flowmon │  │
 │  │   └─ sixg-control  the dashboard                      │  │
 │  └───────────────────────────────────────────────────────┘  │
 └─────────────────────────────────────────────────────────────┘
```

- The whole testbed lives inside **one KVM virtual machine**.
- The VM is **locked down**: it can reach the internet (to download software) but it **cannot** reach your PC or your home network.
- When you **stop** the testbed, the VM shuts down and uses **zero CPU and zero RAM**.
- You open the dashboard on your PC through a private SSH tunnel. Nothing is exposed to your network.

---

## 3. What you need

### Hardware

| | Minimum | Recommended |
|---|---|---|
| CPU | 12 cores with virtualization (Intel VT-x or AMD-V), AVX2 support | 16 cores |
| RAM | 24 GB | 32 GB or more |
| Free disk | 80 GB (SSD) | 200 GB SSD |
| Internet | Needed for first-time setup | |

The VM itself uses **10 CPU cores and 20 GB RAM** while it runs. Its disk is "thin": it can grow up to 200 GB but only uses what it really needs.

To check that your CPU supports virtualization:

```bash
egrep -c '(vmx|svm)' /proc/cpuinfo     # must print a number bigger than 0
```

If it prints `0`, turn on **Intel VT-x / AMD-V (SVM)** in your BIOS settings.

### Software

- **Ubuntu 22.04 or newer** (other Linux systems with KVM may work, but are not tested)
- A user account with `sudo` rights
- `git`, `curl`, `python3`, `ssh` (normally already installed)

---

## 4. Folder layout

```
Project6G/
├── README.md               this file
└── testbed/
    ├── 6g                  the main launcher command (run it on your PC)
    ├── host/               runs on your PC
    │   ├── 00-install-host.sh   one-time install of KVM + network + firewall
    │   ├── sixg-net.xml         the VM's private network
    │   ├── sixg-isolate.xml     the firewall that isolates the VM
    │   ├── user-data.tpl        first-boot settings for the VM
    │   ├── relay.py             forwards real devices to the VM
    │   └── launch.sh            for desktop icons (start/stop without a terminal)
    ├── vm/                 runs inside the VM
    │   ├── 01-k3s.sh            install Kubernetes (k3s) + Helm
    │   ├── 02-core-ran.sh       deploy 5G core + simulated radio
    │   ├── 03-observability.sh  deploy Prometheus, Grafana, Loki, Alloy
    │   └── 04-build-images.sh   build the testbed's own container images
    ├── k8s/                Kubernetes settings for every part
    │   ├── core/   ran/   oran/   edge/   obs/   control/
    ├── images/             Dockerfiles for our own images
    │   ├── srsran-gnb/  srsue/  srsran-zmq/  flexric/
    │   ├── device-gateway/  device-hub/  ardupilot-sitl/  flowmon/
    └── dashboard/          the web control panel
        ├── backend/   (Python, FastAPI)
        └── frontend/  (React, TypeScript)
```

The folder `testbed/keys/` is created automatically. It holds the SSH key for the VM and is **never** uploaded to git.

---

## 5. First-time setup

Do this once. It takes about **1 to 2 hours**, mostly waiting for downloads and image builds.

In all steps below, start from the project folder:

```bash
git clone https://github.com/Shariar13/Project6G.git
cd Project6G/testbed
```

### Step 1. Prepare your PC (about 5 minutes)

This installs KVM and libvirt, creates the private VM network and the isolation firewall.

```bash
sudo bash host/00-install-host.sh
```

Nothing from this step starts by itself when your PC boots.

### Step 2. Create the VM (about 10 to 15 minutes)

```bash
./6g create
```

This will:

1. Create an SSH key in `testbed/keys/`
2. Download the Ubuntu 22.04 cloud image
3. Create the VM (10 CPU, 20 GB RAM, no display, no shared folders)
4. **Check that the isolation firewall is attached.** If it is not, it stops right away for safety
5. Install updates inside the VM and restart it once

When you see `VM ready. Next: 6g start`, go on.

### Step 3. Copy the testbed files into the VM

```bash
SSHOPT="-i keys/sixg_ed25519 -o UserKnownHostsFile=keys/known_hosts"
scp $=SSHOPT -r vm k8s images sixg@10.166.0.10:~/
scp $=SSHOPT -r dashboard sixg@10.166.0.10:~/images/
```

> If you use **bash** (not zsh), write `$SSHOPT` instead of `$=SSHOPT`.

### Step 4. Log in to the VM

```bash
./6g ssh
```

You are now **inside** the VM. Steps 5 to 9 all run here.

### Step 5. Install Kubernetes (about 3 minutes)

```bash
bash ~/vm/01-k3s.sh
source ~/.bashrc
```

At the end you should see one node with status `Ready`.

### Step 6. Build the container images (about 45 to 90 minutes)

srsRAN and FlexRIC are built from source, so this is the slowest step. The order matters: `srsran-zmq` needs `srsran-gnb` and `srsue` first.

```bash
bash ~/vm/04-build-images.sh srsran-gnb srsue srsran-zmq flexric \
     flowmon device-hub device-gateway ardupilot-sitl dashboard
```

Each image prints `loaded into k3s` when done. If one fails, the last 40 lines of its build log are shown. Full logs are in `~/build-<name>.log`.

### Step 7. Deploy the 5G core and the simulated radio (about 5 minutes)

```bash
bash ~/vm/02-core-ran.sh
```

### Step 8. Deploy monitoring (about 5 minutes)

```bash
bash ~/vm/03-observability.sh
```

### Step 9. Deploy the O-RAN part, the edge, traffic meter and dashboard

```bash
kubectl create namespace sixg-ric
helm upgrade --install oran ~/k8s/oran -n sixg-ran
kubectl apply -f ~/k8s/obs/flowmon.yaml
kubectl apply -f ~/k8s/edge/device-hub.yaml
kubectl apply -f ~/k8s/control/dashboard.yaml
```

Check that everything is running (all pods should show `Running`):

```bash
kubectl get pods -A
```

It is normal that some pods restart a few times in the first minutes while other parts are still starting.

Now leave the VM:

```bash
exit
```

### Step 10. Start and open the dashboard

Back on your PC:

```bash
./6g start
```

Open **http://127.0.0.1:8660** in your browser. 🎉

### Step 11. Save a clean snapshot (strongly recommended)

When everything shows healthy in the dashboard, save this good state:

```bash
./6g snapshot clean
```

Now you can always go back to it with `./6g reset` (see [section 9](#9-snapshots-and-reset)).

### Optional: desktop icons

To start and stop the testbed by clicking an icon (no terminal), make two `.desktop` files in `~/.local/share/applications/` that run:

```
/full/path/to/Project6G/testbed/host/launch.sh start
/full/path/to/Project6G/testbed/host/launch.sh stop
```

The start icon also opens the dashboard in your browser when it is ready.

---

## 6. Daily use

### Start

```bash
cd Project6G/testbed
./6g start
```

Wait about **3 minutes** after a cold start until everything is healthy. Then open:

| What | Address |
|---|---|
| **Dashboard** (main control panel) | http://127.0.0.1:8660 |
| Grafana (charts, log search) | http://127.0.0.1:8661 |
| Open5GS WebUI (subscriber list) | http://127.0.0.1:8662 |

These addresses only work on your own PC.

### Check status

```bash
./6g status
```

Shows if the VM is running, CPU time, RAM in use and disk use.

### Stop

```bash
./6g stop
```

Always stop the testbed when you are done. It takes about 15 seconds, and after that the VM uses **no CPU and no RAM**. All your data (devices, test history, logs) is kept on disk.

### Passwords

- **Grafana:** user `admin`. Get the password with:
  ```bash
  ./6g ssh "sudo k3s kubectl -n sixg-obs get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo"
  ```
- **Open5GS WebUI:** default login `admin` / `1423`.

---

## 7. The dashboard: user manual

The dashboard is the main way to use the testbed. Everything on it is **live**: it reads real data from the running system, not example data.

At the top right, the badge (for example `27/27 healthy`) shows how many parts are working. Yellow means some part needs attention. Right after a restart it can stay yellow for about 5 minutes. This is normal.

### Overview

The home page. A quick look at the whole testbed:

- Health of every component (core, radio, RIC, edge, monitoring)
- How many phones and devices are connected
- Live traffic and key numbers
- Recent warnings and events

**Use it to:** check in one glance that the testbed is OK.

### Live Architecture

An animated map of the whole network. Each box is a real component. The moving dots on the lines are **real traffic**, measured live on each link (N2, N3, N4, N6, SBI, E2 ...).

- Green box = healthy, yellow/red = problem, grey = not running
- Click any box to open a side panel with its details, logs and actions

**Use it to:** explain the network to others, and to see where traffic flows.

### Control Panel

Start, stop and restart parts of the network.

- **Start / stop / restart** each component
- **Safe network restart:** restarts the core and radio in the correct order and waits until every phone is connected again (takes about 4 minutes)
- **UE actions:** tell a simulated phone to disconnect, reconnect, or open a new data session
- **Audit log:** a list of every action anyone did, with time

**Use it to:** test what happens when parts fail, and bring the network back.

### Devices

Add and manage devices that connect to the 5G network. Each device gets:

- Its own 5G subscriber (SIM identity) in the core, with fresh secret keys
- Its own gateway that acts like a 5G modem
- A choice of slice (eMBB, URLLC, mMTC)

**To add a device:**

1. Use the **Connect a device** panel on the left
2. Choose the type: drone, phone, IoT sensor, or custom
3. Choose **Simulated** (made by the testbed) or a **real device** (see [section 8](#8-connecting-real-devices))
4. Pick a slice and click create

The device then moves through a **5-step timeline** (subscriber created, gateway started, registered on 5G, data session up, traffic flowing). Each step turns green when it really happens.

Click a device to open its details: traffic chart, connection test, settings files and QR code for real devices.

**Device live view:** click **Open live view** to get a full page for that device with:

- An animated path from the device through the 5G network to the edge, with the measured speed on each hop
- **Live video** from the device camera
- A **map** with the device position and track (for drones and phones)
- **Telemetry** cards (drone altitude, speed, battery, flight mode ...)
- **MQTT** values and a live message feed (for sensors and phones)

A simulated drone really flies a square route (ArduPilot flight software) and sends its camera and telemetry through its own 5G connection.

### 5G Core

The inside of the 5G core:

- All subscribers stored in the core database
- Live charts for AMF (registrations) and SMF (data sessions)
- Status of each core function

### RAN & RIC

The radio side:

- Each simulated base station (gNB) and its connected phones
- The srsRAN software radio: live per-phone radio numbers (signal quality, data rate)
- The O-RAN RIC (FlexRIC): E2 connection state, xApp status and logs

### Slices

The three network slices (eMBB, URLLC, mMTC):

- Which phones and devices use each slice
- Traffic per slice
- **Isolation check:** tests that one slice cannot reach another

### Logs

Every log line from every component in one place.

- Filter by component, or type a search (LogQL)
- **Live tail** to watch logs as they come in
- **Download** the logs you are looking at

### Cluster

The Kubernetes layer: node CPU, RAM and disk, and the list of all pods with their state and restarts.

### Grafana link

The left menu also has a link to Grafana for deeper charts and log search.

### Test records (API)

Each experiment can be saved as a **test record** with a name, purpose, tester and time window. When you finish a test, you can download **one ZIP with only that test's data**: a readable report, the logs of each component in that time window, Kubernetes events, the actions taken, and a metrics summary. Records are kept for good.

Today this is used through the API page at **http://127.0.0.1:8660/api/docs** (`/api/tests`).

---

## 8. Connecting real devices

Real devices (a drone, your phone, a laptop) can join the testbed through a **phone hotspot or Wi-Fi router** that your PC is also connected to.

```
 Real device ──Wi-Fi──► Hotspot/router ──► Your PC (relay.py) ──► VM gateway ──► 5G network ──► Edge
```

`./6g start` starts a small relay on your PC (`host/relay.py`). It only listens on private addresses, only accepts private senders, and only opens ports that the dashboard asks for. `./6g stop` stops it.

Two connection modes:

| Mode | For | How the device connects |
|---|---|---|
| **UDP relay** | Drones (MAVLink telemetry, video) | Send telemetry to `<your PC IP>:14550+` and video to port `8890+`. The exact ports are shown in the dashboard |
| **VPN** | Phones, laptops, anything with WireGuard | Install the WireGuard app and scan the QR code shown in the dashboard. All the device's traffic then goes through the 5G network |

**Steps:**

1. Connect your PC and the device to the **same** hotspot or router
2. `./6g start`
3. In the dashboard, open **Devices** > **Connect a device**, choose the real device type and mode
4. Follow the steps the dashboard shows (they include your PC's address and the exact ports)
5. Watch the 5-step timeline turn green

The relay log is in `testbed/keys/relay.log` if something does not connect.

---

## 9. Snapshots and reset

A snapshot is a saved copy of the whole VM. It is perfect for security tests: let an attacker break things, then go back to clean in seconds.

```bash
./6g snapshot clean          # save the current state as "clean"
./6g snapshot before-test-3  # any name you like
./6g reset                   # go back to "clean"
./6g reset before-test-3     # go back to a named snapshot
```

To see all snapshots:

```bash
virsh -c qemu:///system snapshot-list sixg-testbed
```

---

## 10. All commands

Run these from the `testbed/` folder on your PC.

| Command | What it does |
|---|---|
| `./6g create` | Build the VM (first time only) |
| `./6g start` | Boot the VM, open the tunnels and the device relay |
| `./6g stop` | Shut everything down cleanly. Frees all CPU and RAM |
| `./6g status` | Show VM state, CPU, RAM and disk use |
| `./6g ssh` | Open a shell inside the VM |
| `./6g ssh "<command>"` | Run one command inside the VM |
| `./6g snapshot NAME` | Save a snapshot |
| `./6g reset [NAME]` | Roll back to a snapshot (default `clean`) |
| `./6g destroy` | Delete the VM and its disk (asks you to type `YES`). The Ubuntu image and SSH key are kept |

Useful commands **inside** the VM:

```bash
kubectl get pods -A                          # all running parts
kubectl -n sixg-core get pods                # just the 5G core
kubectl -n sixg-core logs deploy/core-amf    # logs of one part
kubectl -n sixg-ran rollout restart deploy   # restart all radio parts
```

---

## 11. Troubleshooting

**`./6g create` says "Run first: sudo bash host/00-install-host.sh"**
You skipped step 1. Run it, then try again.

**"Permission denied" with virsh or libvirt**
Your user was just added to the `libvirt` group. Log out and log in again (the `6g` command usually handles this by itself).

**"VM did not come up on SSH"**
Check the VM is really running: `./6g status`. If it shows `shut off`, run `./6g start` again. If your PC is low on RAM, close other programs.

**The dashboard does not open at 127.0.0.1:8660**
After a cold start, Kubernetes needs 1 to 3 minutes. Wait, then run `./6g start` again. It is safe to run it twice: it only rebuilds the tunnels.

**The badge shows "N need attention" right after start**
Normal for about 5 minutes after any restart. If it stays yellow, open **Cluster** to see which pod is not ready, or **Logs** to read its errors.

**Simulated phones do not reconnect after a core restart**
Use **Control Panel > Safe network restart**. It restarts parts in the right order: UPFs, then SMF, then base stations, then phones.

**The RIC shows "E2 disconnected" for a minute**
FlexRIC can restart once when the srsRAN radio reconnects. It recovers by itself within about 1 minute.

**An image build fails in step 6**
Read the log: `cat ~/build-<name>.log`. Most failures are network timeouts. Run the same build command again for only that image, for example `bash ~/vm/04-build-images.sh flexric`.

**Something is badly broken**
`./6g reset` goes back to your clean snapshot.

**I want to start over completely**
`./6g destroy`, then begin again at step 2.

---

## 12. Safety and isolation

The testbed is made for security testing, so it is locked down:

- **Firewall on the VM network card** (`host/sixg-isolate.xml`): the VM can reach the internet, but **not** your PC and **not** any private network (home Wi-Fi, office LAN). IPv6 is blocked.
- `./6g create` **refuses to continue** if this firewall is not attached.
- **No shared folders, no display, no clipboard** between your PC and the VM.
- The dashboard and Grafana are only reachable at `127.0.0.1` on your own PC, through SSH.
- The device relay only opens the ports the dashboard asks for, and only for private addresses.
- **Nothing starts at PC boot.** The VM and its network only run when you type `./6g start`.

Never run real attack tools against networks or devices you do not own or do not have permission to test.

---

## 13. Known limits

Being honest about what this testbed is and is not:

- It is a **5G Standalone network with 6G ideas on top**. A real open-source 6G core does not exist yet.
- **No real radio.** srsRAN and UERANSIM send radio signals as data inside the VM. There is no antenna and no RF hardware.
- **O-RAN is lightweight.** FlexRIC is used instead of the full O-RAN SC platform, which is too heavy for one VM. O-CU / O-DU / O-RU are emulated, not truly split.
- **Single machine.** It is not built for very high speeds or large cluster-scale tests.
- srsRAN shows 0 for downlink rate in some radio counters, even though downlink data works.
- Planned, not yet built: attack scenarios with automatic scoring, attacker containers, intrusion detection, a Tests page in the dashboard (the API already works).
