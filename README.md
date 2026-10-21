# PEAK PCAN 电动轮椅电机速度控制

依据 `D:\work\doc\电动轮椅CAN通讯协议通用解密版.pdf` 第2～7页编写，Python 3.10+。
默认使用 python-can 的 PCAN 后端和 PEAK-System Windows 驱动，500 kbit/s、标准数据帧、8字节数据。

## Windows / PEAK PCAN 安装

1. 解压并运行 `D:\BaiduNetdiskDownload\PCAN\驱动\win\PEAK-System_Driver-Setup.zip`
   内的 `PeakOemDrv.exe`，安装 PEAK-System 设备驱动。
2. 接入 PCAN-USB，确认设备管理器能识别设备；关闭 PCAN-View 等占用同一通道的软件。
3. 安装 Python 依赖并先做只接收诊断：

```powershell
python -m pip install -r requirements.txt
python can_diagnose.py --seconds 5
```

默认通道是 `PCAN_USBBUS1`。多通道或多个适配器可显式指定，例如
`--channel PCAN_USBBUS2`。确认接收、接线和安全措施后再添加 `--send`：

```powershell
# 预览，不连接设备
python motor_control.py --mode direct --max-rpm 300 --linear-speed 0.1 --angular-speed 0
# 实际发送；首次测试请使用很低速度和很短时间
python motor_control.py --mode direct --max-rpm 300 --linear-speed 0.02 --angular-speed 0 --duration 1 --send
```

`PeakOemDrv.exe` 是系统驱动安装程序，不复制进项目，也不通过 `--library` 加载。
python-can 的 `pcan` 接口会调用驱动安装的 PCAN-Basic 运行库。

## 旧 CANalyst-II 后端（保留兼容）

### Ubuntu运行（Python 3.10+）

将整个项目目录复制到Ubuntu（包含 `libs/linux`），进入项目目录执行：

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip libusb-1.0-0 usbutils
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

配置USB访问权限（规则只匹配CANalyst-II的VID/PID 04d8:0053）：

```bash
sudo install -m 644 99-canalystii.rules /etc/udev/rules.d/99-canalystii.rules
sudo usermod -aG plugdev "$USER"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb
```

注销并重新登录以生效组权限，重新插拔USB，再激活虚拟环境。
用 `lsusb -d 04d8:0053` 检查设备；如果VID/PID不同，先确认实际型号，
不要直接用其他设备的规则。无需Windows DLL、Zadig或配置 `can0`。

优先使用厂商Linux后端（与此前Windows成功路径相同的VCI API）：

```bash
# 接收诊断，不发送控制报文
python can_diagnose.py --backend controlcan --channel 0 --seconds 5
# 先预览，不连接设备
python motor_control.py --backend controlcan --mode direct --max-rpm 300 --linear-speed 0.1 --angular-speed 0
# 零速观察5秒，无故障后以目标速度运行60秒
python motor_control.py --backend controlcan --mode direct --max-rpm 300 --linear-speed 0.1 --angular-speed 0 --startup-timeout 5 --duration 60 --send
```

按实车方向校准，默认左轮方向-1、右轮+1，正线速度对应前进。
启动观察期间仍发送零速使能和配置；目标速度前不会提前运行，结束发送零速和失能。

`controlcan` 在Linux使用 `ctypes.CDLL` 加载厂商SO（cdecl），
在Windows使用 `ctypes.WinDLL` 加载DLL（stdcall）。厂商Linux头文件v2.02将
DWORD/ULONG定义为32位，代码使用固定32位类型，避免64位Linux的long宽度差异。
内置库按CPU与Python位数选择：

| 平台 | 路径 |
| --- | --- |
| PC 64位 | `libs/linux/x86_64/libcontrolcan.so` |
| PC 32位 | `libs/linux/x86/libcontrolcan.so` |
| ARM 64位 | `libs/linux/aarch64/libcontrolcan.so` |
| ARM 32位 | `libs/linux/arm/libcontrolcan.so` |

