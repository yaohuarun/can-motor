"""Versioned BLE wire protocol shared by the Ubuntu motor gateway and Android app."""

from dataclasses import dataclass
from enum import IntEnum
import math
import struct


SERVICE_UUID = '7e57d004-2b7b-4ec4-95a1-6f6b4f9b1000'
COMMAND_UUID = '7e57d004-2b7b-4ec4-95a1-6f6b4f9b1001'
STATUS_UUID = '7e57d004-2b7b-4ec4-95a1-6f6b4f9b1002'
CAPABILITIES_UUID = '7e57d004-2b7b-4ec4-95a1-6f6b4f9b1003'

PROTOCOL_VERSION = 1
COMMAND_CENTERED = 0x01
COMMAND_STRUCT = struct.Struct('<BBHIIff')
STATUS_STRUCT = struct.Struct('<BBBBIIhhBBH')
CAPABILITIES_STRUCT = struct.Struct('<BBHffHHI')
UINT32_MASK = 0xFFFFFFFF


class ProtocolError(ValueError):
    """Raised when a BLE payload is not valid for this protocol version."""


class ControlState(IntEnum):
    IDLE = 0
    WAIT_CENTER = 1
    ARMED = 2
    SAFE_STOP = 3


class StopReason(IntEnum):
    NONE = 0
    USER = 1
    WATCHDOG = 2
    DISCONNECT = 3
    INVALID_COMMAND = 4
    SPEED_LIMIT = 5
    CAN_FAULT = 6
    SHUTDOWN = 7
    BLUEZ_LOST = 8


@dataclass(frozen=True)
class MotionCommand:
    session_id: int
    sequence: int
    linear_speed: float
    angular_speed: float
    centered: bool = False


@dataclass(frozen=True)
class GatewayStatus:
    state: ControlState
    reason: StopReason
    session_id: int
    accepted_sequence: int
    target_linear_milli: int
    target_angular_milli: int
    left_fault: int
    right_fault: int
    watchdog_remaining_ms: int


@dataclass(frozen=True)
class Capabilities:
    max_linear_speed: float
    max_angular_speed: float
    command_period_ms: int = 50
    watchdog_timeout_ms: int = 300
    max_motor_rpm_tenths: int = 0


def _uint32(value, name):
    if not isinstance(value, int) or not 0 <= value <= UINT32_MASK:
        raise ProtocolError(f'{name}必须是uint32')
    return value


def sequence_is_newer(candidate: int, previous: int) -> bool:
    """Compare uint32 counters, accepting forward movement across wrap-around."""
    candidate = _uint32(candidate, '序号')
    previous = _uint32(previous, '上一序号')
    difference = (candidate - previous) & UINT32_MASK
    return 0 < difference < 0x80000000


def encode_command(command: MotionCommand) -> bytes:
    session_id = _uint32(command.session_id, '会话标识')
    sequence = _uint32(command.sequence, '序号')
    if session_id == 0:
        raise ProtocolError('会话标识不能为0')
    if not math.isfinite(command.linear_speed) or not math.isfinite(command.angular_speed):
        raise ProtocolError('速度必须为有限值')
    flags = COMMAND_CENTERED if command.centered else 0
    return COMMAND_STRUCT.pack(PROTOCOL_VERSION, flags, 0, session_id, sequence,
                               command.linear_speed, command.angular_speed)


