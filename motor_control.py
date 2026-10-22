"""电动轮椅 CAN 协议控制。默认仅预览；--send 才连接硬件。"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import time

GEAR_RATIO = 15.75
WHEEL_DIAMETER_M = 0.254
TRACK_WIDTH_M = 0.420


def differential_wheel_rpm(linear_speed: float, angular_speed: float):
    """车体 m/s、rad/s 转为左、右轮端 rpm，前进和逆时针为正。"""
    for value, name in ((linear_speed, '线速度m/s'),
                        (angular_speed, '角速度rad/s')):
        if not math.isfinite(value):
            raise ValueError(f'{name} 必须为有限数值')
    turn_speed = angular_speed * (TRACK_WIDTH_M / 2)
    factor = 60 / (math.pi * WHEEL_DIAMETER_M)
    left = (linear_speed - turn_speed) * factor
    right = (linear_speed + turn_speed) * factor
    if not all(math.isfinite(value) for value in (left, right)):
        raise ValueError('差速换算结果必须为有限数值，目标速度过大')
    return left, right


def bounded(value, low, high, name):
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} 必须在 {low}..{high} 之间')
    return value


def speed_raw(rpm: float, max_rpm: float) -> int:
    bounded(max_rpm, 0.1, 6553.5, '最高转速')
    bounded(rpm, -max_rpm, max_rpm, '目标转速')
    return round(rpm / max_rpm * 16384)


def wheel_speed_raw(wheel_rpm: float, max_motor_rpm: float, direction=1) -> int:
    motor_rpm = wheel_rpm * GEAR_RATIO * direction
    return speed_raw(motor_rpm, max_motor_rpm)


def control_frame(right: int, left: int, torque=20, depth=100, enabled=True):
    for speed in (right, left):
        bounded(speed, -16384, 16384, '速度原始值')
    bounded(torque, 0, 100, '转矩百分比')
    bounded(depth, 0, 100, '摇杆深度')
    # 第4位按从1起计数理解为 bit3；未充电=1。
    return struct.pack('>hhBBBB', right, left, torque, depth, 0,
                       0x08 | (0x05 if enabled else 0))


def external_frame(right: int, left: int, enabled=True):
    for speed in (right, left):
        bounded(speed, -16384, 16384, '速度原始值')
    # 只开启速度控制，不开启模拟摇杆；X/Y未启用，填0。
    return struct.pack('>hhBBBB', right, left, 5 if enabled else 0, 0, 0, 0)


def config_frame(max_rpm, battery='lithium', swap=False, pi=0,
                 left_comp=0, right_comp=0, overvoltage=33,
                 undervoltage=22, brake_voltage=13):
    bounded(max_rpm, 0.1, 6553.5, '最高转速')
    if battery not in ('lithium', 'lead'):
        raise ValueError('未知电池类型')
    for value, lo, hi, name in (
        (pi, 0, 2, 'PI组'), (left_comp, 0, 10, '左补偿'),
        (right_comp, 0, 10, '右补偿'), (overvoltage, 29, 35, '过压'),
        (undervoltage, 18, 23, '欠压'), (brake_voltage, 6, 15, '刹车电压')):
        bounded(value, lo, hi, name)
    flags = (battery == 'lead') | ((5 if swap else 0) << 1) | (pi << 4)
    return struct.pack('<HBBBBBB', round(max_rpm * 10), flags,
                       left_comp | (right_comp << 4), overvoltage,
                       undervoltage, brake_voltage, 0xAA)


def parse_feedback(can_id, data):
    if can_id not in (0x101, 0x102) or len(data) != 8:
        return None
    speed, current = struct.unpack('>hH', data[:4])
    return dict(wheel='左' if can_id == 0x101 else '右', speed_raw=speed,
                current_raw=current, fault=data[4], battery_raw=data[5],
                extra=data[6], revolutions=data[7])


def feedback_fault_label(fault, previous_fault=None):
    if fault == 0:
        return '无故障，0x0A已清除' if previous_fault == 0x0A else '无故障'
    if fault == 0x0A:
        return 'CAN接收故障告警，继续收发不退出'
    return '其他故障'


def feedback_speed_rpm(speed_raw, max_rpm):
    return speed_raw / 16384 * max_rpm


def battery_level(battery_raw):
    levels = {
        0: '放电，10%以下', 5: '放电，10%', 12: '放电，20%',
        20: '放电，40%', 44: '放电，60%', 75: '放电，80%',
        102: '放电，100%', 122: '充电，10%及以下',
        130: '充电，20%', 140: '充电，40%', 160: '充电，60%',
        180: '充电，80%', 220: '充电，100%',
    }
    return levels.get(battery_raw, f'未知等级（原始值={battery_raw}）')


def feedback_target_rpm(wheel, left_raw, right_raw, max_rpm, running):
    if not running:
        return 0.0
    return feedback_speed_rpm(left_raw if wheel == '左' else right_raw, max_rpm)


def format_feedback(can_id, data, status, target_rpm, max_rpm, previous_fault=None):
    fault = status['fault']
    label = feedback_fault_label(fault, previous_fault)
    speed_rpm = feedback_speed_rpm(status['speed_raw'], max_rpm)
    if round(speed_rpm, 1) == 0:
        speed_rpm = 0.0
    return (f'RX ID=0x{can_id:03X} {status["wheel"]}轮 '
            f'DATA={bytes(data).hex(" ").upper()} '
            f'目标转速={target_rpm:.1f} rpm '
            f'速度={speed_rpm:.1f} rpm '
            f'Q轴电流原始值={status["current_raw"]} '
            f'故障=0x{fault:02X}（{label}） '
            f'电池电量={battery_level(status["battery_raw"])} '
            f'运行圈数={status["revolutions"]}')


def should_print_feedback(previous, fault, now):
    return (previous is None or previous[0] != fault or
            now - previous[1] >= 0.5)


class StartupRecovery:
    """0x0A只告警；启动前继续零速等待，运行中保持周期收发。"""
    def __init__(self, started, timeout):
        self.deadline = started + timeout
        self.clear = set()
        self.ready = False
        self.running = False

    def observe(self, status):
        fault, wheel = status['fault'], status['wheel']
        if fault:
            if fault == 0x0A:
                self.clear.discard(wheel)
                self.ready = False
                return
            label = 'CAN接收故障' if fault == 0x0A else '故障'
            raise RuntimeError(f'{wheel}轮{label} 0x{fault:02X}')
        self.clear.add(wheel)
        self.ready = self.clear == {'左', '右'}

    def check_timeout(self, now):
        if not self.ready and now >= self.deadline:
            raise RuntimeError('启动通信恢复超时：未收到左右轮均无故障的反馈，停止控制')

    def begin_run(self, now, latest):
        if now < self.deadline:
            return False
        # 已收到且持续刷新的0x0A反馈允许继续零速等待，不因观察结束退出。
        if any(item[0] == 0x0A for item in latest.values()):
            for wheel in ('左', '右'):
                item = latest.get(wheel)
                if item is None or now - item[1] > 1:
                    raise RuntimeError(f'{wheel}轮反馈缺失或超过1秒未更新，停止控制')
            return False
        self.check_timeout(now)
        for wheel in ('左', '右'):
            item = latest.get(wheel)
            if item is None or item[0] != 0 or now - item[1] > 1:
                raise RuntimeError(f'观察结束：{wheel}轮未提供最近1秒内的无故障反馈，停止控制')
        self.running = True
        return True


def prepare_usb_backend():
    """提前加载并缓存后端，供 canalystii 内部 usb.core.find() 使用。"""
    import usb.backend.libusb1
    import usb.backend.libusb0

    backend = usb.backend.libusb1.get_backend()
    if backend is None:
        try:
            import libusb_package
        except ImportError:
            pass
        else:
            backend = usb.backend.libusb1.get_backend(
                find_library=libusb_package.find_library)
    if backend is None:
        backend = usb.backend.libusb0.get_backend()
    if backend is None:
        if sys.platform.startswith('linux'):
            raise RuntimeError('未找到libusb动态库，请执行 sudo apt install libusb-1.0-0；'
                               '如提示权限不足，请按README配置udev规则。')
        raise RuntimeError(
            'PyUSB 找不到可用的 libusb DLL。请用运行脚本的同一个 Python 执行：\n'
            '  python -m pip install --upgrade libusb-package\n'
            '安装后仍失败，请检查 Python 与 DLL 的32/64位是否一致。')
    return backend


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['external', 'direct'], default='external')
    p.add_argument('--linear-speed', type=float, default=0,
                   help='车体线速度m/s，前进为正，默认0')
    p.add_argument('--angular-speed', type=float, default=0,
                   help='车体角速度rad/s，俯视逆时针左转为正，默认0')
    p.add_argument('--left-direction', type=int, choices=[-1, 1], default=-1,
                   help='左轮安装方向系数，默认-1，按实车前进方向校准')
    p.add_argument('--right-direction', type=int, choices=[-1, 1], default=1,
                   help='右轮安装方向系数，默认1，补偿镜像安装')
    p.add_argument('--startup-only', action='store_true',
                   help='仅零速通信诊断，故障清除后也不发送目标速度')
    p.add_argument('--max-rpm', type=float, required=True,
                   help='电机轴最高转速rpm（减速前）；external须与上控一致，direct写入配置帧')
    p.add_argument('--duration', type=float, default=60, help='目标速度运行秒数，默认60，必须大于0')
    p.add_argument('--period-ms', type=float, default=20, help='工程初值，协议未规定周期')
    p.add_argument('--tx-timeout', type=float, default=0.1, help='发送队列等待秒数')
    p.add_argument('--startup-timeout', type=float, default=5,
                   help='固定零速观察秒数，提前清除也不提前运行，默认5，最大300')
    p.add_argument('--channel', default=None,
                   help='PCAN通道名（默认PCAN_USBBUS1）；旧后端使用0或1')
    p.add_argument('--device', type=int, default=0)
    p.add_argument('--backend', choices=['auto', 'pcan', 'canalystii', 'controlcan'],
                   default='auto',
                   help='CAN后端；auto在Windows和Linux/Ubuntu均使用pcan')
    p.add_argument('--library', '--dll', dest='dll',
                   help='厂商ControlCAN.dll或libcontrolcan.so路径，默认按系统和架构选择')
    p.add_argument('--torque', type=int, default=20)
    p.add_argument('--depth', type=int, default=100)
    p.add_argument('--battery', choices=['lithium', 'lead'], default='lithium')
    p.add_argument('--swap', action='store_true')
    p.add_argument('--pi', type=int, default=0)
    p.add_argument('--left-comp', type=int, default=0)
    p.add_argument('--right-comp', type=int, default=0)
    p.add_argument('--overvoltage', type=int, default=33)
    p.add_argument('--undervoltage', type=int, default=22)
    p.add_argument('--brake-voltage', type=int, default=13)
    p.add_argument('--send', action='store_true', help='实际连接CAN并发送')
    a = p.parse_args(argv)
    try:
        bounded(a.duration, 0.001, 86400, '运行时间')
        bounded(a.period_ms, 1, 1000, '发送周期ms')
        bounded(a.tx_timeout, 0.001, 5, '发送等待秒数')
        bounded(a.startup_timeout, 0.1, 300, '零速观察秒数')
        bounded(a.device, 0, 255, '设备索引')
        from controlcan_backend import resolve_backend
        resolved_backend = resolve_backend(a.backend)
        if resolved_backend != 'pcan' and a.channel not in (None, '0', '1'):
            raise ValueError('canalystii/controlcan 的通道必须为0或1')
        # 使用配置帧的0.1rpm精度作为换算基准。
        bounded(a.max_rpm, 0.1, 6553.5, '最高转速')
        max_rpm = round(a.max_rpm * 10) / 10
        left_rpm, right_rpm = differential_wheel_rpm(
            0 if a.startup_only else a.linear_speed,
            0 if a.startup_only else a.angular_speed)
        right = wheel_speed_raw(right_rpm, max_rpm, a.right_direction)
        left = wheel_speed_raw(left_rpm, max_rpm, a.left_direction)
        cfg = config_frame(max_rpm, a.battery, a.swap, a.pi,
                           a.left_comp, a.right_comp, a.overvoltage,
                           a.undervoltage, a.brake_voltage)
        cmd = control_frame(right, left, a.torque, a.depth)
        if a.mode == 'external':
            frames = [(0x108, external_frame(right, left))]
            # 先保持功能开启发送零速，再关闭外部功能。
            zero = [(0x108, external_frame(0, 0))]
            off = [(0x108, external_frame(0, 0, False))]
        else:
            frames = [(0x103, cmd), (0x103, cfg)]
            zero = [(0x103, control_frame(0, 0, a.torque, a.depth)), (0x103, cfg)]
            off = [(0x103, control_frame(0, 0, 0, 0, False)), (0x103, cfg)]
    except (ValueError, RuntimeError) as exc:
        p.error(str(exc))
    if a.startup_only:
        frames = zero
        print('仅零速诊断模式：忽略目标速度，故障清除后继续保持零速。')
    else:
        print(f'车体目标：线速度={a.linear_speed:g} m/s，角速度={a.angular_speed:g} rad/s')
        print(f'轮端目标rpm：左={left_rpm:g}，右={right_rpm:g}；'
              f'减速比={GEAR_RATIO:g}；电机轴指令rpm：'
              f'左={left_rpm * GEAR_RATIO * a.left_direction:g}，'
              f'右={right_rpm * GEAR_RATIO * a.right_direction:g}')
    for can_id, payload in frames:
        print(f'待发送 标准帧 ID=0x{can_id:03X} DLC=8 DATA={payload.hex(" ").upper()}')
    if not a.send:
        print('仅预览。加入 --send 后发送；首次调试请架空驱动轮。')
        return 0
    try:
        import can
    except (ImportError, RuntimeError) as exc:
        print(f'CAN后端准备失败，未发送指令：{exc}', file=sys.stderr)
        return 1
    period = a.period_ms / 1000
    try:
        from controlcan_backend import open_bus
        bus = open_bus(resolved_backend, a.channel, a.device, a.dll)
    except Exception as exc:
        print(f'CAN接口打开失败，未发送指令：{exc}\n'
              '请检查USB连接、设备索引、设备驱动，并关闭占用设备的厂商软件。\n'
              'Ubuntu需检查libusb依赖和udev权限；Windows需匹配USB驱动，详见README。', file=sys.stderr)
        return 1

    def transmit(batch):
        for can_id, payload in batch:
            bus.send(can.Message(arbitration_id=can_id, data=payload,
                                 is_extended_id=False, channel=a.channel), timeout=a.tx_timeout)

    result = 0
    try:
        started = time.monotonic()
        recovery = StartupRecovery(started, a.startup_timeout)
        deadline = started + a.startup_timeout if a.startup_only else None
        next_send = started
        last_print = {}
        latest = {}
        next_summary = started
        print(f'零速观察{a.startup_timeout:g}秒：持续发送使能零速及配置，'
              '接收左右轮反馈；即使故障提前清除也不提前运行。')
        for can_id, payload in zero:
            print(f'启动发送 ID=0x{can_id:03X} DATA={payload.hex(" ").upper()}')
        while deadline is None or time.monotonic() < deadline:
            transmit(frames if recovery.running and not a.startup_only else zero)
            next_send += period
            # 非阻塞读取，限制单周期数量，避免繁忙总线饿死发送。
            for _ in range(100):
                msg = bus.recv(timeout=0)
                if msg is None:
                    break
                if msg.is_extended_id or msg.is_remote_frame or msg.is_error_frame:
                    continue
                status = parse_feedback(msg.arbitration_id, msg.data)
                if status:
                    now = time.monotonic()
                    latest[status['wheel']] = (status['fault'], now)
                    previous = last_print.get(status['wheel'])
                    if should_print_feedback(previous, status['fault'], now):
                        target_rpm = feedback_target_rpm(
                            status['wheel'], left, right, max_rpm,
                            recovery.running and not a.startup_only)
                        print(format_feedback(msg.arbitration_id, msg.data, status,
                                              target_rpm, max_rpm,
                                              None if previous is None else previous[0]))
                        last_print[status['wheel']] = (status['fault'], now)
                    if not a.startup_only or status['fault'] not in (0, 0x0A):
                        recovery.observe(status)
            now = time.monotonic()
            if not a.startup_only and deadline is None and recovery.begin_run(now, latest):
                deadline = now + a.duration
                print(f'零速观察结束，左右轮最新反馈无故障；开始目标速度控制，运行{a.duration:g}秒。')
            if (a.startup_only or not recovery.running) and now >= next_summary:
                states = []
                for wheel in ('左', '右'):
                    item = latest.get(wheel)
                    if item is None:
                        state = '尚未收到反馈'
                    else:
                        fault, received = item
                        state = f'最近故障码0x{fault:02X}，距今{now - received:.1f}秒'
                    states.append(f'{wheel}轮：{state}')
                print(f'{"零速诊断" if a.startup_only else "启动等待"}，剩余{max(0, recovery.deadline - now):.1f}秒；'
                      + '；'.join(states))
                next_summary = now + 1
            if next_send < now:
                next_send = now  # 不补发积压的运动指令
            limit = deadline if deadline is not None else max(recovery.deadline, next_send)
            time.sleep(max(0, min(next_send, limit) - now))
        if a.startup_only:
            print('零速诊断结束，发送零速及失能帧；未发送目标速度指令。')
    except KeyboardInterrupt:
        print('收到中断，发送零速并关闭控制。')
    except can.CanTimeoutError as exc:
        result = 1
        print(f'发送队列等待超时：{exc}\n'
              f'当前 device={a.device}, channel={a.channel}, bitrate=500000。\n'
              '尚不能确认指令是否执行。请先运行 can_diagnose.py 检查接收，'
              '再核对接线、供电、终端及驱动兼容性。', file=sys.stderr)
    except Exception as exc:
        result = 1
        print(f'运行失败：{exc}', file=sys.stderr)
    finally:
        # 每次独立尝试，发送失败不能阻止后续停止帧或关闭USB。
        try:
            stop_errors = []
            for batch in (zero,) * 5 + (off,) * 5:
                try:
                    transmit(batch)
                except Exception as exc:
                    stop_errors.append(str(exc))
                time.sleep(period)
            if stop_errors:
                result = 1
                print(f'停止帧发送失败 {len(stop_errors)}/10 组：{stop_errors[0]}。'
                      '无法确认电机停止，请使用硬件急停。', file=sys.stderr)
        finally:
            bus.shutdown()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
