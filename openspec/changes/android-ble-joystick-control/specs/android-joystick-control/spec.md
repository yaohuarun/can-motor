# Spec Delta

## Purpose

为操作者提供 Android BLE 虚拟手柄，以明确的连接与解锁状态实时发送小车线速度和角速度，并在松手、失联或应用失去控制资格时优先请求停车。

## ADDED Requirements

### Requirement: Discover and connect to the control gateway
App SHALL 扫描并仅展示广播指定控制服务的 BLE 设备，允许用户显式连接和断开。App MUST 显示扫描、连接、服务发现、已连接、控制未解锁、可控制及断开状态，并按 Android 版本请求所需的附近设备权限。

#### Scenario: Connect to a compatible gateway
- **WHEN** 用户选择广播指定服务的 Ubuntu 工控机且授权所需权限
- **THEN** App 建立 GATT 连接、发现控制与状态特征，并显示已连接但尚未解锁

#### Scenario: Incompatible or unauthorized device
- **WHEN** 设备缺少指定服务、协议版本不兼容或未通过配对授权
- **THEN** App 不进入可控制状态，并显示可诊断的失败原因

### Requirement: Map joystick input to body velocity
App SHALL 将虚拟手柄纵轴映射为车体线速度、横轴映射为车体角速度，沿用前进为正和俯视逆时针为正的约定。映射 MUST 包含中心死区，输出不得超过工控机公布的线速度与角速度上限。

#### Scenario: Joystick centered
- **WHEN** 手柄位置位于中心死区
- **THEN** App 产生线速度 0 m/s 和角速度 0 rad/s

#### Scenario: Combined motion
- **WHEN** 用户向前并向左拖动手柄且输入位于有效范围
- **THEN** App 产生正线速度和正角速度，且两者均不超过公布上限

### Requirement: Send live control commands
App SHALL 在用户持续触摸手柄且控制已解锁时以 20 Hz 发送最新速度指令。每条指令 MUST 携带协议版本、会话标识、递增序号、线速度、角速度和手柄是否回中的状态；同一时刻 MUST 只有一个发送循环。

#### Scenario: Hold joystick away from center
- **WHEN** 控制已解锁且用户持续保持非中心手柄位置
- **THEN** App 每 50 ms 发送一次最新目标，序号单调递增

#### Scenario: UI input changes faster than BLE writes
- **WHEN** 多次触摸事件发生在一次发送周期内
- **THEN** 下一条指令采用最新手柄位置，不排队补发过期目标

### Requirement: Stop on release and loss of control eligibility
App MUST 在手柄释放、触摸取消、用户点击停止、控制页面失去前台资格或开始断开时立即将本地目标置零并尽力连续发送零速度。App MUST 在 BLE 已断开时立即禁用非零输入，不得把客户端停车动作当作工控机看门狗的替代品。

#### Scenario: Joystick released
- **WHEN** 用户从非中心位置松开手柄
- **THEN** 手柄回中，App 立即发送零速度并在后续发送周期保持零速度

#### Scenario: App leaves active control screen
- **WHEN** App 进入后台、控制页面停止或 Activity 被销毁
- **THEN** App 停止接受非零输入并尽力发送零速度后结束控制循环

#### Scenario: BLE disconnects unexpectedly
- **WHEN** GATT 连接意外断开
- **THEN** App 立即显示断开、清除控制资格并阻止非零指令，等待工控机独立停车

### Requirement: Require center-to-arm after connection
App SHALL 在每次新连接或重连后保持控制未解锁，直到工控机确认收到当前会话的回中指令。非中心手柄不得直接解锁，旧会话的确认不得解锁新会话。

#### Scenario: Reconnect while joystick is displaced
- **WHEN** BLE 重连时手柄不在中心死区
- **THEN** App 保持控制未解锁、发送零目标或不发送运动目标，并提示用户松手回中

#### Scenario: Center acknowledged for current session
- **WHEN** 手柄处于中心且工控机确认当前会话已解锁
- **THEN** App 进入可控制状态并允许后续非零指令

### Requirement: Present gateway status
App SHALL 订阅工控机状态通知并显示控制状态、最近接受的指令序号、目标线速度与角速度、看门狗/断链停车原因以及左右电机故障摘要。过期会话或乱序状态不得覆盖当前会话状态。

#### Scenario: Gateway accepts a command
- **WHEN** 工控机确认当前会话的一条指令
- **THEN** App 更新最近接受序号和当前目标显示

#### Scenario: Gateway enters safe stop
- **WHEN** 状态通知报告超时、断链、非法指令或 CAN 故障停车
- **THEN** App 清除可控制状态、使手柄回中并突出显示停车原因
