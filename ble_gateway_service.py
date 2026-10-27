"""Ubuntu BLE motor gateway with explicit mock and guarded real-CAN modes."""
import argparse
import asyncio
import secrets
import sys

from ble_gateway import BleControlStateMachine, BleMotorGateway
from ble_protocol import Capabilities, GatewayStatus, StopReason, encode_status
from bluez_gatt import (BluezPeripheral, DbusNextBluezTransport, DeviceSecurity,
                        MotorGattApplication)
from motor_control import (MotorControlSession, config_frame, control_frame,
                           external_frame)


def security(_device):
    return DeviceSecurity(True, True, True, True)


def status_payload(machine, left_fault=0, right_fault=0):
    remaining = 0
    if machine.last_valid_at is not None:
        remaining = max(0, round((machine.watchdog_seconds -
                                  (machine.clock() - machine.last_valid_at)) * 1000))
    linear, angular = machine.target
    return encode_status(GatewayStatus(
        machine.state, machine.reason, machine.session_id,
        machine.last_sequence or 0, round(linear * 1000),
        round(angular * 1000), left_fault, right_fault, remaining))


def logged_handler(handler):
    last_report = None

    def accept(value, device):
        nonlocal last_report
        result = handler(value)
        command = result.command
        report = (result.accepted, result.state, result.reason,
                  None if command is None else command.centered,
                  None if command is None else
                  (command.linear_speed, command.angular_speed))
        if report != last_report:
            print('BLE command:', f'device={device or "unknown"}',
                  f'accepted={result.accepted}', f'state={result.state.name}',
                  f'reason={result.reason.name}',
                  f'sequence={None if command is None else command.sequence}',
                  f'centered={None if command is None else command.centered}',
                  f'target={None if command is None else (command.linear_speed, command.angular_speed)}',
                  flush=True)
            last_report = report
        return result

    return accept


def poll_and_log_watchdog(machine, poll):
    previous = machine.state
    last_valid_at = machine.last_valid_at
    state = poll()
    if (previous != state and machine.reason == StopReason.WATCHDOG and
            last_valid_at is not None):
        elapsed_ms = round((machine.clock() - last_valid_at) * 1000)
        print('BLE watchdog stop:', f'no valid command for {elapsed_ms} ms',
              f'last_sequence={machine.last_sequence}', flush=True)
    return state


async def serve(application, tick, shutdown, adapter_address=None):
    transport = await DbusNextBluezTransport.connect_system()
    peripheral = BluezPeripheral(
        transport, application, adapter_address=adapter_address)
    await peripheral.start()
    try:
        while True:
            await tick()
    finally:
        try:
            await peripheral.stop()
        finally:
            shutdown()


async def run_mock(args):
    machine = BleControlStateMachine()
    machine.connect(secrets.randbelow(0xffffffff) + 1)
    application = MotorGattApplication(
        Capabilities(args.max_linear_speed, args.max_angular_speed,
                     50, 300, round(args.max_rpm * 10)),
        logged_handler(lambda value: machine.accept(
            value, args.max_linear_speed, args.max_angular_speed)), security)

    async def tick():
        poll_and_log_watchdog(machine, machine.poll)
        application.publish_status(status_payload(machine))
        await asyncio.sleep(0.05)

    print('BLE gateway running with simulated CAN; no motor backend is open', flush=True)
    await serve(application, tick, lambda: None, args.adapter_address)


def make_stop_frames(args):
    if args.mode == 'external':
        return ([(0x108, external_frame(0, 0))],
                [(0x108, external_frame(0, 0, False))], None)
    config = config_frame(
        args.max_rpm, args.battery, False, args.pi, 0, 0,
        args.overvoltage, args.undervoltage, args.brake_voltage)
    return ([(0x103, control_frame(0, 0, args.torque, 100)),
             (0x103, config)],
            [(0x103, control_frame(0, 0, 0, 0, False)),
             (0x103, config)], config)


def verify_startup_feedback(session, zero_frames, seconds, period):
    """Hold zero speed until both motors provide fresh, fault-free feedback.

    Fault 0x0A is the controller's recoverable CAN receive warning. After the
    minimum observation window it keeps the gateway in zero-speed startup
    indefinitely; every other fault fails closed.
    """
    deadline = session.now() + seconds
    latest = {}
    next_send = session.now()
    warning_reported = False
    while True:
        session.transmit(zero_frames)
        for _, status in session.receive_feedback():
            latest[status['wheel']] = (status['fault'], session.now())
        next_send += period
        session.wait_until(next_send)
        now = session.now()
        fatal = {wheel: fault for wheel, (fault, _) in latest.items()
                 if fault not in (0, 0x0A)}
        if fatal:
            raise RuntimeError(f'startup rejected: motor fault: {fatal}')
        if now < deadline:
            continue
        if set(latest) != {'左', '右'}:
            raise RuntimeError('startup rejected: missing left/right motor feedback')
        stale = [wheel for wheel, (_, seen) in latest.items()
                 if now - seen > 1.0]
        if stale:
            raise RuntimeError('startup rejected: stale motor feedback: ' +
                               ', '.join(stale))
        warnings = [wheel for wheel, (fault, _) in latest.items()
                    if fault == 0x0A]
        if warnings:
            if not warning_reported:
                print('Startup remains at zero speed; waiting for fault 0x0A '
                      'to clear on: ' + ', '.join(warnings), flush=True)
                warning_reported = True
            continue
        return latest


