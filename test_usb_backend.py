"""不枚举USB设备，仅验证DLL后端选择与失败诊断。"""
import sys
import types
import unittest
from unittest.mock import Mock, patch

from motor_control import prepare_usb_backend


class UsbBackendTests(unittest.TestCase):
    def modules(self, results, legacy=None):
        usb = types.ModuleType('usb')
        usb.backend = types.ModuleType('usb.backend')
        usb.backend.libusb1 = types.ModuleType('usb.backend.libusb1')
        usb.backend.libusb0 = types.ModuleType('usb.backend.libusb0')
        usb.backend.libusb1.get_backend = Mock(side_effect=results)
        usb.backend.libusb0.get_backend = Mock(return_value=legacy)
        package = types.ModuleType('libusb_package')
        package.find_library = Mock()
        return usb, package, {
            'usb': usb, 'usb.backend': usb.backend,
            'usb.backend.libusb1': usb.backend.libusb1,
            'usb.backend.libusb0': usb.backend.libusb0,
            'libusb_package': package,
        }

    def test_bundled_dll_callback(self):
        expected = object()
        usb, package, modules = self.modules([None, expected])
        with patch.dict(sys.modules, modules):
            self.assertIs(prepare_usb_backend(), expected)
        usb.backend.libusb1.get_backend.assert_called_with(
            find_library=package.find_library)

    def test_existing_backend(self):
        expected = object()
        usb, _, modules = self.modules([expected])
        with patch.dict(sys.modules, modules):
            self.assertIs(prepare_usb_backend(), expected)
        usb.backend.libusb1.get_backend.assert_called_once_with()

    def test_missing_dll(self):
        _, _, modules = self.modules([None, None])
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, 'libusb-package'):
                prepare_usb_backend()

    def test_legacy_backend(self):
        expected = object()
        _, _, modules = self.modules([None, None], expected)
        with patch.dict(sys.modules, modules):
            self.assertIs(prepare_usb_backend(), expected)
