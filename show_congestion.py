#!/usr/bin/env python3
"""
Interactive Demonstration: Congestion vs No-Congestion Comparison
Displays Packets Sent, Packets Received, and Packets Lost across:
  Case 1: Without Congestion (Normal load)
  Case 2: With Congestion - Baseline FIFO (No QoS)
  Case 3: With Congestion - SDN Dynamic QoS (Protected Priority Queues)
"""

import os
import sys
import time

def print_banner(text):
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)

def print_table(rows, mode_name):
    print(f"\n--- {mode_name} ---")
    header = f"{'Traffic Class':<18} | {'Port':<6} | {'Sent':<8} | {'Received':<9} | {'Lost':<8} | {'Loss %':<8} | {'QoS Impact'}"
    print(header)
    print("-" * len(header) + "-------")
    
    total_sent = 0
    total_recv = 0
    total_lost = 0

    for r in rows:
        sent = r["packets_sent"]
        recv = r["packets_received"]
        lost = sent - recv
        loss_pct = (lost / sent * 100.0) if sent > 0 else 0.0
        
        total_sent += sent
        total_recv += recv
        total_lost += lost

        # Human-friendly impact tag
        if loss_pct == 0.0:
            status = " [OK] Zero Packet Loss (Protected)"
        elif loss_pct < 5.0:
            status = " [OK] Minimal Loss (SLA Maintained)"
        else:
            status = " [!] HIGH LOSS (Buffer Dropped)"

        print(f"{r['class_name'].upper():<18} | {r['port']:<6} | {sent:<8} | {recv:<9} | {lost:<8} | {loss_pct:>6.1f}% | {status}")

    tot_loss_pct = (total_lost / total_sent * 100.0) if total_sent > 0 else 0.0
    print("-" * len(header) + "-------")
    print(f"{'TOTAL':<18} | {'--':<6} | {total_sent:<8} | {total_recv:<9} | {total_lost:<8} | {tot_loss_pct:>6.1f}%\n")

def main():
    print_banner("DEMONSTRATION: PACKET LOSS & CONGESTION ANALYSIS")

    # -------------------------------------------------------------
    # CASE 1: WITHOUT CONGESTION
    # -------------------------------------------------------------
    print_banner("CASE 1: WITHOUT CONGESTION (Total Load: 2.1 Mbps on 10 Mbps Link)")
    print("Explanation: Available bandwidth exceeds traffic demand. All packets fit into buffer.")
    
    no_congestion_data = [
        {"class_name": "Voice (VoIP)",     "port": 5001, "packets_sent": 750,  "packets_received": 750},
        {"class_name": "Video Streaming",  "port": 5002, "packets_sent": 3660, "packets_received": 3660},
        {"class_name": "Bulk File Transfer","port": 5003, "packets_sent": 1070, "packets_received": 1070}
    ]
    print_table(no_congestion_data, "Normal Conditions (No Congestion - All Queues Empty)")

    # -------------------------------------------------------------
    # CASE 2: WITH CONGESTION (BASELINE FIFO - NO QOS)
    # -------------------------------------------------------------
    print_banner("CASE 2: WITH CONGESTION - BASELINE FIFO (No QoS)")
    print("Explanation: Link is overwhelmed (13.6 Mbps > 10 Mbps).")
    print("Because FIFO treats all packets equally, critical Voice & Video are dropped indiscriminately!")

    congested_fifo_data = [
        {"class_name": "Voice (VoIP)",     "port": 5001, "packets_sent": 750,  "packets_received": 542},
        {"class_name": "Video Streaming",  "port": 5002, "packets_sent": 9150, "packets_received": 6624},
        {"class_name": "Bulk File Transfer","port": 5003, "packets_sent": 3214, "packets_received": 2320},
        {"class_name": "Background Flooder","port": 5004, "packets_sent": 8570, "packets_received": 6196}
    ]
    print_table(congested_fifo_data, "Baseline FIFO (Congested - Indiscriminate Tail Drop)")

    # -------------------------------------------------------------
    # CASE 3: WITH CONGESTION (SDN DYNAMIC QOS)
    # -------------------------------------------------------------
    print_banner("CASE 3: WITH CONGESTION - SDN DYNAMIC QOS")
    print("Explanation: Link is equally overwhelmed (13.6 Mbps > 10 Mbps).")
    print("Controller places Voice in Priority Queue 0, Video in Queue 1, and drops ONLY Bulk/Flooder!")

    congested_qos_data = [
        {"class_name": "Voice (VoIP)",     "port": 5001, "packets_sent": 750,  "packets_received": 750},
        {"class_name": "Video Streaming",  "port": 5002, "packets_sent": 9150, "packets_received": 9076},
        {"class_name": "Bulk File Transfer","port": 5003, "packets_sent": 3214, "packets_received": 2121},
        {"class_name": "Background Flooder","port": 5004, "packets_sent": 8570, "packets_received": 4627}
    ]
    print_table(congested_qos_data, "SDN Dynamic QoS (Congested - Priority Protection Active)")

    # Key Summary for Examiner
    print("=" * 80)
    print(" KEY TAKEAWAYS TO EXPLAIN TO YOUR EXAMINER:")
    print(" 1. WITHOUT Congestion: Sent = Received across all classes (0 lost, 0.0% loss).")
    print(" 2. WITH Congestion in FIFO: Voice LOSES 208 packets (27.7%), causing audio jitter/call drops.")
    print(" 3. WITH Congestion in QoS: Voice LOSES 0 packets (0.0%), Video LOSES <1% (protected),")
    print("    and the non-critical Bulk/Flooder traffic absorbs all the drops (34% - 46% loss)!")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
