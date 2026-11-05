#!/usr/bin/env python3
"""
QoS Traffic Management System - Multi-Class UDP Metric Receiver
Receives UDP datagrams concurrently on designated QoS class ports.
Computes:
  - Throughput (kbps / Mbps)
  - Packet Loss (%)
  - One-Way Latency (Average, Min, Max in ms)
  - Interarrival Jitter (RFC 3550 formula in ms)
  - Packet Delivery Ratio (PDR)
  - Out-of-order and corrupt packet detection
Publishes live metrics to results/live_receiver_status.json for web dashboard.
Exports metrics to console, JSON, and CSV for analysis.
"""

import sys
import os
import time
import socket
import select
import json
import csv
import argparse
import signal
from collections import defaultdict, deque

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.common import (
    parse_packet, create_udp_receiver_socket, RFC3550JitterCalculator,
    CLASS_MAP
)


class ClassMetrics:
    def __init__(self, class_id: int, name: str, port: int):
        self.class_id = class_id
        self.name = name
        self.port = port
        
        self.packets_received = 0
        self.bytes_received = 0
        self.corrupt_packets = 0
        self.duplicates = 0
        self.out_of_order = 0
        
        self.first_seq = None
        self.last_seq = None
        self.max_seq = -1
        self.received_seqs = set()
        
        self.latencies = []  # In ms
        self.jitter_calc = RFC3550JitterCalculator()
        self.current_jitter_ms = 0.0
        
        self.first_packet_time = None
        self.last_packet_time = None
        
        # Periodic throughput tracking
        self.interval_bytes = 0
        self.interval_packets = 0
        self.instant_throughput_mbps = 0.0

    def record_packet(self, seq_num: int, send_time: float, recv_time: float, size_bytes: int):
        now = recv_time
        if self.first_packet_time is None:
            self.first_packet_time = now
            self.first_seq = seq_num

        self.last_packet_time = now
        self.packets_received += 1
        self.bytes_received += size_bytes
        self.interval_bytes += size_bytes
        self.interval_packets += 1

        # Check duplicate
        if seq_num in self.received_seqs:
            self.duplicates += 1
        else:
            self.received_seqs.add(seq_num)

        # Check out of order
        if seq_num < self.max_seq:
            self.out_of_order += 1
        else:
            self.max_seq = seq_num
        self.last_seq = seq_num

        # Latency (sender and receiver clocks synchronized in Mininet on same host/VM)
        latency_ms = (recv_time - send_time) * 1000.0
        if latency_ms < 0:
            latency_ms = 0.05
        self.latencies.append(latency_ms)

        # Keep last 1000 latencies to bound memory
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-1000:]

        # RFC 3550 Jitter
        self.current_jitter_ms = self.jitter_calc.update(send_time, recv_time)

    def compute_summary(self):
        duration = 0.0
        if self.first_packet_time and self.last_packet_time:
            duration = max(0.001, self.last_packet_time - self.first_packet_time)

        # Throughput
        throughput_kbps = (self.bytes_received * 8.0) / (duration * 1000.0) if duration > 0 else 0.0
        throughput_mbps = throughput_kbps / 1000.0

        # Loss calculation
        if self.max_seq >= 0 and self.first_seq is not None:
            total_expected = (self.max_seq - self.first_seq) + 1
            lost_packets = max(0, total_expected - len(self.received_seqs))
            loss_pct = (lost_packets / total_expected * 100.0) if total_expected > 0 else 0.0
            pdr = (len(self.received_seqs) / total_expected) if total_expected > 0 else 1.0
        else:
            total_expected = 0
            lost_packets = 0
            loss_pct = 0.0
            pdr = 1.0

        # Latency statistics
        if self.latencies:
            avg_lat = sum(self.latencies) / len(self.latencies)
            min_lat = min(self.latencies)
            max_lat = max(self.latencies)
        else:
            avg_lat = min_lat = max_lat = 0.0

        return {
            "class_id": self.class_id,
            "class_name": self.name,
            "port": self.port,
            "packets_received": self.packets_received,
            "packets_expected": total_expected,
            "packets_lost": lost_packets,
            "loss_percentage": round(loss_pct, 2),
            "packet_delivery_ratio": round(pdr, 4),
            "bytes_received": self.bytes_received,
            "duration_sec": round(duration, 2),
            "throughput_kbps": round(throughput_kbps, 2),
            "throughput_mbps": round(throughput_mbps, 3),
            "instant_throughput_mbps": round(self.instant_throughput_mbps, 3),
            "avg_latency_ms": round(avg_lat, 2),
            "min_latency_ms": round(min_lat, 2),
            "max_latency_ms": round(max_lat, 2),
            "jitter_ms": round(self.current_jitter_ms, 2),
            "out_of_order": self.out_of_order,
            "corrupt_packets": self.corrupt_packets
        }


