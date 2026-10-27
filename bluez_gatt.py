"""BlueZ-facing GATT object model and registration lifecycle.

The transport is injected so the safety logic can be tested without a system bus.
The production adapter implements these calls with BlueZ GattManager1 and
LEAdvertisingManager1 on the system D-Bus.
"""
from dataclasses import dataclass

from ble_protocol import (CAPABILITIES_UUID, COMMAND_UUID, SERVICE_UUID,
                          STATUS_UUID, encode_capabilities)

BLUEZ_SERVICE = 'org.bluez'
ROOT_PATH = '/com/example/canmotor'
SERVICE_PATH = ROOT_PATH + '/service0'
COMMAND_PATH = SERVICE_PATH + '/command'
STATUS_PATH = SERVICE_PATH + '/status'
CAPABILITIES_PATH = SERVICE_PATH + '/capabilities'
ADVERTISEMENT_PATH = ROOT_PATH + '/advertisement0'


class BluezUnavailable(RuntimeError):
    pass


class ControlRejected(PermissionError):
    pass


@dataclass(frozen=True)
class DeviceSecurity:
    paired: bool
    trusted: bool
    connected: bool
    encrypted: bool

    @property
    def authorized(self):
        return self.paired and self.trusted and self.connected and self.encrypted


def diagnose_adapter(objects, adapter_path='/org/bluez/hci0'):
    interfaces = objects.get(adapter_path, {})
    missing = [name for name in ('org.bluez.GattManager1',
                                  'org.bluez.LEAdvertisingManager1')
               if name not in interfaces]
    if missing:
        raise BluezUnavailable('adapter lacks: ' + ', '.join(missing))
    adapter = interfaces.get('org.bluez.Adapter1', {})
    if adapter.get('Powered') is False:
        raise BluezUnavailable('Bluetooth adapter is powered off')
    return adapter_path


def find_adapter_by_address(objects, address):
    """Return the BlueZ object path for a stable controller address."""
    expected = address.upper()
    matches = []
    for path, interfaces in objects.items():
        adapter = interfaces.get('org.bluez.Adapter1')
        if adapter and str(adapter.get('Address', '')).upper() == expected:
            matches.append(path)
    if not matches:
        raise BluezUnavailable(f'Bluetooth adapter {expected} was not found')
    if len(matches) != 1:
        raise BluezUnavailable(f'Bluetooth adapter address {expected} is ambiguous')
    return diagnose_adapter(objects, matches[0])


class MotorGattApplication:
    def __init__(self, capabilities, command_handler, security_provider):
        self.capabilities = capabilities
        self.command_handler = command_handler
        self.security_provider = security_provider
        self.controller = None
        self.notifying = False
        self.status_value = bytes(20)
        self.notification_sink = None

    def managed_objects(self):
        return {
            SERVICE_PATH: {'org.bluez.GattService1': {
                'UUID': SERVICE_UUID, 'Primary': True}},
            COMMAND_PATH: {'org.bluez.GattCharacteristic1': {
                'UUID': COMMAND_UUID, 'Service': SERVICE_PATH,
                'Flags': ['write-without-response', 'encrypt-write']}},
            STATUS_PATH: {'org.bluez.GattCharacteristic1': {
                'UUID': STATUS_UUID, 'Service': SERVICE_PATH,
                'Flags': ['notify', 'encrypt-read']}},
            CAPABILITIES_PATH: {'org.bluez.GattCharacteristic1': {
                'UUID': CAPABILITIES_UUID, 'Service': SERVICE_PATH,
                'Flags': ['read', 'encrypt-read']}},
        }

    def read_capabilities(self):
        return encode_capabilities(self.capabilities)

    def write_command(self, value, device_path):
        security = self.security_provider(device_path)
        if not security.authorized:
            raise ControlRejected('paired, trusted, connected and encrypted link required')
        if self.controller not in (None, device_path):
            raise ControlRejected('another client owns the control session')
        self.controller = device_path
        return self.command_handler(bytes(value), device_path)

    def disconnect(self, device_path):
        if self.controller == device_path:
            self.controller = None

    def start_notify(self, sink):
        self.notification_sink = sink
        self.notifying = True
        print('BLE status notifications subscribed', flush=True)

    def stop_notify(self):
        self.notifying = False
        self.notification_sink = None
        print('BLE status notifications stopped', flush=True)

    def publish_status(self, value):
        self.status_value = bytes(value)
        if self.notifying and self.notification_sink is not None:
            try:
                self.notification_sink(self.status_value)
            except Exception:
                return False
        return True


