#!/usr/bin/env bash
set -Eeuo pipefail

adapter="hci0"
service_name="can-motor-ble.service"
real_service_name="can-motor-ble-real.service"

usage() {
    echo "Usage: sudo bash ubuntu/reset_ble_adapter.sh [--adapter hci0]"
}

while (($#)); do
    case "$1" in
        --adapter)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            adapter="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

for command in systemctl rfkill btmgmt bluetoothctl busctl pgrep awk grep; do
    command -v "$command" >/dev/null || {
        echo "Missing required command: $command" >&2
        exit 1
    }
done

adapter_path="/org/bluez/${adapter}"

echo "[1/5] Stopping the installed gateway service (if present)"
for unit in "$service_name" "$real_service_name"; do
    if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "^${unit}"; then
        systemctl stop "$unit"
    fi
done

echo "[2/5] Stopping foreground BLE gateway processes"
mapfile -t gateway_pids < <(pgrep -f '[b]le_gateway_service.py' || true)
if ((${#gateway_pids[@]})); then
    kill -TERM "${gateway_pids[@]}"
    remaining=("${gateway_pids[@]}")
    for _ in {1..25}; do
        remaining=()
        for pid in "${gateway_pids[@]}"; do
            kill -0 "$pid" 2>/dev/null && remaining+=("$pid")
        done
        ((${#remaining[@]} == 0)) && break
        sleep 0.2
    done
    if ((${#remaining[@]})); then
        echo "Gateway did not stop cleanly; remaining PID(s): ${remaining[*]}" >&2
        exit 1
    fi
fi

echo "[3/5] Unblocking and configuring Bluetooth"
rfkill unblock bluetooth

configure_adapter() {
    bluetoothctl >/dev/null <<EOF
power on
discoverable off
pairable on
quit
EOF
}

managers_available() {
    local introspection
    introspection=$(busctl introspect org.bluez "$adapter_path" 2>/dev/null || true)
    grep -q 'org.bluez.GattManager1' <<<"$introspection" &&
        grep -q 'org.bluez.LEAdvertisingManager1' <<<"$introspection"
}

read_capacity() {
    active=$(busctl get-property org.bluez "$adapter_path" \
        org.bluez.LEAdvertisingManager1 ActiveInstances 2>/dev/null | awk '{print $2}')
    supported=$(busctl get-property org.bluez "$adapter_path" \
        org.bluez.LEAdvertisingManager1 SupportedInstances 2>/dev/null | awk '{print $2}')
    [[ "$active" =~ ^[0-9]+$ && "$supported" =~ ^[0-9]+$ ]]
}

configure_adapter

echo "[4/5] Checking whether a full adapter reset is needed"
if managers_available && read_capacity && ((active < supported)); then
    echo "BlueZ is healthy; skipping service restart and adapter power cycle."
else
    echo "BlueZ is unavailable or its advertising slots are occupied; resetting ${adapter}."
    systemctl restart bluetooth
    rfkill unblock bluetooth
    btmgmt -i "$adapter" power off >/dev/null
    btmgmt -i "$adapter" power on >/dev/null
    configure_adapter
    managers_ready=0
    for _ in {1..20}; do
        if managers_available; then
            managers_ready=1
            break
        fi
        sleep 0.25
    done
    if ((managers_ready == 0)); then
        echo "BlueZ managers are not available on ${adapter_path}." >&2
        exit 1
    fi
fi

echo "[5/5] Verifying that an advertising instance is available"
if ! read_capacity; then
    echo "Could not read BlueZ advertising instance counts." >&2
    exit 1
fi
if ((active >= supported)); then
    echo "No free BLE advertising instance: active=${active}, supported=${supported}." >&2
    exit 1
fi

echo "BLE adapter ${adapter} is ready: active=${active}, supported=${supported}."
echo "The adapter is ready for the selected mock or real gateway command."
