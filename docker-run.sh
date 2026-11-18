#!/usr/bin/env bash
set -euo pipefail   # abort on errors, undefined vars

# --------------------------------------------------------------
# Pull the Apple‑silicon‑compatible Mininet image (once)
# --------------------------------------------------------------
docker pull amirreza225/mininet-apple-silicon:latest

# --------------------------------------------------------------
# Run a privileged container that:
#   • mounts the repo at /workdir
#   • forwards dashboard (8080) and receiver ports (5001‑5004)
#   • uses a *user* switch (avoids missing OVS kernel modules)
# --------------------------------------------------------------
docker run --rm -it \
  --name cos-traffic-mininet \
  --privileged \
  -v "$(pwd)":/workdir \
  -p 8080:8080 -p 5001:5001 -p 5002:5002 -p 5003:5003 -p 5004:5004 \
  -w /workdir \
  amirreza225/mininet-apple-silicon:latest \
  bash -c '
    # --------------------------------------------------------------
    # Make the project root importable for Python modules
    # --------------------------------------------------------------
    export PYTHONPATH=.

    # --------------------------------------------------------------
    # ① Start the dashboard server (background)
    # --------------------------------------------------------------
    python3 web/server.py &
    SERVER_PID=$!

    # --------------------------------------------------------------
    # ② Start the Ryu controller (background)
    # --------------------------------------------------------------
    ryu-manager app/ryu_controller.py &
    RYU_PID=$!

    # Give the services a moment to bind their ports
    sleep 2

    # --------------------------------------------------------------
    # ③ Launch Mininet with a *user* switch (no OVS kernel module needed)
    # --------------------------------------------------------------
    sudo -E mn --custom topology/qos_topology.py --topo qos_topo \
        --controller=remote,ip=127.0.0.1,port=6653 \
        --switch=user

    # --------------------------------------------------------------
    # ④ Clean up background processes when Mininet exits
    # --------------------------------------------------------------
    kill $SERVER_PID $RYU_PID
  '


