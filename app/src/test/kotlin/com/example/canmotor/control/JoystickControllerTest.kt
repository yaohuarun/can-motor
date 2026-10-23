package com.example.canmotor.control

import org.junit.Assert.*
import org.junit.Test
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class JoystickControllerTest {
    @Test fun mapsDirectionsDeadZoneAndCombinedMotion() {
        val joystick = JoystickController()
        joystick.update(0f, -1f, 2f, 1f); assertTrue(joystick.target.linear > 0)
        joystick.update(0f, 1f, 2f, 1f); assertTrue(joystick.target.linear < 0)
        joystick.update(-1f, 0f, 2f, 1f); assertTrue(joystick.target.angular > 0)
        joystick.update(1f, 0f, 2f, 1f); assertTrue(joystick.target.angular < 0)
        joystick.update(-0.5f, -0.5f, 2f, 1f)
        assertTrue(joystick.target.linear > 0 && joystick.target.angular > 0)
        joystick.update(0.05f, 0.05f, 2f, 1f); assertTrue(joystick.target.centered)
    }

    @Test fun latestInputIsCoalescedAndSequenceAdvancesPerFiftyMsTick() {
        val joystick = JoystickController()
        joystick.update(0f, -0.2f, 1f, 1f)
        joystick.update(0f, -0.8f, 1f, 1f)
        val first = joystick.nextCommand(9, true)
        val second = joystick.nextCommand(9, true)
        assertEquals(0.8f, first.linearSpeed, 0.0001f)
        assertEquals(first.sequence + 1, second.sequence)
        val locked = joystick.nextCommand(9, false)
        assertEquals(0f, locked.linearSpeed)
        assertTrue(locked.centered)
    }

    @Test fun senderMaintainsOnlyOneActiveLoop() {
        val joystick = JoystickController()
        val sender = LatestCommandSender(joystick)
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        sender.start(scope, { 1 }, { true }, {})
        sender.start(scope, { 2 }, { true }, {})
        assertTrue(sender.running)
        sender.stop()
        assertFalse(sender.running)
    }
}
