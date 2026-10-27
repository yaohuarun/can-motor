from pathlib import Path
import unittest


class UbuntuDeploymentTests(unittest.TestCase):
    def test_service_is_unprivileged_and_safety_hardened(self):
        unit = Path('ubuntu/can-motor-ble.service').read_text(encoding='utf-8')
        for setting in ('User=canmotor', 'NoNewPrivileges=true',
                        'ProtectSystem=strict', 'DevicePolicy=closed', '--mock-can'):
            self.assertIn(setting, unit)
        self.assertNotIn('User=root', unit)

        real = Path('ubuntu/can-motor-ble-real.service').read_text(encoding='utf-8')
        for setting in ('User=canmotor', 'NoNewPrivileges=true',
                        'ConditionPathExists=/etc/can-motor/real-can-enabled',
                        '--real-can', '--confirm-hardware-commissioned',
                        '--mode direct', '--max-rpm 3000',
                        '--adapter-address 90:DE:80:18:88:0E', 'Restart=no'):
            self.assertIn(setting, real)
        self.assertIn('Conflicts=can-motor-ble.service', real)
        self.assertNotIn('--confirm-wheels-off-ground', real)
        self.assertNotIn('User=root', real)

    def test_policy_is_scoped_and_preflight_never_opens_can(self):
        policy = Path('ubuntu/com.example.canmotor.conf').read_text(encoding='utf-8')
        self.assertIn('policy user="canmotor"', policy)
        self.assertNotIn('allow user="*"', policy)
        preflight = Path('ubuntu/preflight.py').read_text(encoding='utf-8')
        self.assertNotIn('open_bus(', preflight)
        self.assertIn('--mock-can', preflight)
        service = Path('ble_gateway_service.py').read_text(encoding='utf-8')
        self.assertIn('required=True', service)
        self.assertIn("args.confirm_wheels_off_ground or args.confirm_hardware_commissioned", service)
        self.assertIn("open_bus('pcan'", service)

    def test_ble_reset_script_is_scoped_and_checks_advertising_capacity(self):
        reset = Path('ubuntu/reset_ble_adapter.sh').read_text(encoding='utf-8')
        self.assertIn("set -Eeuo pipefail", reset)
        self.assertIn("systemctl restart bluetooth", reset)
        self.assertIn("skipping service restart and adapter power cycle", reset)
        self.assertEqual(reset.count("bluetoothctl >/dev/null <<EOF"), 1)
        self.assertIn("rfkill unblock bluetooth", reset)
        self.assertIn("btmgmt -i \"$adapter\" power off", reset)
        self.assertIn("ActiveInstances", reset)
        self.assertIn("SupportedInstances", reset)
        self.assertIn("[b]le_gateway_service.py", reset)
        self.assertIn("can-motor-ble-real.service", reset)
        self.assertNotIn("pkill -9", reset)


if __name__ == '__main__':
    unittest.main()
