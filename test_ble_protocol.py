import math
import struct
import unittest

from ble_protocol import (
    CAPABILITIES_GOLDEN_HEX, COMMAND_GOLDEN_HEX, STATUS_GOLDEN_HEX,
    Capabilities, ControlState, GatewayStatus, MotionCommand, ProtocolError,
    StopReason, decode_capabilities, decode_command, decode_status,
    encode_capabilities, encode_command, encode_status, sequence_is_newer,
)


class BleProtocolTests(unittest.TestCase):
    def test_command_golden_vector(self):
        command = MotionCommand(0x12345678, 0x01020304, 0.5, -0.25, True)
        encoded = encode_command(command)
        self.assertEqual(encoded.hex(' ').upper(), COMMAND_GOLDEN_HEX)
        self.assertEqual(decode_command(encoded, expected_session=0x12345678,
                                        previous_sequence=0x01020303,
                                        max_linear_speed=2.5,
                                        max_angular_speed=1.0), command)

    def test_status_golden_vector(self):
        status = GatewayStatus(ControlState.ARMED, StopReason.NONE,
                               0x12345678, 0x01020304, 123, -456,
                               0x0A, 0, 250)
        encoded = encode_status(status)
        self.assertEqual(encoded.hex(' ').upper(), STATUS_GOLDEN_HEX)
        self.assertEqual(decode_status(encoded), status)

    def test_capabilities_golden_vector(self):
        capabilities = Capabilities(2.5, 1.0, 50, 300, 30000)
        encoded = encode_capabilities(capabilities)
        self.assertEqual(encoded.hex(' ').upper(), CAPABILITIES_GOLDEN_HEX)
        decoded = decode_capabilities(encoded)
        self.assertAlmostEqual(decoded.max_linear_speed, 2.5)
        self.assertAlmostEqual(decoded.max_angular_speed, 1.0)
        self.assertEqual(decoded.command_period_ms, 50)
        self.assertEqual(decoded.watchdog_timeout_ms, 300)
        self.assertEqual(decoded.max_motor_rpm_tenths, 30000)

    def test_rejects_invalid_command_shape_and_metadata(self):
        valid = bytearray(encode_command(MotionCommand(7, 2, 0.1, 0.2)))
        invalid_payloads = [valid[:-1], valid + b'\0']
        for payload in invalid_payloads:
            with self.subTest(length=len(payload)), self.assertRaises(ProtocolError):
                decode_command(payload)
        for index, value in ((0, 2), (1, 0x80), (2, 1), (4, 0)):
            payload = bytearray(valid)
            payload[index] = value
            with self.subTest(index=index), self.assertRaises(ProtocolError):
                decode_command(payload)

    def test_rejects_wrong_session_nonfinite_and_out_of_range(self):
        with self.assertRaisesRegex(ProtocolError, '当前会话'):
            decode_command(encode_command(MotionCommand(7, 2, 0, 0)), expected_session=8)
        for value in (math.nan, math.inf, -math.inf):
            payload = struct.pack('<BBHIIff', 1, 0, 0, 7, 2, value, 0)
            with self.subTest(value=value), \
                    self.assertRaisesRegex(ProtocolError, '有限值'):
                decode_command(payload)
            with self.subTest(value=value), \
                    self.assertRaisesRegex(ProtocolError, '有限值'):
                encode_command(MotionCommand(7, 2, value, 0))
        with self.assertRaisesRegex(ProtocolError, '线速度'):
            decode_command(encode_command(MotionCommand(7, 2, 2.6, 0)), max_linear_speed=2.5)
        with self.assertRaisesRegex(ProtocolError, '角速度'):
            decode_command(encode_command(MotionCommand(7, 2, 0, -1.1)), max_angular_speed=1.0)

    def test_sequence_comparison_rejects_duplicates_and_old_values(self):
        self.assertTrue(sequence_is_newer(11, 10))
        self.assertFalse(sequence_is_newer(10, 10))
        self.assertFalse(sequence_is_newer(9, 10))
        self.assertTrue(sequence_is_newer(0, 0xFFFFFFFF))
        self.assertFalse(sequence_is_newer(0xFFFFFFFF, 0))
        payload = encode_command(MotionCommand(7, 10, 0, 0))
        for previous in (10, 11):
            with self.subTest(previous=previous), self.assertRaisesRegex(ProtocolError, '重复或乱序'):
                decode_command(payload, previous_sequence=previous)


if __name__ == '__main__':
    unittest.main()
