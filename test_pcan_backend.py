import sys
import types
import unittest
from unittest.mock import Mock, patch

from controlcan_backend import open_bus, resolve_backend


class PcanBackendTests(unittest.TestCase):
    def test_auto_backend_is_platform_specific(self):
        with patch('controlcan_backend.platform.system', return_value='Windows'):
            self.assertEqual(resolve_backend(), 'pcan')
        with patch('controlcan_backend.platform.system', return_value='Linux'):
            self.assertEqual(resolve_backend(), 'pcan')

    def test_explicit_backend_is_not_changed_on_windows(self):
        with patch('controlcan_backend.platform.system', return_value='Windows'):
            self.assertEqual(resolve_backend('canalystii'), 'canalystii')

    def test_linux_rejects_non_pcan_backends(self):
        with patch('controlcan_backend.platform.system', return_value='Linux'):
            for backend in ('controlcan', 'canalystii'):
                with self.subTest(backend=backend), self.assertRaisesRegex(
                        RuntimeError, '仅支持PCAN'):
                    resolve_backend(backend)

    def test_default_pcan_channel_and_bitrate(self):
        can = types.ModuleType('can')
        can.Bus = Mock(return_value=object())
        with patch.dict(sys.modules, {'can': can}):
            bus = open_bus('pcan', None, 0)
        self.assertIs(bus, can.Bus.return_value)
        can.Bus.assert_called_once_with(interface='pcan', channel='PCAN_USBBUS1',
                                        bitrate=500000)

    def test_named_pcan_channel(self):
        can = types.ModuleType('can')
        can.Bus = Mock(return_value=object())
        with patch.dict(sys.modules, {'can': can}):
            open_bus('pcan', 'PCAN_USBBUS2', 0)
        self.assertEqual(can.Bus.call_args.kwargs['channel'], 'PCAN_USBBUS2')


if __name__ == '__main__':
    unittest.main()
