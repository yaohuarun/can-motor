# Ubuntu 工控机部署与开机自启动

本文说明如何将 CAN Motor BLE 网关部署到 Ubuntu 工控机的 `/opt/can-motor`，并配置真实 PCAN 服务开机启动。

## 修复重启后 App 扫描不到网关

网关广播显式导出 `Discoverable=true`、`DiscoverableTimeout=0`，避免依赖适配器全局的可发现开关和 180 秒超时。BlueZ 5.64 支持这些广播属性。适配器 `Discoverable: no` 仍可保持不变；验收以手机能扫描并完成连接为准。此修改不开放配对，也不改变配对、信任和加密校验。

在车辆停止后，将新版 `bluez_gatt.py` 传到工控机，再在该文件所在目录执行：

```bash
sudo install -o canmotor -g canmotor -m 0644 bluez_gatt.py /opt/can-motor/bluez_gatt.py
sudo systemctl restart can-motor-ble-real.service
sudo journalctl -u can-motor-ble-real.service -n 30 --no-pager
```

无需替换 systemd 服务文件或 `override.conf`，现有速度参数继续生效。启动日志应出现 `BLE adapter selected` 和 `BLE advertisement registered`，后者包含 `discoverable=True discoverable_timeout=0`；手机订阅状态成功后应出现 `BLE status notifications subscribed`。这些日志表示注册或订阅阶段完成，并不代替实际射频广播验证。

验收：关闭 App 后重启工控机，等待服务启动，再打开 App 扫描并连接；重复断开与连接，且等待超过 180 秒后再次扫描。全程不需要手动开启全局 `discoverable` 或从系统蓝牙页面主动连接。如果仍然扫描超时，应采集 `btmon` 广播记录及手机扫描日志，区分广播未实际发出和手机过滤；不要仅凭 `ActiveInstances: 1` 判断无线广播正常。

## 1. 安全前提

- 必须先完成 `HARDWARE_ACCEPTANCE.md` 中的现场验收。
- 首次运行必须架空驱动轮，确认硬件急停或直接断电手段有效。
- BLE 停车、App 停止按钮和软件看门狗不能替代硬件急停。
- 真实服务设置为 `Restart=no`。发生 CAN 故障后应先排查原因，不得盲目自动重启。

## 2. 安装依赖并检查硬件

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip bluez dbus rsync rfkill
```

PCAN 还需要安装 PEAK PCAN-Basic 和 PCAN chardev 驱动。确认设备、驱动和动态库就绪：

```bash
lsusb | grep -i -E 'peak|0c72'
lsmod | grep pcan
ls -l /dev/pcan*
cat /proc/pcan
ldconfig -p | grep -i pcan
```

本机当前第一个 PCAN-USB 设备节点应为 `/dev/pcanusb32`。

检查蓝牙：

```bash
bluetoothctl show
```

输出应包含 `Powered: yes`、`Roles: peripheral`，并且 `SupportedInstances` 不能为 0。

## 3. 创建服务用户

```bash
getent passwd canmotor >/dev/null || \
  sudo useradd --system --user-group \
    --home-dir /opt/can-motor \
    --shell /usr/sbin/nologin canmotor

sudo install -d -o canmotor -g canmotor /opt/can-motor
```

## 4. 部署项目

进入包含 `ble_gateway_service.py` 的源码根目录：

```bash
cd /path/to/can-motor
ls ble_gateway_service.py requirements.txt ubuntu/can-motor-ble-real.service
```

同步项目：

```bash
sudo rsync -a \
  --exclude='.git/' \
  --exclude='.gradle/' \
  --exclude='.kotlin/' \
  --exclude='.venv/' \
  --exclude='build/' \
  --exclude='app/build/' \
  --exclude='__pycache__/' \
  ./ /opt/can-motor/

sudo chown -R canmotor:canmotor /opt/can-motor
```

创建 Python 环境：

```bash
sudo -u canmotor python3 -m venv /opt/can-motor/.venv
sudo -u canmotor /opt/can-motor/.venv/bin/pip install --upgrade pip
sudo -u canmotor /opt/can-motor/.venv/bin/pip install \
  -r /opt/can-motor/requirements.txt
```

## 5. 安装权限配置

```bash
sudo install -m 0644 \
  /opt/can-motor/ubuntu/com.example.canmotor.conf \
  /etc/dbus-1/system.d/com.example.canmotor.conf

sudo install -m 0644 \
  /opt/can-motor/ubuntu/99-canmotor.rules \
  /etc/udev/rules.d/99-canmotor.rules

sudo udevadm control --reload-rules
sudo udevadm trigger
sudo systemctl reload dbus
sudo systemctl restart bluetooth
```

如果 PCAN 已经插入，重新插拔一次。

## 6. 安装真实 CAN 服务

先确认 PCAN 通道和速度限制符合现场配置：

```bash
grep '^ExecStart=' /opt/can-motor/ubuntu/can-motor-ble-real.service
```

安装服务及硬件验收标志：

```bash
sudo install -m 0644 \
  /opt/can-motor/ubuntu/can-motor-ble-real.service \
  /etc/systemd/system/can-motor-ble-real.service

