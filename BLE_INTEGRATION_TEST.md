# Android—Ubuntu BLE 无 CAN 联调

1. Ubuntu 执行 `python3 ubuntu/preflight.py --mock-can`，确认 GATT Manager 和 Advertising Manager 存在。
2. 执行 `python3 ble_gateway_service.py --mock-can`；日志必须包含 `simulated CAN`。
3. Android 安装 debug APK，配对后扫描 `CanMotor`。预期发现命令、状态和能力特征。
4. 保持手柄回中，确认当前会话从 `WAIT_CENTER` 转为 `ARMED`。
5. 保持非零位置 2 秒；序号应以 20 Hz 递增，状态确认与当前会话一致。
6. 松手后下一帧必须是零速，后续心跳继续保持零速。
7. 暂停 App 发送超过 300 ms，预期 `SAFE_STOP/WATCHDOG`。
8. 关闭手机蓝牙，预期断链停车；重连后必须再次回中，旧会话通知不得解锁。

自动化判定：`python -m unittest test_cross_end_integration -v`。此流程不打开 CAN，不能作为实机验收的替代。
