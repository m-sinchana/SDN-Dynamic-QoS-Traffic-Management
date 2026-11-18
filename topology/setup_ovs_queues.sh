#!/bin/bash
# QoS Traffic Management System - OVS Queue Setup Script
# Configures Linux HTB (Hierarchical Token Bucket) QoS queues on the bottleneck switch port.

PORT_NAME=${1:-"s1-eth4"}
MAX_RATE_BPS=10000000  # 10 Mbps bottleneck

echo "[*] Configuring QoS Queues on Open vSwitch port: $PORT_NAME"

# Clean up existing QoS records
ovs-vsctl --all destroy qos >/dev/null 2>&1
ovs-vsctl --all destroy queue >/dev/null 2>&1

# Apply Hierarchical Token Bucket (HTB) with 3 Priority Queues:
# Queue 0 (Voice): High Priority, 1 Mbps guaranteed, burst up to 10 Mbps
# Queue 1 (Video): Medium Priority, 4 Mbps guaranteed, max 8 Mbps
# Queue 2 (Bulk): Low Priority, 500 kbps min, capped at 5 Mbps normally (and rate-limited during congestion)
ovs-vsctl -- set Port "$PORT_NAME" qos=@newqos -- \
    --id=@newqos create QoS type=linux-htb other-config:max-rate=$MAX_RATE_BPS queues=0=@q0,1=@q1,2=@q2 -- \
    --id=@q0 create Queue other-config:min-rate=1000000 other-config:max-rate=10000000 other-config:priority=1 -- \
    --id=@q1 create Queue other-config:min-rate=4000000 other-config:max-rate=8000000 other-config:priority=2 -- \
    --id=@q2 create Queue other-config:min-rate=500000 other-config:max-rate=5000000 other-config:priority=3

echo "[+] Successfully configured 3 QoS queues on $PORT_NAME:"
echo "    - Queue 0 (Voice): Priority 1, min-rate: 1Mbps, max-rate: 10Mbps"
echo "    - Queue 1 (Video): Priority 2, min-rate: 4Mbps, max-rate: 8Mbps"
echo "    - Queue 2 (Bulk):  Priority 3, min-rate: 0.5Mbps, max-rate: 5Mbps"

echo ""
echo "[*] Verifying QoS configuration with ovs-vsctl:"
ovs-vsctl list qos
ovs-vsctl list queue
