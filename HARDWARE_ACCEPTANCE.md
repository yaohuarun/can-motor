# 实机验收记录

## 首次真实 CAN 启动

必须先架空左右驱动轮，并确认硬件急停或直接断电手段有效。不要把真实模式安装为
开机自启；首次验收只允许在前台运行：

```bash
sudo bash ubuntu/reset_ble_adapter.sh
sudo .venv/bin/python3 ble_gateway_service.py \
  --real-can --confirm-wheels-off-ground \
  --channel PCAN_USBBUS1 --mode direct --max-rpm 3000 \
  --max-linear-speed 0.10 --max-angular-speed 0.30
```

程序会先连续发送至少 5 秒零速，并要求左右电机均提供新鲜且故障码为 0 的反馈。
启动阶段的 `0x0A` CAN 接收警告只会让程序继续保持零速等待，不会开放 BLE；其他
故障、反馈缺失或反馈中断会安全退出。看到 `REAL CAN ENABLED` 后才能连接 App。连接后先保持
手柄回中，确认 `READY`、`已解锁` 和确认序号递增，再进行短促低速测试。

方向错误时立即急停并退出，不要通过反向拖动手柄补偿。确认接线和安装方向后，使用
`--left-direction`、`--right-direction`（值只能为 `-1` 或 `1`）校准。

全部验收项通过前禁止创建 `/etc/can-motor/real-can-enabled`，也禁止启用
`can-motor-ble-real.service`。该标志文件表示设备已完成硬件验收，而不是普通配置项。

## 已完成的自动验证

- Python 单元/集成测试：58 项通过。
- Kotlin/JVM 单元测试：通过。
- Android API 37.0 仪器测试：1 项通过。
- Android lint：通过。
- Debug APK：构建成功。
- OpenSpec 严格校验：通过。

## 待现场执行（不得由模拟结果代替）

前置条件：驱动轮架空、硬件急停已验证、现场人员能立即断电、初始转速限制为低速。

- [ ] 低速前进、后退、左转和右转方向正确。
- [ ] App 显示的左右目标与实际电机指令一致。
- [ ] 松手和停止按钮使车轮停止。
- [ ] 强制结束 App 后在可接受时间内停止。
- [ ] 手机离开 BLE 范围或关闭蓝牙后停止。
- [ ] 终止网关进程后执行零速和失能。
- [ ] 注入 CAN 故障后执行零速和失能。
- [ ] 断链重连后必须重新回中，不恢复旧目标。

任何一项停车失败：立即使用硬件急停，记录日志和条件，禁止提高速度或部署开机自启服务。
