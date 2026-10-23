import unittest

from ble_gateway import BleControlStateMachine, BleMotorGateway
from ble_protocol import (ControlState, GatewayStatus, MotionCommand, StopReason,
                          decode_status, encode_command, encode_status)


class Clock:
    now = 0.0
    def __call__(self): return self.now


class FakeMotor:
    def __init__(self): self.target = None; self.stopped = 0
    def update_realtime_target(self, linear, angular, maximum, *args): self.target = (linear, angular)
    def safe_stop(self, frames): self.target = (0, 0); self.stopped += 1
    def close(self, *args): return []


class CrossEndIntegrationTests(unittest.TestCase):
    def test_android_to_ubuntu_simulated_session(self):
        clock = Clock(); motor = FakeMotor(); machine = BleControlStateMachine(clock)
        gateway = BleMotorGateway(motor, machine, 1, 1, 300, [('zero', b'')], [('off', b'')])
        machine.connect(100)
        gateway.command(encode_command(MotionCommand(100, 1, 0, 0, True)))
        self.assertEqual(machine.state, ControlState.ARMED)
        for sequence in range(2, 12):
            clock.now += 0.05
            gateway.command(encode_command(MotionCommand(100, sequence, 0.1, 0.2)))
            self.assertEqual(gateway.poll(), ControlState.ARMED)
        gateway.command(encode_command(MotionCommand(100, 12, 0, 0, True)))
        self.assertEqual(motor.target, (0.0, 0.0))
        status = GatewayStatus(machine.state, machine.reason, 100, 12, 0, 0, 0, 0, 300)
        self.assertEqual(decode_status(encode_status(status)), status)
        clock.now += 0.301
        gateway.poll()
        self.assertEqual(machine.reason, StopReason.WATCHDOG)
        gateway.disconnect()
        machine.connect(101)
        rejected = gateway.command(encode_command(MotionCommand(101, 1, 0.1, 0)))
        self.assertFalse(rejected.accepted)
        self.assertEqual(machine.state, ControlState.WAIT_CENTER)


if __name__ == '__main__':
    unittest.main()
