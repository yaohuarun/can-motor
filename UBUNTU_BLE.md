# Ubuntu BLE 控制网关

## BLE 重启前自动清理

需要重新启动前台 BLE 网关时，在项目根目录执行：

```bash
sudo bash ubuntu/reset_ble_adapter.sh
sudo .venv/bin/python3 ble_gateway_service.py --mock-can
```

脚本只停止本项目的网关进程及服务，然后重启 BlueZ、解除蓝牙软阻塞、重置
`hci0`，最后检查 GATT/广播管理器及可用广播实例。使用其他适配器时传入
`--adapter hci1`。

真实 CAN 模式不得使用当前默认的 systemd 单元；该单元仍固定为安全的
`--mock-can`。架空驱动轮并验证硬件急停后，按照 `HARDWARE_ACCEPTANCE.md` 在前台
显式启动真实模式。

## 验收后启用真实 CAN 开机启动

只有完成 `HARDWARE_ACCEPTANCE.md` 的全部停车测试后，才能安装实机服务。实机
单元固定携带 `--real-can --confirm-hardware-commissioned`，因此日常启动不需要手工
输入这两个参数；程序本身仍保留显式模式和验收门槛，避免误运行脚本时开启 CAN。

```bash
sudo install -d -o canmotor -g canmotor /opt/can-motor
# 将当前项目（包括 .venv）部署到 /opt/can-motor 后：
sudo install -m 0644 ubuntu/can-motor-ble-real.service \
  /etc/systemd/system/can-motor-ble-real.service
sudo install -d -m 0755 /etc/can-motor
sudo touch /etc/can-motor/real-can-enabled
sudo systemctl disable --now can-motor-ble.service
sudo systemctl daemon-reload
sudo systemctl enable --now can-motor-ble-real.service
systemctl status can-motor-ble-real.service
journalctl -u can-motor-ble-real.service -f
```

实机服务遇到 CAN 故障或启动检查失败后不会自动重启。排除故障并重新架空测试前，
不要手工重启。撤销开机启动：

```bash
sudo systemctl disable --now can-motor-ble-real.service
sudo rm /etc/can-motor/real-can-enabled
```

> BLE 停车不是功能安全急停。首次试验必须架空驱动轮，且操作人员能够立即断电或使用硬件急停。

## 安装与预检

```bash
sudo apt update
sudo apt install python3-venv bluez dbus
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
python3 ubuntu/preflight.py --mock-can
bluetoothctl show
busctl introspect org.bluez /org/bluez/hci0
```

预检只读取 BlueZ 状态，不打开 CAN，也不发送电机命令。适配器必须提供
`org.bluez.GattManager1` 和 `org.bluez.LEAdvertisingManager1`。

## 配对与授权

网关的 LE 广播单独设置为持续可发现（`Discoverable=true`、`DiscoverableTimeout=0`），无需将适配器的全局可发现开关永久打开。新手机配对仍需按下面步骤临时开启配对。已配对手机直接从 App 扫描连接即可。

```bash
bluetoothctl
power on
agent on
default-agent
pairable on
pair PHONE_MAC
trust PHONE_MAC
paired-devices
```

网关只接受已配对、trusted 且已加密的连接。撤销手机：

```bash
bluetoothctl remove PHONE_MAC
```

## 部署与日志

将 `ubuntu/com.example.canmotor.conf` 安装到 `/etc/dbus-1/system.d/`，
`ubuntu/99-canmotor.rules` 安装到 `/etc/udev/rules.d/`，服务单元安装到
`/etc/systemd/system/can-motor-ble.service`。完成后执行：

```bash
sudo udevadm control --reload-rules
sudo systemctl daemon-reload
sudo systemctl enable --now can-motor-ble.service
systemctl status can-motor-ble.service
journalctl -u can-motor-ble.service -f
```

## 安全试验

1. 确认硬件急停有效，并架空左右驱动轮。
2. 首次仅使用模拟 CAN，核对回中解锁和状态通知。
3. 实机从最低速度开始，分别检查前进、后退和转向符号。
4. 松手、关闭 App、移走手机及停止服务，每种情况必须停车。
5. 20 Hz 指令流中断超过 300 ms 会触发网关看门狗。无线、进程或调度故障可能增加延迟，因此不能替代硬件急停。

任何停车失败都必须终止试验，不得提高速度或启用开机自启。
