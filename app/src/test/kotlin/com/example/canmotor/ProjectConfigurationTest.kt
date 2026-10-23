package com.example.canmotor

import org.junit.Assert.assertEquals
import org.junit.Test

class ProjectConfigurationTest {
    @Test fun protocolModuleIsAvailable() {
        assertEquals(20, com.example.canmotor.protocol.BleProtocol.COMMAND_SIZE)
    }
}
