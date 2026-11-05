#!/usr/bin/env python3
"""
QoS Traffic Management System - Multi-Class UDP Traffic Generator (Sender)
Generates real-time UDP streams using Python's standard `socket` module.
Supports:
  - Voice traffic (Class 1: 160-byte packets, 50 pps / 64 kbps, DSCP 46)
  - Video streaming (Class 2: 1024-byte packets, 305 pps / 2.5 Mbps, DSCP 34)
  - Bulk transfer (Class 3: 1400-byte packets, 178 pps / 2.0 Mbps, DSCP 0)
  - Heavy Congestion Flooder (Class 4: 1400-byte packets, 892 pps / 10+ Mbps)
  - Presets: 'light', 'moderate', 'heavy'
Publishes status to results/live_sender_status.json for web dashboard.
"""

import sys
import os
import time
import socket
import argparse
import json
import threading
import signal

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.common import (
    create_packet, create_udp_sender_socket, CLASS_MAP, CLASS_NAME_TO_ID
)


class SenderManager:
    def __init__(self, status_file: str = None):
        self.project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.status_file = status_file or os.path.join(self.project_dir, 'results', 'live_sender_status.json')
        os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
        self.active_flows = {}
        self.lock = threading.Lock()
        self.stop_requested = threading.Event()

    def update_flow_status(self, class_name: str, status: dict):
        with self.lock:
            self.active_flows[class_name] = status
            self._write_status()

    def remove_flow_status(self, class_name: str):
        with self.lock:
            if class_name in self.active_flows:
                del self.active_flows[class_name]
            self._write_status()

    def _write_status(self):
        try:
            data = {
                "timestamp": time.time(),
                "active_count": len(self.active_flows),
                "is_active": len(self.active_flows) > 0,
                "flows": self.active_flows
            }
            with open(self.status_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


GLOBAL_MANAGER = SenderManager()


def run_sender_flow(target_ip: str, port: int, class_name: str, 
                    rate_kbps: float, packet_size: int, duration: float, 
                    tos: int = 0, stop_event: threading.Event = None,
                    manager: SenderManager = GLOBAL_MANAGER):
    """
    Runs a continuous packet transmission flow at the specified rate_kbps.
    Paces packets using precision timers.
    """
    class_id = CLASS_NAME_TO_ID.get(class_name, 3)
    sock = create_udp_sender_socket(tos=tos)

    bytes_per_sec = (rate_kbps * 1000.0) / 8.0
    packets_per_sec = bytes_per_sec / packet_size if packet_size > 0 else 100
    inter_packet_interval = 1.0 / packets_per_sec if packets_per_sec > 0 else 0.01

    print(f"[*] Starting Flow '{class_name}' (Class ID: {class_id}) -> {target_ip}:{port}")
    print(f"    Target Rate: {rate_kbps:.1f} kbps | Packet Size: {packet_size} B | "
          f"PPS: {packets_per_sec:.1f} | TOS: 0x{tos:02x}")

    seq_num = 0
    start_time = time.time()
    next_send_time = time.perf_counter()
    total_bytes_sent = 0
    total_packets_sent = 0

    manager.update_flow_status(class_name, {
        "class_name": class_name,
        "target_ip": target_ip,
        "port": port,
        "target_rate_kbps": rate_kbps,
        "packet_size": packet_size,
        "packets_sent": 0,
        "bytes_sent": 0,
        "duration": duration,
        "active": True
    })

    last_stat_update = time.time()

    while True:
        if stop_event and stop_event.is_set():
            break
        if manager.stop_requested.is_set():
            break
        if duration > 0 and (time.time() - start_time) >= duration:
            break

        packet = create_packet(class_id=class_id, seq_num=seq_num, target_total_size=packet_size)
        
        try:
            sock.sendto(packet, (target_ip, port))
            total_bytes_sent += len(packet)
            total_packets_sent += 1
            seq_num += 1
        except OSError:
            pass

        now_t = time.time()
        if (now_t - last_stat_update) >= 1.0:
            manager.update_flow_status(class_name, {
                "class_name": class_name,
                "target_ip": target_ip,
                "port": port,
                "target_rate_kbps": rate_kbps,
                "packet_size": packet_size,
                "packets_sent": total_packets_sent,
                "bytes_sent": total_bytes_sent,
                "elapsed": round(now_t - start_time, 1),
                "active": True
            })
            last_stat_update = now_t

        next_send_time += inter_packet_interval
        now = time.perf_counter()
        sleep_time = next_send_time - now
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            next_send_time = now

    elapsed = time.time() - start_time
    actual_rate_kbps = (total_bytes_sent * 8.0) / (elapsed * 1000.0) if elapsed > 0 else 0
    print(f"[+] Completed Flow '{class_name}': Sent {total_packets_sent} pkts "
          f"({total_bytes_sent / (1024*1024):.2f} MB) in {elapsed:.2f}s "
          f"(Avg Rate: {actual_rate_kbps:.2f} kbps)")

    manager.remove_flow_status(class_name)
    sock.close()


def main():
    parser = argparse.ArgumentParser(description="Low-level UDP Traffic Generator")
    parser.add_argument("--dst", default="10.0.0.4", help="Destination IP address (receiver)")
    parser.add_argument("--class", dest="traffic_class", default="voice", 
                        choices=["voice", "video", "bulk", "congestion_flooder", "all"],
                        help="Traffic class to generate")
    parser.add_argument("--preset", choices=["light", "moderate", "heavy"], default=None,
                        help="Pre-configured traffic load preset")
    parser.add_argument("--port", type=int, default=None, help="Destination UDP port")
    parser.add_argument("--rate", type=float, default=None, help="Target rate in kbps")
    parser.add_argument("--size", type=int, default=None, help="Packet size in bytes")
    parser.add_argument("--duration", type=float, default=15.0, help="Transmission duration in seconds")
    parser.add_argument("--config", default="config/traffic_config.json", help="Path to config file")
    args = parser.parse_args()

    def handle_sig(sig, frame):
        print("\n[*] Stopping sender flows...")
        GLOBAL_MANAGER.stop_requested.set()

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    cfg_path = args.config
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'traffic_config.json')

    with open(cfg_path, 'r') as f:
        config = json.load(f)

    classes_cfg = config.get("classes", {})

    if args.preset:
        threads = []
        if args.preset == "light":
            # Light: Voice 64k, Video 1000k, Bulk 1000k
            plan = [
                ("voice", 64, 160, 5001, 184),
                ("video", 1000, 1024, 5002, 136),
                ("bulk", 1000, 1400, 5003, 0)
            ]
        elif args.preset == "moderate":
            # Moderate: Voice 64k, Video 2500k, Bulk 5500k (~8.1 Mbps)
            plan = [
                ("voice", 64, 160, 5001, 184),
                ("video", 2500, 1024, 5002, 136),
                ("bulk", 5500, 1400, 5003, 0)
            ]
        else: # heavy
            # Heavy: Voice 64k, Video 2500k, Bulk 3000k, Flooder 8000k (~13.6 Mbps)
            plan = [
                ("voice", 64, 160, 5001, 184),
                ("video", 2500, 1024, 5002, 136),
                ("bulk", 3000, 1400, 5003, 0),
                ("congestion_flooder", 8000, 1400, 5004, 0)
            ]

        for cname, rate, size, port, tos in plan:
            t = threading.Thread(
                target=run_sender_flow,
                kwargs={
                    "target_ip": args.dst,
                    "port": port,
                    "class_name": cname,
                    "rate_kbps": rate,
                    "packet_size": size,
                    "duration": args.duration,
                    "tos": tos,
                    "manager": GLOBAL_MANAGER
                }
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

    elif args.traffic_class == "all":
        threads = []
        for cname in ["voice", "video", "bulk"]:
            cinfo = classes_cfg[cname]
            t = threading.Thread(
                target=run_sender_flow,
                kwargs={
                    "target_ip": args.dst,
                    "port": cinfo["port"],
                    "class_name": cname,
                    "rate_kbps": cinfo["target_rate_kbps"],
                    "packet_size": cinfo["packet_size_bytes"],
                    "duration": args.duration,
                    "tos": cinfo.get("tos", 0),
                    "manager": GLOBAL_MANAGER
                }
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()
    else:
        cinfo = classes_cfg.get(args.traffic_class, {})
        port = args.port if args.port is not None else cinfo.get("port", 5001)
        rate_kbps = args.rate if args.rate is not None else cinfo.get("target_rate_kbps", 64)
        packet_size = args.size if args.size is not None else cinfo.get("packet_size_bytes", 160)
        tos = cinfo.get("tos", 0)

        run_sender_flow(
            target_ip=args.dst,
            port=port,
            class_name=args.traffic_class,
            rate_kbps=rate_kbps,
            packet_size=packet_size,
            duration=args.duration,
            tos=tos,
            manager=GLOBAL_MANAGER
        )


if __name__ == "__main__":
    main()
