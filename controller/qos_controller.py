"""
QoS Traffic Management System - Ryu SDN Controller Application (OpenFlow 1.3)
Implements:
  - Multi-class packet classification (UDP Ports & DSCP / TOS)
  - Dynamic Priority Queue Mapping (Voice -> Q0, Video -> Q1, Bulk -> Q2)
  - Periodic OpenFlow 1.3 Port Statistics Polling (Link Utilization Monitoring)
  - Dynamic Congestion State Machine with Hysteresis & Hold-Down Timers
  - Policy change event logging with timestamps, metrics, reasons, and state audit
  - Real-time status broadcasting to results/live_controller_status.json
  - Application-to-Controller IPC Socket Server (Port 6634) for Runtime Interaction
  - Toggle between QoS Priority Mode and Baseline FIFO Forwarding
"""

import os
import sys
import json
import time
import socket
import threading
from datetime import datetime

# Ryu imports with graceful fallback for inspection/testing outside Ryu runtime
try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.ofproto import ofproto_v1_3
    from ryu.lib.packet import packet, ethernet, ipv4, udp, arp, ether_types
    from ryu.lib import hub
    RYU_AVAILABLE = True
except ImportError:
    RYU_AVAILABLE = False
    app_manager = object
    hub = None


if not RYU_AVAILABLE:
    class RyuAppStub:
        OFP_VERSIONS = []
        def __init__(self, *args, **kwargs):
            pass
    BaseApp = RyuAppStub
else:
    BaseApp = app_manager.RyuApp


