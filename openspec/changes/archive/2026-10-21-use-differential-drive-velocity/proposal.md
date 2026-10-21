# Proposal

## Why

现有程序要求分别设置左右轮端 rpm，使用者需自行计算车体运动。改为与 ROS 2 差速小车一致的线速度和角速度输入，使直行、转弯和原地旋转可直接表达。

## What Changes

- **BREAKING**：将命令行 `--left-rpm`、`--right-rpm` 替换为 `--linear-speed`（m/s）和 `--angular-speed`（rad/s），均默认 0；旧参数报参数错误。
- 正线速度表示车体前进，正角速度表示俯视逆时针左转。
- 使用轮径 0.254 m、左右轮中心距 0.420 m、减速比 15.75，计算左右轮速并复用现有 CAN 编码和安装方向补偿。
- 预览显示车体目标、左右轮端 rpm 和带安装方向的电机轴 rpm；任一轮超速报错，不截断。
- 更新使用文档和无硬件测试，保留零速启动、诊断、停止与两种 CAN 控制模式。

## Capabilities

### New Capabilities

- `differential-drive-command`: 车体速度输入、双轮差速换算、有效性校验及预览。

### Modified Capabilities

无。

## Impact

涉及 `motor_control.py` 的参数解析、目标计算及预览，`test_protocol.py`、`test_startup_only.py` 和 `README.md`。不新增依赖，不改变 CAN 帧格式、后端或反馈解码。本次仅采用 ROS 2 的速度语义，不新增 ROS 2 节点、话题订阅或里程计；现有命令调用方需要迁移参数。
