#!/bin/bash
# ==============================================================================
# QoS Traffic Management System - Scripted Live Demonstration
# Demonstrates:
#   1. Clean traffic flow across Voice, Video, and Bulk classes
#   2. Dynamic onset of heavy link congestion (>80% utilization)
#   3. Controller detection via OpenFlow 1.3 Port Statistics
#   4. Dynamic prioritization (Queue 0 for Voice, Queue 1 for Video)
#   5. Automatic policy relaxation when congestion ceases
# ==============================================================================

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "================================================================================"
echo "    SDN-BASED QOS TRAFFIC MANAGEMENT SYSTEM - SCRIPTED DEMONSTRATION"
echo "================================================================================"

# Check if Mininet is available
if command -v mn >/dev/null 2>&1; then
    echo "[*] Mininet environment detected on host."
    echo "[*] Step 1: Cleaning previous Mininet state..."
    sudo mn -c >/dev/null 2>&1 || true

    echo "[*] Step 2: Starting Ryu SDN Controller in background..."
    ryu-manager controller/qos_controller.py > /tmp/ryu_qos.log 2>&1 &
    RYU_PID=$!
    echo "    Ryu started with PID: $RYU_PID"
    sleep 2

    echo "[*] Step 3: Launching Mininet Topology (10 Mbps Bottleneck)..."
    echo "    Senders: h1 (Voice), h2 (Video), h3 (Bulk)"
    echo "    Receiver: h4 (Server)"
    echo "    Switch: s1 (Ingress with OVS HTB Queues), s2 (Egress)"
    
    # Run automated test within Mininet
    sudo python3 - <<EOF
import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from topology.qos_topology import QoSTopo, configure_ovs_queues

topo = QoSTopo()
c0 = RemoteController('c0', ip='127.0.0.1', port=6633)
net = Mininet(topo=topo, controller=c0, switch=OVSSwitch, link=TCLink, autoSetMacs=True, autoStaticArp=True)
net.start()
configure_ovs_queues("s1-eth4")

h1, h2, h3, h4 = net.get('h1', 'h2', 'h3', 'h4')

print("\n[*] Starting Receiver on h4...")
h4.cmd('python3 app/receiver.py --bind 0.0.0.0 --ports 5001,5002,5003,5004 --duration 20 --out-json results/live_demo_metrics.json &')
time.sleep(1)

print("[*] Starting Normal Traffic Flows:")
print("    h1 -> Voice (Port 5001, 64 kbps, DSCP EF)")
h1.cmd('python3 app/sender.py --class voice --dst 10.0.0.4 --duration 18 &')
print("    h2 -> Video (Port 5002, 2.5 Mbps, DSCP AF41)")
h2.cmd('python3 app/sender.py --class video --dst 10.0.0.4 --duration 18 &')
print("    h3 -> Bulk  (Port 5003, 2.0 Mbps, Best Effort)")
h3.cmd('python3 app/sender.py --class bulk --dst 10.0.0.4 --duration 18 &')

print("\n[*] Running clean traffic for 5 seconds...")
time.sleep(5)

print("\n[!] >>> TRIGGERING LIVE HEAVY CONGESTION (Flooder on h3: 10 Mbps UDP burst) <<<")
h3.cmd('python3 app/sender.py --class congestion_flooder --dst 10.0.0.4 --duration 8 &')

print("[*] Waiting for traffic transmission to complete and controller to react...")
time.sleep(14)

net.stop()
EOF

    echo "[*] Stopping Ryu Controller..."
    kill -9 $RYU_PID >/dev/null 2>&1 || true

else
    echo "[!] Mininet not present in local environment (running in standalone simulation/evaluation mode)."
    echo ""
    echo "[*] Step 1: Running Complete Automated Test Suite (17 Tests)..."
    python3 tests/run_all_tests.py

    echo ""
    echo "[*] Step 2: Running 3-Condition Performance Study (Light, Moderate, Heavy)..."
    python3 tests/run_experiment.py

    echo ""
    echo "[*] Step 3: Generating Visual Charts and Dashboard..."
    python3 tests/plot_results.py

    echo ""
    echo "[*] Step 4: Calculating Jain's Fairness Index for Heavy Congestion..."
    python3 tests/calculate_fairness.py --csv results/heavy_congestion_qos.csv
fi

echo ""
echo "================================================================================"
echo "    DEMONSTRATION COMPLETED SUCCESSFULLY!"
echo "    - Results stored in: results/"
echo "    - Static Dashboard: results/evaluation_dashboard.html"
echo "    - Interactive Web Server: Start with 'python3 web/server.py 8080'"
echo "    - Full Report: docs/report.md"
echo "================================================================================"
