#!/usr/bin/env bash
# Startup script for Helix's debug menu (space-G).
#
# codelldb must already be running before starting a Helix debug session:
#   codelldb --port 15678
#
# Helix spawns this script with -p <mux-port> via port-arg, then connects.
# After connecting, run dap-observer in another terminal:
#   dap-observer $(cat /tmp/dap-mux-port)
set -euo pipefail

# Log args so we know how Helix formats port-arg
echo "debug.sh args: $*" > /tmp/debug-sh-args.log
for i in "$@"; do echo "  [$i]" >> /tmp/debug-sh-args.log; done

# Save mux port for dap-observer (parse from -p <port> or -p<port>)
args=("$@")
for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "-p" ]]; then
        echo "${args[$((i+1))]}" > /tmp/dap-mux-port
    elif [[ "${args[$i]}" =~ ^-p([0-9]+)$ ]]; then
        echo "${BASH_REMATCH[1]}" > /tmp/dap-mux-port
    fi
done

exec dmux --attach 15678 --headless "$@"
