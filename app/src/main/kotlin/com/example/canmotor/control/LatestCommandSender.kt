package com.example.canmotor.control

import com.example.canmotor.protocol.BleProtocol
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class LatestCommandSender(private val joystick: JoystickController) {
    private var job: Job? = null
    val running get() = job?.isActive == true

    @Synchronized fun start(scope: CoroutineScope, session: () -> Long,
                            armed: () -> Boolean, send: (ByteArray) -> Boolean,
                            onLinkFailure: () -> Unit = {}) {
        if (running) return
        job = scope.launch(Dispatchers.Default) {
            var lastSuccessfulWriteNanos = System.nanoTime()
            while (isActive) {
                val submitted = try {
                    send(BleProtocol.encodeCommand(joystick.nextCommand(session(), armed())))
                } catch (_: Exception) {
                    false
                }
                val now = System.nanoTime()
                if (submitted) lastSuccessfulWriteNanos = now
                if (!submitted && now - lastSuccessfulWriteNanos >= 150_000_000L) {
                    joystick.center()
                    onLinkFailure()
                    break
                }
                delay(50)
            }
        }
    }

    @Synchronized fun stop() { job?.cancel(); job = null }
}
