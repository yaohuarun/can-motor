"""Safety state machine for BLE motor-control sessions."""
from dataclasses import dataclass
import time

from ble_protocol import (ControlState, MotionCommand, ProtocolError, StopReason,
                          decode_command)


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    command: MotionCommand | None
    state: ControlState
    reason: StopReason


class BleControlStateMachine:
    def __init__(self, clock=time.monotonic, watchdog_seconds=0.300):
        self.clock = clock
        self.watchdog_seconds = watchdog_seconds
        self.state = ControlState.IDLE
        self.reason = StopReason.NONE
        self.session_id = 0
        self.last_sequence = None
        self.last_valid_at = None
        self.target = (0.0, 0.0)

    def connect(self, session_id):
        if not isinstance(session_id, int) or not 0 < session_id <= 0xffffffff:
            raise ValueError('session_id must be a nonzero uint32')
        self.session_id = session_id
        self.last_sequence = None
        self.last_valid_at = None
        self.target = (0.0, 0.0)
        self.state = ControlState.WAIT_CENTER
        self.reason = StopReason.NONE

    def accept(self, payload, max_linear_speed, max_angular_speed):
        try:
            command = decode_command(
                payload, expected_session=self.session_id,
                previous_sequence=self.last_sequence,
                max_linear_speed=max_linear_speed,
                max_angular_speed=max_angular_speed)
        except ProtocolError:
            self.safe_stop(StopReason.INVALID_COMMAND)
            return CommandResult(False, None, self.state, self.reason)
        if self.state == ControlState.WAIT_CENTER and not (
                command.centered and command.linear_speed == 0 and
                command.angular_speed == 0):
            self.target = (0.0, 0.0)
            return CommandResult(False, command, self.state, self.reason)
        self.last_sequence = command.sequence
        self.last_valid_at = self.clock()
        if self.state == ControlState.WAIT_CENTER:
            self.state = ControlState.ARMED
        if self.state != ControlState.ARMED:
            return CommandResult(False, command, self.state, self.reason)
        self.target = (command.linear_speed, command.angular_speed)
        self.reason = StopReason.NONE
        return CommandResult(True, command, self.state, self.reason)

    def poll(self):
        if (self.state == ControlState.ARMED and self.last_valid_at is not None and
                self.clock() - self.last_valid_at > self.watchdog_seconds):
            self.safe_stop(StopReason.WATCHDOG)
        return self.state

    def disconnect(self):
        self.safe_stop(StopReason.DISCONNECT)
        self.session_id = 0

    def safe_stop(self, reason):
        self.target = (0.0, 0.0)
        self.state = ControlState.SAFE_STOP
        self.reason = reason
        self.last_valid_at = None


class BleMotorGateway:
    """Connect validated BLE commands to the newest-target motor session."""
    def __init__(self, motor, state_machine, max_linear_speed, max_angular_speed,
                 max_motor_rpm, zero_frames, off_frames, mode='external',
                 left_direction=-1, right_direction=1, config=None, torque=20,
                 depth=100, period=0.02):
        self.motor, self.machine = motor, state_machine
        self.max_linear_speed, self.max_angular_speed = max_linear_speed, max_angular_speed
        self.max_motor_rpm = max_motor_rpm
        self.zero_frames, self.off_frames = zero_frames, off_frames
        self.mode, self.left_direction, self.right_direction = mode, left_direction, right_direction
        self.config, self.torque, self.depth, self.period = config, torque, depth, period

    def command(self, payload):
        result = self.machine.accept(payload, self.max_linear_speed, self.max_angular_speed)
        if not result.accepted:
            self.motor.safe_stop(self.zero_frames)
            return result
        command = result.command
        try:
            self.motor.update_realtime_target(command.linear_speed, command.angular_speed,
                self.max_motor_rpm, self.left_direction, self.right_direction,
                self.mode, self.config, self.torque, self.depth)
        except ValueError:
            self.machine.safe_stop(StopReason.SPEED_LIMIT)
            self.motor.safe_stop(self.zero_frames)
            return CommandResult(False, command, self.machine.state, self.machine.reason)
        return result

    def poll(self):
        previous = self.machine.state
        state = self.machine.poll()
        if state == ControlState.SAFE_STOP and previous != state:
            self.motor.safe_stop(self.zero_frames)
        return state

    def disconnect(self):
        self.machine.disconnect()
        self.motor.safe_stop(self.zero_frames)

    def fail(self, reason=StopReason.CAN_FAULT):
        self.machine.safe_stop(reason)
        self.motor.safe_stop(self.zero_frames)

    def close(self):
        self.machine.safe_stop(StopReason.SHUTDOWN)
        self.motor.safe_stop(self.zero_frames)
        return self.motor.close(self.zero_frames, self.off_frames, self.period)
