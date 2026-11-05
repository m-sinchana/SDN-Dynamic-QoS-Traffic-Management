#!/usr/bin/env python3
"""
Unit and Integration Tests for Low-Level UDP Sockets and Protocol Serialization
Validates:
  1. Packet framing, byte serialization, and checksum/header unpacking
  2. Corrupted packet detection and error handling
  3. RFC 3550 Jitter calculation algorithm accuracy
  4. Real socket loopback transmission and metrics calculation
"""

import sys
import os
import time
import socket
import threading
import unittest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.common import (
    create_packet, parse_packet, RFC3550JitterCalculator,
    create_udp_sender_socket, create_udp_receiver_socket,
    MAGIC_HEADER, PROTOCOL_VERSION, HEADER_SIZE
)
from app.receiver import ClassMetrics


class TestProtocolSerialization(unittest.TestCase):
    def test_packet_creation_and_parsing(self):
        class_id = 1  # Voice
        seq_num = 42
        target_size = 160
        payload = b"Hello QoS Protocol!"

        pkt = create_packet(class_id, seq_num, target_size, payload)
        self.assertEqual(len(pkt), target_size)

        parsed = parse_packet(pkt)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["class_id"], class_id)
        self.assertEqual(parsed["seq_num"], seq_num)
        self.assertAlmostEqual(parsed["send_time"], time.time(), delta=1.0)
        self.assertTrue(parsed["payload"].startswith(payload))

    def test_corrupted_packets(self):
        # Truncated packet
        short_pkt = b"QS123"
        self.assertIsNone(parse_packet(short_pkt))

        # Bad magic bytes
        bad_magic = b"XX" + b"\x01\x01\x00\x00\x00\x01" + b"\x00" * 10
        self.assertIsNone(parse_packet(bad_magic))

    def test_rfc3550_jitter_calculator(self):
        calc = RFC3550JitterCalculator()
        # Transit time 1: send 10.0, recv 10.05 -> transit = 0.05
        j1 = calc.update(10.0, 10.05)
        self.assertEqual(j1, 0.0)  # Initial transit establishes baseline

        # Transit time 2: send 10.1, recv 10.18 -> transit = 0.08
        # D = |0.08 - 0.05| = 0.03
        # J = 0 + (0.03 - 0) / 16 = 0.03 / 16 = 0.001875 s = 1.875 ms
        j2 = calc.update(10.1, 10.18)
        self.assertAlmostEqual(j2, 1.875, places=3)

    def test_class_metrics_pipeline(self):
        """Tests ClassMetrics loss, latency, jitter and out-of-order tracking logic."""
        m = ClassMetrics(class_id=1, name="voice", port=5001)
        base_time = 1000.0

        # Simulate 10 packets, but drop seq 4 and 7 (lost) and deliver seq 8 before 6 (reordering)
        sent_seqs = [0, 1, 2, 3, 5, 8, 6, 9]
        for idx, seq in enumerate(sent_seqs):
            send_t = base_time + (seq * 0.02)
            recv_t = send_t + 0.012  # 12ms latency
            m.record_packet(seq_num=seq, send_time=send_t, recv_time=recv_t, size_bytes=160)

        summary = m.compute_summary()
        self.assertEqual(summary["packets_received"], 8)
        self.assertEqual(summary["packets_expected"], 10)  # seq 0 through 9
        self.assertEqual(summary["packets_lost"], 2)       # 4 and 7 missing
        self.assertEqual(summary["loss_percentage"], 20.0)
        self.assertEqual(summary["out_of_order"], 1)       # seq 6 arrived after 8
        self.assertAlmostEqual(summary["avg_latency_ms"], 12.0, places=1)
        self.assertAlmostEqual(summary["packet_delivery_ratio"], 0.8, places=2)
        print("\n[ClassMetrics Test] Successfully verified loss detection (2/10 = 20%) & 12ms latency.")

    def test_duplicate_packets(self):
        """Tests that duplicate sequence numbers are properly caught."""
        m = ClassMetrics(class_id=1, name="voice", port=5001)
        now = time.time()
        m.record_packet(seq_num=10, send_time=now, recv_time=now + 0.01, size_bytes=160)
        m.record_packet(seq_num=10, send_time=now, recv_time=now + 0.012, size_bytes=160)
        self.assertEqual(m.duplicates, 1)
        self.assertEqual(m.packets_received, 2)
        self.assertEqual(len(m.received_seqs), 1)

    def test_absent_receiver_udp_safety(self):
        """Tests that UDP sender gracefully handles sending to an unmonitored destination."""
        sock = create_udp_sender_socket()
        pkt = create_packet(class_id=1, seq_num=1, target_total_size=160)
        try:
            # Send to an unused high port on loopback; UDP should not crash
            sock.sendto(pkt, ("127.0.0.1", 49999))
        except (PermissionError, OSError):
            pass  # Sandbox or OS level restriction is handled safely
        finally:
            sock.close()


class TestSocketLoopback(unittest.TestCase):
    def test_udp_stream_metrics(self):
        test_port = 15001
        test_host = "127.0.0.1"

        try:
            recv_sock = create_udp_receiver_socket(test_host, test_port)
        except (PermissionError, OSError) as e:
            print(f"\n[Note] Socket bind restricted by OS sandbox ({e}). Skipping live loopback socket test.")
            return

        metrics = ClassMetrics(class_id=1, name="voice", port=test_port)
        stop_recv = threading.Event()
        received_count = 0

        def receiver_thread():
            nonlocal received_count
            recv_sock.settimeout(0.2)
            while not stop_recv.is_set():
                try:
                    data, _ = recv_sock.recvfrom(2048)
                    recv_t = time.time()
                    p = parse_packet(data)
                    if p:
                        metrics.record_packet(p["seq_num"], p["send_time"], recv_t, len(data))
                        received_count += 1
                except (socket.timeout, OSError):
                    continue

        th = threading.Thread(target=receiver_thread)
        th.start()

        # Send 50 packets over UDP
        try:
            send_sock = create_udp_sender_socket()
            num_pkts = 50
            for seq in range(num_pkts):
                pkt = create_packet(class_id=1, seq_num=seq, target_total_size=160)
                send_sock.sendto(pkt, (test_host, test_port))
                time.sleep(0.002)  # 2ms pace

            time.sleep(0.1)
            stop_recv.set()
            th.join()
            recv_sock.close()
            send_sock.close()

            summary = metrics.compute_summary()
            self.assertEqual(summary["packets_received"], num_pkts)
            self.assertEqual(summary["packets_lost"], 0)
            self.assertEqual(summary["loss_percentage"], 0.0)
            self.assertGreater(summary["throughput_kbps"], 0.0)
            self.assertGreater(summary["avg_latency_ms"], 0.0)
            print(f"\n[Test Loopback Result] Successfully sent & received {num_pkts} packets.")
            print(f"                       Throughput: {summary['throughput_kbps']:.2f} kbps, "
                  f"Avg Latency: {summary['avg_latency_ms']:.2f} ms, Jitter: {summary['jitter_ms']:.2f} ms")
        except (PermissionError, OSError) as e:
            stop_recv.set()
            th.join()
            recv_sock.close()
            print(f"\n[Note] Socket sendto restricted by OS sandbox ({e}).")


if __name__ == '__main__':
    unittest.main()
