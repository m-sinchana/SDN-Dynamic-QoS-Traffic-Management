#!/usr/bin/env python3
"""
QoS Traffic Management System - Results Visualizer & Graph Generator
Generates:
  1. High-resolution dark-mode performance & comparison plots (PNG) using matplotlib
  2. Structured metric JSON summaries for web dashboard integration
  3. Interactive HTML/SVG evaluation dashboard synchronization
  4. ASCII terminal bar charts for instant terminal inspection
"""

import os
import sys
import json
import csv
import argparse

# Configure writable cache directory for matplotlib before import
if 'MPLCONFIGDIR' not in os.environ:
    os.environ['MPLCONFIGDIR'] = '/tmp/matplotlib_cache'
os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)

# Check for matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')


def setup_dark_style():
    """Configures matplotlib rcParams to match the dashboard dark theme."""
    if not MATPLOTLIB_AVAILABLE:
        return
    plt.rcParams.update({
        'figure.facecolor': '#1e293b',
        'axes.facecolor': '#0f172a',
        'text.color': '#f8fafc',
        'axes.labelcolor': '#94a3b8',
        'xtick.color': '#94a3b8',
        'ytick.color': '#94a3b8',
        'grid.color': '#334155',
        'grid.linestyle': '--',
        'grid.alpha': 0.6,
        'font.size': 10
    })


def parse_metrics_csv(csv_path: str) -> list:
    """
    Parses any experiment CSV file (19-col receiver output, 11-col study output,
    or 8-col export format) and returns a list of normalized class metric dicts.
    Handles missing or corrupted columns gracefully.
    """
    if not os.path.exists(csv_path):
        return []

    rows = []
    try:
        raw_items = []
        if csv_path.endswith('.json'):
            with open(csv_path, 'r', encoding='utf-8') as f:
                jdata = json.load(f)
            if isinstance(jdata, list):
                raw_items = jdata
            elif isinstance(jdata, dict):
                if "per_class" in jdata and isinstance(jdata["per_class"], dict):
                    raw_items = list(jdata["per_class"].values())
                else:
                    raw_items = [jdata]
        else:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_items = list(reader)

        for r in raw_items:
            cname = (r.get("class_name") or r.get("class") or "").strip().lower()
            if not cname:
                continue

                # Throughput Mbps
                tp = 0.0
                try:
                    if r.get("throughput_mbps"):
                        tp = float(r.get("throughput_mbps"))
                    elif r.get("throughput_kbps"):
                        tp = float(r.get("throughput_kbps")) / 1000.0
                except (ValueError, TypeError):
                    tp = 0.0

                # Loss Percentage
                loss = 0.0
                try:
                    if r.get("loss_percentage") is not None:
                        loss = float(r.get("loss_percentage"))
                except (ValueError, TypeError):
                    loss = 0.0

                # Latency
                lat = 0.0
                try:
                    if r.get("avg_latency_ms") is not None:
                        lat = float(r.get("avg_latency_ms"))
                except (ValueError, TypeError):
                    lat = 0.0

                # Jitter
                jit = 0.0
                try:
                    if r.get("jitter_ms") is not None:
                        jit = float(r.get("jitter_ms"))
                except (ValueError, TypeError):
                    jit = 0.0

                # Packets
                rx_pkts = 0
                lost_pkts = 0
                try:
                    rx_pkts = int(float(r.get("packets_received", 0) or 0))
                except (ValueError, TypeError):
                    rx_pkts = 0
                try:
                    lost_pkts = int(float(r.get("packets_lost", 0) or 0))
                except (ValueError, TypeError):
                    lost_pkts = 0

                rows.append({
                    "class_name": cname,
                    "port": r.get("port", ""),
                    "throughput_mbps": round(tp, 3),
                    "loss_percentage": round(loss, 2),
                    "avg_latency_ms": round(lat, 2),
                    "jitter_ms": round(jit, 2),
                    "packets_received": rx_pkts,
                    "packets_lost": lost_pkts
                })
    except Exception as e:
        print(f"[-] Warning: Failed to parse CSV {csv_path}: {e}")

    return rows


