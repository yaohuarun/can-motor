package com.example.canmotor.control

class ControlSafetyCoordinator(
    private val joystick: JoystickController,
    private val sendZeroNow: () -> Unit,
    private val stopSender: () -> Unit,
) {
    var connected = false
        private set
    var foregroundEligible = false
        private set

    fun connected() { connected = true; foregroundEligible = true }
    fun released() = zeroAndRetainHeartbeat()
    fun touchCancelled() = zeroAndRetainHeartbeat()
    fun stopPressed() = zeroAndRetainHeartbeat()
    fun pageStopped() { foregroundEligible = false; zeroAndStop() }
    fun appBackgrounded() { foregroundEligible = false; zeroAndStop() }
    fun disconnected() { connected = false; foregroundEligible = false; joystick.center(); stopSender() }

    fun acceptsMotion() = connected && foregroundEligible

    private fun zeroAndRetainHeartbeat() {
        joystick.center()
        if (connected) sendZeroNow()
    }
    private fun zeroAndStop() { zeroAndRetainHeartbeat(); stopSender() }
}
