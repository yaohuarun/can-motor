package com.example.canmotor.ble

import com.example.canmotor.protocol.BleProtocol
import com.example.canmotor.protocol.Capabilities
import com.example.canmotor.protocol.ControlState
import com.example.canmotor.protocol.GatewayStatus

enum class ConnectionStage {
    IDLE, SCANNING, CONNECTING, DISCOVERING, READING_CAPABILITIES,
    SUBSCRIBING, READY, FAILED
}

interface GattTransport {
    fun startFilteredScan(serviceUuid: java.util.UUID)
    fun stopScan()
    fun connect(address: String)
    fun discoverServices()
    fun readCharacteristic(uuid: java.util.UUID)
    fun enableNotifications(uuid: java.util.UUID)
    fun writeWithoutResponse(uuid: java.util.UUID, value: ByteArray): Boolean
    fun disconnect()
}

class GattClientController(private val transport: GattTransport) {
    var stage: ConnectionStage = ConnectionStage.IDLE
        private set
    var capabilities: Capabilities? = null
        private set
    var latestStatus: GatewayStatus? = null
        private set
    var activeAddress: String? = null
        private set
    var failure: String? = null
        private set
    private var operationPending = false
    private val retiredSessionIds = mutableSetOf<Long>()

    @Synchronized fun startScan() {
        require(stage == ConnectionStage.IDLE || stage == ConnectionStage.FAILED)
        clearSession()
        stage = ConnectionStage.SCANNING
        transport.startFilteredScan(BleProtocol.SERVICE_UUID)
    }

    @Synchronized fun onScanResult(address: String) {
        if (stage != ConnectionStage.SCANNING || operationPending) return
        operationPending = true
        activeAddress = address
        transport.stopScan()
        stage = ConnectionStage.CONNECTING
        transport.connect(address)
    }

    @Synchronized fun onConnected() {
        if (stage != ConnectionStage.CONNECTING) return
        operationPending = false
        stage = ConnectionStage.DISCOVERING
        operationPending = true
        transport.discoverServices()
    }

    @Synchronized fun onServicesDiscovered(serviceFound: Boolean) {
        if (stage != ConnectionStage.DISCOVERING) return
        operationPending = false
        if (!serviceFound) return fail("Motor control service not found")
        stage = ConnectionStage.READING_CAPABILITIES
        operationPending = true
        transport.readCharacteristic(BleProtocol.CAPABILITIES_UUID)
    }

    @Synchronized fun onCapabilities(value: ByteArray) {
        if (stage != ConnectionStage.READING_CAPABILITIES) return
        operationPending = false
        try {
            capabilities = BleProtocol.decodeCapabilities(value)
        } catch (error: IllegalArgumentException) {
            return fail("Invalid gateway capabilities")
        }
        stage = ConnectionStage.SUBSCRIBING
        operationPending = true
        transport.enableNotifications(BleProtocol.STATUS_UUID)
    }

    @Synchronized fun onNotificationsEnabled(success: Boolean) {
        if (stage != ConnectionStage.SUBSCRIBING) return
        operationPending = false
        if (!success) return fail("Status subscription failed")
        stage = ConnectionStage.READY
    }

    @Synchronized fun onStatus(value: ByteArray) {
        if (stage != ConnectionStage.READY) return
        val decoded = try { BleProtocol.decodeStatus(value) } catch (_: IllegalArgumentException) { return }
        val current = latestStatus
        if (current != null && decoded.sessionId != current.sessionId) {
            // The gateway creates a new session when its service restarts.
            // Switch only on its safe initial status; this prevents a late
            // notification from an old session from taking control back.
            if (decoded.sessionId in retiredSessionIds ||
                decoded.state != ControlState.WAIT_CENTER ||
                decoded.acceptedSequence != 0L) return
            retiredSessionIds += current.sessionId
            latestStatus = decoded
            return
        }
        if (current != null &&
            !BleProtocol.sequenceIsNewer(decoded.acceptedSequence, current.acceptedSequence) &&
            decoded.acceptedSequence != current.acceptedSequence) return
        latestStatus = decoded
    }

    @Synchronized fun send(value: ByteArray): Boolean =
        stage == ConnectionStage.READY &&
            transport.writeWithoutResponse(BleProtocol.COMMAND_UUID, value)

    @Synchronized fun onAuthenticationFailure() = fail("Pairing or encryption required")
    @Synchronized fun onStageTimeout(expected: ConnectionStage) {
        if (stage != expected) return
        val message = when (stage) {
            ConnectionStage.SCANNING -> "扫描超时：未发现网关，请检查工控机蓝牙和网关服务"
            ConnectionStage.CONNECTING -> "蓝牙连接超时：请检查工控机蓝牙、配对状态后重试"
            ConnectionStage.DISCOVERING -> "发现服务超时：请检查工控机 BLE 网关服务"
            ConnectionStage.READING_CAPABILITIES -> "读取能力超时：请检查配对和加密状态"
            ConnectionStage.SUBSCRIBING -> "订阅状态超时：请检查网关服务后重试"
            else -> return
        }
        if (stage == ConnectionStage.SCANNING) transport.stopScan()
        fail(message)
    }
    @Synchronized fun onFailure(message: String) = fail(message)
    @Synchronized fun onDisconnected() {
        if (stage == ConnectionStage.FAILED) return
        transport.disconnect(); clearSession(); stage = ConnectionStage.IDLE
    }

    @Synchronized fun disconnect() {
        if (stage == ConnectionStage.SCANNING) transport.stopScan()
        transport.disconnect()
        clearSession()
        stage = ConnectionStage.IDLE
    }

    private fun fail(message: String) {
        failure = message
        transport.disconnect()
        activeAddress = null
        operationPending = false
        stage = ConnectionStage.FAILED
    }

    private fun clearSession() {
        activeAddress = null
        capabilities = null
        latestStatus = null
        retiredSessionIds.clear()
        failure = null
        operationPending = false
    }
}
