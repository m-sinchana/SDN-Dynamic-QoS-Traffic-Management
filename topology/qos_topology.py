#!/usr/bin/env python3
"""
QoS Traffic Management System - Mininet Bottleneck Topology
Constructs a reproducible network topology with OpenFlow 1.3 switches:
  - Ingress Switch (s1) connects three multi-class traffic generators (h1, h2, h3)
  - Egress Switch (s2) connects the central QoS metric receiver (h4)
  - Deliberately rate-limited bottleneck link (s1 <-> s2) at 10 Mbps using TCLink
  - Configures OVS Linux HTB QoS queues on the bottleneck port
"""

import os
import sys
import time
import subprocess
import argparse

# Graceful import check for Mininet
try:
    from mininet.topo import Topo
    from mininet.net import Mininet
    from mininet.node import RemoteController, OVSSwitch
    from mininet.link import TCLink
    from mininet.cli import CLI
    from mininet.log import setLogLevel, info
    MININET_AVAILABLE = True
except ImportError:
    MININET_AVAILABLE = False
    Topo = object


class QoSTopo(Topo):
    """
    QoS Bottleneck Network Topology:
      [h1 (Voice: 10.0.0.1)] --\
      [h2 (Video: 10.0.0.2)] ---- [s1] ===(10 Mbps Bottleneck)=== [s2] ---- [h4 (Receiver: 10.0.0.4)]
      [h3 (Bulk:  10.0.0.3)] --/
    """
    def build(self):
        # Add Hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        # Add OpenFlow 1.3 Switches
        s1 = self.addSwitch('s1', dpid='0000000000000001', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', dpid='0000000000000002', protocols='OpenFlow13')

        # Add Fast Access Links (100 Mbps, 1ms latency)
        # Port assignments on s1:
        # s1-eth1 -> h1
        # s1-eth2 -> h2
        # s1-eth3 -> h3
        # s1-eth4 -> s2 (Bottleneck link)
        self.addLink(h1, s1, port1=1, port2=1, bw=100, delay='1ms')
        self.addLink(h2, s1, port1=1, port2=2, bw=100, delay='1ms')
        self.addLink(h3, s1, port1=1, port2=3, bw=100, delay='1ms')

        # Add Bottleneck Trunk Link between s1 and s2:
        # 10 Mbps Bandwidth, 10ms Delay, 100 packet queue buffer
        self.addLink(s1, s2, port1=4, port2=1, cls=TCLink,
                     bw=10, delay='10ms', max_queue_size=100)

        # Add Egress Link from s2 to Receiver h4
        # s2-eth2 -> h4
        self.addLink(s2, h4, port1=2, port2=1, bw=100, delay='1ms')


def configure_ovs_queues(bottleneck_interface="s1-eth4"):
    """
    Configures Linux HTB QoS Queues directly on Open vSwitch via ovs-vsctl:
    Queue 0: Voice (High priority, min 1Mbps, max 10Mbps)
    Queue 1: Video (Medium priority, min 4Mbps, max 8Mbps)
    Queue 2: Bulk  (Low priority, min 0.5Mbps, max 5Mbps)
    """
    info(f"*** Configuring OVS QoS queues on {bottleneck_interface}...\n")
    try:
        # Clear existing QoS
        subprocess.run(["ovs-vsctl", "--all", "destroy", "qos"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["ovs-vsctl", "--all", "destroy", "queue"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Create QoS with 3 Queues
        cmd = [
            "ovs-vsctl", "--", "set", "Port", bottleneck_interface, "qos=@newqos", "--",
            "--id=@newqos", "create", "QoS", "type=linux-htb", "other-config:max-rate=10000000", "queues=0=@q0,1=@q1,2=@q2", "--",
            "--id=@q0", "create", "Queue", "other-config:min-rate=1000000", "other-config:max-rate=10000000", "other-config:priority=1", "--",
            "--id=@q1", "create", "Queue", "other-config:min-rate=4000000", "other-config:max-rate=8000000", "other-config:priority=2", "--",
            "--id=@q2", "create", "Queue", "other-config:min-rate=500000", "other-config:max-rate=5000000", "other-config:priority=3"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            info(f"[+] OVS queues successfully configured on {bottleneck_interface}\n")
        else:
            info(f"[-] OVS queue configuration warning: {res.stderr}\n")
    except Exception as e:
        info(f"[-] Failed to execute ovs-vsctl: {e}\n")


def run(controller_ip="127.0.0.1", controller_port=6633, cli_mode=True):
    if not MININET_AVAILABLE:
        print("[-] Mininet is not installed in the current environment.")
        print("    Please run this script inside a Linux VM or container with Mininet & Open vSwitch installed.")
        return

    setLogLevel('info')
    topo = QoSTopo()
    c0 = RemoteController('c0', ip=controller_ip, port=controller_port)

    info('*** Creating network with OpenFlow 1.3 switches\n')
    net = Mininet(
        topo=topo,
        controller=c0,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True
    )

    info('*** Starting network\n')
    net.start()

    # Configure Open vSwitch protocols to OpenFlow 1.3
    for s in ['s1', 's2']:
        os.system(f"ovs-vsctl set bridge {s} protocols=OpenFlow13")

    # Configure hardware/kernel QoS queues on bottleneck port
    configure_ovs_queues("s1-eth4")

    info('*** Testing basic connectivity (pingAll)\n')
    net.pingAll()

    if cli_mode:
        info('*** Starting Mininet CLI\n')
        info('*** Tip: Start receiver on h4: h4 python3 app/receiver.py &\n')
        info('*** Tip: Start senders: h1 python3 app/sender.py --class voice --dst 10.0.0.4 &\n')
        CLI(net)

    info('*** Stopping network\n')
    net.stop()


def main():
    parser = argparse.ArgumentParser(description="Mininet QoS Bottleneck Topology")
    parser.add_argument("--controller", default="127.0.0.1", help="Ryu Controller IP")
    parser.add_argument("--port", type=int, default=6633, help="OpenFlow Port (6633 or 6653)")
    parser.add_argument("--no-cli", action="store_true", help="Run without Mininet CLI")
    args = parser.parse_args()

    run(controller_ip=args.controller, controller_port=args.port, cli_mode=not args.no_cli)


if __name__ == '__main__':
    main()