async def run_real(args):
    if not (args.confirm_wheels_off_ground or args.confirm_hardware_commissioned):
        raise RuntimeError('real CAN requires --confirm-wheels-off-ground during testing '
                           'or --confirm-hardware-commissioned after acceptance')
    try:
        import can
        from controlcan_backend import open_bus
        bus = open_bus('pcan', args.channel, 0, None)
    except Exception as exc:
        raise RuntimeError(f'failed to open PCAN: {exc}') from exc

    period = args.can_period_ms / 1000
    session = MotorControlSession(bus, can, args.channel, args.tx_timeout)
    zero, off, config = make_stop_frames(args)
    session.safe_stop(zero)
    machine = BleControlStateMachine()
    gateway = BleMotorGateway(
        session, machine, args.max_linear_speed, args.max_angular_speed,
        args.max_rpm, zero, off, mode=args.mode, config=config,
        torque=args.torque,
        left_direction=args.left_direction, right_direction=args.right_direction,
        period=period)
    left_fault = right_fault = 0
    closed = False

    def shutdown():
        nonlocal closed
        if closed:
            return
        closed = True
        errors = gateway.close()
        if errors:
            print('Errors while sending shutdown frames:', '; '.join(errors),
                  file=sys.stderr, flush=True)

    try:
        print(f'Zero-speed startup observation for {args.startup_timeout:g}s...', flush=True)
        feedback_seen = verify_startup_feedback(
            session, zero, args.startup_timeout, period)
        machine.connect(secrets.randbelow(0xffffffff) + 1)
        application = MotorGattApplication(
            Capabilities(args.max_linear_speed, args.max_angular_speed,
                         50, 300, round(args.max_rpm * 10)),
            logged_handler(gateway.command), security)

        async def tick():
            nonlocal left_fault, right_fault, feedback_seen
            try:
                poll_and_log_watchdog(machine, gateway.poll)
                target = session.current_realtime_target()
                session.transmit(zero if target is None else target[0])
                for _, feedback in session.receive_feedback():
                    feedback_seen[feedback['wheel']] = (
                        feedback['fault'], session.now())
                    if feedback['wheel'] == '左':
                        left_fault = feedback['fault']
                    else:
                        right_fault = feedback['fault']
                    if feedback['fault'] not in (0, 0x0A):
                        gateway.fail(StopReason.CAN_FAULT)
                        raise RuntimeError(
                            f"{feedback['wheel']} motor fault 0x{feedback['fault']:02X}")
                stale = [wheel for wheel, (_, seen) in feedback_seen.items()
                         if session.now() - seen > 1.0]
                if stale:
                    gateway.fail(StopReason.CAN_FAULT)
                    raise RuntimeError(
                        'motor feedback stale for: ' + ', '.join(stale))
                application.publish_status(status_payload(
                    machine, left_fault, right_fault))
            except Exception:
                gateway.fail(StopReason.CAN_FAULT)
                raise
            await asyncio.sleep(period)

        print('REAL CAN ENABLED: wheels must remain off the ground; hardware E-stop required',
              flush=True)
        await serve(application, tick, shutdown, args.adapter_address)
    finally:
        shutdown()


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--mock-can', action='store_true',
                      help='run BLE protocol without opening CAN hardware')
    mode.add_argument('--real-can', action='store_true',
                      help='open PCAN and permit motor commands')
    parser.add_argument('--confirm-wheels-off-ground', action='store_true',
                        help='required acknowledgement for real CAN mode')
    parser.add_argument('--confirm-hardware-commissioned', action='store_true',
                        help='deployment acknowledgement after hardware acceptance')
    parser.add_argument('--channel', default='PCAN_USBBUS1')
    parser.add_argument('--adapter-address',
                        help='stable Bluetooth controller MAC address')
    parser.add_argument('--mode', choices=('external', 'direct'), default='direct',
                        help='direct uses 0x103; external uses 0x108')
    parser.add_argument('--max-rpm', type=float, default=3000.0)
    parser.add_argument('--max-linear-speed', type=float, default=0.10)
    parser.add_argument('--max-angular-speed', type=float, default=0.30)
    parser.add_argument('--left-direction', type=int, choices=(-1, 1), default=-1)
    parser.add_argument('--right-direction', type=int, choices=(-1, 1), default=1)
    parser.add_argument('--startup-timeout', type=float, default=5.0)
    parser.add_argument('--can-period-ms', type=float, default=20.0)
    parser.add_argument('--tx-timeout', type=float, default=0.1)
    parser.add_argument('--torque', type=int, default=20)
    parser.add_argument('--battery', choices=('lithium', 'lead'), default='lithium')
    parser.add_argument('--pi', type=int, choices=(0, 1, 2), default=0)
    parser.add_argument('--overvoltage', type=int, default=33)
    parser.add_argument('--undervoltage', type=int, default=22)
    parser.add_argument('--brake-voltage', type=int, default=13)
    args = parser.parse_args(argv)
    if args.adapter_address is not None:
        parts = args.adapter_address.split(':')
        if (len(parts) != 6 or
                any(len(part) != 2 or any(
                    character not in '0123456789abcdefABCDEF'
                    for character in part) for part in parts)):
            parser.error('--adapter-address must be a Bluetooth MAC address')
        args.adapter_address = args.adapter_address.upper()
    if args.max_rpm <= 0 or args.max_linear_speed <= 0 or args.max_angular_speed <= 0:
        parser.error('speed limits must be positive')
    if not 1 <= args.can_period_ms <= 1000:
        parser.error('--can-period-ms must be in 1..1000')
    if not 0.1 <= args.startup_timeout <= 300:
        parser.error('--startup-timeout must be in 0.1..300')
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        asyncio.run(run_mock(args) if args.mock_can else run_real(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f'BLE gateway stopped safely: {exc}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
