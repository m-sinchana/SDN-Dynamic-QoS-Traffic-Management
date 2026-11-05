# Viva Voce & Technical Defense Guide: SDN Dynamic QoS System
**Team 10: Coursework Project Defense & Viva Preparation**

This document prepares every team member for the project viva examination, covering foundational SDN architecture, socket programming principles, mathematical definitions, and role-specific technical questions.

---

## Part 1: Core Conceptual Topics (Mandatory for All Members)

### 1. Why is UDP used instead of TCP?
- **Real-Time Multimedia Requirements:** Voice over IP (VoIP) and live video streaming are delay-sensitive, jitter-sensitive, and loss-tolerant up to small thresholds.
- **TCP Head-of-Line Blocking & ARQ:** TCP guarantees delivery via acknowledgments and retransmissions. If a packet is dropped during congestion, TCP holds back subsequent packets in the receive buffer, creating latency spikes and jitter that make live audio/video stutter.
- **Congestion Backoff:** TCP's AIMD algorithm halves the congestion window upon packet loss, causing throughput to collapse. Real-time media encoders produce packets at fixed intervals (e.g. 20ms audio frames) regardless of network state.
- **Low-Level Socket Control:** Standard UDP sockets (`socket.SOCK_DGRAM`) allow precise packet pacing, custom framing, zero protocol overhead, and direct manipulation of the IP Type of Service (TOS) / DSCP byte.

### 2. Why does ordinary FIFO forwarding struggle under congestion?
- **Tail-Drop & Buffer Bloat:** Standard FIFO (First-In, First-Out) switches maintain a single packet queue. During network saturation, large bulk packets (1400 bytes) fill up the switch buffer, causing "buffer bloat".
- **Starvation of Small Packets:** A small 160-byte voice packet arriving at a full FIFO queue is either dropped at the tail or forced to wait behind dozens of large bulk packets, inflating transit delay from 10ms to >140ms and jitter to >40ms.
- **Lack of Flow Awareness:** FIFO treats a critical voice packet identically to background file download packets, degrading all flows equally regardless of application SLA.

### 3. How does SDN separate the Control Plane and Data Plane?
- **Data Plane (Forwarding Plane):** Resides in the Open vSwitch (OVS) switches in the kernel or hardware. It performs line-rate packet parsing, flow table matching, and action execution (`set_queue`, `output`, `drop`) without inspecting higher-level application logic.
- **Control Plane:** Resides in the centralized Ryu SDN Controller. It executes the routing logic, monitors global link statistics, detects congestion, and pushes flow table modifications (`OFPFlowMod`) to switches via OpenFlow 1.3 protocol over TCP port 6633.
- **Programmability:** Control decisions (e.g., dynamically rate-limiting bulk traffic when port utilization exceeds 80%) are decoupled from switch hardware, enabling intelligent, runtime network adaptation.

### 4. How does traffic classification work?
The system uses a multi-tier classification hierarchy:
1. **L4 UDP Destination Port:**
   - Port `5001` $\to$ Voice (VoIP)
   - Port `5002` $\to$ Video Streaming
   - Port `5003` $\to$ Bulk Data
   - Port `5004` $\to$ Stress Flooder
2. **L3 IP DSCP / TOS Byte:**
   - DSCP `46` (0x2E, TOS `0xb8`) $\to$ Expedited Forwarding (EF) / Voice
   - DSCP `34` (0x22, TOS `0x88`) $\to$ Assured Forwarding (AF41) / Video
   - DSCP `0`  (0x00, TOS `0x00`) $\to$ Best Effort (BE) / Bulk
3. **Application Announcements (IPC Socket):** Applications can dynamically notify the controller via TCP port `6634` using JSON commands (`ANNOUNCE_CLASS`).

### 5. How are OpenFlow rules and Open vSwitch (OVS) queues applied?
- **Linux Kernel HTB Queues:** Open vSwitch leverages Linux Hierarchical Token Bucket (HTB) traffic control on the bottleneck interface (`s1-eth4`):
  - `Queue 0`: Min-rate 1 Mbps, Max-rate 10 Mbps, Priority 1 (Voice)
  - `Queue 1`: Min-rate 4 Mbps, Max-rate 8 Mbps, Priority 2 (Video)
  - `Queue 2`: Min-rate 0.5 Mbps, Max-rate 5 Mbps, Priority 3 (Bulk)
- **OpenFlow Action:** When a packet matches an installed flow entry, the OpenFlow action `OFPActionSetQueue(queue_id)` attaches the queue metadata to the packet buffer before executing `OFPActionOutput(out_port)`. The kernel then schedules the packet according to that queue's priority.

