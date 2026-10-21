import contextlib
import io
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from motor_control import main


class StartupOnlyTests(unittest.TestCase):
    def test_zero_speed_even_when_fault_clears_and_returns(self):
        bus = Mock()
        feedback = []
        for fault in (0x0A, 0, 0x0A):
            for can_id in (0x101, 0x102):
                feedback.append(SimpleNamespace(
                    arbitration_id=can_id, is_extended_id=False,
                    is_remote_frame=False, is_error_frame=False,
                    data=bytes([0, 0, 0, 0, fault, 0, 0, 0])))
            feedback.append(None)
        bus.recv.side_effect = lambda **kw: feedback.pop(0) if feedback else None
        can = SimpleNamespace(Message=lambda **kw: SimpleNamespace(**kw),
                              CanTimeoutError=type('CanTimeoutError', (Exception,), {}))
        output = io.StringIO()
        with patch.dict(sys.modules, {'can': can}), \
                patch('controlcan_backend.open_bus', return_value=bus), \
                contextlib.redirect_stdout(output):
            result = main(['--backend', 'controlcan', '--mode', 'direct',
                           '--max-rpm', '100', '--left-rpm', '10', '--right-rpm', '10',
                           '--startup-only', '--startup-timeout', '0.1', '--send'])
        self.assertEqual(result, 0)
        self.assertIn('0x0A已清除', output.getvalue())
        self.assertNotIn('开始目标速度控制', output.getvalue())
        for call in bus.send.call_args_list:
            payload = call.args[0].data
            if payload[-1] != 0xAA:
                self.assertEqual(payload[:4], bytes(4))
        bus.shutdown.assert_called_once()
