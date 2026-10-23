package com.example.canmotor.ble

import com.example.canmotor.protocol.BleProtocol
import com.example.canmotor.protocol.Capabilities
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class GattClientControllerTest {
    private class FakeTransport : GattTransport {
        val calls = mutableListOf<String>()
        override fun startFilteredScan(serviceUuid: UUID) { calls += "scan:$serviceUuid" }
        override fun stopScan() { calls += "stopScan" }
        override fun connect(address: String) { calls += "connect:$address" }
        override fun discoverServices() { calls += "discover" }
        override fun readCharacteristic(uuid: UUID) { calls += "read:$uuid" }
        override fun enableNotifications(uuid: UUID) { calls += "notify:$uuid" }
        override fun writeWithoutResponse(uuid: UUID, value: ByteArray): Boolean { calls += "write:$uuid"; return true }
        override fun disconnect() { calls += "disconnect" }
    }

    @Test fun fullSerializedConnectionAndWriteFlow() {
        val transport = FakeTransport(); val client = GattClientController(transport)
        client.startScan(); client.onScanResult("AA"); client.onScanResult("BB")
        client.onConnected(); client.onServicesDiscovered(true)
        client.onCapabilities(BleProtocol.encodeCapabilities(Capabilities(1f, 2f)))
        client.onNotificationsEnabled(true)
        assertEquals(ConnectionStage.READY, client.stage)
        assertEquals("AA", client.activeAddress)
        assertEquals(1, transport.calls.count { it.startsWith("connect:") })
        assertTrue(client.send(ByteArray(20)))
        client.disconnect()
        assertEquals(ConnectionStage.IDLE, client.stage)
        assertNull(client.capabilities)
    }

    @Test fun missingServiceAndAuthenticationFailureCleanSession() {
        val transport = FakeTransport(); val client = GattClientController(transport)
        client.startScan(); client.onScanResult("AA"); client.onConnected()
        client.onServicesDiscovered(false)
        assertEquals(ConnectionStage.FAILED, client.stage)
        assertNull(client.activeAddress)
        client.startScan(); client.onScanResult("BB"); client.onAuthenticationFailure()
        assertEquals(ConnectionStage.FAILED, client.stage)
        assertFalse(client.send(ByteArray(20)))
    }
}