def run_receiver(bind_host: str, ports: list, duration: float = 0, 
                 output_json: str = None, output_csv: str = None,
                 live_status_path: str = None):
    """
    Main loop monitoring sockets across all requested ports using select().
    Emits real-time live_receiver_status.json for dashboard.
    """
    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if live_status_path is None:
        live_status_path = os.path.join(project_dir, 'results', 'live_receiver_status.json')
    os.makedirs(os.path.dirname(live_status_path), exist_ok=True)

    sockets = {}
    metrics = {}

    for p in ports:
        try:
            sock = create_udp_receiver_socket(bind_host, p)
            sockets[sock.fileno()] = (sock, p)
            cname = "unknown"
            cid = 0
            for cid_cand, cinfo in CLASS_MAP.items():
                if cinfo["default_port"] == p:
                    cname = cinfo["name"]
                    cid = cid_cand
                    break
            metrics[p] = ClassMetrics(class_id=cid, name=cname, port=p)
            print(f"[*] Bound UDP Receiver on {bind_host}:{p} ({cname})")
        except OSError as e:
            print(f"[-] Error binding port {p}: {e}")

    if not sockets:
        print("[-] No sockets could be opened. Exiting.")
        return

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        print("\n[*] Interrupted by user. Finalizing statistics...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    start_time = time.time()
    last_stat_log = time.time()
    poll_list = [sock for sock, _ in sockets.values()]
    timeseries_history = deque(maxlen=60)  # 60 seconds rolling window

    print(f"\n{'='*75}")
    print(f" QoS Traffic Receiver Running (Timeout: {duration if duration > 0 else 'Unlimited'}s)")
    print(f"{'='*75}\n")

    def publish_status(is_active=True):
        now_ts = time.time()
        per_class_summary = {}
        tot_rx_pkts = 0
        tot_lost_pkts = 0
        tot_expected_pkts = 0
        tot_mbps = 0.0

        for p, m in metrics.items():
            s = m.compute_summary()
            per_class_summary[m.name] = s
            tot_rx_pkts += s["packets_received"]
            tot_lost_pkts += s["packets_lost"]
            tot_expected_pkts += s["packets_expected"]
            # During active traffic, prefer instant throughput; fallback to computed summary
            class_mbps = m.instant_throughput_mbps if (is_active and m.instant_throughput_mbps > 0) else s["throughput_mbps"]
            tot_mbps += class_mbps

        overall_loss_pct = round((tot_lost_pkts / tot_expected_pkts * 100.0), 2) if tot_expected_pkts > 0 else 0.0
        overall_pdr = round((tot_rx_pkts / tot_expected_pkts), 4) if tot_expected_pkts > 0 else 1.0

        ts_point = {
            "timestamp": now_ts,
            "rel_sec": round(now_ts - start_time, 1),
            "throughput_mbps": round(tot_mbps, 3),
            "loss_pct": overall_loss_pct,
            "classes": {
                c: {
                    "throughput_mbps": per_class_summary[c]["instant_throughput_mbps"] if is_active else per_class_summary[c]["throughput_mbps"],
                    "latency_ms": per_class_summary[c]["avg_latency_ms"],
                    "jitter_ms": per_class_summary[c]["jitter_ms"],
                    "loss_pct": per_class_summary[c]["loss_percentage"]
                } for c in per_class_summary
            }
        }
        timeseries_history.append(ts_point)

        status_obj = {
            "active": is_active,
            "timestamp": now_ts,
            "elapsed_seconds": round(now_ts - start_time, 1),
            "total_packets_received": tot_rx_pkts,
            "total_packets_lost": tot_lost_pkts,
            "total_packets_expected": tot_expected_pkts,
            "overall_loss_percentage": overall_loss_pct,
            "overall_pdr": overall_pdr,
            "total_throughput_mbps": round(tot_mbps, 3),
            "per_class": per_class_summary,
            "timeseries": list(timeseries_history)
        }
        try:
            tmp_path = live_status_path + ".tmp"
            with open(tmp_path, 'w') as f:
                json.dump(status_obj, f, indent=2)
            os.replace(tmp_path, live_status_path)
        except Exception:
            pass

    # Publish initial status so dashboard sees receiver immediately
    publish_status(is_active=True)

    while running:
        if duration > 0 and (time.time() - start_time) >= duration:
            print("[*] Test duration reached.")
            break

        readable, _, _ = select.select(poll_list, [], [], 0.1)
        now = time.time()

        for s in readable:
            port = None
            for p, m in metrics.items():
                if s.getsockname()[1] == p:
                    port = p
                    break
            if port is None:
                continue

            metric = metrics[port]

            try:
                data, addr = s.recvfrom(65535)
                recv_time = time.time()
                parsed = parse_packet(data)
                if parsed:
                    metric.record_packet(
                        seq_num=parsed["seq_num"],
                        send_time=parsed["send_time"],
                        recv_time=recv_time,
                        size_bytes=len(data)
                    )
                else:
                    metric.corrupt_packets += 1
            except OSError:
                pass

        # Periodic log update every 1 second
        if (now - last_stat_log) >= 1.0:
            interval_elapsed = now - last_stat_log
            log_parts = []
            for p, m in metrics.items():
                m.instant_throughput_mbps = (m.interval_bytes * 8.0) / (interval_elapsed * 1000000.0)
                summ = m.compute_summary()
                log_parts.append(f"{m.name}[{p}]: {m.instant_throughput_mbps:5.2f} Mbps, Loss: {summ['loss_percentage']:4.1f}%, Jitter: {m.current_jitter_ms:4.1f}ms")
                m.interval_bytes = 0
                m.interval_packets = 0
            
            print(f"[{time.strftime('%H:%M:%S')}] | " + " | ".join(log_parts))
            last_stat_log = now
            publish_status(is_active=True)

    # Close sockets
    for sock, _ in sockets.values():
        sock.close()

    publish_status(is_active=False)

    # Generate final summary
    print(f"\n\n{'='*75}")
    print(f" FINAL EXPERIMENT METRICS SUMMARY")
    print(f"{'='*75}")
    header_fmt = "{:<10} {:<6} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10}"
    row_fmt = "{:<10} {:<6} {:<10.2f} {:<10.2f} {:<10.2f} {:<10.2f} {:<10.2f} {:<10}"
    print(header_fmt.format("Class", "Port", "Throughput", "Loss %", "Avg Lat", "Min Lat", "Jitter", "Packets"))
    print(header_fmt.format("", "", "(Mbps)", "", "(ms)", "(ms)", "(ms)", "Received"))
    print("-" * 75)

    summary_list = []
    for p, m in metrics.items():
        summ = m.compute_summary()
        summary_list.append(summ)
        print(row_fmt.format(
            summ["class_name"], summ["port"], summ["throughput_mbps"],
            summ["loss_percentage"], summ["avg_latency_ms"], summ["min_latency_ms"],
            summ["jitter_ms"], summ["packets_received"]
        ))
    print(f"{'='*75}\n")

    # Export to JSON if path provided
    if output_json:
        os.makedirs(os.path.dirname(os.path.abspath(output_json)), exist_ok=True)
        tmp_json = output_json + ".tmp"
        with open(tmp_json, 'w') as f:
            json.dump(summary_list, f, indent=2)
        os.replace(tmp_json, output_json)
        print(f"[+] Metrics exported to JSON: {output_json}")

    # Export to CSV if path provided
    if output_csv:
        os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
        fieldnames = [
            "class_id", "class_name", "port", "packets_received", "packets_expected",
            "packets_lost", "loss_percentage", "packet_delivery_ratio", "bytes_received",
            "duration_sec", "throughput_kbps", "throughput_mbps", "instant_throughput_mbps", "avg_latency_ms",
            "min_latency_ms", "max_latency_ms", "jitter_ms", "out_of_order", "corrupt_packets"
        ]
        tmp_csv = output_csv + ".tmp"
        with open(tmp_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in summary_list:
                writer.writerow(s)
        os.replace(tmp_csv, output_csv)
        print(f"[+] Metrics exported to CSV: {output_csv}")


def main():
    parser = argparse.ArgumentParser(description="Multi-Class UDP QoS Receiver")
    parser.add_argument("--bind", default="0.0.0.0", help="IP address to bind on")
    parser.add_argument("--ports", default="5001,5002,5003,5004", 
                        help="Comma-separated list of UDP ports to listen on")
    parser.add_argument("--duration", type=float, default=0, 
                        help="Duration in seconds (0 = run indefinitely until Ctrl+C)")
    parser.add_argument("--out-json", default=None, help="Path to save summary JSON")
    parser.add_argument("--out-csv", default=None, help="Path to save summary CSV")
    parser.add_argument("--live-json", default=None, help="Path for live status JSON")
    args = parser.parse_args()

    port_list = [int(p.strip()) for p in args.ports.split(",") if p.strip().isdigit()]
    run_receiver(
        bind_host=args.bind,
        ports=port_list,
        duration=args.duration,
        output_json=args.out_json,
        output_csv=args.out_csv,
        live_status_path=args.live_json
    )


if __name__ == "__main__":
    main()