sudo install -d -m 0755 /etc/can-motor
sudo touch /etc/can-motor/real-can-enabled
sudo systemctl daemon-reload
```

## 7. 放行 PCAN 设备节点

服务使用 `DevicePolicy=closed`，必须放行实际节点 `/dev/pcanusb32`：

```bash
sudo SYSTEMD_EDITOR=nano systemctl edit can-motor-ble-real.service
```

在下面两条注释之间加入配置：

```ini
### Anything between here and the comment below will become the new contents of the file

[Service]
DeviceAllow=/dev/pcanusb32 rw

### Lines below this comment will be discarded
```

保存操作：

1. 按 `Ctrl+O`。
2. 显示 `.#override.conf...` 临时文件名时直接按回车，不要改名。
3. 按 `Ctrl+X` 退出。

加载并确认：

```bash
sudo systemctl daemon-reload
systemctl cat can-motor-ble-real.service
```

输出末尾应包含：

```ini
# /etc/systemd/system/can-motor-ble-real.service.d/override.conf
[Service]
DeviceAllow=/dev/pcanusb32 rw
```

如果实际节点不是 `/dev/pcanusb32`，使用 `ls -l /dev/pcan*` 显示的节点。

## 8. 启用开机启动

```bash
sudo systemctl enable --now can-motor-ble-real.service
```

验证：

```bash
systemctl is-enabled can-motor-ble-real.service
systemctl is-active can-motor-ble-real.service
systemctl status can-motor-ble-real.service --no-pager
journalctl -u can-motor-ble-real.service -n 100 --no-pager
```

正常情况下，前两条命令分别输出 `enabled` 和 `active`。

## 9. 验证 BLE 广播

```bash
bluetoothctl show
```

服务启动成功后，`ActiveInstances` 应大于 0，例如：

```text
ActiveInstances: 0x01 (1)
```

BLE 广播名称为 `CanMotor`。控制器自身的 `Name` 或 `Alias` 可以是其他名称，不影响 App 按 Service UUID 扫描。手机普通蓝牙页面不一定显示 BLE GATT 外设，应使用 CAN Motor App 或 nRF Connect。

## 10. 手机配对和授权

```bash
bluetoothctl
```

进入交互界面后执行：

```text
power on
agent on
default-agent
pairable on
scan on
pair PHONE_MAC
trust PHONE_MAC
paired-devices
quit
```

将 `PHONE_MAC` 替换为手机蓝牙地址。

## 11. 更新程序

确认车辆处于安全状态后执行：

```bash
sudo systemctl stop can-motor-ble-real.service
cd /path/to/can-motor

sudo rsync -a \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='build/' \
  --exclude='app/build/' \
  --exclude='__pycache__/' \
  ./ /opt/can-motor/

sudo chown -R canmotor:canmotor /opt/can-motor
sudo -u canmotor /opt/can-motor/.venv/bin/pip install \
  -r /opt/can-motor/requirements.txt

sudo install -m 0644 \
  /opt/can-motor/ubuntu/can-motor-ble-real.service \
  /etc/systemd/system/can-motor-ble-real.service

sudo systemctl daemon-reload
sudo systemctl start can-motor-ble-real.service
```

`systemctl edit` 创建的 `override.conf` 不会被上述操作覆盖。

## 12. 蓝牙重置

```bash
cd /opt/can-motor
sudo bash ubuntu/reset_ble_adapter.sh
sudo systemctl start can-motor-ble-real.service
```

重置脚本会停止网关，但不会取消开机启动，因此重置后必须手动恢复服务。

## 13. 常用命令

```bash
# 实时日志
journalctl -u can-motor-ble-real.service -f

# 重启服务
sudo systemctl restart can-motor-ble-real.service

# 停止服务，但保留开机启动
sudo systemctl stop can-motor-ble-real.service

# 取消开机启动并停止
sudo systemctl disable --now can-motor-ble-real.service
```

## 14. 常见故障

### `failed to open PCAN: An operation is not allowed`

```bash
lsmod | grep pcan
ls -l /dev/pcan*
cat /proc/pcan
systemctl cat can-motor-ble-real.service
```

确认 `DeviceAllow` 与实际设备节点一致，例如：

```ini
DeviceAllow=/dev/pcanusb32 rw
```

### App 一直显示 `SCANNING`

```bash
systemctl is-active can-motor-ble-real.service
bluetoothctl show
journalctl -u can-motor-ble-real.service -n 100 --no-pager
```

如果服务未运行或 `ActiveInstances` 为 0，手机无法发现网关。

### 修改 service 后启动参数没有变化

systemd 使用 `/etc/systemd/system/` 中的副本。重新安装后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart can-motor-ble-real.service
```
