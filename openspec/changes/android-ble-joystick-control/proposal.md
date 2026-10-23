# Proposal

## Why

现有控制程序只能在工控机命令行启动固定的线速度和角速度，无法让操作者通过移动设备实时驾驶小车。需要提供 Android 虚拟手柄和 Ubuntu 工控机 BLE 控制入口，同时把失联、松手和重连行为设计为默认停车，降低无线遥控失控风险。

## What Changes

- 新增 Android App，通过 BLE 扫描、连接并控制 Ubuntu 工控机提供的专用 GATT 服务。
- App 提供双轴虚拟手柄，将纵向和横向输入映射为线速度与角速度，并以 20 Hz 发送带序号的控制指令。
- 手柄释放、页面失去控制资格或用户主动停止时，App 立即发送零速度。
- Ubuntu 工控机新增 BLE GATT 外设服务，校验指令后复用现有差速换算、限速、CAN 控制、反馈和停机逻辑。
- 工控机设置独立的 300 ms 指令看门狗；BLE 断开、指令超时、数据非法或服务退出时进入零速安全状态。
- 建立显式控制会话：连接或重连后必须先收到手柄回中状态，才允许非零运动指令。
- App 显示连接状态、控制是否解锁、当前目标速度以及工控机返回的运行/故障状态。
- BLE 软件停车不替代硬件急停、驱动器保护和机械制动。

## Capabilities

### New Capabilities

- `android-joystick-control`: Android 端 BLE 发现、连接、虚拟手柄输入、控制会话和状态展示行为。
- `ble-motor-control-gateway`: Ubuntu 工控机端 BLE GATT 服务、命令协议、看门狗、安全状态和现有电机控制链路集成行为。

### Modified Capabilities

- `differential-drive-command`: 允许经过验证的实时 BLE 线速度与角速度指令复用现有差速换算、限速和 CAN 生命周期，而不改变命令行控制语义。

## Impact

- 新增 Android/Kotlin 工程及其 BLE、界面和自动化测试代码。
- Ubuntu 端新增基于 BlueZ D-Bus 的 BLE 广播/GATT 服务和运行入口，并增加相应系统依赖及部署配置。
- 重构 `motor_control.py` 中可复用的控制会话边界，使固定命令行目标和实时 BLE 目标共享同一套换算、校验、发送与停止逻辑。
- 新增版本化的紧凑二进制 BLE 应用协议、会话序号、状态通知以及跨端协议测试向量。
- 更新 Ubuntu 安装、蓝牙适配器能力检查、权限、systemd 运行、配对、实车安全验证和故障排查文档。
