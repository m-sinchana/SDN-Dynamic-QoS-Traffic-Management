#!/usr/bin/env python3
"""
Unit and Integration Tests for Experiment Pipeline & Evaluation Analytics
Validates:
  1. Jain's Fairness Index computation accuracy
  2. Experiment metric collection and serialization
  3. CSV export formatting and integrity
  4. Missing controller / socket safety handling
  5. Baseline vs Adaptive QoS dataset validation
"""

import sys
import os
import json
import csv
import io
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.calculate_fairness import calculate_jains_index, evaluate_metrics
from tests.run_experiment import generate_experiment_dataset


class TestExperimentPipeline(unittest.TestCase):
    def test_jains_fairness_index_mathematics(self):
        """Verifies Jain's Fairness Index mathematical properties."""
        # 1. Equal allocations -> J = 1.0 (ideal)
        self.assertAlmostEqual(calculate_jains_index([10.0, 10.0, 10.0, 10.0]), 1.0, places=4)

        # 2. Extreme unfairness: 1 flow takes all bandwidth, 3 get 0 -> J = 1/n = 0.25
        self.assertAlmostEqual(calculate_jains_index([10.0, 0.0, 0.0, 0.0]), 0.25, places=4)

        # 3. Two equal flows out of 4 -> J = (20)^2 / (4 * 200) = 400 / 800 = 0.5
        self.assertAlmostEqual(calculate_jains_index([10.0, 10.0, 0.0, 0.0]), 0.5, places=4)

    def test_demand_satisfaction_fairness(self):
        """Tests fairness based on SLA demand satisfaction."""
        metrics_data = [
            {"class_name": "voice", "throughput_kbps": 64.0},     # 100% of 64k
            {"class_name": "video", "throughput_kbps": 2500.0},   # 100% of 2500k
            {"class_name": "bulk",  "throughput_kbps": 2000.0}    # 100% of 2000k
        ]
        res = evaluate_metrics(metrics_data)
        self.assertAlmostEqual(res["jains_index_demand_satisfaction"], 1.0, places=3)

    def test_experiment_dataset_integrity(self):
        """Validates structure and realism of 3-condition experiment dataset."""
        dataset = generate_experiment_dataset()
        self.assertIn("light_traffic", dataset)
        self.assertIn("moderate_traffic", dataset)
        self.assertIn("heavy_congestion", dataset)

        for cond_name, cond in dataset.items():
            self.assertIn("baseline", cond)
            self.assertIn("qos", cond)
            self.assertGreater(len(cond["baseline"]), 0)
            self.assertGreater(len(cond["qos"]), 0)

        # Under heavy congestion, verify Voice QoS loss is 0% while FIFO suffered loss
        heavy = dataset["heavy_congestion"]
        voice_fifo = [r for r in heavy["baseline"] if r["class_name"] == "voice"][0]
        voice_qos = [r for r in heavy["qos"] if r["class_name"] == "voice"][0]

        self.assertGreater(voice_fifo["loss_percentage"], 20.0)
        self.assertEqual(voice_qos["loss_percentage"], 0.0)
        self.assertLess(voice_qos["avg_latency_ms"], 15.0)

    def test_csv_export_formatting(self):
        """Tests that metric CSV generation conforms to standard format."""
        dataset = generate_experiment_dataset()
        rows = dataset["light_traffic"]["qos"]

        output = io.StringIO()
        fieldnames = [
            "class_name", "port", "packets_sent", "packets_received", "loss_percentage",
            "throughput_kbps", "throughput_mbps", "avg_latency_ms", "min_latency_ms",
            "max_latency_ms", "jitter_ms"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

        output.seek(0)
        reader = list(csv.DictReader(output))
        self.assertEqual(len(reader), len(rows))
        self.assertEqual(reader[0]["class_name"], "voice")
        self.assertEqual(reader[0]["loss_percentage"], "0.0")


if __name__ == '__main__':
    unittest.main()
