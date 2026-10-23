package com.example.canmotor.control

import com.example.canmotor.protocol.ControlState
import com.example.canmotor.protocol.GatewayStatus
import com.example.canmotor.protocol.StopReason
import org.junit.Assert.*
import org.junit.Test

class ControlUiStateTest {
    private fun status(session: Long, sequence: Long, state: ControlState) =
        GatewayStatus(state, StopReason.NONE, session, sequence, 100, -200, 1, 2, 250)

    @Test fun currentSessionCenterAckArmsAndStaleNotificationsAreDropped() {
        val reducer = ControlUiStateReducer(); reducer.beginSession(8)
        assertFalse(reducer.state.armed)
        assertFalse(reducer.acceptStatus(status(7, 100, ControlState.ARMED)))
        assertTrue(reducer.acceptStatus(status(8, 2, ControlState.ARMED)))
        assertTrue(reducer.state.armed)
        assertFalse(reducer.acceptStatus(status(8, 1, ControlState.SAFE_STOP)))
        assertEquals(2, reducer.state.acceptedSequence)
        assertEquals(1, reducer.state.leftFault)
    }

    @Test fun reconnectNeverReusesPreviousArmedState() {
        val reducer = ControlUiStateReducer(); reducer.beginSession(8)
        reducer.acceptStatus(status(8, 2, ControlState.ARMED))
        reducer.beginSession(9)
        assertFalse(reducer.state.armed)
        assertFalse(reducer.acceptStatus(status(8, 3, ControlState.ARMED)))
    }
}
