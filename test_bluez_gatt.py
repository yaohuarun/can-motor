import unittest

from ble_protocol import Capabilities, MotionCommand, encode_command
from bluez_gatt import (BluezPeripheral, BluezUnavailable, ControlRejected,
                        DeviceSecurity, MotorGattApplication, diagnose_adapter,
                        find_adapter_by_address,
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
        advertisement = transport.calls[2][3]
        self.assertTrue(advertisement['Discoverable'])
        self.assertEqual(advertisement['DiscoverableTimeout'], 0)
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

    async def test_adapter_is_selected_by_stable_address(self):
        transport = FakeTransport()
        transport.objects['/org/bluez/hci0']['org.bluez.Adapter1']['Address'] = (
            'C0:E3:50:CE:EF:AD')
        transport.objects['/org/bluez/hci1'] = {
            'org.bluez.Adapter1': {
                'Powered': True, 'Address': '90:DE:80:18:88:0E'},
            'org.bluez.GattManager1': {},
            'org.bluez.LEAdvertisingManager1': {}}
        self.assertEqual(find_adapter_by_address(
            transport.objects, '90:de:80:18:88:0e'), '/org/bluez/hci1')
        peripheral = BluezPeripheral(
            transport, self.app(), adapter_address='90:DE:80:18:88:0E')
        await peripheral.start()
        self.assertEqual(peripheral.adapter_path, '/org/bluez/hci1')
        self.assertEqual(transport.calls[1][1], '/org/bluez/hci1')
        self.assertEqual(transport.calls[2][1], '/org/bluez/hci1')
        with self.assertRaises(BluezUnavailable):
            find_adapter_by_address(transport.objects, '00:00:00:00:00:00')

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
        self.assertTrue(advertisement.Discoverable)
        self.assertEqual(advertisement.DiscoverableTimeout, 0)
        # Verify exported D-Bus signatures: BlueZ reads GetAll, not Python fields.
        from dbus_next.service import ServiceInterface
        exported = ServiceInterface._get_all_property_values
        values = {}
        def collect(interface, properties, user_data, error):
            self.assertIsNone(error)
            values.update(properties)
        exported(advertisement, collect)
        self.assertEqual(values['Discoverable'].signature, 'b')
        self.assertTrue(values['Discoverable'].value)
        self.assertEqual(values['DiscoverableTimeout'].signature, 'q')
        self.assertEqual(values['DiscoverableTimeout'].value, 0)
        self.assertEqual(advertisement.TxPower, 0)
        advertisement.TxPower = -8
        self.assertEqual(advertisement.TxPower, -8)

        advertisement = _build_advertisement_interface({
            'Type': 'peripheral', 'ServiceUUIDs': ['service'],
            'LocalName': 'CanMotor', 'TxPower': -12})
        self.assertEqual(advertisement.TxPower, -12)

    async def test_advertisement_discovery_does_not_depend_on_adapter_global_state(self):
        transport = FakeTransport()
        adapter = transport.objects['/org/bluez/hci0']['org.bluez.Adapter1']
        adapter.update(Discoverable=False, DiscoverableTimeout=180, Pairable=False)
        peripheral = BluezPeripheral(transport, self.app())
        for _ in range(2):
            await peripheral.start()
            registration = [c for c in transport.calls if c[0] == 'register_ad'][-1]
            interface = _build_advertisement_interface(registration[3])
            self.assertTrue(interface.Discoverable)
            self.assertEqual(interface.DiscoverableTimeout, 0)
            self.assertFalse(adapter['Discoverable'])
            self.assertFalse(adapter['Pairable'])
            await peripheral.stop()


if __name__ == '__main__':
    unittest.main()
