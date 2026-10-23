# Spec Delta

## ADDED Requirements

### Requirement: Validated realtime body velocity source
系统 SHALL 允许已验证的实时控制源按现有单位和方向约定更新车体线速度与角速度。每个实时目标 MUST 独立经过有限值、差速换算和两侧电机最高转速校验；实时入口不得改变现有命令行参数、预览模式或固定目标行为。

#### Scenario: Valid BLE body velocity target
- **WHEN** BLE 网关提交有限且未导致任一电机超速的线速度和角速度
- **THEN** 系统使用与命令行相同的轮径、轮距、减速比和安装方向生成下一周期电机指令

#### Scenario: Invalid BLE body velocity target
- **WHEN** BLE 网关提交非有限值或导致任一电机超速的目标
- **THEN** 系统拒绝该目标且不发送截断、缩放或部分更新后的运动指令

#### Scenario: Existing command-line operation
- **WHEN** 用户按原方式运行固定目标命令或预览且未启用 BLE 网关
- **THEN** 参数默认值、输出、启动观察和控制生命周期保持不变

### Requirement: Realtime target safe-state transition
实时控制会话 SHALL 支持在不关闭 CAN 接口的情况下立即把当前目标替换为零速度，并在会话结束时执行既有零速和失能序列。进入安全状态后，旧的非零目标 MUST 被丢弃，只有新的已解锁会话可以恢复运动。

#### Scenario: Watchdog requests safe stop
- **WHEN** BLE 网关因超时、断链或非法指令请求安全停车
- **THEN** 下一 CAN 控制周期使用零速度，并丢弃此前的非零实时目标

#### Scenario: Remote session ends
- **WHEN** BLE 控制服务退出或活动控制会话结束
- **THEN** 系统尝试发送既有零速及失能序列后关闭 CAN 接口
