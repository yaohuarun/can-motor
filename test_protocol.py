import unittest
import io
from contextlib import redirect_stdout

from motor_control import (config_frame, control_frame, external_frame,
                           parse_feedback, speed_raw, wheel_speed_raw, StartupRecovery, main)


class ProtocolTests(unittest.TestCase):
    def test_cli_mirrored_wheels_and_direction_override(self):
        args = ['--mode', 'direct', '--max-rpm', '1575',
                '--left-rpm', '10', '--right-rpm', '10']
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertIn('F9 9A 06 66 14 64 00 0D', output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ['--right-direction', '1']), 0)
        self.assertIn('06 66 06 66 14 64 00 0D', output.getvalue())

    def test_wheel_to_motor_conversion(self):
        self.assertEqual(wheel_speed_raw(10, 1575), 1638)
        self.assertEqual(wheel_speed_raw(10, 1575, -1), -1638)
        self.assertEqual(wheel_speed_raw(-10, 1575), -1638)
        self.assertEqual(wheel_speed_raw(0, 100), 0)
        self.assertEqual(wheel_speed_raw(100, 1575), 16384)
        with self.assertRaises(ValueError):
            wheel_speed_raw(10, 100)

    def test_startup_can_fault_recovers_only_after_both_clear(self):
        recovery = StartupRecovery(0, 2)
        recovery.observe(dict(wheel='左', fault=0x0A))
        recovery.observe(dict(wheel='右', fault=0x0A))
        self.assertFalse(recovery.ready)
        recovery.observe(dict(wheel='左', fault=0))
        self.assertFalse(recovery.ready)
        recovery.observe(dict(wheel='右', fault=0))
        self.assertTrue(recovery.ready)
        recovery.check_timeout(3)
        self.assertFalse(recovery.begin_run(1, {'左': (0, 1), '右': (0, 1)}))
        self.assertTrue(recovery.begin_run(2, {'左': (0, 2), '右': (0, 2)}))
        recovery.observe(dict(wheel='左', fault=0x0A))
        self.assertTrue(recovery.running)
        self.assertFalse(recovery.ready)

    def test_startup_other_fault_stops_immediately(self):
        recovery = StartupRecovery(0, 2)
        with self.assertRaises(RuntimeError):
            recovery.observe(dict(wheel='右', fault=1))

    def test_full_two_minutes_and_fresh_feedback_required(self):
        recovery = StartupRecovery(0, 120)
        for wheel in ('左', '右'):
            recovery.observe(dict(wheel=wheel, fault=0))
        self.assertFalse(recovery.begin_run(119.99, {'左': (0, 119), '右': (0, 119)}))
        with self.assertRaisesRegex(RuntimeError, '最近1秒'):
            recovery.begin_run(120, {'左': (0, 118), '右': (0, 120)})
        recovery.observe(dict(wheel='左', fault=0x0A))
        self.assertFalse(recovery.ready)
        self.assertFalse(recovery.begin_run(120, {'左': (0x0A, 120), '右': (0, 120)}))
        self.assertFalse(recovery.begin_run(121, {'左': (0x0A, 121), '右': (0, 121)}))
        with self.assertRaisesRegex(RuntimeError, '未更新'):
            recovery.begin_run(123, {'左': (0x0A, 121), '右': (0, 123)})
        recovery.observe(dict(wheel='左', fault=0))
        self.assertTrue(recovery.begin_run(120, {'左': (0, 120), '右': (0, 120)}))

    def test_startup_fault_or_missing_feedback_times_out(self):
        recovery = StartupRecovery(0, 2)
        recovery.observe(dict(wheel='左', fault=0))
        recovery.check_timeout(1.9)
        with self.assertRaisesRegex(RuntimeError, '恢复超时'):
            recovery.check_timeout(2)

    def test_startup_recurrence_revokes_clear_status(self):
        recovery = StartupRecovery(0, 2)
        recovery.observe(dict(wheel='左', fault=0))
        recovery.observe(dict(wheel='左', fault=0x0A))
        recovery.observe(dict(wheel='右', fault=0))
        self.assertFalse(recovery.ready)

    def test_speed_and_byte_order(self):
        self.assertEqual(speed_raw(30, 300), 1638)
        self.assertEqual(control_frame(16384, -16384, 20, 100),
                         bytes.fromhex('40 00 C0 00 14 64 00 0D'))
        self.assertEqual(external_frame(16384, -16384),
                         bytes.fromhex('40 00 C0 00 05 00 00 00'))

    def test_config_little_endian_and_flags(self):
        self.assertEqual(config_frame(300), bytes.fromhex('B8 0B 00 00 21 16 0D AA'))
        self.assertEqual(config_frame(300, 'lead', True, 2, 3, 4)[2:4],
                         bytes.fromhex('2B 43'))

    def test_stop(self):
        self.assertEqual(control_frame(0, 0, 0, 0, False),
                         bytes.fromhex('00 00 00 00 00 00 00 08'))
        self.assertEqual(external_frame(0, 0, False), bytes(8))

    def test_invalid_commands(self):
        for rpm, maximum in [(301, 300), (-301, 300), (0, 0), (float('nan'), 300)]:
            with self.assertRaises(ValueError):
                speed_raw(rpm, maximum)
        with self.assertRaises(ValueError):
            config_frame(300, brake_voltage=16)
        with self.assertRaises(ValueError):
            control_frame(16385, 0)

    def test_feedback(self):
        status = parse_feedback(0x101, bytes.fromhex('C0 00 00 20 10 66 00 01'))
        self.assertEqual(status['speed_raw'], -16384)
        self.assertEqual(status['fault'], 0x10)
        self.assertIsNone(parse_feedback(0x103, bytes(8)))
        self.assertIsNone(parse_feedback(0x101, bytes(7)))


if __name__ == '__main__':
    unittest.main()
