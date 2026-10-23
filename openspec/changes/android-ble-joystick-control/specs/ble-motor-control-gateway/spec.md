# Spec Delta

## Purpose

让 Ubuntu 工控机作为受控的 BLE GATT 外设接收 Android 实时运动指令，并以独立看门狗和确定性的安全状态把无线控制接入现有电机 CAN 控制链路。

## ADDED Requirements

### Requirement: Advertise an authenticated control service
网关 SHALL 通过 BLE 广播版本化的专用 GATT 控制服务，并提供命令写入、状态通知和只读能力信息。运动命令 MUST 仅接受来自已配对且已授权设备的加密连接；同一时刻最多一个客户端拥有控制权。

#### Scenario: Authorized client connects
- **WHEN** 已配对且授权的 Android 设备连接并完成服务发现
- **THEN** 网关允许建立新控制会话并提供能力信息

#### Scenario: Unauthorized client writes
- **WHEN** 未配对、未授权或未加密的客户端尝试写入运动命令
- **THEN** 网关拒绝写入且保持零速安全状态

#### Scenario: Second client requests control
- **WHEN** 已有活动控制会话且另一客户端请求控制
- **THEN** 网关拒绝第二客户端取得控制权且不改变当前目标

### Requirement: Validate versioned motion commands
网关 SHALL 只接受长度、版本、会话标识、序号、标志和数值均有效的命令。线速度与角速度 MUST 为有限值并处于公布范围，序号 MUST 在当前会话中递增；格式错误、越界、重复、乱序或旧会话命令不得驱动电机。

#### Scenario: Valid command
- **WHEN** 当前授权会话提交版本兼容、序号递增且速度有效的命令
- **THEN** 网关接受该命令、更新时间戳并发布对应确认状态

#### Scenario: Invalid or stale command
- **WHEN** 命令格式错误、数值非有限或越界、序号未递增或会话标识已过期
- **THEN** 网关拒绝该命令、进入零速安全状态并报告非法指令原因

### Requirement: Require center-to-arm for every session
网关 MUST 在每次连接建立的新会话中以未解锁状态开始，只有收到该会话的有效回中零速度指令后才能接受非零目标。断开、超时或安全故障 MUST 撤销解锁状态。

#### Scenario: Nonzero command before arming
- **WHEN** 新会话尚未回中解锁便收到非零指令
- **THEN** 网关拒绝运动、保持零速并报告等待回中

#### Scenario: Valid centered command arms control
- **WHEN** 新会话收到标记为手柄回中且线速度和角速度均为零的有效指令
- **THEN** 网关解锁该会话并通知 App 可以控制

### Requirement: Enforce a 300 ms command watchdog
网关 MUST 使用单调时钟从最近一次有效命令计时；活动会话超过 300 ms 未收到下一条有效指令时，必须立即进入零速安全状态并撤销控制解锁。无效命令不得刷新看门狗。

#### Scenario: Command stream remains healthy
- **WHEN** 已解锁会话持续以 20 Hz 提交有效指令
- **THEN** 看门狗持续刷新且网关执行最新目标

#### Scenario: Command stream stalls
- **WHEN** 最近有效指令距今超过 300 ms
- **THEN** 网关发送零速度、撤销解锁并报告指令超时

### Requirement: Stop on disconnect and process termination
网关 MUST 在 BLE 客户端断开、BlueZ 服务丢失、程序正常退出、中断或未处理异常时尽力立即发送零速度和失能序列，并清除活动会话。重新广播或重连不得自动恢复旧的非零目标。

#### Scenario: BLE link disconnects
- **WHEN** 活动控制客户端断开
- **THEN** 网关立即执行零速安全停机并清除会话

#### Scenario: Gateway shuts down
- **WHEN** 网关收到终止信号或运行异常
- **THEN** 网关在释放 CAN 和 BLE 资源前尝试完成既有零速及失能序列

### Requirement: Apply only the newest valid target
网关 SHALL 以固定 CAN 控制周期重复发送最近一条有效目标，不补发积压的 BLE 指令。新目标 MUST 复用现有差速换算、安装方向、转速限制、启动观察、故障处理和 CAN 退出行为。

#### Scenario: Several commands arrive before one CAN cycle
- **WHEN** 一个 CAN 周期内收到多条有效且递增的 BLE 指令
- **THEN** 下一周期仅应用序号最大的最新目标

#### Scenario: Remote target exceeds a wheel limit
- **WHEN** 线速度和角速度组合导致任一电机超过配置的最高转速
- **THEN** 网关拒绝目标并进入零速安全状态，不截断或缩放指令

### Requirement: Publish control and motor status
网关 SHALL 向活动客户端通知协议版本、会话标识、控制状态、最近接受序号、当前目标、最近停车原因和左右电机故障摘要。状态通知失败不得阻塞 CAN 发送或延迟安全停车。

#### Scenario: State changes
- **WHEN** 会话解锁、目标更新、看门狗触发、BLE 断开前或电机故障发生
- **THEN** 网关尽力发布最新状态，同时以电机控制安全路径为最高优先级
