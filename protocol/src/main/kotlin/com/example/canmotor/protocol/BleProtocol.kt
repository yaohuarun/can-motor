package com.example.canmotor.protocol

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object BleProtocol {
    val SERVICE_UUID: UUID = UUID.fromString("7e57d004-2b7b-4ec4-95a1-6f6b4f9b1000")
    val COMMAND_UUID: UUID = UUID.fromString("7e57d004-2b7b-4ec4-95a1-6f6b4f9b1001")
    val STATUS_UUID: UUID = UUID.fromString("7e57d004-2b7b-4ec4-95a1-6f6b4f9b1002")
    val CAPABILITIES_UUID: UUID = UUID.fromString("7e57d004-2b7b-4ec4-95a1-6f6b4f9b1003")

    const val VERSION: Int = 1
    const val COMMAND_SIZE: Int = 20
    const val STATUS_SIZE: Int = 20
    const val CAPABILITIES_SIZE: Int = 20
    private const val CENTERED_FLAG: Int = 1
    private const val UINT32_HALF_RANGE: Long = 0x8000_0000L
    private const val UINT32_MODULUS: Long = 0x1_0000_0000L

    fun encodeCommand(command: MotionCommand): ByteArray {
        requireUInt32(command.sessionId, "sessionId")
        require(command.sessionId != 0L) { "sessionId must not be zero" }
        requireUInt32(command.sequence, "sequence")
        require(command.linearSpeed.isFinite() && command.angularSpeed.isFinite()) {
            "speeds must be finite"
        }
        return littleEndian(COMMAND_SIZE)
            .put(VERSION.toByte())
            .put(if (command.centered) CENTERED_FLAG.toByte() else 0)
            .putShort(0)
            .putInt(command.sessionId.toInt())
            .putInt(command.sequence.toInt())
            .putFloat(command.linearSpeed)
            .putFloat(command.angularSpeed)
            .array()
    }

    fun decodeCommand(
        payload: ByteArray,
        expectedSession: Long? = null,
        previousSequence: Long? = null,
        maxLinearSpeed: Float? = null,
        maxAngularSpeed: Float? = null,
    ): MotionCommand {
        require(payload.size == COMMAND_SIZE) { "command must be $COMMAND_SIZE bytes" }
        val buffer = payload.littleEndian()
        require(buffer.unsignedByte() == VERSION) { "unsupported protocol version" }
        val flags = buffer.unsignedByte()
        require(flags and CENTERED_FLAG.inv() == 0) { "unknown command flags" }
        require(buffer.unsignedShort() == 0) { "reserved command bits must be zero" }
        val sessionId = buffer.unsignedInt()
        val sequence = buffer.unsignedInt()
        val linear = buffer.float
        val angular = buffer.float
        require(sessionId != 0L) { "sessionId must not be zero" }
        require(expectedSession == null || sessionId == expectedSession) { "stale session" }
        require(previousSequence == null || sequenceIsNewer(sequence, previousSequence)) {
            "duplicate or out-of-order sequence"
        }
        require(linear.isFinite() && angular.isFinite()) { "speeds must be finite" }
        require(maxLinearSpeed == null || kotlin.math.abs(linear) <= maxLinearSpeed) {
            "linear speed exceeds capability"
        }
        require(maxAngularSpeed == null || kotlin.math.abs(angular) <= maxAngularSpeed) {
            "angular speed exceeds capability"
        }
        return MotionCommand(sessionId, sequence, linear, angular, flags and CENTERED_FLAG != 0)
    }

    fun encodeStatus(status: GatewayStatus): ByteArray = littleEndian(STATUS_SIZE)
        .put(VERSION.toByte())
        .put(status.state.wireValue.toByte())
        .put(status.reason.wireValue.toByte())
        .put(0)
        .putInt(requireUInt32(status.sessionId, "sessionId").toInt())
        .putInt(requireUInt32(status.acceptedSequence, "acceptedSequence").toInt())
        .putShort(requireInt16(status.targetLinearMilli, "targetLinearMilli").toShort())
        .putShort(requireInt16(status.targetAngularMilli, "targetAngularMilli").toShort())
        .put(requireUInt8(status.leftFault, "leftFault").toByte())
        .put(requireUInt8(status.rightFault, "rightFault").toByte())
        .putShort(requireUInt16(status.watchdogRemainingMs, "watchdogRemainingMs").toShort())
        .array()

    fun decodeStatus(payload: ByteArray): GatewayStatus {
        require(payload.size == STATUS_SIZE) { "status must be $STATUS_SIZE bytes" }
        val buffer = payload.littleEndian()
        require(buffer.unsignedByte() == VERSION) { "unsupported status version" }
        val state = ControlState.fromWire(buffer.unsignedByte())
        val reason = StopReason.fromWire(buffer.unsignedByte())
        require(buffer.unsignedByte() == 0) { "reserved status byte must be zero" }
        return GatewayStatus(
            state = state,
            reason = reason,
            sessionId = buffer.unsignedInt(),
            acceptedSequence = buffer.unsignedInt(),
            targetLinearMilli = buffer.short.toInt(),
            targetAngularMilli = buffer.short.toInt(),
            leftFault = buffer.unsignedByte(),
            rightFault = buffer.unsignedByte(),
            watchdogRemainingMs = buffer.unsignedShort(),
        )
    }

    fun encodeCapabilities(capabilities: Capabilities): ByteArray {
        require(capabilities.maxLinearSpeed.isFinite() && capabilities.maxLinearSpeed > 0f)
        require(capabilities.maxAngularSpeed.isFinite() && capabilities.maxAngularSpeed > 0f)
        return littleEndian(CAPABILITIES_SIZE)
            .put(VERSION.toByte()).put(0).putShort(0)
            .putFloat(capabilities.maxLinearSpeed)
            .putFloat(capabilities.maxAngularSpeed)
            .putShort(requireUInt16(capabilities.commandPeriodMs, "commandPeriodMs").toShort())
            .putShort(requireUInt16(capabilities.watchdogTimeoutMs, "watchdogTimeoutMs").toShort())
            .putInt(requireUInt32(capabilities.maxMotorRpmTenths, "maxMotorRpmTenths").toInt())
            .array()
    }

    fun decodeCapabilities(payload: ByteArray): Capabilities {
        require(payload.size == CAPABILITIES_SIZE) { "capabilities must be $CAPABILITIES_SIZE bytes" }
        val buffer = payload.littleEndian()
        require(buffer.unsignedByte() == VERSION) { "unsupported capabilities version" }
        require(buffer.unsignedByte() == 0 && buffer.unsignedShort() == 0) {
            "capabilities flags and reserved bits must be zero"
        }
        val result = Capabilities(
            maxLinearSpeed = buffer.float,
            maxAngularSpeed = buffer.float,
            commandPeriodMs = buffer.unsignedShort(),
            watchdogTimeoutMs = buffer.unsignedShort(),
            maxMotorRpmTenths = buffer.unsignedInt(),
        )
        require(result.maxLinearSpeed.isFinite() && result.maxLinearSpeed > 0f)
        require(result.maxAngularSpeed.isFinite() && result.maxAngularSpeed > 0f)
        require(result.commandPeriodMs > 0 && result.watchdogTimeoutMs > 0)
        return result
    }

    fun sequenceIsNewer(candidate: Long, previous: Long): Boolean {
        requireUInt32(candidate, "candidate")
        requireUInt32(previous, "previous")
        val difference = (candidate - previous + UINT32_MODULUS) % UINT32_MODULUS
        return difference in 1 until UINT32_HALF_RANGE
    }

    private fun littleEndian(size: Int) = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN)
    private fun ByteArray.littleEndian() = ByteBuffer.wrap(this).order(ByteOrder.LITTLE_ENDIAN)
    private fun ByteBuffer.unsignedByte() = get().toInt() and 0xff
    private fun ByteBuffer.unsignedShort() = short.toInt() and 0xffff
    private fun ByteBuffer.unsignedInt() = int.toLong() and 0xffff_ffffL
    private fun requireUInt8(value: Int, name: String) = value.also { require(it in 0..0xff) { "$name must be uint8" } }
    private fun requireUInt16(value: Int, name: String) = value.also { require(it in 0..0xffff) { "$name must be uint16" } }
    private fun requireInt16(value: Int, name: String) = value.also { require(it in Short.MIN_VALUE..Short.MAX_VALUE) { "$name must be int16" } }
    private fun requireUInt32(value: Long, name: String) = value.also { require(it in 0..0xffff_ffffL) { "$name must be uint32" } }
}

