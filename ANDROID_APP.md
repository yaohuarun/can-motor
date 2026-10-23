# CAN Motor Android App

## 安装与连接

1. 安装 `app/build/outputs/apk/debug/app-debug.apk`。
2. Android 12+ 授予“附近设备”扫描和连接权限；Android 11 及以下授予蓝牙和位置权限。
3. 先在系统蓝牙设置中与 Ubuntu 工控机配对，再扫描并连接 `CanMotor`。

## 操作与状态

每次新连接都先显示“等待手柄回中”。松开手柄，待工控机确认当前会话后才能操作。上下拖动控制前后，左右拖动控制转向；松手或点击“立即停止”会立即归零。

界面显示连接阶段、会话 ID、确认序号、速度目标、停车原因和左右故障码。`WATCHDOG` 表示 300 ms 内未收到有效指令；`DISCONNECT`、`CAN_FAULT` 和 `INVALID_COMMAND` 都会撤销解锁。

## 安全警告

BLE 和 App 不能替代硬件急停、驱动器保护或机械制动。首次试验必须架空车轮、使用低速，并保证硬件急停随时可用。