def plot_live_run(csv_path: str, out_dir: str = None, out_name: str = "live_run_performance.png") -> dict:
    """
    Generates performance chart (Throughput, Loss, Latency by class) from a single experiment CSV.
    Saves PNG chart and latest_run_metrics.json.
    """
    if out_dir is None:
        out_dir = RESULTS_DIR
    os.makedirs(out_dir, exist_ok=True)

    rows = parse_metrics_csv(csv_path)
    if not rows:
        return {"success": False, "error": f"No valid metric rows found in {csv_path}"}

    # Filter for standard classes
    labels = []
    throughputs = []
    losses = []
    latencies = []
    jitters = []
    class_dict = {}

    color_map = {
        'VOICE': '#22c55e',
        'VIDEO': '#a855f7',
        'BULK': '#f59e0b',
        'CONGESTION_FLOODER': '#ef4444'
    }

    bar_colors = []
    for r in rows:
        cname = r["class_name"].upper()
        if cname == "CONGESTION_FLOODER" and len(rows) > 3:
            # Skip flooder from default 3-class plot for cleaner view, but store in json
            class_dict[r["class_name"]] = r
            continue
        labels.append(cname)
        throughputs.append(r["throughput_mbps"])
        losses.append(r["loss_percentage"])
        latencies.append(r["avg_latency_ms"])
        jitters.append(r["jitter_ms"])
        bar_colors.append(color_map.get(cname, '#38bdf8'))
        class_dict[r["class_name"]] = r

    # Save structured JSON
    metrics_summary_path = os.path.join(out_dir, "latest_run_metrics.json")
    try:
        with open(metrics_summary_path, 'w') as f:
            json.dump({
                "source_csv": os.path.basename(csv_path),
                "timestamp": os.path.getmtime(csv_path) if os.path.exists(csv_path) else 0,
                "classes": class_dict
            }, f, indent=2)
    except Exception:
        pass

    out_png = os.path.join(out_dir, out_name)
    if not MATPLOTLIB_AVAILABLE or not labels:
        return {"success": True, "metrics": class_dict, "chart": None}

    try:
        setup_dark_style()
        fig, axes = plt.subplots(1, 3, figsize=(11, 4.2))
        fig.patch.set_facecolor('#1e293b')

        # Subplot 1: Throughput
        ax1 = axes[0]
        ax1.set_facecolor('#0f172a')
        bars1 = ax1.bar(labels, throughputs, color=bar_colors, width=0.55, edgecolor='#334155', linewidth=1)
        ax1.set_ylabel('Throughput (Mbps)', fontweight='600')
        ax1.set_title('Throughput by Class', fontsize=12, fontweight='700', color='#38bdf8', pad=10)
        ax1.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax1.spines.values():
            spine.set_color('#334155')
        # Annotate bars
        for b in bars1:
            h = b.get_height()
            ax1.annotate(f"{h:.2f}M", xy=(b.get_x() + b.get_width() / 2, h),
                         xytext=(0, 4), textcoords="offset points", ha='center', va='bottom',
                         fontsize=9, color='#f8fafc', fontweight='600')
        ax1.set_ylim(0, max(max(throughputs + [0.1]) * 1.25, 0.5))

        # Subplot 2: Packet Loss
        ax2 = axes[1]
        ax2.set_facecolor('#0f172a')
        loss_colors = ['#22c55e' if l < 2.0 else ('#f59e0b' if l < 15.0 else '#ef4444') for l in losses]
        bars2 = ax2.bar(labels, losses, color=loss_colors, width=0.55, edgecolor='#334155', linewidth=1)
        ax2.set_ylabel('Packet Loss (%)', fontweight='600')
        ax2.set_title('Packet Loss by Class', fontsize=12, fontweight='700', color='#38bdf8', pad=10)
        ax2.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax2.spines.values():
            spine.set_color('#334155')
        for b in bars2:
            h = b.get_height()
            ax2.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h),
                         xytext=(0, 4), textcoords="offset points", ha='center', va='bottom',
                         fontsize=9, color='#f8fafc', fontweight='600')
        ax2.set_ylim(0, max(max(losses + [5.0]) * 1.25, 10.0))

        # Subplot 3: Latency
        ax3 = axes[2]
        ax3.set_facecolor('#0f172a')
        lat_colors = ['#22c55e' if lt < 20.0 else ('#f59e0b' if lt < 60.0 else '#ef4444') for lt in latencies]
        bars3 = ax3.bar(labels, latencies, color=lat_colors, width=0.55, edgecolor='#334155', linewidth=1)
        ax3.set_ylabel('Average Latency (ms)', fontweight='600')
        ax3.set_title('Avg Latency by Class', fontsize=12, fontweight='700', color='#38bdf8', pad=10)
        ax3.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax3.spines.values():
            spine.set_color('#334155')
        for b in bars3:
            h = b.get_height()
            ax3.annotate(f"{h:.1f}ms", xy=(b.get_x() + b.get_width() / 2, h),
                         xytext=(0, 4), textcoords="offset points", ha='center', va='bottom',
                         fontsize=9, color='#f8fafc', fontweight='600')
        ax3.set_ylim(0, max(max(latencies + [10.0]) * 1.25, 20.0))

        plt.suptitle(f"Performance Metrics: {os.path.basename(csv_path)}",
                     fontsize=13, fontweight='700', color='#f8fafc', y=0.98)
        plt.tight_layout()
        plt.subplots_adjust(top=0.88)
        plt.savefig(out_png, dpi=180, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        print(f"[+] Successfully generated live performance chart: {out_png}")

        # Also generate individual charts for modular dashboard widgets
        # 1. Individual Throughput Chart
        fig_tp, ax_tp = plt.subplots(figsize=(6.5, 3.8))
        fig_tp.patch.set_facecolor('#1e293b')
        ax_tp.set_facecolor('#0f172a')
        b_tp = ax_tp.bar(labels, throughputs, color=bar_colors, width=0.5, edgecolor='#334155', linewidth=1)
        ax_tp.set_ylabel('Throughput (Mbps)', fontweight='600')
        ax_tp.set_title(f'Throughput by Traffic Class\n({os.path.basename(csv_path)})', fontsize=11, fontweight='700', color='#38bdf8', pad=10)
        ax_tp.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax_tp.spines.values():
            spine.set_color('#334155')
        for b in b_tp:
            h = b.get_height()
            ax_tp.annotate(f"{h:.2f} Mbps", xy=(b.get_x() + b.get_width() / 2, h),
                           xytext=(0, 4), textcoords="offset points", ha='center', va='bottom',
                           fontsize=9, color='#f8fafc', fontweight='600')
        ax_tp.set_ylim(0, max(max(throughputs + [0.1]) * 1.25, 0.5))
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "live_run_throughput.png"), dpi=180, facecolor=fig_tp.get_facecolor(), edgecolor='none')
        plt.close(fig_tp)

        # 2. Individual Loss Chart
        fig_ls, ax_ls = plt.subplots(figsize=(6.5, 3.8))
        fig_ls.patch.set_facecolor('#1e293b')
        ax_ls.set_facecolor('#0f172a')
        b_ls = ax_ls.bar(labels, losses, color=loss_colors, width=0.5, edgecolor='#334155', linewidth=1)
        ax_ls.set_ylabel('Packet Loss (%)', fontweight='600')
        ax_ls.set_title(f'Packet Loss by Traffic Class\n({os.path.basename(csv_path)})', fontsize=11, fontweight='700', color='#38bdf8', pad=10)
        ax_ls.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax_ls.spines.values():
            spine.set_color('#334155')
        for b in b_ls:
            h = b.get_height()
            ax_ls.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h),
                           xytext=(0, 4), textcoords="offset points", ha='center', va='bottom',
                           fontsize=9, color='#f8fafc', fontweight='600')
        ax_ls.set_ylim(0, max(max(losses + [5.0]) * 1.25, 10.0))
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "live_run_loss.png"), dpi=180, facecolor=fig_ls.get_facecolor(), edgecolor='none')
        plt.close(fig_ls)

        # 3. Individual Latency Chart
        fig_lt, ax_lt = plt.subplots(figsize=(6.5, 3.8))
        fig_lt.patch.set_facecolor('#1e293b')
        ax_lt.set_facecolor('#0f172a')
        b_lt = ax_lt.bar(labels, latencies, color=lat_colors, width=0.5, edgecolor='#334155', linewidth=1)
        ax_lt.set_ylabel('Average Latency (ms)', fontweight='600')
        ax_lt.set_title(f'Average Latency by Traffic Class\n({os.path.basename(csv_path)})', fontsize=11, fontweight='700', color='#38bdf8', pad=10)
        ax_lt.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax_lt.spines.values():
            spine.set_color('#334155')
        for b in b_lt:
            h = b.get_height()
            ax_lt.annotate(f"{h:.1f} ms", xy=(b.get_x() + b.get_width() / 2, h),
                           xytext=(0, 4), textcoords="offset points", ha='center', va='bottom',
                           fontsize=9, color='#f8fafc', fontweight='600')
        ax_lt.set_ylim(0, max(max(latencies + [10.0]) * 1.25, 20.0))
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "live_run_latency.png"), dpi=180, facecolor=fig_lt.get_facecolor(), edgecolor='none')
        plt.close(fig_lt)
    except Exception as e:
        print(f"[-] Matplotlib plot_live_run error: {e}")

    return {"success": True, "metrics": class_dict, "chart": out_png}


