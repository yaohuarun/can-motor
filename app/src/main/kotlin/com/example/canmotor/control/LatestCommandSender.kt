package com.example.canmotor.control

import com.example.canmotor.protocol.BleProtocol
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class LatestCommandSender(private val joystick: JoystickController) {
    private var job: Job? = null
    val running get() = job?.isActive == true

    @Synchronized fun start(scope: CoroutineScope, session: () -> Long,
                            armed: () -> Boolean, send: (ByteArray) -> Unit) {
        if (running) return
        job = scope.launch {
            while (isActive) {
                send(BleProtocol.encodeCommand(joystick.nextCommand(session(), armed())))
                delay(50)
            }
        }
    }

    @Synchronized fun stop() { job?.cancel(); job = null }
}