### 6. How is congestion detected dynamically?
- The Ryu controller runs an asynchronous monitoring loop that queries `OFPPortStatsRequest` every 1.0 second for the bottleneck interface.
- On `OFPPortStatsReply`, the controller computes transmission throughput:
  $$\text{Throughput (bps)} = \frac{\Delta \text{tx\_bytes} \times 8}{\Delta t}$$
  $$\text{Utilization (\%)} = \left(\frac{\text{Throughput}}{10{,}000{,}000}\right) \times 100$$
- **Congestion Trigger:** If utilization $\ge 80.0\%$ for 2 consecutive samples, the state machine transitions to `CONGESTED`, throttling Queue 2.
- **Hysteresis & Hold-Down Timer:** The system only returns to `NORMAL` when utilization drops $< 60.0\%$ for 4 consecutive samples, eliminating oscillation and route-flapping.

### 7. How are metrics mathematically calculated?
- **Packet Loss Percentage:**
  $$N_{expected} = (S_{max} - S_{first}) + 1, \quad \text{Loss \%} = \left(\frac{N_{expected} - N_{received}}{N_{expected}}\right) \times 100$$
- **Packet Delivery Ratio (PDR):**
  $$\text{PDR} = \frac{N_{received}}{N_{expected}}$$
- **One-Way Latency:**
  $$\text{Latency} = (T_{receive} - T_{send}) \times 1000 \quad \text{(ms)}$$
  *(Note: Senders and receiver run on the same VM/kernel in Mininet, guaranteeing synchronized monotonic system clocks).*
- **RFC 3550 Interarrival Jitter:**
  $$D(i, j) = (R_j - S_j) - (R_i - S_i), \quad J_i = J_{i-1} + \frac{|D(i, j)| - J_{i-1}}{16}$$
- **Jain's Fairness Index:**
  For demand satisfaction ratios $x_i = \frac{T_{achieved, i}}{T_{target, i}}$:
  $$J(x_1, \dots, x_n) = \frac{\left(\sum x_i\right)^2}{n \sum x_i^2}$$

### 8. What is the Manual QoS Mode and how does it work?
- **Two Operating Modes:**
  1. **Automatic Mode (`AUTO`):** The Ryu controller continuously monitors link utilization via OpenFlow port statistics and automatically triggers congestion QoS policies when utilization $\ge 80\%$ and relaxes when $< 60\%$.
  2. **Manual Mode (`MANUAL`):** Automatic threshold-based policy transitions are paused. The operator has full deterministic control to manually toggle the congestion QoS policy ON (throttling Bulk traffic on Queue 2 to protect Voice and Video) or OFF (restoring standard allocations).
- **Control Interface:** Managed directly via `app/class_notifier.py` using command-line arguments (e.g. `--adaptation MANUAL`, `--manual-policy ON`) or the interactive CLI terminal menu (`python3 app/class_notifier.py --menu`).
- **Audit Logging:** Every mode change and manual policy override is recorded in `results/policy_events.json` with timestamp, operator reason, metric values, and queue assignments.

### 9. How are experimental results collected and validated?
- **Multi-Condition Testing:** Evaluated under 3 repeatable conditions:
  1. *Light Load (~21% capacity)*
  2. *Moderate Load (~81% capacity)*
  3. *Heavy Congestion (~136% overload)*
- **Baseline Comparison:** The exact same traffic pattern is run under Baseline FIFO (`mode=FIFO`, no priority queues) and SDN Dynamic QoS (`mode=QOS`).
- **Data Persistence:** Receiver writes raw measurements to CSV (`results/*_baseline.csv` and `results/*_qos.csv`), summary metrics to JSON, and the interactive web server persists experiment runs into `results/experiment_history.json`.

---

## Part 2: Role-Specific Viva Questions

### Member 1: Application Specialist (Sockets & Protocol Design)
**Key Files Owned:** `app/common.py`, `app/sender.py`, `app/receiver.py`, `app/class_notifier.py`

#### Q: Explain your binary packet structure and byte-level serialization.
> **Answer:** "We use Python's standard `struct` module with format `!2sBBIdH` (18 bytes fixed header):
> - `!`: Network Big-Endian byte order.
> - `2s`: 2-byte magic identifier `b'QS'` to reject non-system or malformed datagrams.
> - `B`: 1-byte Protocol Version (`1`).
> - `B`: 1-byte Traffic Class ID (1=Voice, 2=Video, 3=Bulk, 4=Flooder).
> - `I`: 4-byte unsigned integer sequence number for loss and out-of-order tracking.
> - `d`: 8-byte double-precision IEEE 754 timestamp (`time.time()`).
> - `H`: 2-byte unsigned short payload length."

