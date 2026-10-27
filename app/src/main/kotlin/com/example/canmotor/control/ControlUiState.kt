package com.example.canmotor.control

import com.example.canmotor.ble.ConnectionStage
import com.example.canmotor.protocol.ControlState
import com.example.canmotor.protocol.GatewayStatus
import com.example.canmotor.protocol.StopReason

data class ControlUiState(
    val connection: ConnectionStage = ConnectionStage.IDLE,
    val sessionId: Long = 0,
    val armed: Boolean = false,
    val acceptedSequence: Long = 0,
    val targetLinear: Float = 0f,
    val targetAngular: Float = 0f,
    val stopReason: StopReason = StopReason.NONE,
    val leftFault: Int = 0,
    val rightFault: Int = 0,
    val message: String? = null,
    val maxLinearSpeed: Float? = null,
)

class ControlUiStateReducer {
    @Volatile
    var state = ControlUiState()
        private set

    fun beginSession(sessionId: Long, connection: ConnectionStage = ConnectionStage.READY) {
        require(sessionId != 0L)
        state = ControlUiState(connection = connection, sessionId = sessionId)
    }

    fun reset(connection: ConnectionStage = ConnectionStage.IDLE) {
        state = ControlUiState(connection = connection)
    }

    fun connectionChanged(stage: ConnectionStage) {
        state = state.copy(connection = stage)
        if (stage != ConnectionStage.READY) state = state.copy(armed = false,
            targetLinear = 0f, targetAngular = 0f)
    }

    fun acceptStatus(status: GatewayStatus): Boolean {
        if (status.sessionId != state.sessionId) return false
        if (state.acceptedSequence != 0L &&
            status.acceptedSequence != state.acceptedSequence &&
            !com.example.canmotor.protocol.BleProtocol.sequenceIsNewer(
                status.acceptedSequence, state.acceptedSequence)) return false
        state = state.copy(
            armed = status.state == ControlState.ARMED,
            acceptedSequence = status.acceptedSequence,
            targetLinear = status.targetLinearMilli / 1000f,
            targetAngular = status.targetAngularMilli / 1000f,
            stopReason = status.reason,
            leftFault = status.leftFault,
            rightFault = status.rightFault,
        )
        return true
    }
}
