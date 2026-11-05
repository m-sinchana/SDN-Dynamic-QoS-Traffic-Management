"""
QoS Traffic Management System - Common Protocol & Socket Utilities
Low-level UDP socket helpers, binary packet serialization, and RFC 3550 jitter calculation.
Uses Python's standard library `socket` and `struct` (no high-level networking frameworks).
"""

import socket
import struct
import time
import os
import sys
import json

MAGIC_HEADER = b'QS'
PROTOCOL_VERSION = 1
HEADER_FORMAT = '!2sBBIdH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 18 bytes

# Traffic Class Mapping
CLASS_MAP = {
    1: {"name": "voice", "default_port": 5001, "dscp": 46, "tos": 184},
    2: {"name": "video", "default_port": 5002, "dscp": 34, "tos": 136},
    3: {"name": "bulk", "default_port": 5003, "dscp": 0, "tos": 0},
    4: {"name": "congestion_flooder", "default_port": 5004, "dscp": 0, "tos": 0}
}

CLASS_NAME_TO_ID = {v["name"]: k for k, v in CLASS_MAP.items()}


def create_packet(class_id: int, seq_num: int, target_total_size: int, payload_data: bytes = None) -> bytes:
    """
    Constructs a low-level binary packet with a strict protocol header:
    - Magic bytes (2B): 'QS'
    - Version (1B): 1
    - Class ID (1B): 1=Voice, 2=Video, 3=Bulk, 4=Congestion
    - Sequence Number (4B uint32)
    - Timestamp (8B double): time.time()
    - Payload Length (2B uint16)
    - Payload: padded to meet target_total_size
    """
    now = time.time()
    min_size = HEADER_SIZE
    if target_total_size < min_size:
        target_total_size = min_size
    
    needed_payload = target_total_size - HEADER_SIZE
    if payload_data is None:
        # Create deterministic repeatable payload padding
        payload = b'X' * needed_payload
    else:
        if len(payload_data) < needed_payload:
            payload = payload_data + (b'\x00' * (needed_payload - len(payload_data)))
        else:
            payload = payload_data[:needed_payload]

    header = struct.pack(HEADER_FORMAT, MAGIC_HEADER, PROTOCOL_VERSION, class_id, seq_num, now, len(payload))
    return header + payload


def parse_packet(raw_bytes: bytes):
    """
    Unpacks and validates a received raw UDP packet.
    Returns:
        dict with {class_id, seq_num, send_time, payload_len, payload} or None if corrupted/invalid.
    """
    if len(raw_bytes) < HEADER_SIZE:
        return None

    try:
        magic, version, class_id, seq_num, send_time, payload_len = struct.unpack(
            HEADER_FORMAT, raw_bytes[:HEADER_SIZE]
        )
    except struct.error:
        return None

    if magic != MAGIC_HEADER or version != PROTOCOL_VERSION:
        return None

    actual_payload = raw_bytes[HEADER_SIZE:HEADER_SIZE + payload_len]
    return {
        "class_id": class_id,
        "seq_num": seq_num,
        "send_time": send_time,
        "payload_len": payload_len,
        "payload": actual_payload,
        "total_size": len(raw_bytes)
    }


def create_udp_sender_socket(tos: int = 0) -> socket.socket:
    """
    Creates a low-level UDP socket and configures IP_TOS (DSCP) socket options.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Try setting IP_TOS for DSCP classification
    if tos > 0:
        try:
            # On Linux and macOS, IP_TOS sets the Type-of-Service / DSCP field
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos)
        except OSError as e:
            sys.stderr.write(f"Warning: Failed to set IP_TOS={tos}: {e}\n")

    # Increase send buffer to minimize local drops during bursts
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
    except OSError:
        pass

    return sock


def create_udp_receiver_socket(host: str, port: int) -> socket.socket:
    """
    Creates a low-level UDP socket bound to host:port with optimized receive buffer.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
    except OSError:
        pass

    sock.bind((host, port))
    return sock


class RFC3550JitterCalculator:
    """
    Computes interarrival jitter using the exact algorithm specified in RFC 3550 (RTP):
    D(i, j) = (R_j - S_j) - (R_i - S_i)
    J(i) = J(i-1) + (|D(i, j)| - J(i-1)) / 16
    """
    def __init__(self):
        self.last_transit = None
        self.jitter = 0.0

    def update(self, send_time: float, recv_time: float) -> float:
        transit = recv_time - send_time
        if self.last_transit is not None:
            d = abs(transit - self.last_transit)
            self.jitter += (d - self.jitter) / 16.0
        self.last_transit = transit
        return self.jitter * 1000.0  # Return jitter in milliseconds