def decode_command(payload, *, expected_session=None, previous_sequence=None,
                   max_linear_speed=None, max_angular_speed=None) -> MotionCommand:
    if len(payload) != COMMAND_STRUCT.size:
        raise ProtocolError(f'命令长度必须为{COMMAND_STRUCT.size}字节')
    version, flags, reserved, session_id, sequence, linear, angular = COMMAND_STRUCT.unpack(payload)
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f'不支持的协议版本{version}')
    if flags & ~COMMAND_CENTERED:
        raise ProtocolError('命令包含未知标志位')
    if reserved != 0:
        raise ProtocolError('命令保留位必须为0')
    if session_id == 0:
        raise ProtocolError('会话标识不能为0')
    if expected_session is not None and session_id != expected_session:
        raise ProtocolError('命令不属于当前会话')
    if previous_sequence is not None and not sequence_is_newer(sequence, previous_sequence):
        raise ProtocolError('命令序号重复或乱序')
    if not math.isfinite(linear) or not math.isfinite(angular):
        raise ProtocolError('速度必须为有限值')
    if max_linear_speed is not None and abs(linear) > max_linear_speed:
        raise ProtocolError('线速度超出公布范围')
    if max_angular_speed is not None and abs(angular) > max_angular_speed:
        raise ProtocolError('角速度超出公布范围')
    return MotionCommand(session_id, sequence, linear, angular,
                         bool(flags & COMMAND_CENTERED))


def encode_status(status: GatewayStatus) -> bytes:
    return STATUS_STRUCT.pack(
        PROTOCOL_VERSION, int(status.state), int(status.reason), 0,
        _uint32(status.session_id, '会话标识'),
        _uint32(status.accepted_sequence, '接受序号'),
        status.target_linear_milli, status.target_angular_milli,
        status.left_fault, status.right_fault, status.watchdog_remaining_ms)


def decode_status(payload) -> GatewayStatus:
    if len(payload) != STATUS_STRUCT.size:
        raise ProtocolError(f'状态长度必须为{STATUS_STRUCT.size}字节')
    version, state, reason, reserved, session_id, sequence, linear, angular, left, right, watchdog = STATUS_STRUCT.unpack(payload)
    if version != PROTOCOL_VERSION or reserved != 0:
        raise ProtocolError('状态版本或保留位无效')
    try:
        control_state = ControlState(state)
        stop_reason = StopReason(reason)
    except ValueError as exc:
        raise ProtocolError('状态枚举值无效') from exc
    return GatewayStatus(control_state, stop_reason, session_id, sequence,
                         linear, angular, left, right, watchdog)


def encode_capabilities(capabilities: Capabilities) -> bytes:
    if (not math.isfinite(capabilities.max_linear_speed) or
            not math.isfinite(capabilities.max_angular_speed) or
            capabilities.max_linear_speed <= 0 or capabilities.max_angular_speed <= 0):
        raise ProtocolError('能力速度上限必须为正有限值')
    return CAPABILITIES_STRUCT.pack(
        PROTOCOL_VERSION, 0, 0,
        capabilities.max_linear_speed, capabilities.max_angular_speed,
        capabilities.command_period_ms, capabilities.watchdog_timeout_ms,
        capabilities.max_motor_rpm_tenths)


def decode_capabilities(payload) -> Capabilities:
    if len(payload) != CAPABILITIES_STRUCT.size:
        raise ProtocolError(f'能力长度必须为{CAPABILITIES_STRUCT.size}字节')
    version, flags, reserved, linear, angular, period, timeout, rpm = CAPABILITIES_STRUCT.unpack(payload)
    if version != PROTOCOL_VERSION or flags != 0 or reserved != 0:
        raise ProtocolError('能力版本、标志或保留位无效')
    result = Capabilities(linear, angular, period, timeout, rpm)
    if (not math.isfinite(linear) or not math.isfinite(angular) or
            linear <= 0 or angular <= 0 or period <= 0 or timeout <= 0):
        raise ProtocolError('能力参数无效')
    return result


# Cross-language V1 golden vectors. Kotlin tests must assert these exact bytes.
COMMAND_GOLDEN_HEX = '01 01 00 00 78 56 34 12 04 03 02 01 00 00 00 3F 00 00 80 BE'
STATUS_GOLDEN_HEX = '01 02 00 00 78 56 34 12 04 03 02 01 7B 00 38 FE 0A 00 FA 00'
CAPABILITIES_GOLDEN_HEX = '01 00 00 00 00 00 20 40 00 00 80 3F 32 00 2C 01 30 75 00 00'
