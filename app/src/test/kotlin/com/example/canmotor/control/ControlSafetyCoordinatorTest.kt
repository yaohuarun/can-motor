package com.example.canmotor.control

import org.junit.Assert.*
import org.junit.Test

class ControlSafetyCoordinatorTest {
    @Test fun everyLifecycleExitClearsMotionAndDisconnectBlocksIt() {
        for (event in listOf<(ControlSafetyCoordinator) -> Unit>(
            { it.released() }, { it.touchCancelled() }, { it.stopPressed() },
            { it.pageStopped() }, { it.appBackgrounded() }
        )) {
            val joystick = JoystickController(); var zeros = 0; var stops = 0
            val safety = ControlSafetyCoordinator(joystick, { zeros++ }, { stops++ })
            safety.connected(); joystick.update(0f, -1f, 1f, 1f)
            event(safety)
            assertTrue(joystick.target.centered)
            assertEquals(1, zeros)
        }
        val joystick = JoystickController(); var stops = 0
        val safety = ControlSafetyCoordinator(joystick, {}, { stops++ })
        safety.connected(); safety.disconnected()
        assertFalse(safety.acceptsMotion())
        assertEquals(1, stops)
    }
}
