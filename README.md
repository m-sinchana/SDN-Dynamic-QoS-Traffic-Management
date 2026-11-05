# SDN Dynamic QoS Traffic Management System (UDP)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![SDN Controller](https://img.shields.io/badge/SDN-Ryu%20OpenFlow%201.3-green.svg)](https://ryu-sdn.org/)
[![Network Emulator](https://img.shields.io/badge/Emulator-Mininet-orange.svg)](http://mininet.org/)
[![Protocol](https://img.shields.io/badge/Sockets-Low--Level%20UDP-red.svg)](https://docs.python.org/3/library/socket.html)
[![Tests](https://img.shields.io/badge/Unit%20Tests-17%20Passed-brightgreen.svg)]()

An academic, small, properly working Quality-of-Service (QoS) networking project built using raw Python UDP sockets, OpenFlow 1.3 with Open vSwitch, Linux Hierarchical Token Bucket (HTB) queues, and a dynamic Ryu SDN controller.

---

## 🎯 The 7 Core Project Requirements & 1 Extra Feature

| # | Academic Requirement | Implementation in this Project |
| :- | :--- | :--- |
| **1** | **Generate multiple classes of UDP traffic** | `app/sender.py` produces **Voice** (64 kbps, 160B, port 5001), **Video** (2.5 Mbps, 1024B, port 5002), and **Bulk** (2.0 Mbps, 1400B, port 5003). |
| **2** | **Classify traffic into application classes** | `controller/qos_controller.py` inspects packets and matches UDP ports & IP DSCP values (Voice DSCP 46 EF, Video DSCP 34 AF41, Bulk DSCP 0 BE). |
| **3** | **Implement SDN-based priority policies** | `controller/qos_controller.py` maps classes to Open vSwitch queues via `OFPActionSetQueue`: Queue 0 = Voice (Strict Priority), Queue 1 = Video (Medium Priority), Queue 2 = Bulk (Normal / Throttled). |
| **4** | **Create network congestion intentionally** | High-load flooder in `app/sender.py` generates combined load (~13.6 Mbps) exceeding the configurable 10 Mbps bottleneck link between switch `s1` and `s2`. |
| **5** | **Measure throughput, latency, and packet loss** | `app/receiver.py` computes actual received throughput (Mbps), one-way latency (ms), packet loss (%), and RFC 3550 interarrival jitter (ms), saving directly into CSV and JSON. |
| **6** | **Analyze fairness using Jain's Fairness Index** | `tests/calculate_fairness.py` computes Jain's Fairness Index $J = \frac{(\sum x_i)^2}{n \sum x_i^2}$ from measured throughput and SLA demand satisfaction. |
| **7** | **Dynamically modify QoS policies upon congestion** | Ryu controller polls OpenFlow 1.3 port statistics; if link utilization $\ge 80\%$, it automatically throttles Bulk traffic (Queue 2) to protect Voice & Video; relaxes when $< 60\%$ with hysteresis. |
| **+1** | **[EXTRA FEATURE] Manual QoS Mode** | Operator can switch between **Automatic Mode** (controller adapts dynamically) and **Manual Mode** (operator explicitly enables or disables the congestion QoS policy) via CLI or interactive terminal menu (`app/class_notifier.py`). |

---

## 📋 Table of Contents
- [Repository Structure](#-repository-structure)
- [Architecture & Design](#-architecture--design)
- [Development Environments: macOS vs Ubuntu VM](#-development-environments-macos-vs-ubuntu-vm)
- [How to Run on macOS (Development & Unit Tests)](#-how-to-run-on-macos-development--unit-tests)
- [How to Run on Ubuntu VirtualBox VM (Real Mininet SDN Experiment)](#-how-to-run-on-ubuntu-virtualbox-vm-real-mininet-sdn-experiment)
- [Manual QoS Mode CLI & Interactive Menu Guide](#-manual-qos-mode-cli--interactive-menu-guide)
- [Performance Results & Jain's Fairness Analysis](#-performance-results--jains-fairness-analysis)
- [Automated Test Suite (17 Tests)](#-automated-test-suite-17-tests)
- [Viva Voce Team Member Roles](#-viva-voce-team-member-roles)

---

## 📂 Repository Structure

```
qos-traffic-management/
├── README.md                 # Complete reproduction guide and documentation
├── requirements.txt          # Python dependencies
├── demo.sh                   # One-click scripted live demonstration
├── config/
│   ├── traffic_config.json   # Traffic class parameters, rates, packet sizes, DSCP
│   └── qos_policy.json       # Bottleneck speed, HTB queue specs, thresholds
├── app/
│   ├── common.py             # Binary packet framing, socket utilities, RFC 3550 jitter
│   ├── sender.py             # Multi-class UDP traffic generator & pacer
│   ├── receiver.py           # Multi-port UDP receiver & metrics calculator
│   └── class_notifier.py     # Application-to-Controller IPC socket client
├── controller/
│   └── qos_controller.py     # Ryu OpenFlow 1.3 controller with dynamic congestion engine
├── topology/
│   ├── qos_topology.py       # Mininet topology script (10 Mbps bottleneck via TCLink)
│   └── setup_ovs_queues.sh   # Linux HTB QoS queue setup on OVS ports
├── tests/
│   ├── test_sockets.py       # Unit tests for socket framing, loss, and jitter algorithms
│   ├── run_experiment.py     # 3-condition automated evaluation runner (Light/Med/Heavy)
│   ├── calculate_fairness.py # Jain's Fairness Index calculator
│   └── plot_results.py       # ASCII & HTML/SVG visualization generator
├── results/                  # Raw CSV experiment data, JSON summary, and dashboard
│   ├── evaluation_dashboard.html
│   ├── metrics_summary.json
│   ├── light_traffic_baseline.csv
│   ├── light_traffic_qos.csv
│   ├── moderate_traffic_baseline.csv
│   ├── moderate_traffic_qos.csv
│   ├── heavy_congestion_baseline.csv
│   └── heavy_congestion_qos.csv
└── docs/
    ├── architecture_diagram.md # In-depth architecture, packet format & state machine
    ├── report.md               # Formal project report covering all 11 assignment to-dos
    └── viva_preparation.md     # Viva defense guide partitioned by team roles
```

---

## 🏗 Architecture & Design

```
+-----------------------------------------------------------------------+
|                         Ryu SDN Controller                            |
|  - OpenFlow 1.3 Learning Switch & Flow Classifier                     |
|  - Real-Time Port Stats Monitoring (1.0 Hz)                           |
|  - Dynamic Congestion State Machine (Threshold: 80%, Relax: 60%)      |
|  - Application IPC Control Socket Server (TCP Port 6634)              |
+-----------------------------------+-----------------------------------+
                                    | OpenFlow 1.3 Control Channel
                                    v
[h1: Voice Sender]  --\      +---------------+                     +---------------+
(10.0.0.1, Port 5001)  +---->| Switch s1     |  10 Mbps Bottleneck | Switch s2     |
                             | (Ingress OVS) |====================>| (Egress OVS)  |----+
[h2: Video Sender]  -------->| Linux HTB Qs: |  Delay: 10ms        |               |    |
(10.0.0.2, Port 5002)  +---->| Q0: Voice     |  Buffer: 100 pkts   +---------------+    |
                             | Q1: Video     |                                          v
[h3: Bulk / Flooder] --/     | Q2: Bulk      |                                   [h4: Receiver]
(10.0.0.3, Port 5003/5004)   +---------------+                                   (10.0.0.4)
```

---

## 💻 Development Environments: macOS vs Ubuntu VM

This project is carefully architected to support dual-environment workflows:

1. **macOS Environment (Code Editing & Unit Testing):**
   - Mininet and Open vSwitch kernel modules are **not** supported natively on macOS.
   - On macOS, you can run all **17 automated unit tests**, socket serialization checks, mathematical Jain's Fairness calculations, and visualization tools without requiring root or virtualization.
2. **Ubuntu VirtualBox VM (Live SDN Network Experiment):**
   - Ubuntu 20.04 or 22.04 LTS runs inside VirtualBox with Mininet, Open vSwitch, and Ryu installed.
   - On Ubuntu, you run the actual SDN topology, physical-style Linux HTB queues, real-time OpenFlow 1.3 switch flow installation, and live multi-process UDP traffic generators.

---

## 🍏 How to Run on macOS (Development & Unit Tests)

On your Mac, you can verify all controller logic, protocol framing, metrics pipelines, and fairness calculations:

### 1. Run Complete Automated Test Suite (17 Tests)
```bash
python3 tests/run_all_tests.py
```
*Expected Output:*
```text
================================================================================
 RUNNING COMPLETE AUTOMATED TEST SUITE (SDN QoS SYSTEM)
================================================================================
...
Ran 17 tests in 0.203s
 [PASS] ALL 17 TESTS PASSED CLEANLY!
================================================================================
```

### 2. Run the Multi-Condition Performance Benchmark
```bash
python3 tests/run_experiment.py
```
*Evaluates Baseline FIFO vs SDN Dynamic QoS under Light (~2 Mbps), Moderate (~8 Mbps), and Heavy Congestion (~13.6 Mbps) conditions.*

### 3. Generate Terminal Visualizations & PNG Charts
```bash
python3 tests/plot_results.py
```
*Prints high-resolution ASCII comparison bar charts in your console and creates PNG charts in `results/`.*

### 4. Calculate Jain's Fairness Index from Experiment Data
```bash
python3 tests/calculate_fairness.py --csv results/heavy_congestion_qos.csv
```

---

## 🐧 How to Run on Ubuntu VirtualBox VM (Real Mininet SDN Experiment)

Follow these exact steps inside your Ubuntu VirtualBox VM for your coursework demonstration:

### Step 1: Start the Ryu SDN Controller
Open **Terminal 1** in the project directory:
```bash
ryu-manager controller/qos_controller.py
```
*Controller initializes with OpenFlow 1.3, listens on port 6633 for switches, and opens IPC socket port 6634.*

### Step 2: Start the Mininet Bottleneck Topology
Open **Terminal 2** (requires `sudo`):
```bash
sudo python3 topology/qos_topology.py
```
*Mininet builds switches `s1` & `s2`, configures Linux HTB Queues (Q0 Voice, Q1 Video, Q2 Bulk) on bottleneck port `s1-eth4` at 10 Mbps, and opens the `mininet>` prompt.*

### Step 3: Start the Multi-Class Receiver on Host h4
Inside the **Mininet CLI (Terminal 2)**:
```bash
mininet> h4 python3 app/receiver.py --bind 0.0.0.0 --ports 5001,5002,5003,5004 --duration 35 --out-csv results/mininet_live.csv &
```
*Receiver concurrently monitors ports 5001 (Voice), 5002 (Video), 5003 (Bulk), and 5004 (Flooder).*

### Step 4: Generate Multi-Class UDP Traffic
Inside the **Mininet CLI (Terminal 2)**:
```bash
mininet> h1 python3 app/sender.py --class voice --dst 10.0.0.4 --duration 30 &
mininet> h2 python3 app/sender.py --class video --dst 10.0.0.4 --duration 30 &
mininet> h3 python3 app/sender.py --class bulk --dst 10.0.0.4 --duration 30 &
```
*Normal traffic flows cleanly through the 10 Mbps bottleneck without loss.*

### Step 5: Intentionally Create Network Congestion
Inside the **Mininet CLI (Terminal 2)**, launch the congestion flooder from `h3`:
```bash
mininet> h3 python3 app/sender.py --class congestion_flooder --dst 10.0.0.4 --duration 12 &
```
*Total traffic surges to ~13.6 Mbps, intentionally exceeding the 10 Mbps bottleneck capacity.*  
*Watch **Terminal 1 (Controller)**: The controller detects port utilization $\ge 80\%$, logs a `CONGESTION_TRIGGERED` audit event, and dynamically throttles Bulk traffic (Queue 2) to protect Voice (Queue 0) and Video (Queue 1).*

### Step 6: Plot Actual Mininet Experiment Results & Fairness
Once traffic completes:
```bash
python3 tests/plot_results.py --csv results/mininet_live.csv
python3 tests/calculate_fairness.py --csv results/mininet_live.csv
```

---

## 🎮 Manual QoS Mode CLI & Interactive Menu Guide

The project includes a simple, dedicated **Manual QoS Mode** that lets the operator switch between automatic dynamic adaptation and manual operator control.

### Option A: Interactive Terminal Menu
Open **Terminal 3** and run:
```bash
python3 app/class_notifier.py --menu
```
*Interactive Menu Output:*
```text
====================================================================
     SDN DYNAMIC QoS TRAFFIC MANAGEMENT - OPERATOR MENU
====================================================================
  Target Controller:     127.0.0.1:6634
  Connection:            CONNECTED
  Adaptation Mode:       AUTO
  Forwarding Mode:       QOS
  Congestion State:      NORMAL
  Bottleneck Load:       4.52 Mbps (45.2%)
--------------------------------------------------------------------
  1. View Detailed Controller Status & Statistics
  2. Switch to Automatic QoS Mode (Dynamic Port Stats Adaptation)
  3. Switch to Manual QoS Mode (Operator Control)
  4. [Manual Mode] ENABLE Congestion Policy (Throttle Bulk -> Protect Voice/Video)
  5. [Manual Mode] DISABLE Congestion Policy (Restore Standard Allocations)
  6. Switch Forwarding Mode (QoS Priority Queues vs Baseline FIFO)
  7. View Recent Policy Audit Events
  8. Reset Statistics Counters
  9. Exit
====================================================================
Enter choice [1-9]:
```

### Option B: Direct Command-Line Flags
You can also send commands directly using CLI flags:
```bash
# Check current controller status:
python3 app/class_notifier.py --status

# Switch to Manual Mode:
python3 app/class_notifier.py --adaptation MANUAL

# Manually enable the Congestion QoS policy (throttle bulk to protect voice/video):
python3 app/class_notifier.py --manual-policy ON

# Manually disable the Congestion QoS policy (restore normal allocations):
python3 app/class_notifier.py --manual-policy OFF

# Switch back to Automatic Mode:
python3 app/class_notifier.py --adaptation AUTO

# Toggle between QoS Priority Mode and Baseline FIFO Forwarding:
python3 app/class_notifier.py --mode FIFO
python3 app/class_notifier.py --mode QOS
```
```
*** Creating network with OpenFlow 1.3 switches
*** Configuring OVS QoS queues on s1-eth4...
[+] OVS queues successfully configured on s1-eth4:
    - Queue 0 (Voice): Priority 1, min-rate: 1Mbps, max-rate: 10Mbps
    - Queue 1 (Video): Priority 2, min-rate: 4Mbps, max-rate: 8Mbps
    - Queue 2 (Bulk):  Priority 3, min-rate: 0.5Mbps, max-rate: 5Mbps
*** Testing basic connectivity (pingAll)
*** Starting Mininet CLI
mininet>
```

### Step 3: Run the Multi-Class Receiver
Inside the Mininet CLI:
```bash
mininet> h4 python3 app/receiver.py --bind 0.0.0.0 --ports 5001,5002,5003,5004 --duration 30 &
```

### Step 4: Launch Traffic Generators (Senders)
Inside the Mininet CLI, start all three traffic classes simultaneously:
```bash
mininet> h1 python3 app/sender.py --class voice --dst 10.0.0.4 --duration 25 &
mininet> h2 python3 app/sender.py --class video --dst 10.0.0.4 --duration 25 &
mininet> h3 python3 app/sender.py --class bulk --dst 10.0.0.4 --duration 25 &
```

### Step 5: Trigger Live Dynamic Congestion
While traffic is flowing cleanly, trigger a heavy UDP flood from `h3` that overwhelms the 10 Mbps link:
```bash
mininet> h3 python3 app/sender.py --class congestion_flooder --dst 10.0.0.4 --duration 10 &
```
Observe the **Controller Console (Terminal 1)**:
```
[QoS-Controller] Bottleneck Port: 13.56 Mbps (135.6% utilization) | State: CONGESTED
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
[QoS-Controller] [CONGESTION DETECTED] Bottleneck link exceeded threshold!
[QoS-Controller] Dynamically adjusting flow table: Throttling Bulk traffic (Queue 2) to protect Voice & Video.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```
Once the flooder stops:
```
***************************************************************************
[QoS-Controller] [CONGESTION CLEARED] Bottleneck link load normalized.
[QoS-Controller] Restoring standard QoS allocations across all flows.
***************************************************************************
```

---

## 📊 Automated Performance Evaluation (3 Conditions)

Run the full evaluation benchmark comparing **SDN Dynamic QoS** against **Baseline FIFO**:
```bash
python3 tests/run_experiment.py
```
This runs:
1. **Light Load (~2.1 Mbps / 21% link capacity):** Uncongested network.
2. **Moderate Load (~8.1 Mbps / 81% link capacity):** Nearing link threshold.
3. **Heavy Congestion (~13.6 Mbps / 136% capacity):** Severe bottleneck overload.

---

## 📈 Results Summary & Comparison

### Heavy Congestion Condition (136% Bottleneck Overload)

| Metric | Baseline FIFO (No QoS) | SDN Dynamic QoS | Improvement / Impact |
| :--- | :--- | :--- | :--- |
| **Voice Packet Loss** | **27.70%** | **0.00%** | **100% loss eliminated** |
| **Voice Avg Latency** | **142.50 ms** | **11.40 ms** | **12.5x faster delivery** |
| **Voice Jitter (RFC 3550)** | **42.80 ms** | **0.82 ms** | **52x jitter reduction** |
| **Video Packet Loss** | 27.60% | 0.80% | High-definition stream preserved |
| **Video Avg Latency** | 148.00 ms | 18.20 ms | Smooth, buffer-free playback |
| **Bulk Data Loss** | 27.80% | 34.00% | Absorbs congestion backpressure |
| **Jain's Fairness Index** | 0.9750 | **1.0000** | **Ideal SLA demand fairness** |

---

## 🖥 Interactive Web Dashboard & Real-Time REST API

Launch the dedicated live dashboard and control server:
```bash
python3 web/server.py 8080
```
Open **`http://127.0.0.1:8080/`** in your browser.

The dashboard features:
1. **Live Network Monitor:** Auto-refreshing gauges for PDR, loss, throughput, latency, jitter, and link utilization.
2. **Interactive Topology Visualization:** SVG rendering of the Mininet network with active flow indicators and congestion pulse warnings.
3. **Simulation Controls:** Light, Moderate, and Heavy traffic presets; live start/stop experiment; force congestion trigger.
4. **Before-and-After Comparison:** Side-by-side FIFO vs QoS tables and 5 interactive dynamic SVG timeseries graphs.
5. **QoS Policy Explainability:** Data-driven causal explanations detailing why congestion occurred, which thresholds were breached, and the measurable latency aftermath.
6. **Experiment History & Export:** Persisted history across reloads with one-click CSV export and report download.
7. **System Health Bar:** Real-time health indicators for Controller, Mininet, OVS, and Sockets.

### REST API Endpoints
- `GET /api/status`: Component health checks (Controller, Mininet, OVS, Receiver, Sender).
- `GET /api/metrics/live`: Real-time packet counts, throughput, loss, latency, jitter, and queue statistics.
- `GET /api/topology`: Node and link metadata with live utilization percentages.
- `GET /api/policy/explain`: Causal explanations of all dynamic policy transitions.
- `GET /api/policy/logs`: Audit log of policy transition events.
- `GET /api/comparison`: Comparative performance metrics across all 3 conditions.
- `GET /api/history`: Persisted experiment history list.
- `POST /api/experiment/start`: Start experiment with preset or custom parameters.
- `POST /api/experiment/stop`: Stop active experiment run.
- `POST /api/experiment/reset`: Reset state counters.
- `POST /api/controller/mode`: Toggle between `QOS` and `FIFO`.
- `POST /api/controller/trigger_congestion`: Manually simulate congestion spike.
- `GET /api/export/csv`: Download active run metrics as CSV.
- `GET /api/export/report`: Download project report.

---

## 🧪 Automated Test Suite (17 Tests)

Run the full automated test suite verifying protocol framing, controller state machine, and analytics:
```bash
python3 tests/run_all_tests.py
```
*Coverage includes:*
- `tests/test_sockets.py`: UDP framing, serialization, corrupt datagram rejection, RFC 3550 jitter calculation, gap detection, packet delivery ratio, duplicate detection, and absent receiver safety.
- `tests/test_controller_logic.py`: Multi-class classification (port & DSCP), congestion threshold detection, dynamic policy transitions, hysteresis and hold-down timer verification, **Manual QoS Mode suppression of auto-triggers**, and **manual operator policy toggling with audit logging**.
- `tests/test_experiment_pipeline.py`: Jain's Fairness Index mathematics, 3-condition dataset integrity, and CSV export formatting.

---

## 🔧 Troubleshooting Guide

| Issue / Error | Likely Cause | Solution |
| :--- | :--- | :--- |
| `Cannot find switch 's1'` | Previous Mininet instance crashed or left dirty state | Run `sudo mn -c` to clean up Mininet processes, links, and temporary files. |
| `Warning: sch_htb: quantum of class 50001 is big` | Standard Linux kernel notice on HTB rate limits | **Harmless.** The Linux kernel automatically tunes token bucket quantum for low-rate queues. |
| `Address already in use (Port 6633/6653/6634)` | An existing controller or IPC instance is running | Kill previous instances: `sudo fuser -k 6633/tcp 6634/tcp 8080/tcp` |
| `Operation not permitted (Socket sendto)` | Running outside root/sudo inside strict sandbox | In Mininet, run topology with `sudo python3 topology/qos_topology.py`. Unit tests handle sandbox restrictions automatically. |

---

## ⚠️ Known Limitations & Assumptions

1. **Clock Synchronization:** Latency calculations measure one-way transit delay using system timestamps (`time.time()`). When running in Mininet, all virtual hosts share the underlying Linux host's monotonic system clock, ensuring sub-millisecond precision without NTP skew. In a real-world multi-host physical deployment, synchronized hardware PTP (IEEE 1588) or round-trip delay (RTT / 2) estimation would be required.
2. **Mininet Environment Requirement:** Kernel-level Open vSwitch queuing (`set_queue`) and network namespaces require a Linux environment (Ubuntu 20.04/22.04 VM, VirtualBox, or native Linux). When running on macOS or environments without Mininet, the system operates in standalone evaluation/simulation mode.

---

## 👥 Viva Voce Team Member Roles

Refer to [docs/viva_preparation.md](docs/viva_preparation.md) for full viva Q&A prep:
- **Member 1 (Application Specialist):** `app/common.py`, `app/sender.py`, `app/receiver.py`. Explains low-level UDP socket programming, RFC 3550 jitter formula, framing, and gap detection.
- **Member 2 (SDN Controller Specialist):** `controller/qos_controller.py`. Explains OpenFlow 1.3 match rules, port statistics polling, dynamic congestion state machine, and IPC socket listener.
- **Member 3 (Topology & Testing Specialist):** `topology/qos_topology.py`, `topology/setup_ovs_queues.sh`, `tests/`. Explains Mininet TCLink bottleneck setup, Linux HTB OVS queue configuration, Jain's Fairness Index, and comparative evaluation results.
