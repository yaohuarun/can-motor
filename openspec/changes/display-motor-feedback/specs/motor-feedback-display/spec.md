# Spec Delta

## Purpose

让操作人员无需额外抓取和手工解析 CAN 报文，即可从控制台直接核对左右电机反馈中的关键运行状态，并按协议显示有意义的转速和电量等级。

## ADDED Requirements

### Requirement: Decode supported motor feedback
系统 SHALL 仅将标准数据帧 `0x101` 和 `0x102` 的 8 字节载荷识别为电机反馈，并分别标识为左电机和右电机。系统 MUST 按协议字段解码有符号速度、无符号 Q 轴电流、故障代码、电池电量和运行圈数；其他 ID 或非 8 字节载荷不得作为电机状态展示。

#### Scenario: Decode left motor feedback
- **WHEN** 控制台收到 ID 为 `0x101` 的有效 8 字节标准数据帧
- **THEN** 系统将其标识为左电机，并解码速度、Q 轴电流、故障代码、电池电量和运行圈数

#### Scenario: Decode right motor feedback
- **WHEN** 控制台收到 ID 为 `0x102` 的有效 8 字节标准数据帧
- **THEN** 系统将其标识为右电机，并解码速度、Q 轴电流、故障代码、电池电量和运行圈数

#### Scenario: Ignore unsupported feedback
- **WHEN** 收到其他 CAN ID、非 8 字节载荷、扩展帧、远程帧或错误帧
- **THEN** 系统不将该帧作为电机状态展示

### Requirement: Display complete motor feedback
系统 SHALL 在输出有效电机反馈时，在同一条控制台记录中显示电机侧别、原始 CAN 数据、目标转速、rpm 反馈速度、Q 轴电流、故障代码、电池电量等级和运行圈数。目标转速 MUST 位于反馈速度左侧，并反映对应电机当前实际下发阶段的目标；速度 MUST 按“反馈标幺值 / 16384 × 电机最高转速”换算；电池值 MUST 按协议表映射充放电状态及等级，表外值须保留原始值并标记未知；故障代码 MUST 使用两位十六进制格式；Q 轴电流 MUST 标记为原始值。

#### Scenario: Display a normal feedback frame
- **WHEN** 有效电机反馈满足现有输出条件且故障代码为零
- **THEN** 控制台记录同时包含该电机的五项解码字段，并将故障状态显示为无故障

#### Scenario: Convert feedback speed to rpm
- **WHEN** 电机最高转速为 300 rpm 且反馈速度标幺值为 16384、8192 或 -16384
- **THEN** 控制台分别显示 300.0 rpm、150.0 rpm 或 -300.0 rpm

#### Scenario: Display the current motor target
- **WHEN** 系统输出任一电机的有效反馈
- **THEN** 控制台在反馈速度左侧显示该电机当前下发的目标转速；启动观察或零速诊断期间显示 0.0 rpm，进入运行后显示该侧电机的运行目标

#### Scenario: Map battery level
- **WHEN** 电池原始值存在于协议电量表
- **THEN** 控制台显示对应的充电或放电状态及百分比等级，其中充电值 122 显示为 10%及以下

#### Scenario: Preserve unknown battery value
- **WHEN** 电池原始值不在协议电量表中
- **THEN** 控制台将电量标记为未知等级并显示该原始值

#### Scenario: Display a faulty feedback frame
- **WHEN** 有效电机反馈满足现有输出条件且故障代码非零
- **THEN** 控制台记录同时包含该电机的五项解码字段、十六进制故障代码及现有故障状态说明

### Requirement: Preserve feedback logging and control behavior
新增字段展示 MUST 保持现有的每轮反馈限频、故障变化即时输出、原始数据可见性、启动通信恢复、运行中告警以及非可恢复故障停止行为，不得改变 CAN 控制帧或收发周期。

#### Scenario: Repeated unchanged feedback
- **WHEN** 同一电机在限频窗口内连续上报故障状态未变化的有效反馈
- **THEN** 系统继续按现有限频规则输出，而不因新增展示字段提高日志频率

#### Scenario: Fault state changes
- **WHEN** 电机反馈的故障代码发生变化
- **THEN** 系统按现有规则立即输出包含全部五项字段的新状态，并继续执行既有故障处理策略
