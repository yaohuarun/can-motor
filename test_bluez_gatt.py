import unittest

from ble_protocol import Capabilities, MotionCommand, encode_command
from bluez_gatt import (BluezPeripheral, BluezUnavailable, ControlRejected,
                        DeviceSecurity, MotorGattApplication, diagnose_adapter,
                        _build_advertisement_interface, _build_dbus_interfaces)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.objects = {'/org/bluez/hci0': {
            'org.bluez.Adapter1': {'Powered': True},
            'org.bluez.GattManager1': {},
            'org.bluez.LEAdvertisingManager1': {}}}

    async def get_managed_objects(self): return self.objects
    async def export_application(self, *a): self.calls.append(('export', *a))
    async def register_application(self, *a): self.calls.append(('register_app', *a))
    async def register_advertisement(self, *a): self.calls.append(('register_ad', *a))
    async def unregister_advertisement(self, *a): self.calls.append(('unregister_ad', *a))
    async def unregister_application(self, *a): self.calls.append(('unregister_app', *a))
    async def unexport_application(self, *a): self.calls.append(('unexport', *a))


class BluezGattTests(unittest.IsolatedAsyncioTestCase):
    def app(self, handler=lambda value, device: value):
        return MotorGattApplication(
            Capabilities(1, 1), handler,
            lambda device: DeviceSecurity(True, True, True, True))

    async def test_register_and_unregister(self):
        transport = FakeTransport()
        peripheral = BluezPeripheral(transport, self.app())
        await peripheral.start()
        self.assertTrue(peripheral.registered)
        self.assertEqual(transport.calls[1][0], 'register_app')
        self.assertEqual(transport.calls[2][0], 'register_ad')
        await peripheral.stop()
        self.assertFalse(peripheral.registered)
        self.assertIn('unregister_ad', [c[0] for c in transport.calls])

    async def test_adapter_diagnostics_and_bluez_loss(self):
        with self.assertRaises(BluezUnavailable):
            diagnose_adapter({'/org/bluez/hci0': {'org.bluez.GattManager1': {}}})
        transport = FakeTransport()
        peripheral = BluezPeripheral(transport, self.app())
        await peripheral.start()
        peripheral.application.controller = '/device/one'
        await peripheral.bluez_lost()
        self.assertIsNone(peripheral.application.controller)
        self.assertFalse(peripheral.registered)

    async def test_authorization_single_controller_and_notification_failure(self):
        security = {'/good': DeviceSecurity(True, True, True, True),
                    '/bad': DeviceSecurity(True, True, True, False)}
        received = []
        app = MotorGattApplication(Capabilities(1, 1),
                                   lambda value, device: received.append(device),
                                   lambda device: security.get(
                                       device, DeviceSecurity(True, True, True, True)))
        command = encode_command(MotionCommand(1, 1, 0, 0, True))
        with self.assertRaises(ControlRejected):
            app.write_command(command, '/bad')
        app.write_command(command, '/good')
        with self.assertRaises(ControlRejected):
            app.write_command(command, '/other')
        app.start_notify(lambda value: (_ for _ in ()).throw(RuntimeError('gone')))
        self.assertFalse(app.publish_status(bytes(20)))
        self.assertEqual(received, ['/good'])

    async def test_production_dbus_interfaces_are_constructible(self):
        interfaces = _build_dbus_interfaces(self.app())
        self.assertEqual(len(interfaces), 5)
        self.assertEqual(interfaces[0][1].name,
                         'org.freedesktop.DBus.ObjectManager')
        advertisement = _build_advertisement_interface({
            'Type': 'peripheral', 'ServiceUUIDs': ['service'],
            'LocalName': 'CanMotor'})
        self.assertEqual(advertisement.name, 'org.bluez.LEAdvertisement1')


if __name__ == '__main__':
    unittest.main()