class BluezPeripheral:
    def __init__(self, transport, application, adapter_path='/org/bluez/hci0',
                 adapter_address=None):
        self.transport = transport
        self.application = application
        self.adapter_path = adapter_path
        self.adapter_address = adapter_address
        self.registered = False

    async def start(self):
        objects = await self.transport.get_managed_objects()
        if self.adapter_address is not None:
            self.adapter_path = find_adapter_by_address(
                objects, self.adapter_address)
        else:
            diagnose_adapter(objects, self.adapter_path)
        adapter = objects[self.adapter_path].get('org.bluez.Adapter1', {})
        print(f'BLE adapter selected: path={self.adapter_path} '
              f'address={adapter.get("Address", "unknown")} '
              f'powered={adapter.get("Powered", "unknown")} '
              f'adapter_discoverable={adapter.get("Discoverable", "unknown")}',
              flush=True)
        await self.transport.export_application(ROOT_PATH, self.application)
        try:
            await self.transport.register_application(self.adapter_path, ROOT_PATH)
            await self.transport.register_advertisement(
                self.adapter_path, ADVERTISEMENT_PATH,
                {'Type': 'peripheral', 'ServiceUUIDs': [SERVICE_UUID],
                 'LocalName': 'CanMotor', 'Discoverable': True,
                 'DiscoverableTimeout': 0})
        except Exception:
            await self.stop()
            raise
        self.registered = True
        print(f'BLE advertisement registered: adapter={self.adapter_path} '
              f'name=CanMotor service_uuid={SERVICE_UUID} '
              'discoverable=True discoverable_timeout=0', flush=True)

    async def stop(self):
        # Each cleanup is best-effort because BlueZ may already have disappeared.
        for operation, args in (
                (self.transport.unregister_advertisement,
                 (self.adapter_path, ADVERTISEMENT_PATH)),
                (self.transport.unregister_application,
                 (self.adapter_path, ROOT_PATH)),
                (self.transport.unexport_application, (ROOT_PATH,))):
            try:
                await operation(*args)
            except Exception:
                pass
        self.registered = False

    async def bluez_lost(self):
        self.application.controller = None
        self.registered = False


class DbusNextBluezTransport:
    """Production system-bus transport backed by dbus-next on Ubuntu."""

    def __init__(self, bus):
        self.bus = bus
        self._exports = []
        self._advertisement = None

    @classmethod
    async def connect_system(cls):
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType
        return cls(await MessageBus(bus_type=BusType.SYSTEM).connect())

    async def _interface(self, path, interface):
        introspection = await self.bus.introspect(BLUEZ_SERVICE, path)
        proxy = self.bus.get_proxy_object(BLUEZ_SERVICE, path, introspection)
        return proxy.get_interface(interface)

    async def get_managed_objects(self):
        manager = await self._interface('/', 'org.freedesktop.DBus.ObjectManager')
        objects = await manager.call_get_managed_objects()
        return {path: {name: {key: getattr(value, 'value', value)
                              for key, value in properties.items()}
                       for name, properties in interfaces.items()}
                for path, interfaces in objects.items()}

    async def export_application(self, root_path, application):
        for path, interface in _build_dbus_interfaces(application):
            self.bus.export(path, interface)
            self._exports.append((path, interface))

    async def unexport_application(self, root_path):
        for path, interface in reversed(self._exports):
            try:
                self.bus.unexport(path, interface)
            except Exception:
                pass
        self._exports.clear()

    async def register_application(self, adapter_path, root_path):
        manager = await self._interface(adapter_path, 'org.bluez.GattManager1')
        await manager.call_register_application(root_path, {})

    async def unregister_application(self, adapter_path, root_path):
        manager = await self._interface(adapter_path, 'org.bluez.GattManager1')
        await manager.call_unregister_application(root_path)

    async def register_advertisement(self, adapter_path, path, properties):
        advertisement = _build_advertisement_interface(properties)
        self.bus.export(path, advertisement)
        self._advertisement = (path, advertisement)
        manager = await self._interface(adapter_path,
                                        'org.bluez.LEAdvertisingManager1')
        await manager.call_register_advertisement(path, {})

    async def unregister_advertisement(self, adapter_path, path):
        try:
            manager = await self._interface(adapter_path,
                                            'org.bluez.LEAdvertisingManager1')
            await manager.call_unregister_advertisement(path)
        finally:
            if self._advertisement is not None:
                exported_path, interface = self._advertisement
                self.bus.unexport(exported_path, interface)
                self._advertisement = None


