import sys
import types
import unittest
from unittest.mock import Mock, patch

from controlcan_backend import open_bus


class PcanBackendTests(unittest.TestCase):
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
