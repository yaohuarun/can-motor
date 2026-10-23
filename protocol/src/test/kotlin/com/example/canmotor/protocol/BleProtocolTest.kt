package com.example.canmotor.protocol

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BleProtocolTest {
    @Test
    fun `command matches Python golden vector`() {
        val command = MotionCommand(0x12345678, 0x01020304, 0.5f, -0.25f, centered = true)
        assertEquals(COMMAND_GOLDEN, BleProtocol.encodeCommand(command).hex())
        assertEquals(command, BleProtocol.decodeCommand(
            COMMAND_GOLDEN.bytes(), expectedSession = 0x12345678,
            previousSequence = 0x01020303, maxLinearSpeed = 2.5f, maxAngularSpeed = 1f,
        ))
    }

    @Test
    fun `status matches Python golden vector including stop reason`() {
        val status = GatewayStatus(ControlState.ARMED, StopReason.NONE, 0x12345678,
            0x01020304, 123, -456, 10, 0, 250)
        assertEquals(STATUS_GOLDEN, BleProtocol.encodeStatus(status).hex())
        assertEquals(status, BleProtocol.decodeStatus(STATUS_GOLDEN.bytes()))

        val stopped = status.copy(state = ControlState.SAFE_STOP, reason = StopReason.WATCHDOG)
        assertEquals(StopReason.WATCHDOG, BleProtocol.decodeStatus(BleProtocol.encodeStatus(stopped)).reason)
    }

    @Test
    fun `capabilities match Python golden vector`() {
        val capabilities = Capabilities(2.5f, 1f, 50, 300, 30000)
        assertEquals(CAPABILITIES_GOLDEN, BleProtocol.encodeCapabilities(capabilities).hex())
        assertEquals(capabilities, BleProtocol.decodeCapabilities(CAPABILITIES_GOLDEN.bytes()))
    }

    @Test
    fun `rejects invalid fields and stale commands`() {
        val valid = BleProtocol.encodeCommand(MotionCommand(7, 2, 0.1f, 0.2f))
        assertFailsWith<IllegalArgumentException> { BleProtocol.decodeCommand(valid.copyOf(19)) }
        assertFailsWith<IllegalArgumentException> { BleProtocol.decodeCommand(valid, expectedSession = 8) }
        assertFailsWith<IllegalArgumentException> { BleProtocol.decodeCommand(valid, previousSequence = 2) }
        assertFailsWith<IllegalArgumentException> {
            BleProtocol.decodeCommand(BleProtocol.encodeCommand(MotionCommand(7, 3, 2.6f, 0f)), maxLinearSpeed = 2.5f)
        }
        assertFailsWith<IllegalArgumentException> { BleProtocol.encodeCommand(MotionCommand(7, 3, Float.NaN, 0f)) }
    }

    @Test
    fun `sequence comparison handles unsigned wraparound`() {
        assertTrue(BleProtocol.sequenceIsNewer(11, 10))
        assertFalse(BleProtocol.sequenceIsNewer(10, 10))
        assertFalse(BleProtocol.sequenceIsNewer(9, 10))
        assertTrue(BleProtocol.sequenceIsNewer(0, 0xffff_ffffL))
        assertFalse(BleProtocol.sequenceIsNewer(0xffff_ffffL, 0))
    }

    private fun ByteArray.hex() = joinToString(" ") { "%02X".format(it) }
    private fun String.bytes() = split(' ').map { it.toInt(16).toByte() }.toByteArray()

    companion object {
        const val COMMAND_GOLDEN = "01 01 00 00 78 56 34 12 04 03 02 01 00 00 00 3F 00 00 80 BE"
        const val STATUS_GOLDEN = "01 02 00 00 78 56 34 12 04 03 02 01 7B 00 38 FE 0A 00 FA 00"
        const val CAPABILITIES_GOLDEN = "01 00 00 00 00 00 20 40 00 00 80 3F 32 00 2C 01 30 75 00 00"
    }
}
