import unittest
import io
import math
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from motor_control import (config_frame, control_frame, external_frame,
                           parse_feedback, speed_raw, wheel_speed_raw, StartupRecovery, main,
                           differential_wheel_rpm)


class ProtocolTests(unittest.TestCase):
    def test_differential_motion(self):
        # 期望值为轮缘线速度，独立于减速器与安装方向。
        for v, w, expected in (
                (0, 0, (0, 0)), (0.2, 0, (0.2, 0.2)),
                (-0.2, 0, (-0.2, -0.2)), (0, 1, (-0.21, 0.21)),
                (0, -1, (0.21, -0.21)), (0.2, 0.5, (0.095, 0.305))):
            with self.subTest(v=v, w=w):
                left, right = differential_wheel_rpm(v, w)
                self.assertAlmostEqual(left * math.pi * 0.254 / 60, expected[0])
                self.assertAlmostEqual(right * math.pi * 0.254 / 60, expected[1])
        left, right = differential_wheel_rpm(math.pi * 0.254 / 6, 0)
        self.assertAlmostEqual(left, 10)
        self.assertAlmostEqual(right, 10)
        self.assertEqual(wheel_speed_raw(left, 1575), 1638)
        self.assertEqual(wheel_speed_raw(right, 1575, -1), -1638)

    def test_cli_mirrored_wheels_and_direction_override(self):
        args = ['--mode', 'direct', '--max-rpm', '1575',
                '--linear-speed', str(math.pi * 0.254 / 6)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertIn('06 66 F9 9A 14 64 00 0D', output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ['--left-direction', '1', '--right-direction', '-1']), 0)
        self.assertIn('F9 9A 06 66 14 64 00 0D', output.getvalue())

    def test_invalid_body_velocity_never_opens_bus(self):
        for mode in ('external', 'direct'):
            for v, w in (('nan', '0'), ('inf', '0'), ('-inf', '0'),
                         ('0', 'nan'), ('0', 'inf'), ('0', '-inf'),
                         ('1e308', '1e308'), ('1e306', '0'),
                         ('0.2', '0.5'), ('-0.2', '-0.5')):
                with self.subTest(mode=mode, v=v, w=w), \
                        patch('controlcan_backend.open_bus') as open_bus, \
                        redirect_stderr(io.StringIO()) as errors:
                    with self.assertRaises(SystemExit) as exc:
                        main(['--mode', mode, '--max-rpm', '300',
                              f'--linear-speed={v}', f'--angular-speed={w}', '--send'])
                    self.assertEqual(exc.exception.code, 2)
                    self.assertIn('error:', errors.getvalue())
                    open_bus.assert_not_called()

    def test_speed_boundary_and_quantized_maximum(self):
        # 100 rpm轮速恰好对应1575 rpm电机轴速度。
        left, right = differential_wheel_rpm(math.pi * 0.254 * 100 / 60, 0)
        self.assertEqual(wheel_speed_raw(left, 1575), 16384)
        self.assertEqual(wheel_speed_raw(right, 1575, -1), -16384)
        for maximum in ('1575.04', '1574.96'):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--max-rpm', maximum, '--linear-speed',
                                       str(math.pi * 0.254 * 100 / 60)]), 0)
            self.assertIn('40 00 C0 00', output.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['--max-rpm', '1574.94', '--linear-speed',
                  str(math.pi * 0.254 * 100 / 60)])

    def test_default_zero_and_legacy_arguments(self):
        with patch('controlcan_backend.open_bus') as open_bus:
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--max-rpm', '300']), 0)
            self.assertIn('线速度=0 m/s，角速度=0 rad/s', output.getvalue())
            self.assertIn('00 00 00 00 05 00 00 00', output.getvalue())
            for old_arg in ('--left-rpm', '--right-rpm'):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                    main(['--max-rpm', '300', old_arg, '1', '--send'])
                self.assertEqual(exc.exception.code, 2)
            open_bus.assert_not_called()

    def test_modes_share_differential_target_in_preview(self):
        # v=0.1、w=0.2对应左0.058、右0.142 m/s；固定期望编码独立核算。
        for mode, suffix in (('external', '05 00 00 00'),
                             ('direct', '14 64 00 0D')):
            with self.subTest(mode=mode), \
                    patch('controlcan_backend.open_bus') as open_bus, \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--mode', mode, '--max-rpm', '300',
                                       '--linear-speed', '0.1', '--angular-speed', '0.2']), 0)
                self.assertIn('线速度=0.1 m/s，角速度=0.2 rad/s', output.getvalue())
                self.assertIn('轮端目标rpm', output.getvalue())
                self.assertIn('电机轴指令rpm', output.getvalue())
                self.assertIn('23 E0 F1 59 ' + suffix, output.getvalue())
                open_bus.assert_not_called()

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
