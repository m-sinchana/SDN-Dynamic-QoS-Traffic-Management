#!/usr/bin/env python3
"""
Unit and Integration Tests for SDN Controller Logic & Dynamic State Machine
Validates:
  1. Traffic-class classification (UDP port and DSCP matching)
  2. Congestion threshold detection & window counting
  3. Dynamic QoS policy state transitions (NORMAL <-> CONGESTED)
  4. Hysteresis and hold-down timer behavior
  5. Policy audit event logging and explainability records
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from controller.qos_controller import QoSTrafficController


class MockController(QoSTrafficController):
    """Subclass without spawning real network threads to test pure logic."""
    def __init__(self):
        self.project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self.results_dir = os.path.join(self.project_dir, 'results')
        self.config_dir = os.path.join(self.project_dir, 'config')
        os.makedirs(self.results_dir, exist_ok=True)
        self._load_config()

        self.consecutive_congested_samples = 0
        self.consecutive_normal_samples = 0
        self.is_congested = False
        self.qos_mode = "QOS"
        self.adaptation_mode = "AUTO"

        self.voice_port = 5001
        self.video_port = 5002
        self.bulk_port = 5003
        self.congestion_port = 5004

        self.voice_dscp = 46
        self.video_dscp = 34
        self.bulk_dscp = 0

        self.current_utilization_pct = 0.0
        self.current_load_bps = 0.0
        self.active_flows = []
        self.policy_events = []
        self.event_counter = 0
        self.datapaths = {}
        self.logger_prefix = "[Mock-Controller]"

        self.status_file_path = os.path.join(self.results_dir, "test_controller_status.json")
        self.policy_log_path = os.path.join(self.results_dir, "test_policy_events.json")


class TestControllerLogic(unittest.TestCase):
    def setUp(self):
        self.ctrl = MockController()

    def test_classification_logic(self):
        """Verifies mapping of ports and DSCP to traffic classes and queue IDs."""
        test_cases = [
            {"port": 5001, "dscp": 46, "expected_queue": 0, "name": "VOICE"},
            {"port": 5002, "dscp": 34, "expected_queue": 1, "name": "VIDEO"},
            {"port": 5003, "dscp": 0,  "expected_queue": 2, "name": "BULK"},
            {"port": 5004, "dscp": 0,  "expected_queue": 2, "name": "FLOODER"}
        ]
        for tc in test_cases:
            is_voice = (tc["port"] == self.ctrl.voice_port) or (tc["dscp"] == self.ctrl.voice_dscp)
            is_video = (tc["port"] == self.ctrl.video_port) or (tc["dscp"] == self.ctrl.video_dscp)
            is_bulk = (tc["port"] in [self.ctrl.bulk_port, self.ctrl.congestion_port]) or (tc["dscp"] == self.ctrl.bulk_dscp)

            if is_voice:
                assigned_q = 0
            elif is_video:
                assigned_q = 1
            elif is_bulk:
                assigned_q = 2
            else:
                assigned_q = None

            self.assertEqual(assigned_q, tc["expected_queue"], f"Failed for {tc['name']}")

    def test_congestion_detection_state_machine(self):
        """Tests threshold detection: 2 consecutive samples >= 80% triggers CONGESTION."""
        self.assertFalse(self.ctrl.is_congested)
        self.ctrl.congestion_threshold_pct = 80.0
        self.ctrl.trigger_window = 2

        # Sample 1: 85% (1 sample above threshold) -> should not trigger yet
        self.ctrl._evaluate_congestion(utilization_pct=85.0, current_bps=8_500_000.0)
        self.assertFalse(self.ctrl.is_congested, "Triggered too early on 1st sample")
        self.assertEqual(self.ctrl.consecutive_congested_samples, 1)

        # Sample 2: 90% (2nd sample above threshold) -> should trigger!
        self.ctrl._evaluate_congestion(utilization_pct=90.0, current_bps=9_000_000.0)
        self.assertTrue(self.ctrl.is_congested, "Failed to transition to CONGESTED on 2nd sample")
        self.assertGreater(len(self.ctrl.policy_events), 0)
        last_event = self.ctrl.policy_events[-1]
        self.assertEqual(last_event["event_type"], "CONGESTION_TRIGGERED")

    def test_hysteresis_and_cooldown_behavior(self):
        """Tests that congestion relaxes only after 4 consecutive samples < 60%."""
        self.ctrl.is_congested = True
        self.ctrl.relax_threshold_pct = 60.0
        self.ctrl.hold_down_window = 4

        # Samples 1, 2, 3 below 60% -> should remain CONGESTED
        for i in range(1, 4):
            self.ctrl._evaluate_congestion(utilization_pct=50.0, current_bps=5_000_000.0)
            self.assertTrue(self.ctrl.is_congested, f"Relaxed too early on sample {i}")
            self.assertEqual(self.ctrl.consecutive_normal_samples, i)

        # Brief spike back to 65% -> resets consecutive counter
        self.ctrl._evaluate_congestion(utilization_pct=65.0, current_bps=6_500_000.0)
        self.assertTrue(self.ctrl.is_congested)
        self.assertEqual(self.ctrl.consecutive_normal_samples, 0)

        # Now 4 full samples below 60%
        for i in range(1, 4):
            self.ctrl._evaluate_congestion(utilization_pct=45.0, current_bps=4_500_000.0)
            self.assertTrue(self.ctrl.is_congested)

        self.ctrl._evaluate_congestion(utilization_pct=45.0, current_bps=4_500_000.0)
        self.assertFalse(self.ctrl.is_congested, "Failed to relax after 4 consecutive normal samples")
        last_event = self.ctrl.policy_events[-1]
        self.assertEqual(last_event["event_type"], "CONGESTION_CLEARED")

    def test_policy_event_logging(self):
        """Verifies policy events contain required audit fields."""
        self.ctrl._record_policy_event(
            event_type="TEST_POLICY_EVENT",
            reason="Integration test evaluation",
            prev_policy="STANDARD_QOS",
            new_policy="CONGESTION_THROTTLED",
            metric_val=85.4,
            threshold=80.0
        )
        self.assertEqual(len(self.ctrl.policy_events), 1)
        ev = self.ctrl.policy_events[0]
        self.assertIn("timestamp", ev)
        self.assertIn("reason", ev)
        self.assertIn("previous_policy", ev)
        self.assertIn("new_policy", ev)
        self.assertIn("metric_value", ev)
        self.assertEqual(ev["metric_value"], 85.4)

    def test_manual_mode_prevents_automatic_triggering(self):
        """
        Verifies that when adaptation_mode is 'MANUAL', high link utilization
        does NOT automatically trigger congestion policy.
        """
        self.ctrl.adaptation_mode = "MANUAL"
        self.assertFalse(self.ctrl.is_congested)

        # Send multiple consecutive heavy overload samples (95% load)
        for _ in range(5):
            self.ctrl._evaluate_congestion(utilization_pct=95.0, current_bps=9_500_000.0)

        # In MANUAL mode, automatic state transition MUST NOT occur
        self.assertFalse(self.ctrl.is_congested, "Manual mode failed to suppress automatic trigger!")
        self.assertEqual(len(self.ctrl.policy_events), 0, "Policy events were logged during suppressed manual mode")

    def test_manual_policy_toggling(self):
        """
        Verifies operator can manually enable and disable congestion QoS policy
        with explicit audit reason override.
        """
        self.ctrl.adaptation_mode = "MANUAL"
        self.assertFalse(self.ctrl.is_congested)

        # Operator manually enables congestion policy
        self.ctrl._trigger_congestion_policy(active=True, utilization=75.0,
                                             reason_override="Manual operator override: ENABLED")
        self.assertTrue(self.ctrl.is_congested)
        self.assertEqual(len(self.ctrl.policy_events), 1)
        self.assertIn("Manual operator override: ENABLED", self.ctrl.policy_events[-1]["reason"])

        # Operator manually disables congestion policy
        self.ctrl._trigger_congestion_policy(active=False, utilization=75.0,
                                             reason_override="Manual operator override: DISABLED")
        self.assertFalse(self.ctrl.is_congested)
        self.assertEqual(len(self.ctrl.policy_events), 2)
        self.assertIn("Manual operator override: DISABLED", self.ctrl.policy_events[-1]["reason"])


if __name__ == '__main__':
    unittest.main()
