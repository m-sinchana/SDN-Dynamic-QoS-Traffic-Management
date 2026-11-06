# ⚡ SDN Dynamic QoS Traffic Management System

**An adaptive network traffic management system using Software-Defined Networking (SDN) and UDP.**

## 1. Project Overview

Network congestion can significantly affect applications that require low latency and reliable packet delivery, such as voice and video communication.

This project addresses this challenge through an SDN-based Dynamic Quality of Service (QoS) management system. It uses a centralized Ryu controller to classify UDP traffic, enforce priority-based queue management, and dynamically respond to changing network conditions.

The system evaluates how intelligent traffic prioritization affects network performance under different traffic loads.

## 2. How the System Works

The system follows a traffic-to-policy workflow:

1. **Traffic Generation:** Generates three UDP traffic classes: Voice, Video and Bulk.
2. **Packet Classification:** Identifies traffic using UDP port numbers and DSCP markings.
3. **Priority Assignment:** Maps classified traffic to dedicated Open vSwitch queues.
4. **Congestion Monitoring:** Collects switch port statistics through OpenFlow 1.3.
5. **Dynamic Adaptation:** Adjusts Bulk traffic when network utilization reaches the congestion threshold.
6. **Performance Evaluation:** Measures network metrics to evaluate the effectiveness of QoS policies.

## 3. Traffic Management Strategy

Different traffic classes have different network requirements.

| Traffic | UDP Port | DSCP | QoS Queue |
|---|---:|---|---|
| Voice | 5001 | 46 (EF) | Queue 0 |
| Video | 5002 | 34 (AF41) | Queue 1 |
| Bulk | 5003 | 0 (BE) | Queue 2 |

The queue configuration provides:

- **Voice:** Strict priority.
- **Video:** Medium priority.
- **Bulk:** Normal priority with throttling during congestion.

## 4. Adaptive Congestion Control

The central feature of this project is its dynamic congestion management mechanism.

The Ryu controller monitors bottleneck link utilization and changes the QoS policy based on predefined thresholds.

| Network Condition | Controller Action |
|---|---|
| Utilization reaches 80% | Activates congestion policy |
| Utilization falls below 60% | Relaxes congestion policy |

During congestion, Bulk traffic is throttled to help preserve network resources for latency-sensitive Voice and Video traffic.

Hysteresis is used to avoid unnecessary repeated policy changes.

## 5. Measuring Network Performance

The system evaluates network behaviour using the following metrics:

- **Throughput:** Amount of data successfully received per second.
- **Latency:** Time taken for packets to travel from sender to receiver.
- **Packet Loss:** Percentage of packets that fail to reach the receiver.
- **Jitter:** Variation in packet inter-arrival timing, calculated using RFC 3550.
- **Fairness:** Jain's Fairness Index to evaluate bandwidth distribution.

Measurements are collected and stored in CSV and JSON formats for further analysis.

## 6. Experimental Evaluation

The system supports three traffic load conditions:

- Light Load
- Moderate Load
- Heavy Congestion

Baseline FIFO and QoS-enabled traffic management are compared to understand the impact of priority-based scheduling.

The evaluation focuses on protecting critical traffic while managing bandwidth competition during congestion.

## 7. Monitoring and Visualization

An interactive web dashboard provides a centralized view of system operation.

**Dashboard capabilities:**

- Live network performance metrics.
- Network topology visualization.
- Congestion status and QoS policy transitions.
- FIFO versus QoS performance comparison.
- Experiment history.
- CSV and report export.
- Network component health monitoring.

A REST API provides access to network status, topology, metrics, policy information and experiment controls.

## 8. Manual and Automatic Operation

The system supports two operating modes:

- **Automatic Mode:** The controller dynamically adapts QoS policies based on network utilization.
- **Manual Mode:** An operator can control congestion policy activation through the command-line interface.

This supports both automated traffic management and operator-controlled experiments.

## 9. Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Network Protocol | UDP |
| SDN Controller | Ryu |
| Communication Standard | OpenFlow 1.3 |
| Network Emulator | Mininet |
| Virtual Switch | Open vSwitch |
| Queue Management | Linux HTB |
| Visualization | HTML, CSS, JavaScript |

## 10. Testing and Validation

The project includes automated tests covering:

- UDP socket communication and packet handling.
- Packet serialization and jitter calculation.
- Traffic classification.
- Congestion detection and policy transitions.
- Manual QoS operation.
- Fairness calculations.
- Experiment pipeline and data integrity.

Run the automated test suite:

```bash
python3 tests/run_all_tests.py
```

## 11. Project Structure

```text
SDN-Dynamic-QoS-Traffic-Management/
│
├── app/
│   ├── sender.py
│   ├── receiver.py
│   ├── common.py
│   └── class_notifier.py
│
├── controller/
│   └── qos_controller.py
│
├── config/
│   ├── traffic_config.json
│   └── qos_policy.json
│
├── topology/
│   ├── qos_topology.py
│   └── setup_ovs_queues.sh
│
├── tests/
│   ├── test_sockets.py
│   ├── test_controller_logic.py
│   ├── test_experiment_pipeline.py
│   ├── run_experiment.py
│   ├── calculate_fairness.py
│   └── plot_results.py
│
├── results/
│
├── web/
│   └── server.py
│
└── docs/
    ├── architecture_diagram.md
    ├── report.md
    └── viva_preparation.md
```

## 12. Execution Environment

The live SDN implementation requires a compatible Linux environment with:

- Python 3.8+
- Ryu SDN Controller
- Mininet
- Open vSwitch

Ubuntu 20.04/22.04 or a compatible Linux distribution is recommended.

**Note:** Mininet and kernel-level Open vSwitch queue management require a compatible Linux environment. Some analysis and testing utilities can also run independently of the live network topology.

---

## Project Goal

To build an adaptive SDN-based QoS system that intelligently manages competing UDP traffic, responds to network congestion and improves the delivery of critical network applications.