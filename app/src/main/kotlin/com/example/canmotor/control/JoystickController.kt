package com.example.canmotor.control

import com.example.canmotor.protocol.MotionCommand
import kotlin.math.hypot

data class JoystickTarget(val linear: Float, val angular: Float, val centered: Boolean)

enum class MotionAction(val label: String) {
    FORWARD("直线前进"), BACKWARD("直线后退"),
    TURN_LEFT("原地左转"), TURN_RIGHT("原地右转"),
    LEFT_WHEEL_STOP("左轮零速转"), RIGHT_WHEEL_STOP("右轮零速转"),
}

class JoystickController(private val deadZone: Float = 0.12f) {
    var target = JoystickTarget(0f, 0f, true)
        private set
    private var sequence = 0L

    @Synchronized fun action(action: MotionAction, maxLinear: Float, maxAngular: Float) {
        // Match TRACK_WIDTH_M in motor_control.py. v = |omega| * track / 2
        // keeps the inside wheel stationary while the outside wheel moves forward.
        val halfTrack = 0.420f / 2f
        val pivotAngular = minOf(maxAngular, maxLinear / halfTrack)
        val straightSpeed = minOf(0.5f, maxLinear)
        target = when (action) {
            MotionAction.FORWARD -> JoystickTarget(straightSpeed, 0f, false)
            MotionAction.BACKWARD -> JoystickTarget(-straightSpeed, 0f, false)
            MotionAction.TURN_LEFT -> JoystickTarget(0f, maxAngular, false)
            MotionAction.TURN_RIGHT -> JoystickTarget(0f, -maxAngular, false)
            MotionAction.LEFT_WHEEL_STOP -> JoystickTarget(pivotAngular * halfTrack, pivotAngular, false)
            MotionAction.RIGHT_WHEEL_STOP -> JoystickTarget(pivotAngular * halfTrack, -pivotAngular, false)
        }
    }

    @Synchronized fun update(x: Float, y: Float, maxLinear: Float, maxAngular: Float) {
        val radius = hypot(x.toDouble(), y.toDouble()).toFloat()
        if (radius <= deadZone) return center()
        val scale = if (radius > 1f) 1f / radius else 1f
        target = JoystickTarget(
            linear = (-y * scale).coerceIn(-1f, 1f) * maxLinear,
            angular = (-x * scale).coerceIn(-1f, 1f) * maxAngular,
            centered = false,
        )
    }

    @Synchronized fun center() { target = JoystickTarget(0f, 0f, true) }

    @Synchronized fun nextCommand(sessionId: Long, armed: Boolean): MotionCommand {
        sequence = (sequence + 1) and 0xffff_ffffL
        val current = if (armed) target else JoystickTarget(0f, 0f, true)
        return MotionCommand(sessionId, sequence, current.linear, current.angular,
                             current.centered)
    }
}
