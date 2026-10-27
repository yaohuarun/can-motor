package com.example.canmotor.ble

import com.example.canmotor.protocol.BleProtocol
import com.example.canmotor.protocol.Capabilities
import com.example.canmotor.protocol.ControlState
import com.example.canmotor.protocol.GatewayStatus
import com.example.canmotor.protocol.StopReason
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class GattClientControllerTest {
    @Test fun pendingStagesTimeOutAndAllowRetryWithoutLosingFailure() {
        val transport = FakeTransport()
        val client = GattClientController(transport)
        client.startScan()
        client.onStageTimeout(ConnectionStage.CONNECTING)
        assertEquals(ConnectionStage.SCANNING, client.stage)
        client.onStageTimeout(ConnectionStage.SCANNING)
        assertEquals(ConnectionStage.FAILED, client.stage)
        assertTrue(transport.calls.contains("stopScan"))
        client.onDisconnected()
        assertEquals(ConnectionStage.FAILED, client.stage)
        assertNotNull(client.failure)
        for (pending in listOf(ConnectionStage.CONNECTING, ConnectionStage.DISCOVERING,
                ConnectionStage.READING_CAPABILITIES, ConnectionStage.SUBSCRIBING)) {
            client.startScan(); client.onScanResult("AA")
            if (pending != ConnectionStage.CONNECTING) client.onConnected()
            if (pending == ConnectionStage.READING_CAPABILITIES || pending == ConnectionStage.SUBSCRIBING)
                client.onServicesDiscovered(true)
            if (pending == ConnectionStage.SUBSCRIBING)
                client.onCapabilities(BleProtocol.encodeCapabilities(Capabilities(1f, 2f)))
            client.onStageTimeout(pending)
            assertEquals(ConnectionStage.FAILED, client.stage)
        }
        val ready = readyClient()
        ready.onStageTimeout(ConnectionStage.READY)
        assertEquals(ConnectionStage.READY, ready.stage)
    }

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

    private fun readyClient(): GattClientController {
        val client = GattClientController(FakeTransport())
        client.startScan(); client.onScanResult("AA"); client.onConnected()
        client.onServicesDiscovered(true)
        client.onCapabilities(BleProtocol.encodeCapabilities(Capabilities(1f, 2f)))
        client.onNotificationsEnabled(true)
        return client
    }

    private fun status(session: Long, sequence: Long, state: ControlState) =
        BleProtocol.encodeStatus(GatewayStatus(
            state, StopReason.NONE, session, sequence, 0, 0, 0, 0, 300))

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

    @Test fun gatewayRestartSwitchesOnlyOnSafeInitialSessionStatus() {
        val client = readyClient()
        client.onStatus(status(8, 12, ControlState.ARMED))
        assertEquals(8L, client.latestStatus?.sessionId)

        client.onStatus(status(9, 0, ControlState.ARMED))
        assertEquals(8L, client.latestStatus?.sessionId)
        client.onStatus(status(9, 1, ControlState.WAIT_CENTER))
        assertEquals(8L, client.latestStatus?.sessionId)

        client.onStatus(status(9, 0, ControlState.WAIT_CENTER))
        assertEquals(9L, client.latestStatus?.sessionId)
        assertEquals(ControlState.WAIT_CENTER, client.latestStatus?.state)

        client.onStatus(status(8, 13, ControlState.ARMED))
        assertEquals(9L, client.latestStatus?.sessionId)
        client.onStatus(status(8, 0, ControlState.WAIT_CENTER))
        assertEquals(9L, client.latestStatus?.sessionId)
    }
}
