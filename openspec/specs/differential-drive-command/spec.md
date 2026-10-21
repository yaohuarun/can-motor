# differential-drive-command Specification

## Purpose

让双轮差速车辆通过车体线速度与角速度表达目标运动，采用与 ROS 2 一致的单位和方向约定，并将固定车体几何参数转换成左右电机指令，提供可核对的预览及明确的输入错误行为。

## Requirements

### Requirement: Body velocity inputs
系统 SHALL 接受 `--linear-speed`（m/s，前进为正）与 `--angular-speed`（rad/s，俯视逆时针左转为正），两者默认 0；系统 MUST 拒绝已移除的 `--left-rpm`、`--right-rpm` 参数。

#### Scenario: Default stationary command
- **WHEN** 仅提供有效的 `--max-rpm`，不提供速度参数
- **THEN** 左右目标速度均为 0

#### Scenario: Legacy arguments rejected
- **WHEN** 提供任一旧 rpm 参数
- **THEN** 程序返回参数错误且不连接硬件

### Requirement: Differential wheel conversion
系统 SHALL 使用轮径 D=0.254 m、轮距 B=0.420 m，将 v、ω 转换为左轮线速度 v−ωB/2、右轮线速度 v+ωB/2，再分别乘 60/(πD) 得到轮端 rpm。正轮端速度 MUST 表示该轮向车体前进方向滚动。

#### Scenario: Straight forward and reverse
- **WHEN** ω=0，v=0.2 或 v=−0.2
- **THEN** 两轮轮端 rpm 相等，分别为 0.2×60/(π×0.254) 或其相反数

#### Scenario: Spin in either direction
- **WHEN** v=0，ω=1 或 ω=−1
- **THEN** ω=1 时左轮线速度为 −0.21 m/s、右轮为 +0.21 m/s，ω=−1 时左右符号反转

#### Scenario: Combined forward left turn
- **WHEN** v=0.2，ω=0.5
- **THEN** 左轮线速度为 0.095 m/s、右轮为 0.305 m/s，并据轮径转换为 rpm

### Requirement: Motor command conversion and validation
系统 SHALL 将轮端 rpm 乘减速比 15.75，再应用左右安装方向系数，使用现有量化到 0.1 rpm 的电机轴最高转速归一化编码。正常运动模式 MUST 在连接硬件前拒绝非有限速度、非有限中间结果及任一轮超过电机轴最高转速的请求，不截断或缩放目标速度；`--startup-only` MUST 在换算前将目标置零，忽略可解析的速度值。

#### Scenario: Mirrored motors
- **WHEN** 正线速度、零角速度且目标未超速，采用实车校准后的默认左 −1、右 +1 安装方向
- **THEN** 编码前左电机轴 rpm 为负、右为正；减速比只应用一次

#### Scenario: Direction override
- **WHEN** 设置左轮安装方向为 +1、右轮保持 +1，并请求有效的正向直行
- **THEN** 左右电机轴指令均为正

#### Scenario: One wheel exceeds limit
- **WHEN** 转弯请求导致任意一轮电机轴转速绝对值超过量化后的 `--max-rpm`
- **THEN** 程序返回明确的速度错误，不连接设备、不发送报文

#### Scenario: Invalid numerical input
- **WHEN** 任一速度为 NaN、正负无穷，或有限输入在换算中溢出
- **THEN** 程序返回参数错误，不连接设备、不发送报文

### Requirement: Preview and control lifecycle
系统 SHALL 在正常预览中显示带单位的车体目标、左右轮端 rpm 和带安装方向的电机轴 rpm。external 和 direct 模式 MUST 使用同一差速结果并保持现有帧布局。默认不连接硬件；`--startup-only` MUST 忽略目标运动并始终发送零速，保持现有启动观察、故障处理及退出零速与失能行为。

#### Scenario: Dry run
- **WHEN** 提供有效车体速度但未指定 `--send`
- **THEN** 打印目标、换算结果及对应模式的 CAN 预览，不打开 CAN 接口

#### Scenario: Startup diagnostic ignores target
- **WHEN** 指定 `--startup-only` 与可解析的非零或超速目标，随后故障清除
- **THEN** 忽略目标，预览及所有发送的控制速度均为零，不进入目标运动

#### Scenario: Motion and shutdown
- **WHEN** 启动观察完成且左右反馈满足现有放行条件，之后运行结束或中断
- **THEN** 放行前维持零速，放行后发送差速目标，退出时尝试发送零速及失能帧

#### Scenario: Default startup observation
- **WHEN** 未提供 `--startup-timeout` 且双轮反馈提前恢复正常
- **THEN** 程序仍完成默认5秒零速观察后才放行目标速度；显式指定该参数时采用指定时长