这些SO来自本地厂商Linux资料包V1.45。如架构/依赖不兼容，可用
`--library /absolute/path/libcontrolcan.so` 指定该设备的新版厂商库；`--dll`仍作为兼容别名。
遇到加载错误，PC64位可运行 `file libs/linux/x86_64/libcontrolcan.so` 和
`ldd libs/linux/x86_64/libcontrolcan.so` 检查架构和缺失依赖，其他平台替换对应路径。
运行权限错误时检查udev和组权限，不需要以root身份持续运行电机程序。

也保留跨平台的开源USB后端（[python-can官方说明](https://python-can.readthedocs.io/en/stable/interfaces/canalystii.html)）：

```bash
python can_diagnose.py --backend canalystii --channel 0 --seconds 5
```

此前此设备的开源后端出现过发送队列超时，Ubuntu下也需单独验证，
不能用接收成功代替发送成功。当前只在Windows环境完成自动测试和Linux库ELF架构检查，
尚未在Ubuntu与电机实物上验证。

## 参数和接线

### 差速速度参数（ROS 2 约定）

`--linear-speed` 为车体线速度，单位 **m/s**，正值前进；`--angular-speed` 为车体角速度，
单位 **rad/s**，正值表示从上往下看逆时针左转。两者均默认0。
这里采用 ROS 2 的速度语义，程序仍为命令行工具，不订阅 ROS 2 话题。

固定几何参数为轮径 **254 mm（D=0.254 m）**、两轮中心距 **420 mm（B=0.420 m）**，
减速比为 **15.75**。设线速度为v、角速度为ω：

```text
左轮线速度 = v − ω × B/2 = v − ω × 0.21
右轮线速度 = v + ω × B/2 = v + ω × 0.21
轮端rpm = 轮线速度 × 60 / (π × D)
电机轴rpm = 轮端rpm × 15.75 × 安装方向系数
raw = round(电机轴rpm / max_motor_rpm × 16384)
```

前进直行时两轮轮端rpm均为正，默认安装方向使左电机轴为负、右为正。
原地左转（v=0、ω>0）时左轮倒转、右轮前转，安装补偿后两个电机轴指令均为正。
例如 v=0.1 m/s、ω=0 对应每轮约7.51913 rpm、电机轴约118.426 rpm。
任一轮换算后超过 `--max-rpm` 或正常运动目标含NaN/无穷/换算溢出时，程序在连接设备前报错，
不截断或缩放速度。转弯需要分别核对两轮速度。
`--max-rpm` 仍为减速前电机轴最高转速，按配置帧0.1 rpm精度量化后用于编码；请按硬件实际参数设置。

#### 旧参数迁移

`--left-rpm`、`--right-rpm` 已移除，旧调用会报参数错误。旧左右轮端转速nL、nR（rpm）可换算为：
`v=πD(nL+nR)/120`，`ω=πD(nR−nL)/(60B)`，不包含安装方向系数。
例如左右轮端均10 rpm对应 `--linear-speed 0.132994889 --angular-speed 0`。
最高转速、安装方向和其他硬件配置参数保持原有含义。

以下为运动预览，不连接设备：

```powershell
# 直行0.1 m/s
python motor_control.py --max-rpm 300 --linear-speed 0.1 --angular-speed 0
# 以0.1 m/s前进并以0.2 rad/s左转
python motor_control.py --max-rpm 300 --linear-speed 0.1 --angular-speed 0.2
# 以0.2 rad/s原地左转；负角速度为右转
python motor_control.py --max-rpm 300 --linear-speed 0 --angular-speed 0.2
```

```powershell
python -m pip install -r requirements.txt
```

旧 `canalystii` 后端采用 USB 用户态驱动；Windows 需配置 libusb-win32，
参考 [python-can 官方文档](https://python-can.readthedocs.io/en/stable/interfaces/canalystii.html)。
默认 `--backend pcan` 为 PEAK-System 后端；`--backend canalystii` 为旧开源USB后端，
`--backend controlcan` 为旧厂商DLL/SO后端。
更换USB驱动可能影响厂商上位机，先确认设备型号和原驱动。

### `usb.core.NoBackendError: No backend available`

这是PyUSB未能加载底层libusb动态库，发生在发送CAN报文之前。
用运行脚本的同一个Python安装依赖：

```powershell
python -m pip install -r requirements.txt
# 或仅补装DLL包
python -m pip install --upgrade libusb-package
```

脚本会通过 `libusb_package.find_library` 显式定位DLL，并提前初始化PyUSB后端。
仅安装PyUSB本身不一定包含底层DLL。无需将DLL复制到Windows系统目录。
可以只检测后端而不打开CAN设备、不发送指令：

```powershell
python -c "from motor_control import prepare_usb_backend; print(prepare_usb_backend())"
```

后端成功加载与USB设备驱动是两个步骤。如果随后提示找不到设备、访问被拒绝或不支持操作，
再检查设备管理器中的CANalyst-II驱动；按上方官方文档配置libusb-win32。
不要给其他USB设备更换驱动。`CANalystIIBus was not properly shut down`
在此次异常中是构造失败后对象析构产生的次生警告，先解决后端加载问题。

将所选通道 CAN_H、CAN_L 接入控制总线，按设备要求连接参考地。
确认总线两端各有120Ω终端电阻，不要在已有终端的总线上重复添加。
PCAN 使用 `--channel PCAN_USBBUS1`（默认）或 `PCAN_USBBUS2` 等驱动通道名。
旧后端的 `--channel 0` 为第一路、`--channel 1` 为第二路，`--device 0` 为首个USB设备。
首次测试请架空驱动轮、移开乘员并准备硬件急停。脚本退出时会尝试停止，USB断开或总线故障时无法保证停止。

## 保留原上位控制器：external 模式

默认使用外部控制ID `0x108`。原上控必须支持并接收外部速度控制。
`--max-rpm` 必须是上控实际配置的电机最高转速；该模式不会修改配置。
以下300 rpm仅为示例，请替换为实际参数。

```powershell
# 预览0.02 m/s直行的报文，不连接设备
python motor_control.py --max-rpm 300 --linear-speed 0.02 --angular-speed 0
# 实际运行5秒，结束时发送零速，再关闭外部功能
python motor_control.py --max-rpm 300 --linear-speed 0.02 --angular-speed 0 --duration 5 --send
# 反转（方向由安装方式决定）
python motor_control.py --max-rpm 300 --linear-speed=-0.02 --angular-speed 0 --send
```

示例报文：`0x108: 05 0E FA F2 05 00 00 00`。
字节顺序为右轮速度、左轮速度（各2字节，大端有符号），速度功能使能05，X=0，Y=0，模拟摇杆关闭00。
退出时关闭外部功能可能恢复原摇杆控制，因此必须确保原摇杆处于中位。

## 替代原上位控制器：direct 模式

必须避免原上控同时发送 `0x103`。每周期依次发送控制帧和配置帧。
此模式会反复写入最高转速、电池参数、报警阈值和刹车电压，运行前逐项核对硬件参数。

```powershell
# 先预览；核对配置后添加 --send
python motor_control.py --mode direct --max-rpm 300 --linear-speed 0.02 --angular-speed 0 --torque 20 --battery lithium --overvoltage 33 --undervoltage 22 --brake-voltage 13
```

以上例子产生：

```text
0x103: 05 0E FA F2 14 64 00 0D
0x103: B8 0B 00 00 21 16 0D AA
```

控制字0x0D：低3位101使能，bit3为1表示未充电。
配置的最高转速以0.1 rpm为单位、小端编码；300 rpm对应3000，即 B8 0B。
支持 `--swap`、`--pi 0..2`、`--left-comp 0..10`、`--right-comp 0..10`。
运行结束、Ctrl+C或异常时，先连续发送5组零速帧，再发送5组失能帧，最后关闭USB。

## 协议解释与未确定项

### 实机确认：0x0A 为 CAN 接收故障

仅观察通信恢复，不进入目标速度运行，使用：

```powershell
python motor_control.py --backend controlcan --mode direct --max-rpm 100 --startup-only --startup-timeout 60 --send
```

该模式持续60秒发送零速使能＋配置帧并接收反馈，显示原始报文、故障码和每秒汇总。
0x0A清除或再次出现时均继续零速观察，不会进入目标速度运行；其他故障仍停止。
线速度与角速度参数会被强制忽略为0（包括可解析但超速或非有限的值）。Ctrl+C可提前结束，退出时发送零速和失能帧。
`--duration`不用于此模式，观察时长由`--startup-timeout`决定。
零速使能仍可能释放电机制动器，请固定轮椅、架空驱动轮。

用户已确认该固件反馈 `0x0A` 表示CAN接收故障，按此定义处理。
启动后先以零速使能持续发送（direct模式同时发送配置帧），默认固定观察5秒。
即使0x0A提前清除，也必须等待完整观察时间；期间持续打印原始反馈和故障状态。
观察结束时，只有左右轮最近1秒内均有无故障反馈，才发送目标速度并开始计算 `--duration`。
观察结束仍有0x0A时不退出，持续发送零速和配置、接收反馈，直到左右轮反馈均恢复正常再运行。
等待期间反馈缺失或超过1秒未更新仍停止。其他非零故障仍立即停止。
进入目标速度运行后再收到0x0A，只打印告警并继续周期发送及接收，不提前退出；
目标速度运行时间仍按 `--duration` 计算，0x0A不会重置计时。此策略不代表驱动器已经执行指令。
`--startup-timeout 3` 可将固定观察时间调整为3秒（允许0.1～300秒）。

```powershell
# 显式零速观察5秒，再以0.1 m/s直行1分钟
python motor_control.py --backend controlcan --mode direct --max-rpm 300 --linear-speed 0.1 --angular-speed 0 --startup-timeout 5 --duration 60 --send
```

零速使能期间可能释放电磁刹车，应固定车体防止溜车。正负速度与实际前进方向的对应取决于电机安装与接线。

当前默认安装方向系数为左轮-1、右轮+1：正线速度、零角速度将生成左负右正的电机指令，
补偿两轮镜像安装。输入单位为m/s和rad/s，反馈速度保持协议原始符号。
可用 `--left-direction 1 --right-direction -1` 恢复此前的方向设置。
默认方向已依据实车正线速度原先后退的结果反转；调整后请架空确认前进及左转方向。
external模式发送零速外部控制帧，配置仍由原上控负责。
反馈输出按每轮0.5秒限频，故障变化立即输出，避免约1000帧/秒的反馈刷屏拖慢发送。
日志显示反馈ID、8字节原始数据、十六进制故障码和0x0A清除状态；每秒汇总左右轮
最近故障码、反馈距今时间及剩余等待时间，未收到反馈也会明确显示。
这只是等待通信恢复，不发送未在协议中定义的“故障清除”指令。

- 速度换算：`raw = round(rpm / max_rpm * 16384)`，范围±16384，超范围报错。最高转速按0.1 rpm精度量化。
  这是依据第4页比例说明进行的换算，实际转速需反馈/测速验证；此公式中的rpm为差速换算后轮端rpm乘以15.75及安装方向系数的电机轴转速。
- 协议没有规定周期、帧间延时、应答握手或通信超时停车行为。默认20 ms是可调试初值，用 `--period-ms` 修改。
- 协议按发送节点列出0x103，未单独指定配置帧ID，也没有给出双帧识别状态机。
  direct 模式据此让两帧共用0x103、控制帧在前，配置帧以AA结尾；这是需要实机抓包核对的解释。
- 协议第1页20字节 NETWORK_CANFRAME 是上层封装，不作为CAN数据载荷发送；接口只发送ID和8字节有效数据。
- 接收0x101/0x102并打印左右轮反馈原始速度、电流、故障等；0x0A只告警，其他非零故障退出并尝试停止。
  启动期间0x0A按上文恢复流程处理。第6页“以15位数据为标幺值”描述不够明确，电流单位也未给出，因此没有把反馈强行换算成RPM或安培。
- 外部模式没有直接控制转矩或写入最高转速的权限，实际动作还取决于原上控策略。
  收不到反馈不会被解释为已运行；发送成功也不等于电机执行成功。
- 软件未在PCAN及电机实物上验证；默认不发送，需显式指定 `--send`。

## 检查

### 使用本地厂商DLL后端对照测试

项目已从本机厂商资料包复制32/64位DLL到 `libs/x86`、`libs/x64`，
按当前Python位数自动选择。来源为 `D:\work\doc\CAN分析仪资料20250326_顶配Pro\CAN分析仪资料20250326_顶配Pro\二次开发库文件`。
接口结构和调用约定依据同目录 `ControlCAN For VC/ControlCAN.h`。
这提供另一条发送路径，并不代表已经证实非官方后端有故障。

该后端需要与厂商软件相同的USB设备驱动。如果此前用Zadig替换成libusb驱动，
请先恢复资料包提供的厂商驱动；脚本不会替换驱动。关闭厂商测试软件后再运行脚本。

```powershell
# 先验证厂商路径能接收到原有101/102反馈
python can_diagnose.py --backend controlcan --channel 0 --seconds 5
# 核对硬件配置并架空驱动轮后，再进行短时控制测试
python motor_control.py --backend controlcan --mode direct --max-rpm 300 --linear-speed 0.02 --angular-speed 0 --duration 1 --send
```

可用 `--dll "完整路径\ControlCAN.dll"` 指定其他同型号SDK。
厂商 `VCI_Transmit` 返回1仅表示API报告发送1帧，不能当作电机执行成功。
`--tx-timeout` 仅适用于canalystii后端；厂商同步API没有该参数。
未连接实物验证厂商路径，不会自动启动电机做测试。

### 发送队列超时

`Send timed out` 在该驱动中表示硬件TX队列未在限定时间内清空，
不能仅凭此判断缺少ACK或电机协议不匹配。驱动也无法可靠报告ACK和总线错误。
先停止运行命令，保持轮椅静止并检查：

1. `--channel 0` 对应设备第一路，`--channel 1` 对应第二路，必须与物理接线一致。
2. 对端控制器已上电、CAN_H/L接对、参考地按设备要求连接，两端终端电阻正确。
   如需测量H/L间电阻，应断电测量；常规两只120Ω终端并联约为60Ω。
3. 协议波特率是500 kbit/s；关闭其他占用USB设备的软件。

以下仅接收，不发送应用层CAN控制报文（普通模式仍自动ACK，不是硬件静默模式）：

```powershell
python can_diagnose.py --seconds 5
# 如果实际使用第二个PCAN通道
python can_diagnose.py --channel PCAN_USBBUS2 --seconds 5
```

收到101/102说明能接收驱动反馈，103说明看到上控报文，10A为上控摇杆数据。
有接收也不保证本机发送正常；零接收也可能是对端没有主动报文。
确认物理总线正常后，可在低速测试时用 `--tx-timeout 0.5` 判断是否仅等待时间不足；
不要用取消超时来掩盖失败。若仍超时，应与厂商软件抓包对照，并检查该非官方USB后端
与设备固件是否兼容。厂商软件测试与本脚本需分别运行，且各自需要兼容的USB设备驱动。

```powershell
python -m unittest -v
python motor_control.py --help
```

测试覆盖差速直行/倒车/转弯/原地旋转、安装方向、最高转速边界、无效输入、零速诊断、
正负速度字节序、配置位域、停止帧及反馈解码，不需要连接硬件或安装python-can。
