#!/usr/bin/env python3
"""
QoS Traffic Management System - Application-to-Controller IPC Notifier & CLI Menu
Enables low-level socket communication between end-host applications/operator and
the Ryu SDN controller (port 6634) to:
  1. Inspect controller state and real-time link utilization
  2. Switch between Automatic QoS Mode and Manual QoS Mode
  3. Manually toggle Congestion QoS Policy (prioritize Voice/Video, throttle Bulk)
  4. Switch forwarding mode between SDN Priority Queues and Baseline FIFO
  5. Audit policy change events
"""

import socket
import json
import sys
import time
import argparse


def send_ipc_command(host: str, port: int, command_data: dict) -> dict:
    """
    Connects to the Ryu SDN controller IPC socket, sends command JSON,
    and returns parsed JSON response.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        sock.connect((host, port))
        msg = json.dumps(command_data) + "\n"
        sock.sendall(msg.encode('utf-8'))
        
        resp_data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp_data += chunk
            if b"\n" in chunk:
                break

        sock.close()
        return json.loads(resp_data.decode('utf-8').strip())
    except Exception as e:
        return {"status": "error", "message": f"Failed to connect to controller at {host}:{port}: {e}"}


def format_status(status: dict) -> str:
    """Formats controller status dictionary into a clean terminal report."""
    if status.get("status") == "error":
        return f"\n[-] Error querying controller: {status.get('message')}\n"

    lines = [
        "\n" + "=" * 65,
        "          SDN CONTROLLER RUNTIME STATUS & METRICS",
        "=" * 65,
        f"  Adaptation Mode:       {status.get('adaptation_mode', 'UNKNOWN')} " + 
        (" (Dynamic port-stats threshold triggering)" if status.get('adaptation_mode') == 'AUTO' else " (Operator manual control)"),
        f"  Forwarding Mode:       {status.get('mode', 'UNKNOWN')} " + 
        (" (Priority Queues: Q0 Voice, Q1 Video, Q2 Bulk)" if status.get('mode') == 'QOS' else " (Plain FIFO)"),
        f"  Congestion State:      {'CONGESTED (Throttling Bulk)' if status.get('is_congested') else 'NORMAL (Standard allocations)'}",
        f"  Bottleneck Link Load:  {status.get('current_load_mbps', 0.0):.2f} Mbps",
        f"  Link Utilization:      {status.get('current_utilization_pct', 0.0):.1f}%",
        f"  Congestion Threshold:  {status.get('congestion_threshold_pct', 80.0):.1f}% (Relax at {status.get('relax_threshold_pct', 60.0):.1f}%)",
        f"  Connected Switches:    {status.get('datapaths', [])}",
        f"  Active Flow Rules:     {len(status.get('active_flows', []))}",
        f"  Logged Policy Events:  {status.get('policy_event_count', 0)}",
        "=" * 65 + "\n"
    ]
    return "\n".join(lines)


def run_interactive_menu(host: str, port: int):
    """
    Academic-friendly interactive terminal menu for demonstration and viva defense.
    """
    while True:
        # Fetch current status for header
        status = send_ipc_command(host, port, {"type": "GET_STATUS"})
        is_conn = status.get("status") != "error"

        adapt_mode = status.get("adaptation_mode", "N/A") if is_conn else "DISCONNECTED"
        fwd_mode = status.get("mode", "N/A") if is_conn else "DISCONNECTED"
        is_cong = status.get("is_congested", False) if is_conn else False
        util = status.get("current_utilization_pct", 0.0) if is_conn else 0.0

        print("\n" + "=" * 68)
        print("     SDN DYNAMIC QoS TRAFFIC MANAGEMENT - OPERATOR MENU")
        print("=" * 68)
        print(f"  Target Controller:     {host}:{port}")
        print(f"  Connection:            {'CONNECTED' if is_conn else 'DISCONNECTED (Start Ryu controller)'}")
        if is_conn:
            print(f"  Adaptation Mode:       {adapt_mode}")
            print(f"  Forwarding Mode:       {fwd_mode}")
            print(f"  Congestion State:      {'CONGESTED' if is_cong else 'NORMAL'}")
            print(f"  Bottleneck Load:       {status.get('current_load_mbps', 0.0):.2f} Mbps ({util:.1f}%)")
        print("-" * 68)
        print("  1. View Detailed Controller Status & Statistics")
        print("  2. Switch to Automatic QoS Mode (Dynamic Port Stats Adaptation)")
        print("  3. Switch to Manual QoS Mode (Operator Control)")
        print("  4. [Manual Mode] ENABLE Congestion Policy (Throttle Bulk -> Protect Voice/Video)")
        print("  5. [Manual Mode] DISABLE Congestion Policy (Restore Standard Allocations)")
        print("  6. Switch Forwarding Mode (QoS Priority Queues vs Baseline FIFO)")
        print("  7. View Recent Policy Audit Events")
        print("  8. Reset Statistics Counters")
        print("  9. Exit")
        print("=" * 68)

        choice = input("Enter choice [1-9]: ").strip()

        if choice == "1":
            print(format_status(status))

        elif choice == "2":
            resp = send_ipc_command(host, port, {"type": "SET_ADAPTATION_MODE", "mode": "AUTO"})
            if resp.get("status") == "ok":
                print("\n[+] Successfully switched to AUTOMATIC Dynamic Adaptation Mode.")
            else:
                print(f"\n[-] Error: {resp.get('message')}")

        elif choice == "3":
            resp = send_ipc_command(host, port, {"type": "SET_ADAPTATION_MODE", "mode": "MANUAL"})
            if resp.get("status") == "ok":
                print("\n[+] Successfully switched to MANUAL Operator Mode.")
            else:
                print(f"\n[-] Error: {resp.get('message')}")

        elif choice == "4":
            resp = send_ipc_command(host, port, {"type": "SET_MANUAL_QOS", "active": True})
            if resp.get("status") == "ok":
                print("\n[+] Congestion QoS Policy ENABLED manually (Bulk throttled to protect Voice & Video).")
            else:
                print(f"\n[-] Error: {resp.get('message')}")

        elif choice == "5":
            resp = send_ipc_command(host, port, {"type": "SET_MANUAL_QOS", "active": False})
            if resp.get("status") == "ok":
                print("\n[+] Congestion QoS Policy DISABLED manually (Standard allocations restored).")
            else:
                print(f"\n[-] Error: {resp.get('message')}")

        elif choice == "6":
            curr_mode = status.get("mode", "QOS")
            new_mode = "FIFO" if curr_mode == "QOS" else "QOS"
            resp = send_ipc_command(host, port, {"type": "SET_MODE", "mode": new_mode})
            if resp.get("status") == "ok":
                print(f"\n[+] Forwarding mode switched to: {new_mode}")
            else:
                print(f"\n[-] Error: {resp.get('message')}")

        elif choice == "7":
            resp = send_ipc_command(host, port, {"type": "GET_POLICY_LOGS"})
            events = resp.get("policy_events", [])
            print("\n" + "=" * 70)
            print("                 RECENT POLICY AUDIT EVENTS")
            print("=" * 70)
            if not events:
                print("  No policy events recorded yet.")
            for ev in events[-10:]:
                print(f"  [{ev.get('iso_time', 'N/A')}] {ev.get('event_type')}")
                print(f"    Reason:    {ev.get('reason')}")
                print(f"    Policy:    {ev.get('previous_policy')} -> {ev.get('new_policy')}")
                print(f"    Load/Util: {ev.get('metric_value', 0)}% (Threshold: {ev.get('threshold', 0)}%)")
                print("  " + "-" * 66)
            print("=" * 70)

        elif choice == "8":
            resp = send_ipc_command(host, port, {"type": "RESET_STATS"})
            print(f"\n[+] {resp.get('message', 'Stats reset')}")

        elif choice == "9":
            print("\n[*] Exiting menu. Goodbye.\n")
            break
        else:
            print("\n[-] Invalid selection. Please enter a number from 1 to 9.")

        input("\nPress Enter to continue...")


def main():
    parser = argparse.ArgumentParser(
        description="SDN Dynamic QoS Controller Notifier & Management CLI"
    )
    parser.add_argument("--controller", default="127.0.0.1", help="Ryu Controller IP (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6634, help="Controller IPC port (default: 6634)")
    parser.add_argument("--status", action="store_true", help="Print controller runtime status and exit")
    parser.add_argument("--adaptation", choices=["AUTO", "MANUAL"], help="Set adaptation mode: AUTO or MANUAL")
    parser.add_argument("--manual-policy", choices=["ON", "OFF"], help="Manually toggle congestion policy: ON or OFF")
    parser.add_argument("--mode", choices=["QOS", "FIFO"], help="Set forwarding mode: QOS or FIFO")
    parser.add_argument("--menu", action="store_true", help="Launch the interactive terminal management menu")

    # Flow registration arguments (legacy & app integration)
    parser.add_argument("--action", choices=["announce", "set_mode", "status", "simulate_congestion", "menu"],
                        help="Action to perform (optional if using flags)")
    parser.add_argument("--flow-class", default="voice", choices=["voice", "video", "bulk"])
    parser.add_argument("--priority", type=int, default=1, help="Priority level (1=High, 2=Med, 3=Low)")
    parser.add_argument("--queue", type=int, default=0, help="Target OVS queue ID")

    args = parser.parse_args()

    # If --menu is requested or no command arguments provided, launch interactive menu
    if args.menu or args.action == "menu" or (len(sys.argv) == 1):
        run_interactive_menu(args.controller, args.port)
        return

    # Handle --status
    if args.status or args.action == "status":
        status = send_ipc_command(args.controller, args.port, {"type": "GET_STATUS"})
        print(format_status(status))
        return

    # Handle --adaptation mode
    if args.adaptation:
        cmd = {"type": "SET_ADAPTATION_MODE", "mode": args.adaptation}
        resp = send_ipc_command(args.controller, args.port, cmd)
        print(f"[+] Controller response:\n{json.dumps(resp, indent=2)}")
        return

    # Handle --manual-policy
    if args.manual_policy:
        active = (args.manual_policy == "ON")
        cmd = {"type": "SET_MANUAL_QOS", "active": active}
        resp = send_ipc_command(args.controller, args.port, cmd)
        print(f"[+] Controller response:\n{json.dumps(resp, indent=2)}")
        return

    # Handle --mode
    if args.mode or (args.action == "set_mode" and args.mode):
        cmd = {"type": "SET_MODE", "mode": args.mode}
        resp = send_ipc_command(args.controller, args.port, cmd)
        print(f"[+] Controller response:\n{json.dumps(resp, indent=2)}")
        return

    # Handle flow announcement
    if args.action == "announce":
        cmd = {
            "type": "ANNOUNCE_CLASS",
            "class": args.flow_class,
            "priority": args.priority,
            "queue_id": args.queue
        }
        resp = send_ipc_command(args.controller, args.port, cmd)
        print(f"[+] Controller response:\n{json.dumps(resp, indent=2)}")
        return

    # Handle simulate congestion
    if args.action == "simulate_congestion":
        cmd = {"type": "SIMULATE_CONGESTION"}
        resp = send_ipc_command(args.controller, args.port, cmd)
        print(f"[+] Controller response:\n{json.dumps(resp, indent=2)}")
        return


if __name__ == "__main__":
    main()