def _build_dbus_interfaces(application):
    """Build dbus-next service interfaces lazily so tests run without D-Bus."""
    from dbus_next.service import ServiceInterface, dbus_property, method
    from dbus_next.constants import PropertyAccess
    from dbus_next import Variant

    class ObjectManager(ServiceInterface):
        def __init__(self):
            super().__init__('org.freedesktop.DBus.ObjectManager')

        @method()
        def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
            result = {}
            for path, interfaces in application.managed_objects().items():
                result[path] = {}
                for name, values in interfaces.items():
                    converted = {}
                    for key, value in values.items():
                        signature = {'UUID': 's', 'Primary': 'b', 'Service': 'o',
                                     'Flags': 'as'}[key]
                        converted[key] = Variant(signature, value)
                    result[path][name] = converted
            return result

    class Service(ServiceInterface):
        def __init__(self): super().__init__('org.bluez.GattService1')
        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> 's': return SERVICE_UUID
        @dbus_property(access=PropertyAccess.READ)
        def Primary(self) -> 'b': return True

    class Characteristic(ServiceInterface):
        def __init__(self, uuid, path, flags):
            super().__init__('org.bluez.GattCharacteristic1')
            self.uuid, self.path, self.flags = uuid, path, flags
        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> 's': return self.uuid
        @dbus_property(access=PropertyAccess.READ)
        def Service(self) -> 'o': return SERVICE_PATH
        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> 'as': return self.flags
        @dbus_property(access=PropertyAccess.READ)
        def Value(self) -> 'ay':
            if self.path == CAPABILITIES_PATH: return application.read_capabilities()
            if self.path == STATUS_PATH: return application.status_value
            return bytes()
        @dbus_property(access=PropertyAccess.READ)
        def Notifying(self) -> 'b': return application.notifying if self.path == STATUS_PATH else False
        @method()
        def ReadValue(self, options: 'a{sv}') -> 'ay': return self.Value
        @method()
        def WriteValue(self, value: 'ay', options: 'a{sv}'):
            if self.path != COMMAND_PATH: raise PermissionError('not writable')
            device = options.get('device')
            application.write_command(bytes(value), device.value if device else '')
        @method()
        def StartNotify(self):
            if self.path != STATUS_PATH: raise PermissionError('not notifiable')
            application.start_notify(lambda value: self.emit_properties_changed({'Value': value}))
        @method()
        def StopNotify(self): application.stop_notify()

    return [(ROOT_PATH, ObjectManager()), (SERVICE_PATH, Service()),
            (COMMAND_PATH, Characteristic(COMMAND_UUID, COMMAND_PATH,
                                           ['write-without-response', 'encrypt-write'])),
            (STATUS_PATH, Characteristic(STATUS_UUID, STATUS_PATH,
                                         ['notify', 'encrypt-read'])),
            (CAPABILITIES_PATH, Characteristic(CAPABILITIES_UUID, CAPABILITIES_PATH,
                                               ['read', 'encrypt-read']))]


def _build_advertisement_interface(properties):
    from dbus_next.service import ServiceInterface, dbus_property, method
    from dbus_next.constants import PropertyAccess

    class Advertisement(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.LEAdvertisement1')
            self._tx_power = properties.get('TxPower', 0)
        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> 's': return properties['Type']
        @dbus_property(access=PropertyAccess.READ)
        def ServiceUUIDs(self) -> 'as': return properties['ServiceUUIDs']
        @dbus_property(access=PropertyAccess.READ)
        def LocalName(self) -> 's': return properties['LocalName']
        @dbus_property(access=PropertyAccess.READ)
        def Discoverable(self) -> 'b':
            # Set the LE instance flags explicitly, independently of desktop
            # pairing settings and the adapter's global discoverable timeout.
            return properties.get('Discoverable', True)
        @dbus_property(access=PropertyAccess.READ)
        def DiscoverableTimeout(self) -> 'q':
            return properties.get('DiscoverableTimeout', 0)
        @dbus_property(access=PropertyAccess.READWRITE)
        def TxPower(self) -> 'n':
            # BlueZ versions found in the field both read this property and
            # write back the controller-selected power during registration.
            return self._tx_power
        @TxPower.setter
        def TxPower(self, value: 'n'):
            self._tx_power = value
        @method()
        def Release(self):
            print('BLE advertisement released by BlueZ', flush=True)
    return Advertisement()
