#!/usr/bin/env python3
"""Read-only Ubuntu BLE/CAN deployment checks; never starts motor control."""
import argparse
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--adapter', default='hci0')
    parser.add_argument('--mock-can', action='store_true')
    args = parser.parse_args(argv)
    missing = [name for name in ('bluetoothctl', 'busctl') if not shutil.which(name)]
    if missing:
        print('Missing commands: ' + ', '.join(missing), file=sys.stderr)
        return 1
    result = subprocess.run(['busctl', 'tree', 'org.bluez'], check=False,
                            capture_output=True, text=True)
    if result.returncode:
        print('BlueZ is not reachable on the system bus', file=sys.stderr)
        return 1
    print(f'Adapter {args.adapter}: inspect GattManager1 and LEAdvertisingManager1 before service start')
    print('CAN mode: simulated/no hardware access' if args.mock_can else
          'CAN hardware not opened by this read-only preflight')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