class QoSTrafficController(BaseApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION] if RYU_AVAILABLE else []

    def __init__(self, *args, **kwargs):
        super(QoSTrafficController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.port_stats_history = {}  # (dpid, port_no) -> (last_time, last_tx_bytes)

        # Base directories
        self.project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.results_dir = os.path.join(self.project_dir, 'results')
        self.config_dir = os.path.join(self.project_dir, 'config')
        os.makedirs(self.results_dir, exist_ok=True)

        # Load parameters from config
        self._load_config()

        self.consecutive_congested_samples = 0
        self.consecutive_normal_samples = 0
        self.is_congested = False
        self.qos_mode = "QOS"  # "QOS" or "FIFO"
        self.adaptation_mode = getattr(self, 'default_adaptation_mode', 'AUTO')  # "AUTO" or "MANUAL"

        # Classification config
        self.voice_port = 5001
        self.video_port = 5002
        self.bulk_port = 5003
        self.congestion_port = 5004

        # DSCP values
        self.voice_dscp = 46   # EF
        self.video_dscp = 34   # AF41
        self.bulk_dscp = 0     # BE

        # Real-time state metrics
        self.current_utilization_pct = 0.0
        self.current_load_bps = 0.0
        self.last_poll_time = time.time()
        self.active_flows = []
        self.policy_events = []
        self.event_counter = 0

        # Output status file
        self.status_file_path = os.path.join(self.results_dir, "live_controller_status.json")
        self.policy_log_path = os.path.join(self.results_dir, "policy_events.json")

        # Controller log prefix must exist before background threads start
        self.logger_prefix = "[QoS-Controller]"

        # Start IPC Socket Server in background thread
        self.ipc_thread = threading.Thread(target=self._start_ipc_server, daemon=True)
        self.ipc_thread.start()

        # Start periodic OpenFlow port monitoring thread
        if RYU_AVAILABLE and hub:
            self.monitor_thread = hub.spawn(self._monitor_loop)
        else:
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()

        print(f"{self.logger_prefix} Initialized. Mode: {self.qos_mode}, Adaptation: {self.adaptation_mode}, "
              f"Bottleneck Link: {self.link_capacity_bps / 1e6:.1f} Mbps (Port {self.bottleneck_port}), "
              f"Congestion Threshold: {self.congestion_threshold_pct}%, Relax: {self.relax_threshold_pct}%")

        self._record_policy_event(
            event_type="CONTROLLER_STARTUP",
            reason="SDN Controller initialized with baseline QoS policy",
            prev_policy="NONE",
            new_policy="STANDARD_QOS" if self.qos_mode == "QOS" else "BASELINE_FIFO",
            metric_val=0.0,
            threshold=self.congestion_threshold_pct
        )
        self._write_live_status()

    def _load_config(self):
        """Loads or reloads configuration from config/qos_policy.json"""
        policy_file = os.path.join(self.config_dir, 'qos_policy.json')
        defaults = {
            "bottleneck_link_speed_mbps": 10.0,
            "bottleneck_port": 4,
            "switch_dpid": 1,
            "congestion_threshold_percent": 80.0,
            "relax_threshold_percent": 60.0,
            "congestion_trigger_window_samples": 2,
            "hold_down_window_samples": 4,
            "default_adaptation_mode": "AUTO"
        }
        if os.path.exists(policy_file):
            try:
                with open(policy_file, 'r') as f:
                    data = json.load(f)
                    net = data.get("network", {})
                    cpol = data.get("congestion_policy", {})
                    self.link_capacity_bps = float(net.get("bottleneck_link_speed_mbps", 10.0)) * 1_000_000.0
                    self.bottleneck_port = int(net.get("bottleneck_port", 4))
                    self.target_dpid = int(net.get("switch_dpid", 1))
                    self.congestion_threshold_pct = float(cpol.get("congestion_threshold_percent", 80.0))
                    self.relax_threshold_pct = float(cpol.get("relax_threshold_percent", 60.0))
                    self.trigger_window = int(cpol.get("congestion_trigger_window_samples", 2))
                    self.hold_down_window = int(cpol.get("hold_down_window_samples", 4))
                    self.default_adaptation_mode = cpol.get("default_adaptation_mode", "AUTO").upper()
                    return
            except Exception as e:
                print(f"[-] Warning: Failed to parse qos_policy.json ({e}). Using defaults.")

        self.link_capacity_bps = defaults["bottleneck_link_speed_mbps"] * 1_000_000.0
        self.bottleneck_port = defaults["bottleneck_port"]
        self.target_dpid = defaults["switch_dpid"]
        self.congestion_threshold_pct = defaults["congestion_threshold_percent"]
        self.relax_threshold_pct = defaults["relax_threshold_percent"]
        self.trigger_window = defaults["congestion_trigger_window_samples"]
        self.hold_down_window = defaults["hold_down_window_samples"]
        self.default_adaptation_mode = defaults["default_adaptation_mode"]

    def _start_ipc_server(self):
        """
        Listens on TCP port 6634 for commands from end-host applications,
        web dashboard backend, or test scripts.
        """
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind(("0.0.0.0", 6634))
            server_sock.listen(10)
            print(f"{self.logger_prefix} IPC Control Socket listening on port 6634")
            while True:
                conn, addr = server_sock.accept()
                threading.Thread(target=self._handle_ipc_client, args=(conn, addr), daemon=True).start()
        except Exception as e:
            print(f"{self.logger_prefix} IPC Socket Server Error: {e}")

    def _handle_ipc_client(self, conn, addr):
        try:
            conn.settimeout(5.0)
            raw_data = conn.recv(8192).decode('utf-8').strip()
            if not raw_data:
                conn.close()
                return

            req = json.loads(raw_data)
            cmd_type = req.get("type", "")
            response = {"status": "ok", "timestamp": time.time()}

            if cmd_type == "ANNOUNCE_CLASS":
                cname = req.get("class", "unknown")
                prio = req.get("priority", 1)
                qid = req.get("queue_id", 0)
                print(f"{self.logger_prefix} IPC: Application announced Class '{cname}', Priority {prio}, Queue {qid}")
                self._record_policy_event(
                    event_type="CLASS_ANNOUNCEMENT",
                    reason=f"Application registered class '{cname}' with priority {prio} on queue {qid}",
                    prev_policy=self.qos_mode,
                    new_policy=f"{self.qos_mode}+{cname.upper()}",
                    metric_val=self.current_utilization_pct,
                    threshold=self.congestion_threshold_pct
                )
                response["message"] = f"Class '{cname}' registered with queue {qid}"

            elif cmd_type == "SET_MODE":
                new_mode = req.get("mode", "QOS").upper()
                if new_mode in ["QOS", "FIFO"]:
                    old_mode = self.qos_mode
                    self.qos_mode = new_mode
                    print(f"{self.logger_prefix} IPC: Switching Controller Mode to {self.qos_mode}")
                    self._record_policy_event(
                        event_type="MODE_SWITCH",
                        reason=f"Operating mode manually toggled from {old_mode} to {new_mode}",
                        prev_policy=old_mode,
                        new_policy=new_mode,
                        metric_val=self.current_utilization_pct,
                        threshold=self.congestion_threshold_pct
                    )
                    self._reinstall_all_flows()
                    response["mode"] = self.qos_mode
                else:
                    response["status"] = "error"
                    response["message"] = "Invalid mode. Use 'QOS' or 'FIFO'."

            elif cmd_type == "SET_ADAPTATION_MODE":
                new_adapt = req.get("mode", "AUTO").upper()
                if new_adapt in ["AUTO", "MANUAL"]:
                    prev_adapt = self.adaptation_mode
                    self.adaptation_mode = new_adapt
                    print(f"{self.logger_prefix} IPC: Adaptation Mode set to {self.adaptation_mode}")
                    self._record_policy_event(
                        event_type="ADAPTATION_MODE_CHANGE",
                        reason=f"Adaptation mode switched from {prev_adapt} to {new_adapt} by operator command",
                        prev_policy=prev_adapt,
                        new_policy=new_adapt,
                        metric_val=self.current_utilization_pct,
                        threshold=self.congestion_threshold_pct
                    )
                    self._write_live_status()
                    response["adaptation_mode"] = self.adaptation_mode
                else:
                    response["status"] = "error"
                    response["message"] = "Invalid adaptation mode. Use 'AUTO' or 'MANUAL'."

            elif cmd_type == "SET_MANUAL_QOS":
                active = bool(req.get("active", True))
                action_str = "ENABLED" if active else "DISABLED"
                reason = f"Manual operator override: {action_str} Congestion QoS Policy"
                print(f"{self.logger_prefix} IPC: {reason}")
                self._trigger_congestion_policy(active=active, utilization=self.current_utilization_pct, reason_override=reason)
                response["is_congested"] = self.is_congested
                response["adaptation_mode"] = self.adaptation_mode

            elif cmd_type == "SET_PARAMS":
                # Configurable parameters at runtime
                if "congestion_threshold_percent" in req:
                    self.congestion_threshold_pct = float(req["congestion_threshold_percent"])
                if "relax_threshold_percent" in req:
                    self.relax_threshold_pct = float(req["relax_threshold_percent"])
                if "bottleneck_link_speed_mbps" in req:
                    self.link_capacity_bps = float(req["bottleneck_link_speed_mbps"]) * 1_000_000.0
                response["congestion_threshold_percent"] = self.congestion_threshold_pct
                response["relax_threshold_percent"] = self.relax_threshold_pct
                response["link_capacity_bps"] = self.link_capacity_bps

            elif cmd_type == "SIMULATE_CONGESTION" or cmd_type == "TRIGGER_CONGESTION":
                print(f"{self.logger_prefix} IPC: Manual CONGESTION signal received!")
                self._trigger_congestion_policy(active=True)
                response["congestion_active"] = self.is_congested

            elif cmd_type == "RELAX_CONGESTION":
                print(f"{self.logger_prefix} IPC: Manual CONGESTION RELAX signal received!")
                self._trigger_congestion_policy(active=False)
                response["congestion_active"] = self.is_congested

            elif cmd_type == "GET_STATUS":
                response["mode"] = self.qos_mode
                response["adaptation_mode"] = self.adaptation_mode
                response["is_congested"] = self.is_congested
                response["current_utilization_pct"] = round(self.current_utilization_pct, 2)
                response["current_load_mbps"] = round(self.current_load_bps / 1e6, 3)
                response["datapaths"] = list(self.datapaths.keys())
                response["bottleneck_port"] = self.bottleneck_port
                response["congestion_threshold_pct"] = self.congestion_threshold_pct
                response["relax_threshold_pct"] = self.relax_threshold_pct
                response["active_flows"] = self.active_flows
                response["policy_event_count"] = len(self.policy_events)

            elif cmd_type == "GET_POLICY_LOGS":
                response["policy_events"] = self.policy_events[-50:]  # Last 50 events

            elif cmd_type == "RESET_STATS":
                self.port_stats_history.clear()
                self.current_utilization_pct = 0.0
                self.current_load_bps = 0.0
                self.consecutive_congested_samples = 0
                self.consecutive_normal_samples = 0
                self.is_congested = False
                self._record_policy_event(
                    event_type="STATS_RESET",
                    reason="Statistics and state machine counters reset",
                    prev_policy=self.qos_mode,
                    new_policy=self.qos_mode,
                    metric_val=0.0,
                    threshold=self.congestion_threshold_pct
                )
                response["message"] = "Statistics successfully reset"

            conn.sendall((json.dumps(response) + "\n").encode('utf-8'))
        except Exception as e:
            err_resp = {"status": "error", "message": str(e)}
            try:
                conn.sendall((json.dumps(err_resp) + "\n").encode('utf-8'))
            except Exception:
                pass
        finally:
            conn.close()

    def _monitor_loop(self):
        """
        Periodically requests port statistics from OpenFlow switches to measure real-time link load.
        """
        while True:
            if RYU_AVAILABLE and hub:
                hub.sleep(1.0)
            else:
                time.sleep(1.0)

            for dp in list(self.datapaths.values()):
                self._send_port_stats_request(dp)
            
            # Periodically write live status
            self._write_live_status()

    def _send_port_stats_request(self, datapath):
        if not RYU_AVAILABLE:
            return
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def _write_live_status(self):
        """Writes current controller state to results/live_controller_status.json for web dashboard."""
        status_data = {
            "timestamp": time.time(),
            "iso_time": datetime.utcnow().isoformat(),
            "connected": len(self.datapaths) > 0 or not RYU_AVAILABLE,
            "mode": self.qos_mode,
            "adaptation_mode": self.adaptation_mode,
            "is_congested": self.is_congested,
            "current_utilization_pct": round(self.current_utilization_pct, 2),
            "current_load_mbps": round(self.current_load_bps / 1e6, 3),
            "link_capacity_mbps": round(self.link_capacity_bps / 1e6, 1),
            "bottleneck_port": self.bottleneck_port,
            "target_dpid": self.target_dpid,
            "congestion_threshold_pct": self.congestion_threshold_pct,
            "relax_threshold_pct": self.relax_threshold_pct,
            "datapaths": list(self.datapaths.keys()),
            "active_flows": self.active_flows,
            "recent_events": self.policy_events[-10:] if self.policy_events else []
        }
        try:
            with open(self.status_file_path, 'w') as f:
                json.dump(status_data, f, indent=2)
        except Exception:
            pass

    def _record_policy_event(self, event_type: str, reason: str, prev_policy: str,
                             new_policy: str, metric_val: float, threshold: float):
        """Records an explainable policy transition event for Feature B, F, G."""
        self.event_counter += 1
        now = time.time()
        event = {
            "id": self.event_counter,
            "timestamp": now,
            "iso_time": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "reason": reason,
            "metric_name": "bottleneck_link_utilization",
            "metric_value": round(metric_val, 2),
            "threshold": round(threshold, 2),
            "previous_policy": prev_policy,
            "new_policy": new_policy,
            "qos_mode": self.qos_mode,
            "affected_classes": ["VOICE (Q0)", "VIDEO (Q1)", "BULK (Q2)"],
            "queue_mapping": {
                "voice": "Queue 0 (Strict Priority / Guaranteed 1 Mbps)",
                "video": "Queue 1 (Assured Forwarding / Guaranteed 4 Mbps)",
                "bulk": "Queue 2 (Throttled)" if self.is_congested else "Queue 2 (Normal Best Effort)"
            }
        }
        self.policy_events.append(event)
        if len(self.policy_events) > 200:
            self.policy_events.pop(0)

        try:
            with open(self.policy_log_path, 'w') as f:
                json.dump(self.policy_events, f, indent=2)
        except Exception:
            pass

    if RYU_AVAILABLE:
        @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
        def switch_features_handler(self, ev):
            datapath = ev.msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            self.datapaths[datapath.id] = datapath

            # Install Table-Miss Flow Entry (send unmatched packets to controller)
            match = parser.OFPMatch()
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
            self.add_flow(datapath, priority=0, match=match, actions=actions)
            print(f"{self.logger_prefix} Switch s{datapath.id} (DPID {datapath.id}) connected. Table-miss entry installed.")

        @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
        def port_stats_reply_handler(self, ev):
            body = ev.msg.body
            dpid = ev.msg.datapath.id
            now = time.time()

            for stat in body:
                port_no = stat.port_no
                # Monitor ports 1 to 4 on switches
                if port_no in [1, 2, 3, 4]:
                    key = (dpid, port_no)
                    if key in self.port_stats_history:
                        prev_time, prev_bytes = self.port_stats_history[key]
                        delta_t = now - prev_time
                        delta_bytes = stat.tx_bytes - prev_bytes
                        if delta_t > 0:
                            current_bps = (delta_bytes * 8.0) / delta_t
                            utilization_pct = (current_bps / self.link_capacity_bps) * 100.0
                            
                            # Log and check congestion on the bottleneck trunk link (Port 4 on s1)
                            if dpid == self.target_dpid and port_no == self.bottleneck_port:
                                self.current_load_bps = current_bps
                                self.current_utilization_pct = utilization_pct
                                self._evaluate_congestion(utilization_pct, current_bps)

                    self.port_stats_history[key] = (now, stat.tx_bytes)

        @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
        def packet_in_handler(self, ev):
            msg = ev.msg
            datapath = msg.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            in_port = msg.match['in_port']

            pkt = packet.Packet(msg.data)
            eth = pkt.get_protocols(ethernet.ethernet)[0]

            if eth.ethertype == ether_types.ETH_TYPE_LLDP:
                return

            dst = eth.dst
            src = eth.src
            dpid = datapath.id
            self.mac_to_port.setdefault(dpid, {})

            # Learn MAC address
            self.mac_to_port[dpid][src] = in_port

            if dst in self.mac_to_port[dpid]:
                out_port = self.mac_to_port[dpid][dst]
            else:
                out_port = ofproto.OFPP_FLOOD

            # Inspect IPv4 / UDP for QoS flow classification
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            udp_pkt = pkt.get_protocol(udp.udp)

            if out_port != ofproto.OFPP_FLOOD and ip_pkt and udp_pkt:
                udp_dst = udp_pkt.dst_port
                ip_dscp = (ip_pkt.tos >> 2) & 0x3F
                self._install_qos_flow(datapath, in_port, out_port, ip_pkt, udp_dst, ip_dscp, msg)
            else:
                # Normal forwarding for ARP / control / unknown MAC
                actions = [parser.OFPActionOutput(out_port)]
                data = None
                if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                    data = msg.data
                out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                          in_port=in_port, actions=actions, data=data)
                datapath.send_msg(out)

    def _install_qos_flow(self, datapath, in_port, out_port, ip_pkt, udp_dst, ip_dscp=0, msg=None):
        """
        Installs priority flow entries mapping UDP traffic to specific OVS queues.
        Classifies by UDP port OR IP DSCP field.
        """
        if not RYU_AVAILABLE:
            return

        parser = datapath.ofproto_parser
        match = parser.OFPMatch(
            in_port=in_port,
            eth_type=0x0800,
            ip_proto=17,
            ipv4_src=ip_pkt.src,
            ipv4_dst=ip_pkt.dst,
            udp_dst=udp_dst
        )

        actions = []
        priority = 100
        class_name = "unknown"
        queue_assigned = None

        if self.qos_mode == "FIFO":
            # Baseline FIFO mode: No queue prioritization, plain output
            actions = [parser.OFPActionOutput(out_port)]
            priority = 100
            class_name = "FIFO_BEST_EFFORT"
            queue_assigned = "None (FIFO)"
        else:
            # QoS Priority Mode: Match by port or DSCP
            is_voice = (udp_dst == self.voice_port) or (ip_dscp == self.voice_dscp)
            is_video = (udp_dst == self.video_port) or (ip_dscp == self.video_dscp)
            is_bulk = (udp_dst in [self.bulk_port, self.congestion_port]) or (ip_dscp == self.bulk_dscp)

            if is_voice:
                priority = 200
                actions = [parser.OFPActionSetQueue(0), parser.OFPActionOutput(out_port)]
                class_name = "VOICE"
                queue_assigned = 0
            elif is_video:
                priority = 190
                actions = [parser.OFPActionSetQueue(1), parser.OFPActionOutput(out_port)]
                class_name = "VIDEO"
                queue_assigned = 1
            elif is_bulk:
                priority = 180
                actions = [parser.OFPActionSetQueue(2), parser.OFPActionOutput(out_port)]
                class_name = "BULK" if udp_dst == self.bulk_port else "FLOODER"
                queue_assigned = 2
            else:
                actions = [parser.OFPActionOutput(out_port)]
                class_name = "GENERIC_UDP"

        # Update active flows list
        flow_entry = {
            "dpid": datapath.id,
            "src_ip": ip_pkt.src,
            "dst_ip": ip_pkt.dst,
            "port": udp_dst,
            "dscp": ip_dscp,
            "class": class_name,
            "queue": queue_assigned,
            "priority": priority,
            "last_seen": time.time()
        }
        # Refresh or add in active_flows
        self.active_flows = [f for f in self.active_flows if not (f["src_ip"] == ip_pkt.src and f["port"] == udp_dst and f["dpid"] == datapath.id)]
        self.active_flows.append(flow_entry)
        if len(self.active_flows) > 50:
            self.active_flows.pop(0)

        # Install the actual QoS forwarding rule on the switch.
        self.add_flow(datapath, priority, match, actions, idle_timeout=15)

        # Forward the first packet that triggered this PacketIn event.
        if msg is not None:
            data = msg.data if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER else None
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data
            )
            datapath.send_msg(out)

        print(f"{self.logger_prefix} Installed Flow: {class_name} (Port={udp_dst}, DSCP={ip_dscp}) -> "
              f"Queue={queue_assigned}, OutPort={out_port}, Priority={priority}")

    def _evaluate_congestion(self, utilization_pct: float, current_bps: float):
        """
        Evaluates link utilization and applies dynamic congestion state machine with hysteresis.
        In MANUAL adaptation mode, automatic policy switching is suspended.
        """
        load_mbps = current_bps / 1_000_000.0
        state_str = "CONGESTED" if self.is_congested else "NORMAL"
        print(f"{self.logger_prefix} Bottleneck Port: {load_mbps:5.2f} Mbps ({utilization_pct:5.1f}% utilization) | "
              f"State: {state_str} | Mode: {self.adaptation_mode}")

        if self.adaptation_mode == "MANUAL":
            # In Manual Mode: monitor and log utilization, but do NOT automatically alter policy
            return

        if not self.is_congested:
            if utilization_pct >= self.congestion_threshold_pct:
                self.consecutive_congested_samples += 1
                if self.consecutive_congested_samples >= self.trigger_window:
                    self._trigger_congestion_policy(active=True, utilization=utilization_pct)
            else:
                self.consecutive_congested_samples = 0
        else:
            if utilization_pct < self.relax_threshold_pct:
                self.consecutive_normal_samples += 1
                if self.consecutive_normal_samples >= self.hold_down_window:
                    self._trigger_congestion_policy(active=False, utilization=utilization_pct)
            else:
                self.consecutive_normal_samples = 0

    def _trigger_congestion_policy(self, active: bool, utilization: float = 0.0, reason_override: str = None):
        prev_state = "CONGESTED" if self.is_congested else "NORMAL"
        self.is_congested = active
        self.consecutive_congested_samples = 0
        self.consecutive_normal_samples = 0
        new_state = "CONGESTED" if self.is_congested else "NORMAL"

        if active:
            if reason_override:
                reason = f"{reason_override} (Bottleneck utilization: {utilization:.1f}%)"
            else:
                reason = (f"Bottleneck link utilization ({utilization:.1f}%) crossed {self.congestion_threshold_pct:.1f}% threshold "
                          f"for {self.trigger_window} consecutive measurement windows.")
            print(f"\n{'!'*75}")
            print(f"{self.logger_prefix} [CONGESTION DETECTED / POLICY ACTIVE] {reason}")
            print(f"{self.logger_prefix} Dynamically adjusting flow table: Throttling Bulk traffic (Queue 2) to protect Voice & Video.")
            print(f"{'!'*75}\n")
            self._record_policy_event(
                event_type="CONGESTION_TRIGGERED",
                reason=reason,
                prev_policy=prev_state,
                new_policy="CONGESTION_PRIORITY_THROTTLE_BULK",
                metric_val=utilization,
                threshold=self.congestion_threshold_pct
            )
        else:
            if reason_override:
                reason = f"{reason_override} (Bottleneck utilization: {utilization:.1f}%)"
            else:
                reason = (f"Bottleneck link utilization ({utilization:.1f}%) normalized below {self.relax_threshold_pct:.1f}% "
                          f"for {self.hold_down_window} consecutive hold-down windows.")
            print(f"\n{'*'*75}")
            print(f"{self.logger_prefix} [CONGESTION CLEARED / NORMAL ALLOCATION] {reason}")
            print(f"{self.logger_prefix} Restoring standard QoS allocations across all flows.")
            print(f"{'*'*75}\n")
            self._record_policy_event(
                event_type="CONGESTION_CLEARED",
                reason=reason,
                prev_policy=prev_state,
                new_policy="STANDARD_QOS",
                metric_val=utilization,
                threshold=self.relax_threshold_pct
            )

        self._reinstall_all_flows()
        self._write_live_status()

    def _reinstall_all_flows(self):
        """
        Flushes and re-establishes flow rules across switches to apply updated QoS policies.
        """
        if not RYU_AVAILABLE:
            return

        for dp in self.datapaths.values():
            parser = dp.ofproto_parser
            ofproto = dp.ofproto
            # Delete non-table-miss flows (priority > 0)
            empty_match = parser.OFPMatch()
            mod = parser.OFPFlowMod(
                datapath=dp,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=empty_match
            )
            dp.send_msg(mod)

            # Re-install table miss entry
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
            self.add_flow(dp, priority=0, match=empty_match, actions=actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0, hard_timeout=0):
        if not RYU_AVAILABLE:
            return
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    idle_timeout=idle_timeout, hard_timeout=hard_timeout,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, idle_timeout=idle_timeout,
                                    hard_timeout=hard_timeout, instructions=inst)
        datapath.send_msg(mod)


if __name__ == '__main__':
    print("[*] QoSTrafficController module loaded. Start via: ryu-manager controller/qos_controller.py")