#### Q: How does the sender pace packets smoothly?
> **Answer:** "In `app/sender.py`, we calculate the required inter-packet delay:
> $$\Delta t = \frac{\text{packet\_size\_bytes} \times 8}{\text{target\_rate\_bps}}$$
> We pace packets using `time.perf_counter()`. If the schedule falls behind due to OS scheduling, we reset the timestamp to prevent an artificial burst storm."

#### Q: How do you handle missing receivers or corrupted packets?
> **Answer:** "UDP is connectionless; an absent receiver triggers ICMP port unreachable which we catch via `OSError` without crashing. On the receiver side, incoming datagrams are checked for minimum size (18 bytes) and magic header matching. Corrupt datagrams increment the `corrupt_packets` counter and are safely discarded."

---

### Member 2: SDN Controller Specialist (OpenFlow & Policy Adaptation)
**Key Files Owned:** `controller/qos_controller.py`, `config/qos_policy.json`

#### Q: Which controller framework and OpenFlow version did you use?
> **Answer:** "We chose Ryu with OpenFlow 1.3 (`ofproto_v1_3`). OpenFlow 1.3 is essential because it introduced standardized support for multiple flow tables, per-flow meters, and explicit queue actions (`OFPActionSetQueue`), which POX or OpenFlow 1.0 lack."

#### Q: How does the controller install flow rules dynamically?
> **Answer:** "When an initial packet arrives via `EventOFPPacketIn`, the controller inspects IP and UDP headers. It creates an `OFPMatch` on UDP destination port and IP DSCP, binds the flow to the designated OVS queue using `OFPActionSetQueue`, and issues an `OFPFlowMod` to the switch with an `idle_timeout` of 15 seconds."

#### Q: Walk through the dynamic policy change during congestion.
> **Answer:** "Every 1 second, the controller polls port statistics on port 4 of switch `s1`. If utilization exceeds 80% for 2 consecutive samples, the controller transitions to `CONGESTED`. It emits an explainable policy log entry, flushes existing low-priority flow rules via `OFPFC_DELETE`, and modifies the bulk flow rules to clamp Queue 2. Once utilization drops below 60% for 4 seconds, the hold-down timer expires and restores standard rules."

#### Q: How does your controller support Manual QoS Mode alongside Automatic Mode?
> **Answer:** "In `controller/qos_controller.py`, we implemented `self.adaptation_mode` (`'AUTO'` or `'MANUAL'`). In Automatic mode, the port statistics monitoring loop dynamically triggers the congestion policy when link utilization exceeds 80%. In Manual mode, automatic threshold adaptation is paused, and the operator manually commands the controller over the IPC socket (port 6634) using `python3 app/class_notifier.py --menu` or `--manual-policy ON/OFF`. The controller logs each transition with an explainable audit record in `results/policy_events.json`."

---

### Member 3: Topology & Testing Specialist (Mininet, Queues & Evaluation)
**Key Files Owned:** `topology/qos_topology.py`, `topology/setup_ovs_queues.sh`, `tests/`, `web/`

#### Q: Describe the Mininet bottleneck topology.
> **Answer:** "We implemented a two-switch bottleneck topology using Mininet's `TCLink`:
> - Senders `h1`, `h2`, `h3` connect to switch `s1` over 100 Mbps links with 1ms delay.
> - Egress switch `s2` connects to receiver `h4` over 100 Mbps.
> - The trunk link `s1-s2` is constrained to **10 Mbps bandwidth, 10ms delay, and a 100-packet buffer**. Total sender load can reach 13.6 Mbps, producing controlled, measurable queue buildup."

#### Q: How are OVS queues configured in the Linux kernel?
> **Answer:** "In `topology/setup_ovs_queues.sh`, we execute `ovs-vsctl` commands creating an `HTB` QoS record on port `s1-eth4`. We create 3 queues: Queue 0 (min 1M, priority 1), Queue 1 (min 4M, priority 2), and Queue 2 (min 0.5M, max 5M, priority 3). This enables kernel-level packet scheduling upon OpenFlow `set_queue` actions."

#### Q: Summarize the quantitative results under heavy congestion.
> **Answer:** "Under 136% bottleneck overload:
> - **Voice Packet Loss:** Reduced from **27.7% in FIFO** down to **0.0% in SDN QoS**.
> - **Voice Latency:** Dropped from **142.5 ms** down to **11.4 ms** (12.5x improvement).
> - **Voice Jitter:** Dropped from **42.8 ms** down to **0.82 ms** (52x improvement).
> - **Jain's Fairness Index:** Reached an ideal **1.0000** for SLA demand satisfaction."
