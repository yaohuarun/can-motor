package com.example.canmotor.control

import com.example.canmotor.protocol.MotionCommand
import kotlin.math.hypot

data class JoystickTarget(val linear: Float, val angular: Float, val centered: Boolean)

class JoystickController(private val deadZone: Float = 0.12f) {
    var target = JoystickTarget(0f, 0f, true)
        private set
    private var sequence = 0L

    fun update(x: Float, y: Float, maxLinear: Float, maxAngular: Float) {
        val radius = hypot(x.toDouble(), y.toDouble()).toFloat()
        if (radius <= deadZone) return center()
        val scale = if (radius > 1f) 1f / radius else 1f
        target = JoystickTarget(
            linear = (-y * scale).coerceIn(-1f, 1f) * maxLinear,
            angular = (-x * scale).coerceIn(-1f, 1f) * maxAngular,
            centered = false,
        )
    }

    fun center() { target = JoystickTarget(0f, 0f, true) }

    fun nextCommand(sessionId: Long, armed: Boolean): MotionCommand {
        sequence = (sequence + 1) and 0xffff_ffffL
        val current = if (armed) target else JoystickTarget(0f, 0f, true)
        return MotionCommand(sessionId, sequence, current.linear, current.angular,
                             current.centered)
    }
}
