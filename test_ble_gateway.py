import unittest

from ble_gateway import BleControlStateMachine, BleMotorGateway
from ble_protocol import ControlState, MotionCommand, StopReason, encode_command


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


class BleControlStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.machine = BleControlStateMachine(self.clock)
        self.machine.connect(7)

    def command(self, sequence, linear=0, angular=0, centered=False, session=7):
        return encode_command(MotionCommand(session, sequence, linear, angular, centered))

    def test_center_to_arm_and_healthy_twenty_hz_stream(self):
        self.assertFalse(self.machine.accept(self.command(1, 0.1), 1, 1).accepted)
        self.assertEqual(self.machine.state, ControlState.WAIT_CENTER)
        self.assertTrue(self.machine.accept(self.command(1, centered=True), 1, 1).accepted)
        for sequence in range(2, 8):
            self.clock.now += 0.05
            self.assertTrue(self.machine.accept(self.command(sequence, 0.1), 1, 1).accepted)
            self.assertEqual(self.machine.poll(), ControlState.ARMED)

    def test_invalid_first_frame_recovers_with_current_session_zero(self):
        for invalid in (b'bad', self.command(1, session=6, centered=True)):
            with self.subTest(invalid=invalid):
                self.machine.connect(7)
                self.assertFalse(self.machine.accept(invalid, 1, 1).accepted)
                self.assertEqual(self.machine.reason, StopReason.INVALID_COMMAND)
                self.assertFalse(self.machine.accept(self.command(2, 0.1), 1, 1).accepted)
                self.assertEqual(self.machine.target, (0, 0))
                result = self.machine.accept(self.command(3, centered=True), 1, 1)
                self.assertTrue(result.accepted)
                self.assertEqual(result.reason, StopReason.NONE)
                self.assertEqual(self.machine.target, (0, 0))
                self.assertTrue(self.machine.accept(self.command(4, 0.1), 1, 1).accepted)

    def test_invalid_after_arming_recovers_with_forward_sequence_zero(self):
        self.machine.accept(self.command(10, centered=True), 1, 1)
        self.machine.accept(self.command(11, 0.1), 1, 1)
        self.machine.accept(b'bad', 1, 1)
        self.assertTrue(self.machine.accept(self.command(12, centered=True), 1, 1).accepted)
        self.assertEqual(self.machine.last_sequence, 12)
        self.assertEqual(self.machine.reason, StopReason.NONE)

    def test_zero_does_not_clear_hardware_or_shutdown_stop(self):
        for reason in (StopReason.CAN_FAULT, StopReason.SPEED_LIMIT,
                       StopReason.SHUTDOWN, StopReason.BLUEZ_LOST):
            with self.subTest(reason=reason):
                self.machine.connect(7)
                self.machine.safe_stop(reason)
                self.assertFalse(self.machine.accept(
                    self.command(1, centered=True), 1, 1).accepted)
                self.assertEqual(self.machine.reason, reason)
                self.assertEqual(self.machine.target, (0, 0))

    def test_watchdog_boundary_invalid_and_disconnect(self):
        self.machine.accept(self.command(1, centered=True), 1, 1)
        self.clock.now = 0.300
        self.assertEqual(self.machine.poll(), ControlState.ARMED)
        self.clock.now = 0.301
        self.assertEqual(self.machine.poll(), ControlState.SAFE_STOP)
        self.assertEqual(self.machine.reason, StopReason.WATCHDOG)
        self.assertEqual(self.machine.target, (0, 0))

        moving = self.machine.accept(self.command(2, 0.1), 1, 1)
        self.assertFalse(moving.accepted)
        self.assertEqual(self.machine.state, ControlState.SAFE_STOP)
        centered = self.machine.accept(self.command(3, centered=True), 1, 1)
        self.assertTrue(centered.accepted)
        self.assertEqual(self.machine.state, ControlState.ARMED)
        self.assertEqual(self.machine.reason, StopReason.NONE)

        self.machine.connect(8)
        self.assertFalse(self.machine.accept(self.command(2, session=7), 1, 1).accepted)
        self.assertEqual(self.machine.reason, StopReason.INVALID_COMMAND)
        # Wrong-session frames cannot reset the baseline.
        self.assertFalse(self.machine.accept(
            self.command(3, session=7, centered=True), 1, 1).accepted)
        self.assertEqual(self.machine.state, ControlState.SAFE_STOP)

        self.machine.connect(9)
        self.assertTrue(self.machine.accept(
            self.command(100, session=9, centered=True), 1, 1).accepted)
        self.assertFalse(self.machine.accept(
            self.command(1, session=9, centered=True), 1, 1).accepted)
        self.assertEqual(self.machine.reason, StopReason.INVALID_COMMAND)
        recovered = self.machine.accept(
            self.command(2, session=9, centered=True), 1, 1)
        self.assertTrue(recovered.accepted)
        self.assertEqual(self.machine.state, ControlState.ARMED)
        self.assertEqual(self.machine.last_sequence, 2)

        self.machine.connect(9)
        self.assertEqual(self.machine.state, ControlState.WAIT_CENTER)
        self.assertEqual(self.machine.target, (0, 0))
        self.machine.disconnect()
        self.assertEqual(self.machine.reason, StopReason.DISCONNECT)
        self.assertEqual(self.machine.session_id, 0)


class FakeMotor:
    def __init__(self):
        self.targets = []
        self.stops = []
        self.closed = False

    def update_realtime_target(self, linear, angular, max_rpm, *args):
        if abs(linear) * 1000 > max_rpm:
            raise ValueError('wheel overspeed')
        self.targets.append((linear, angular))

    def safe_stop(self, frames):
        self.stops.append(frames)

    def close(self, zero, off, period):
        self.closed = True
        return []


class BleMotorGatewayTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.machine = BleControlStateMachine(self.clock)
        self.machine.connect(7)
        self.motor = FakeMotor()
        self.zero = [(0x108, bytes(8))]
        self.gateway = BleMotorGateway(self.motor, self.machine, 1, 1, 300,
                                       self.zero, self.zero)

    def command(self, sequence, linear=0, centered=False):
        return encode_command(MotionCommand(7, sequence, linear, 0, centered))

    def test_authorized_latest_target_and_all_stop_paths(self):
        self.gateway.command(self.command(1, centered=True))
        self.assertTrue(self.gateway.command(self.command(2, 0.1)).accepted)
        self.assertAlmostEqual(self.motor.targets[-1][0], 0.1)
        self.assertEqual(self.motor.targets[-1][1], 0)
        self.clock.now = 0.301
        self.gateway.poll()
        self.assertEqual(self.motor.stops[-1], self.zero)
        self.machine.connect(8)
        self.gateway.disconnect()
        self.gateway.fail()
        self.gateway.close()
        self.assertTrue(self.motor.closed)
        self.assertGreaterEqual(len(self.motor.stops), 4)

    def test_illegal_and_motor_speed_limit_stop(self):
        result = self.gateway.command(self.command(1, 0.1))
        self.assertFalse(result.accepted)
        self.machine.connect(7)
        self.gateway.command(self.command(1, centered=True))
        result = self.gateway.command(self.command(2, 0.5))
        self.assertFalse(result.accepted)
        self.assertEqual(self.machine.reason, StopReason.SPEED_LIMIT)


if __name__ == '__main__':
    unittest.main()
