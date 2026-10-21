import ctypes as C
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from controlcan_backend import CanObject, InitConfig, ControlCanBus, library_path


class ControlCanTests(unittest.TestCase):
    def test_linux_library_selection(self):
        for machine, bits, directory, elf_class, elf_machine in (
            ('x86_64', 8, 'x86_64', 2, 62), ('i686', 4, 'x86', 1, 3),
            ('aarch64', 8, 'aarch64', 2, 183), ('armv7l', 4, 'arm', 1, 40)):
            with self.subTest(machine=machine), \
                    patch('controlcan_backend.platform.system', return_value='Linux'), \
                    patch('controlcan_backend.platform.machine', return_value=machine), \
                    patch('controlcan_backend.C.sizeof', return_value=bits):
                path = library_path()
                self.assertEqual(path.parent.name, directory)
                header = path.read_bytes()[:20]
                self.assertEqual(header[:4], b'\x7fELF')
                self.assertEqual(header[4], elf_class)
                self.assertEqual(int.from_bytes(header[18:20], 'little'), elf_machine)

    def test_linux_uses_cdll_and_closes_device(self):
        dll = Mock()
        for name in ('VCI_OpenDevice', 'VCI_InitCAN', 'VCI_StartCAN'):
            getattr(dll, name).return_value = 1
        with patch('controlcan_backend.platform.system', return_value='Linux'), \
                patch('controlcan_backend.platform.machine', return_value='x86_64'), \
                patch('controlcan_backend.C.CDLL', return_value=dll) as loader:
            bus = ControlCanBus()
            self.assertTrue(loader.call_args.args[0].endswith('libcontrolcan.so'))
            self.assertEqual(dll.VCI_InitCAN.call_args.args[3]._obj.Timing1, 0x1C)
            bus.shutdown()
            bus.shutdown()
        dll.VCI_CloseDevice.assert_called_once_with(4, 0)

    def test_sdk_layout(self):
        self.assertEqual(C.sizeof(CanObject), 24)
        self.assertEqual(CanObject.Data.offset, 13)
        self.assertEqual(C.sizeof(InitConfig), 16)
        self.assertEqual(InitConfig.Timing0.offset, 13)

    def bus(self):
        bus = ControlCanBus.__new__(ControlCanBus)
        bus.channel, bus.device = 0, 0
        bus.dll = Mock()
        return bus

    def test_normal_transmit_and_payload(self):
        bus = self.bus()
        def transmit(kind, device, channel, ptr, length):
            obj = C.cast(ptr, C.POINTER(CanObject)).contents
            self.assertEqual((kind, channel, length), (4, 0, 1))
            self.assertEqual(obj.ID, 0x103)
            self.assertEqual(obj.SendType, 0)
            self.assertEqual(bytes(obj.Data), bytes.fromhex('06 66 06 66 14 64 00 0D'))
            return 1
        bus.dll.VCI_Transmit.side_effect = transmit
        msg = SimpleNamespace(arbitration_id=0x103, dlc=8, is_extended_id=False,
                              is_remote_frame=False, data=bytes.fromhex('06 66 06 66 14 64 00 0D'))
        bus.send(msg)
        bus.dll.VCI_Transmit.side_effect = None
        bus.dll.VCI_Transmit.return_value = 0
        with self.assertRaisesRegex(RuntimeError, 'Transmit'):
            bus.send(msg)

    def test_shutdown_closes_after_reset_failure(self):
        bus = self.bus()
        bus._opened = True
        bus._dll_dir = Mock()
        dll_directory = bus._dll_dir
        bus.dll.VCI_ResetCAN.side_effect = RuntimeError('reset failed')
        with self.assertRaises(RuntimeError):
            bus.shutdown()
        bus.dll.VCI_CloseDevice.assert_called_once_with(4, 0)
        dll_directory.close.assert_called_once()