data class MotionCommand(
    val sessionId: Long,
    val sequence: Long,
    val linearSpeed: Float,
    val angularSpeed: Float,
    val centered: Boolean = false,
)

data class GatewayStatus(
    val state: ControlState,
    val reason: StopReason,
    val sessionId: Long,
    val acceptedSequence: Long,
    val targetLinearMilli: Int,
    val targetAngularMilli: Int,
    val leftFault: Int,
    val rightFault: Int,
    val watchdogRemainingMs: Int,
)

data class Capabilities(
    val maxLinearSpeed: Float,
    val maxAngularSpeed: Float,
    val commandPeriodMs: Int = 50,
    val watchdogTimeoutMs: Int = 300,
    val maxMotorRpmTenths: Long = 0,
)

enum class ControlState(val wireValue: Int) {
    IDLE(0), WAIT_CENTER(1), ARMED(2), SAFE_STOP(3);
    companion object {
        fun fromWire(value: Int) = entries.singleOrNull { it.wireValue == value }
            ?: throw IllegalArgumentException("invalid control state")
    }
}

enum class StopReason(val wireValue: Int) {
    NONE(0), USER(1), WATCHDOG(2), DISCONNECT(3), INVALID_COMMAND(4),
    SPEED_LIMIT(5), CAN_FAULT(6), SHUTDOWN(7), BLUEZ_LOST(8);
    companion object {
        fun fromWire(value: Int) = entries.singleOrNull { it.wireValue == value }
            ?: throw IllegalArgumentException("invalid stop reason")
    }
}
