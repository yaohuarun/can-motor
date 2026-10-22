"""接收诊断：不发送应用层CAN报文；接口仍为普通模式，会自动ACK有效帧。"""
import argparse
from collections import Counter
import sys
import time

from motor_control import bounded


def capture(bus, seconds, output=print):
    counts = Counter()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        msg = bus.recv(timeout=min(0.1, max(0, deadline - time.monotonic())))
        if msg is None:
            continue
        key = (msg.arbitration_id, msg.is_extended_id, msg.is_remote_frame)
        counts[key] += 1
        if counts[key] <= 3:
            output(f'RX ID=0x{msg.arbitration_id:X} EXT={msg.is_extended_id} '
                   f'RTR={msg.is_remote_frame} DATA={msg.data.hex(" ").upper()}')
    output(f'接收总帧数：{sum(counts.values())}')
    for (can_id, extended, remote), count in sorted(counts.items()):
        output(f'  ID=0x{can_id:X} EXT={extended} RTR={remote}: {count}帧')
    if not counts:
        output('未收到报文：检查通道、H/L/参考地、供电、终端和波特率；'
               '静默总线或驱动兼容问题也可能导致此结果。')
    return counts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--channel', default=None,
                   help='PCAN通道名（默认PCAN_USBBUS1）；旧后端使用0或1')
    p.add_argument('--device', type=int, default=0)
    p.add_argument('--backend', choices=['auto', 'pcan', 'canalystii', 'controlcan'],
                   default='auto',
                   help='CAN后端；auto在Windows和Linux/Ubuntu均使用pcan')
    p.add_argument('--library', '--dll', dest='dll', help='厂商DLL或Linux SO路径')
    p.add_argument('--seconds', type=float, default=5)
    a = p.parse_args(argv)
    try:
        bounded(a.seconds, 0.1, 3600, '诊断时间')
        bounded(a.device, 0, 255, '设备索引')
        from controlcan_backend import resolve_backend
        backend = resolve_backend(a.backend)
        if backend != 'pcan' and a.channel not in (None, '0', '1'):
            raise ValueError('canalystii/controlcan 的通道必须为0或1')
    except (ValueError, RuntimeError) as exc:
        p.error(str(exc))
    bus = None
    try:
        import can
        from controlcan_backend import open_bus
        bus = open_bus(backend, a.channel, a.device, a.dll)
        channel = a.channel or ('PCAN_USBBUS1' if backend == 'pcan' else '0')
        print(f'接收诊断 backend={backend}, channel={channel}, 500000 bit/s，不发送控制报文。')
        capture(bus, a.seconds)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'诊断失败：{exc}', file=sys.stderr)
        return 1
    finally:
        if bus is not None:
            bus.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
