import unittest

from ble_gateway_service import (make_stop_frames, parse_args,
                                 verify_startup_feedback)


class FakeStartupSession:
    def __init__(self, feedback=True, fault=0, clear_after=None):
        self.time = 0.0
        self.feedback = feedback
        self.fault = fault
        self.clear_after = clear_after
        self.sent = []

    def now(self):
        return self.time

    def transmit(self, frames):
        self.sent.append(frames)

    def receive_feedback(self):
        if not self.feedback:
            return []
        if self.clear_after is None:
            self.feedback = False
        fault = 0 if self.clear_after is not None and self.time >= self.clear_after else self.fault
        return [
            (None, {'wheel': '左', 'fault': fault}),
            (None, {'wheel': '右', 'fault': fault}),
        ]

    def wait_until(self, deadline):
        self.time = deadline


class BleGatewayServiceTests(unittest.TestCase):
    def test_real_mode_defaults_are_low_speed_and_explicit(self):
        args = parse_args(['--real-can', '--confirm-wheels-off-ground'])
        self.assertTrue(args.real_can)
        self.assertEqual(args.channel, 'PCAN_USBBUS1')
        self.assertEqual(args.max_rpm, 3000)
        self.assertEqual(args.max_linear_speed, 0.10)
        self.assertEqual(args.max_angular_speed, 0.30)
        self.assertEqual(args.mode, 'direct')
        self.assertEqual(args.battery, 'lithium')
        self.assertEqual(args.pi, 0)

    def test_adapter_address_is_validated_and_normalized(self):
        args = parse_args([
            '--mock-can', '--adapter-address', '90:de:80:18:88:0e'])
        self.assertEqual(args.adapter_address, '90:DE:80:18:88:0E')
        with self.assertRaises(SystemExit):
            parse_args(['--mock-can', '--adapter-address', 'not-a-mac'])

    def test_external_stop_frames_enable_zero_then_disable(self):
        args = parse_args(['--real-can', '--mode', 'external'])
        zero, off, config = make_stop_frames(args)
        self.assertEqual(zero[0][0], 0x108)
        self.assertEqual(zero[0][1][:4], bytes(4))
        self.assertNotEqual(zero, off)
        self.assertIsNone(config)

    def test_direct_stop_frames_use_0x103_control_and_requested_config(self):
        args = parse_args(['--real-can', '--mode', 'direct', '--max-rpm', '3000'])
        zero, off, config = make_stop_frames(args)
        self.assertEqual([can_id for can_id, _ in zero], [0x103, 0x103])
        self.assertEqual(zero[0][1], bytes.fromhex('00 00 00 00 14 64 00 0D'))
        self.assertEqual(config, bytes.fromhex('30 75 00 00 21 16 0D AA'))
        self.assertEqual(off[0][1], bytes.fromhex('00 00 00 00 00 00 00 08'))

    def test_startup_requires_both_fresh_fault_free_feedback(self):
        zero, _, _ = make_stop_frames(parse_args(['--real-can']))
        good = FakeStartupSession()
        latest = verify_startup_feedback(good, zero, 0.1, 0.02)
        self.assertEqual(set(latest), {'左', '右'})
        self.assertGreaterEqual(len(good.sent), 5)
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            verify_startup_feedback(FakeStartupSession(False), zero, 0.1, 0.02)
        with self.assertRaisesRegex(RuntimeError, 'motor fault'):
            verify_startup_feedback(FakeStartupSession(True, 1), zero, 0.1, 0.02)

    def test_startup_holds_zero_until_recoverable_0x0a_clears(self):
        zero, _, _ = make_stop_frames(parse_args(['--real-can']))
        session = FakeStartupSession(True, 0x0A, clear_after=0.16)
        latest = verify_startup_feedback(session, zero, 0.1, 0.02)
        self.assertEqual({fault for fault, _ in latest.values()}, {0})
        self.assertGreaterEqual(session.time, 0.16)


if __name__ == '__main__':
    unittest.main()