def plot_comparison(base_csv: str, qos_csv: str, out_dir: str = None,
                    title_suffix: str = "Heavy Congestion (10 Mbps Bottleneck)") -> dict:
    """
    Compares Baseline FIFO vs SDN Dynamic QoS from their respective CSVs.
    Generates:
      - heavy_congestion_loss.png / comparison_loss.png
      - heavy_congestion_latency.png / comparison_latency.png
      - heavy_congestion_throughput.png / comparison_throughput.png
      - comparison_summary.png
      - comparison_metrics.json
    """
    if out_dir is None:
        out_dir = RESULTS_DIR
    os.makedirs(out_dir, exist_ok=True)

    base_rows = parse_metrics_csv(base_csv)
    qos_rows = parse_metrics_csv(qos_csv)

    if not base_rows or not qos_rows:
        return {"success": False, "error": "One or both comparison CSVs could not be loaded."}

    # Match by class name
    base_map = {r["class_name"].lower(): r for r in base_rows}
    qos_map = {r["class_name"].lower(): r for r in qos_rows}

    # Focus on primary classes: voice, video, bulk
    target_classes = ["voice", "video", "bulk"]
    # Check if target classes exist, else use intersection
    common_classes = [c for c in target_classes if c in base_map and c in qos_map]
    if not common_classes:
        common_classes = [c for c in base_map if c in qos_map and c != "congestion_flooder"]

    if not common_classes:
        return {"success": False, "error": "No common traffic classes found for comparison."}

    labels = [c.capitalize() for c in common_classes]
    base_loss = [base_map[c]["loss_percentage"] for c in common_classes]
    qos_loss = [qos_map[c]["loss_percentage"] for c in common_classes]

    base_lat = [base_map[c]["avg_latency_ms"] for c in common_classes]
    qos_lat = [qos_map[c]["avg_latency_ms"] for c in common_classes]

    base_thr = [base_map[c]["throughput_mbps"] for c in common_classes]
    qos_thr = [qos_map[c]["throughput_mbps"] for c in common_classes]

    base_jit = [base_map[c]["jitter_ms"] for c in common_classes]
    qos_jit = [qos_map[c]["jitter_ms"] for c in common_classes]

    comparison_dict = {
        "title": title_suffix,
        "classes": labels,
        "baseline_csv": os.path.basename(base_csv),
        "qos_csv": os.path.basename(qos_csv),
        "timestamp": max(os.path.getmtime(base_csv) if os.path.exists(base_csv) else 0,
                         os.path.getmtime(qos_csv) if os.path.exists(qos_csv) else 0),
        "fifo": {c: base_map[c] for c in common_classes},
        "qos": {c: qos_map[c] for c in common_classes}
    }

    # Save structured JSON
    comp_json_path = os.path.join(out_dir, "comparison_metrics.json")
    try:
        with open(comp_json_path, 'w') as f:
            json.dump(comparison_dict, f, indent=2)
    except Exception:
        pass

    if not MATPLOTLIB_AVAILABLE:
        return {"success": True, "data": comparison_dict}

    setup_dark_style()
    x = np.arange(len(labels))
    width = 0.35

    # 1. Packet Loss Chart
    try:
        fig, ax = plt.subplots(figsize=(7.5, 4.2))
        fig.patch.set_facecolor('#1e293b')
        ax.set_facecolor('#0f172a')
        b1 = ax.bar(x - width/2, base_loss, width, label='Baseline FIFO', color='#ef4444', edgecolor='#334155', linewidth=1)
        b2 = ax.bar(x + width/2, qos_loss, width, label='SDN Dynamic QoS', color='#0284c7', edgecolor='#334155', linewidth=1)
        ax.set_ylabel('Packet Loss (%)', fontweight='600')
        ax.set_title(f'Packet Loss: FIFO vs QoS\n({title_suffix})', fontsize=11, fontweight='700', color='#38bdf8', pad=10)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontweight='600')
        ax.legend(frameon=True, facecolor='#1e293b', edgecolor='#334155', labelcolor='#f8fafc')
        ax.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color('#334155')
        for b in b1:
            h = b.get_height()
            ax.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                        textcoords="offset points", ha='center', va='bottom', fontsize=9, color='#ef4444', fontweight='700')
        for b in b2:
            h = b.get_height()
            ax.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                        textcoords="offset points", ha='center', va='bottom', fontsize=9, color='#38bdf8', fontweight='700')
        ax.set_ylim(0, max(max(base_loss + qos_loss + [5.0]) * 1.25, 10.0))
        plt.tight_layout()
        loss_png = os.path.join(out_dir, "heavy_congestion_loss.png")
        plt.savefig(loss_png, dpi=180, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        # Also save as comparison_loss.png
        try:
            import shutil
            shutil.copyfile(loss_png, os.path.join(out_dir, "comparison_loss.png"))
        except Exception:
            pass
    except Exception as e:
        print(f"[-] Error generating loss comparison chart: {e}")

    # 2. Latency Chart
    try:
        fig, ax = plt.subplots(figsize=(7.5, 4.2))
        fig.patch.set_facecolor('#1e293b')
        ax.set_facecolor('#0f172a')
        b1 = ax.bar(x - width/2, base_lat, width, label='Baseline FIFO', color='#ef4444', edgecolor='#334155', linewidth=1)
        b2 = ax.bar(x + width/2, qos_lat, width, label='SDN Dynamic QoS', color='#0284c7', edgecolor='#334155', linewidth=1)
        ax.set_ylabel('Average Latency (ms)', fontweight='600')
        ax.set_title(f'Average Latency: FIFO vs QoS\n({title_suffix})', fontsize=11, fontweight='700', color='#38bdf8', pad=10)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontweight='600')
        ax.legend(frameon=True, facecolor='#1e293b', edgecolor='#334155', labelcolor='#f8fafc')
        ax.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color('#334155')
        for b in b1:
            h = b.get_height()
            ax.annotate(f"{h:.1f}ms", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                        textcoords="offset points", ha='center', va='bottom', fontsize=9, color='#ef4444', fontweight='700')
        for b in b2:
            h = b.get_height()
            ax.annotate(f"{h:.1f}ms", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                        textcoords="offset points", ha='center', va='bottom', fontsize=9, color='#38bdf8', fontweight='700')
        ax.set_ylim(0, max(max(base_lat + qos_lat + [10.0]) * 1.25, 20.0))
        plt.tight_layout()
        lat_png = os.path.join(out_dir, "heavy_congestion_latency.png")
        plt.savefig(lat_png, dpi=180, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        try:
            import shutil
            shutil.copyfile(lat_png, os.path.join(out_dir, "comparison_latency.png"))
        except Exception:
            pass
    except Exception as e:
        print(f"[-] Error generating latency comparison chart: {e}")

    # 3. Throughput Chart
    try:
        fig, ax = plt.subplots(figsize=(7.5, 4.2))
        fig.patch.set_facecolor('#1e293b')
        ax.set_facecolor('#0f172a')
        b1 = ax.bar(x - width/2, base_thr, width, label='Baseline FIFO', color='#ef4444', edgecolor='#334155', linewidth=1)
        b2 = ax.bar(x + width/2, qos_thr, width, label='SDN Dynamic QoS', color='#0284c7', edgecolor='#334155', linewidth=1)
        ax.set_ylabel('Throughput (Mbps)', fontweight='600')
        ax.set_title(f'Throughput: FIFO vs QoS\n({title_suffix})', fontsize=11, fontweight='700', color='#38bdf8', pad=10)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontweight='600')
        ax.legend(frameon=True, facecolor='#1e293b', edgecolor='#334155', labelcolor='#f8fafc')
        ax.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color('#334155')
        for b in b1:
            h = b.get_height()
            ax.annotate(f"{h:.2f}M", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                        textcoords="offset points", ha='center', va='bottom', fontsize=9, color='#ef4444', fontweight='700')
        for b in b2:
            h = b.get_height()
            ax.annotate(f"{h:.2f}M", xy=(b.get_x() + b.get_width()/2, h), xytext=(0, 3),
                        textcoords="offset points", ha='center', va='bottom', fontsize=9, color='#38bdf8', fontweight='700')
        ax.set_ylim(0, max(max(base_thr + qos_thr + [0.5]) * 1.25, 1.0))
        plt.tight_layout()
        thr_png = os.path.join(out_dir, "heavy_congestion_throughput.png")
        plt.savefig(thr_png, dpi=180, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        try:
            import shutil
            shutil.copyfile(thr_png, os.path.join(out_dir, "comparison_throughput.png"))
        except Exception:
            pass
    except Exception as e:
        print(f"[-] Error generating throughput comparison chart: {e}")

    # 4. Multi-panel Comparison Summary Chart
    try:
        fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
        fig.patch.set_facecolor('#1e293b')

        # Loss panel
        ax1 = axes[0]
        ax1.set_facecolor('#0f172a')
        ax1.bar(x - width/2, base_loss, width, label='FIFO', color='#ef4444')
        ax1.bar(x + width/2, qos_loss, width, label='QoS', color='#0284c7')
        ax1.set_title('Packet Loss (%)', fontsize=11, fontweight='700', color='#38bdf8')
        ax1.set_xticks(x)
        ax1.set_xticklabels(labels, fontweight='600')
        ax1.grid(axis='y', linestyle='--', alpha=0.5)
        ax1.legend(frameon=True, facecolor='#1e293b', edgecolor='#334155', labelcolor='#f8fafc')
        for spine in ax1.spines.values():
            spine.set_color('#334155')

        # Latency panel
        ax2 = axes[1]
        ax2.set_facecolor('#0f172a')
        ax2.bar(x - width/2, base_lat, width, label='FIFO', color='#ef4444')
        ax2.bar(x + width/2, qos_lat, width, label='QoS', color='#0284c7')
        ax2.set_title('Avg Latency (ms)', fontsize=11, fontweight='700', color='#38bdf8')
        ax2.set_xticks(x)
        ax2.set_xticklabels(labels, fontweight='600')
        ax2.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax2.spines.values():
            spine.set_color('#334155')

        # Throughput panel
        ax3 = axes[2]
        ax3.set_facecolor('#0f172a')
        ax3.bar(x - width/2, base_thr, width, label='FIFO', color='#ef4444')
        ax3.bar(x + width/2, qos_thr, width, label='QoS', color='#0284c7')
        ax3.set_title('Throughput (Mbps)', fontsize=11, fontweight='700', color='#38bdf8')
        ax3.set_xticks(x)
        ax3.set_xticklabels(labels, fontweight='600')
        ax3.grid(axis='y', linestyle='--', alpha=0.5)
        for spine in ax3.spines.values():
            spine.set_color('#334155')

        plt.suptitle(f"SDN Dynamic QoS vs Baseline FIFO ({title_suffix})",
                     fontsize=12, fontweight='700', color='#f8fafc', y=0.98)
        plt.tight_layout()
        plt.subplots_adjust(top=0.88)
        sum_png = os.path.join(out_dir, "comparison_summary.png")
        plt.savefig(sum_png, dpi=180, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
    except Exception as e:
        print(f"[-] Error generating comparison summary: {e}")

    return {"success": True, "data": comparison_dict}


def generate_all_charts(results_dir: str = None, target_csv: str = None) -> dict:
    """
    Orchestrates automatic chart generation across available experiment CSV results.
    Discovers:
      1. Single experiment run CSVs (specified target_csv, or newest experiment CSV)
      2. Baseline vs QoS comparison CSV pairs (heavy_congestion_*.csv or mininet_fifo.csv & demo_qos.csv)
    Generates all corresponding charts and metadata JSONs.
    """
    if results_dir is None:
        results_dir = RESULTS_DIR
    os.makedirs(results_dir, exist_ok=True)

    status = {
        "has_data": False,
        "latest_run": None,
        "comparison": None,
        "source_csv": None
    }

    # 1. Look for Single Run CSV
    candidate_live = []
    if target_csv and os.path.exists(target_csv):
        candidate_live.append(target_csv)

    # Add any CSV in results_dir sorted by mtime
    try:
        all_csvs = [
            os.path.join(results_dir, f) for f in os.listdir(results_dir)
            if f.endswith(".csv") and not f.startswith(".")
        ]
        # Sort newest first
        all_csvs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        # Put non-baseline files first
        live_first = [p for p in all_csvs if not p.endswith("_baseline.csv")]
        base_after = [p for p in all_csvs if p.endswith("_baseline.csv")]
        candidate_live.extend(live_first + base_after)

        vv_test = os.path.join(results_dir, "voice_video_test.json")
        if os.path.exists(vv_test) and os.path.getsize(vv_test) > 50:
            candidate_live.insert(0 if not target_csv else 1, vv_test)
    except Exception:
        pass

    # Fallbacks
    candidate_live.extend([
        os.path.join(results_dir, "latest_experiment.csv"),
        os.path.join(results_dir, "mininet_live.csv"),
        os.path.join(results_dir, "demo_qos.csv")
    ])

    found_live = None
    for cand in candidate_live:
        if os.path.exists(cand) and os.path.getsize(cand) > 50:
            # Quick check if it has valid rows
            try:
                rows = parse_metrics_csv(cand)
                if rows:
                    found_live = cand
                    break
            except Exception:
                continue

    if found_live:
        res = plot_live_run(found_live, results_dir)
        if res.get("success"):
            status["has_data"] = True
            status["latest_run"] = res
            status["source_csv"] = os.path.basename(found_live)

    # 2. Look for Comparison CSV pairs
    comp_pairs = [
        (os.path.join(results_dir, "heavy_congestion_baseline.csv"),
         os.path.join(results_dir, "heavy_congestion_qos.csv"),
         "Heavy Congestion (~136% Overload)"),
        (os.path.join(results_dir, "mininet_fifo.csv"),
         os.path.join(results_dir, "demo_qos.csv"),
         "Mininet Live Run (FIFO vs QoS)"),
        (os.path.join(results_dir, "moderate_traffic_baseline.csv"),
         os.path.join(results_dir, "moderate_traffic_qos.csv"),
         "Moderate Traffic Load (~81% Load)")
    ]

    for base_c, qos_c, title in comp_pairs:
        if os.path.exists(base_c) and os.path.exists(qos_c) and os.path.getsize(base_c) > 50 and os.path.getsize(qos_c) > 50:
            c_res = plot_comparison(base_c, qos_c, results_dir, title)
            if c_res.get("success"):
                status["has_data"] = True
                status["comparison"] = c_res
            break

    # 3. Synchronize evaluation_dashboard.html with web/index.html
    html_out = os.path.join(results_dir, "evaluation_dashboard.html")
    generate_html_dashboard({}, html_out)

    return status


def generate_ascii_bar_chart(title: str, labels: list, values_fifo: list, values_qos: list, unit: str):
    print("\n" + "=" * 70)
    print(f" {title.upper()} ({unit})")
    print("=" * 70)
    max_val = max(max(values_fifo + [0.01]), max(values_qos + [0.01]))
    bar_width = 30

    for label, v_fifo, v_qos in zip(labels, values_fifo, values_qos):
        len_fifo = int((v_fifo / max_val) * bar_width) if max_val > 0 else 0
        len_qos = int((v_qos / max_val) * bar_width) if max_val > 0 else 0

        bar_fifo = "█" * len_fifo
        bar_qos = "█" * len_qos

        print(f"{label:<8} FIFO | {bar_fifo:<30} {v_fifo:6.2f} {unit}")
        print(f"         QoS  | {bar_qos:<30} {v_qos:6.2f} {unit}")
        print("." * 70)


def generate_html_dashboard(summary_data: dict, output_path: str):
    """
    Ensures the evaluation dashboard (results/evaluation_dashboard.html)
    is synchronized with web/index.html.
    """
    web_index = os.path.join(PROJECT_ROOT, 'web', 'index.html')
    if os.path.exists(web_index):
        with open(web_index, 'r', encoding='utf-8') as f:
            html_content = f.read()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[+] Synchronized Interactive HTML Dashboard: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Plot and Visualize QoS Experiment Results")
    parser.add_argument("--summary", default=None, help="Path to metrics_summary.json")
    parser.add_argument("--csv", default=None, help="Path to receiver metrics CSV output (for live run plotting)")
    parser.add_argument("--all", action="store_true", help="Generate all performance & comparison charts")
    args = parser.parse_args()

    results_dir = RESULTS_DIR

    if args.all:
        print("[*] Generating all performance and comparison charts...")
        res = generate_all_charts(results_dir)
        print(f"[+] Chart generation status: has_data={res.get('has_data')}")
        return

    if args.csv and os.path.exists(args.csv):
        print(f"\n[*] Visualizing live experiment run from CSV: {args.csv}")
        res = plot_live_run(args.csv, results_dir)
        if res.get("success"):
            m = res.get("metrics", {})
            print("\n" + "=" * 65)
            print("          LIVE MEASURED EXPERIMENT PERFORMANCE")
            print("=" * 65)
            for cname, data in m.items():
                print(f"  {cname.upper():<10} | Throughput: {data['throughput_mbps']:6.3f} Mbps | Loss: {data['loss_percentage']:5.1f}% | Latency: {data['avg_latency_ms']:5.1f} ms")
            print("=" * 65 + "\n")
        return

    # Default flow: summarize comparisons
    summary_path = args.summary if args.summary else os.path.join(results_dir, "metrics_summary.json")
    if not os.path.exists(summary_path):
        print(f"[-] Summary file not found at: {summary_path}")
        print("    Running tests/run_experiment.py first...")
        import subprocess
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "run_experiment.py")], check=True)

    with open(summary_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)

    # 1. Output ASCII Bar Charts for Heavy Congestion
    heavy = summary_data.get("heavy_congestion", {})
    if heavy:
        labels = ["Voice", "Video", "Bulk"]
        base_loss = [r["loss_percentage"] for r in heavy["baseline"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        qos_loss = [r["loss_percentage"] for r in heavy["qos"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        generate_ascii_bar_chart("Heavy Congestion: Packet Loss Comparison", labels, base_loss, qos_loss, "%")

        base_lat = [r["avg_latency_ms"] for r in heavy["baseline"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        qos_lat = [r["avg_latency_ms"] for r in heavy["qos"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        generate_ascii_bar_chart("Heavy Congestion: Average Latency Comparison", labels, base_lat, qos_lat, "ms")

        base_jit = [r["jitter_ms"] for r in heavy["baseline"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        qos_jit = [r["jitter_ms"] for r in heavy["qos"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        generate_ascii_bar_chart("Heavy Congestion: Interarrival Jitter (RFC 3550)", labels, base_jit, qos_jit, "ms")

        base_thr = [r["throughput_mbps"] for r in heavy["baseline"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        qos_thr = [r["throughput_mbps"] for r in heavy["qos"]["data"] if r["class_name"] in ["voice", "video", "bulk"]]
        generate_ascii_bar_chart("Heavy Congestion: Throughput Comparison", labels, base_thr, qos_thr, "Mbps")

    # 2. Generate charts from CSVs
    print("[*] Generating high-resolution performance charts from CSVs...")
    generate_all_charts(results_dir)


if __name__ == '__main__':
    main()
