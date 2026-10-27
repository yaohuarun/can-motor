package com.example.canmotor.control

import org.junit.Assert.*
import org.junit.Test
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class JoystickControllerTest {
    @Test fun straightButtonsUseHalfMeterPerSecondWithinGatewayLimit() {
        val controller = JoystickController()
        for (limit in listOf(0.1f, 0.5f, 2f)) {
            for (action in listOf(MotionAction.FORWARD, MotionAction.BACKWARD)) {
                controller.action(action, limit, 1f)
                val sign = if (action == MotionAction.FORWARD) 1f else -1f
                assertEquals(sign * minOf(0.5f, limit), controller.target.linear, 0.00001f)
                assertEquals(0f, controller.target.angular, 0f)
            }
        }
        controller.update(0f, -1f, 2f, 1f)
        assertEquals(2f, controller.target.linear, 0.00001f)
    }

    @Test fun fixedActionsAndStationaryWheelGeometry() {
        val controller = JoystickController()
        for (action in MotionAction.entries) {
            controller.action(action, 0.1f, 0.3f)
            val target = controller.target
            assertFalse(target.centered)
            when (action) {
                MotionAction.FORWARD -> { assertEquals(0.1f, target.linear, 0.00001f); assertEquals(0f, target.angular, 0f) }
                MotionAction.BACKWARD -> { assertEquals(-0.1f, target.linear, 0.00001f); assertEquals(0f, target.angular, 0f) }
                MotionAction.TURN_LEFT -> { assertEquals(0f, target.linear, 0f); assertEquals(0.3f, target.angular, 0.00001f) }
                MotionAction.TURN_RIGHT -> { assertEquals(0f, target.linear, 0f); assertEquals(-0.3f, target.angular, 0.00001f) }
                MotionAction.LEFT_WHEEL_STOP -> assertEquals(0f, target.linear - target.angular * 0.21f, 0.00001f)
                MotionAction.RIGHT_WHEEL_STOP -> assertEquals(0f, target.linear + target.angular * 0.21f, 0.00001f)
            }
            controller.center()
            assertTrue(controller.nextCommand(1, true).centered)
        }
        controller.action(MotionAction.LEFT_WHEEL_STOP, 0.02f, 0.3f)
        assertEquals(0.02f, controller.target.linear, 0.00001f)
        assertTrue(controller.target.angular <= 0.3f)
        assertEquals(0f, controller.target.linear - controller.target.angular * 0.21f, 0.00001f)
        assertTrue(controller.nextCommand(1, false).centered)
    }

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
        sender.start(scope, { 1 }, { true }, { true })
        sender.start(scope, { 2 }, { true }, { true })
        assertTrue(sender.running)
        sender.stop()
        assertFalse(sender.running)
    }
}
