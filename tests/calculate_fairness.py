#!/usr/bin/env python3
"""
QoS Traffic Management System - Fairness Evaluation (Jain's Fairness Index)
Calculates Jain's Fairness Index across multiple traffic classes:
  J(x_1, x_2, ..., x_n) = (sum(x_i))^2 / (n * sum(x_i^2))
Evaluates fairness based on:
  1. Absolute Achieved Throughput
  2. Normalized Demand Satisfaction (Achieved / Target Demand)
"""

import sys
import os
import json
import csv
import argparse


def calculate_jains_index(allocations: list) -> float:
    """
    Computes Jain's Fairness Index for a list of non-negative numeric allocations.
    Returns value in [1/n, 1.0].
    """
    if not allocations or len(allocations) == 0:
        return 0.0

    n = len(allocations)
    sum_x = sum(allocations)
    sum_x_sq = sum(x ** 2 for x in allocations)

    if sum_x_sq == 0:
        return 1.0

    index = (sum_x ** 2) / (n * sum_x_sq)
    return round(index, 4)


def evaluate_metrics(results_data: list, config_data: dict = None) -> dict:
    """
    Evaluates fairness and SLA compliance from experiment metrics summary.
    """
    class_targets = {
        "voice": 64.0,       # kbps
        "video": 2500.0,     # kbps
        "bulk": 2000.0       # kbps
    }
    if config_data and "classes" in config_data:
        for cname, cinfo in config_data["classes"].items():
            if "target_rate_kbps" in cinfo:
                class_targets[cname] = cinfo["target_rate_kbps"]

    throughputs_kbps = []
    demand_satisfactions = []
    evaluation_rows = []

    for row in results_data:
        cname = row.get("class_name", "unknown")
        if cname in ["congestion_flooder"]:
            continue  # Exclude artificial disturber flow from fairness index of production classes

        achieved_kbps = float(row.get("throughput_kbps", 0.0))
        target_kbps = class_targets.get(cname, achieved_kbps if achieved_kbps > 0 else 1.0)
        satisfaction = min(1.0, achieved_kbps / target_kbps) if target_kbps > 0 else 1.0

        throughputs_kbps.append(achieved_kbps)
        demand_satisfactions.append(satisfaction)

        evaluation_rows.append({
            "class_name": cname,
            "target_kbps": target_kbps,
            "achieved_kbps": achieved_kbps,
            "satisfaction_ratio": round(satisfaction, 3),
            "loss_pct": float(row.get("loss_percentage", 0.0)),
            "latency_ms": float(row.get("avg_latency_ms", 0.0)),
            "jitter_ms": float(row.get("jitter_ms", 0.0))
        })

    raw_jain = calculate_jains_index(throughputs_kbps)
    demand_jain = calculate_jains_index(demand_satisfactions)

    return {
        "rows": evaluation_rows,
        "jains_index_throughput": raw_jain,
        "jains_index_demand_satisfaction": demand_jain
    }


def main():
    parser = argparse.ArgumentParser(description="Jain's Fairness Index Calculator")
    parser.add_argument("--json", help="Path to receiver metrics JSON output")
    parser.add_argument("--csv", help="Path to receiver metrics CSV output")
    parser.add_argument("--config", default="config/traffic_config.json", help="Path to traffic config")
    args = parser.parse_args()

    data = []
    if args.json and os.path.exists(args.json):
        with open(args.json, 'r') as f:
            data = json.load(f)
    elif args.csv and os.path.exists(args.csv):
        with open(args.csv, 'r') as f:
            reader = csv.DictReader(f)
            data = list(reader)
    else:
        # Default representative test data if no file provided
        print("[*] No input file specified. Displaying demonstration comparison:")
        data = [
            {"class_name": "voice", "throughput_kbps": 64.0, "loss_percentage": 0.0, "avg_latency_ms": 11.2, "jitter_ms": 0.8},
            {"class_name": "video", "throughput_kbps": 2490.0, "loss_percentage": 0.4, "avg_latency_ms": 14.5, "jitter_ms": 1.9},
            {"class_name": "bulk",  "throughput_kbps": 1950.0, "loss_percentage": 2.5, "avg_latency_ms": 22.0, "jitter_ms": 4.1}
        ]

    config_data = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config_data = json.load(f)

    result = evaluate_metrics(data, config_data)

    print("\n" + "=" * 80)
    print(" FAIRNESS AND QUALITY-OF-SERVICE EVALUATION")
    print("=" * 80)
    header = "{:<10} {:<12} {:<14} {:<14} {:<10} {:<10} {:<10}"
    print(header.format("Class", "Target(kbps)", "Achieved(kbps)", "Satisfaction", "Loss %", "Delay(ms)", "Jitter(ms)"))
    print("-" * 80)
    for r in result["rows"]:
        row_str = "{:<10} {:<12.1f} {:<14.1f} {:<14.3f} {:<10.2f} {:<10.2f} {:<10.2f}"
        print(row_str.format(
            r["class_name"], r["target_kbps"], r["achieved_kbps"],
            r["satisfaction_ratio"], r["loss_pct"], r["latency_ms"], r["jitter_ms"]
        ))
    print("-" * 80)
    print(f"Jain's Fairness Index (Raw Throughput):       {result['jains_index_throughput']:.4f}")
    print(f"Jain's Fairness Index (Demand Satisfaction):   {result['jains_index_demand_satisfaction']:.4f}  (1.0 = Ideal Fair Share)")
    print("=" * 80 + "\n")


if __name__ == '__main__':
    main()
