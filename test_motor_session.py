from types import SimpleNamespace
import unittest

from motor_control import MotorControlSession


class FakeBus:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []
        self.shutdown_count = 0

    def send(self, message, timeout):
        self.sent.append((message, timeout))

    def recv(self, timeout):
        return self.messages.pop(0) if self.messages else None

    def shutdown(self):
        self.shutdown_count += 1


class MotorControlSessionTests(unittest.TestCase):
    def test_injected_backend_clock_and_feedback(self):
        feedback = SimpleNamespace(arbitration_id=0x101, data=bytes(8),
                                   is_extended_id=False, is_remote_frame=False,
                                   is_error_frame=False)
        bus = FakeBus([feedback])
        sleeps = []
        can = SimpleNamespace(Message=lambda **values: SimpleNamespace(**values))
        session = MotorControlSession(bus, can, channel='test', tx_timeout=0.25,
                                      clock=lambda: 4.0, sleeper=sleeps.append)
        session.transmit([(0x108, bytes(8))])
        received = list(session.receive_feedback())
        session.wait_until(4.2)
        self.assertEqual(bus.sent[0][0].arbitration_id, 0x108)
        self.assertEqual(bus.sent[0][1], 0.25)
        self.assertEqual(received[0][1]['wheel'], '左')
        self.assertAlmostEqual(sleeps[0], 0.2)

    def test_close_attempts_every_stop_frame_and_is_idempotent(self):
        bus = FakeBus()
        can = SimpleNamespace(Message=lambda **values: SimpleNamespace(**values))
        sleeps = []
        session = MotorControlSession(bus, can, sleeper=sleeps.append)
        self.assertEqual(session.close([(0x108, b'zero')], [(0x108, b'off')], 0.02), [])
        self.assertEqual([item[0].data for item in bus.sent[:5]], [b'zero'] * 5)
        self.assertEqual([item[0].data for item in bus.sent[5:]], [b'off'] * 5)
        self.assertEqual(sleeps, [0.02] * 10)
        self.assertEqual(bus.shutdown_count, 1)
        session.close([], [], 0.02)
        self.assertEqual(bus.shutdown_count, 1)

    def test_realtime_slot_keeps_latest_and_safe_stop_is_next_target(self):
        bus = FakeBus()
        can = SimpleNamespace(Message=lambda **values: SimpleNamespace(**values))
        session = MotorControlSession(bus, can)
        session.update_realtime_target(0.05, 0, 300)
        latest_left, latest_right = session.update_realtime_target(0.1, 0, 300)
        frames, left, right = session.current_realtime_target()
        self.assertEqual((left, right), (latest_left, latest_right))
        self.assertNotEqual(frames[0][1][:4], bytes(4))
        zero = [(0x108, bytes.fromhex('00 00 00 00 05 00 00 00'))]
        session.safe_stop(zero)
        self.assertEqual(session.current_realtime_target(), (zero, 0, 0))

    def test_realtime_target_rejects_nonfinite_and_wheel_overspeed(self):
        bus = FakeBus()
        can = SimpleNamespace(Message=lambda **values: SimpleNamespace(**values))
        session = MotorControlSession(bus, can)
        for linear, angular in ((float('nan'), 0), (100, 0), (0, 100)):
            with self.subTest(linear=linear, angular=angular):
                with self.assertRaises(ValueError):
                    session.update_realtime_target(linear, angular, 300)
        self.assertIsNone(session.current_realtime_target())


if __name__ == '__main__':
    unittest.main()
