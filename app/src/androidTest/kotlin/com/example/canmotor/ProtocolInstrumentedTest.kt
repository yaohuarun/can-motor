package com.example.canmotor

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.example.canmotor.protocol.BleProtocol
import com.example.canmotor.protocol.MotionCommand
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ProtocolInstrumentedTest {
    @Test fun commandEncodingOnAndroidRuntimeMatchesV1WireFormat() {
        val command = MotionCommand(0x12345678, 0x01020304, 0.5f, -0.25f, true)
        val expected = "01 01 00 00 78 56 34 12 04 03 02 01 00 00 00 3F 00 00 80 BE"
        val actual = BleProtocol.encodeCommand(command).joinToString(" ") { "%02X".format(it) }
        assertEquals(expected, actual)
    }
}
