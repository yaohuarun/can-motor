package com.example.canmotor.control

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import kotlin.math.hypot

@Composable
fun VirtualJoystick(onPosition: (Float, Float) -> Unit,
                    onRelease: () -> Unit = {}, modifier: Modifier = Modifier) {
    var knob by remember { mutableStateOf(Offset.Zero) }
    Canvas(modifier.size(260.dp).pointerInput(Unit) {
        detectDragGestures(
            onDragStart = { point ->
                val center = Offset(size.width / 2f, size.height / 2f)
                val delta = point - center
                val radius = minOf(size.width, size.height) / 2f
                val scale = (radius / hypot(delta.x, delta.y)).coerceAtMost(1f)
                knob = Offset(delta.x * scale, delta.y * scale)
                onPosition(knob.x / radius, knob.y / radius)
            },
            onDragEnd = {
                knob = Offset.Zero
                onPosition(0f, 0f)
                onRelease()
            },
            onDragCancel = {
                knob = Offset.Zero
                onPosition(0f, 0f)
                onRelease()
            },
            onDrag = { change, amount ->
                change.consume()
                val radius = minOf(size.width, size.height) / 2f
                val next = knob + amount
                val scale = (radius / hypot(next.x, next.y)).coerceAtMost(1f)
                knob = Offset(next.x * scale, next.y * scale)
                onPosition(knob.x / radius, knob.y / radius)
            })
    }) {
        val radius = size.minDimension / 2f
        drawCircle(Color(0xFFE0F2F1), radius)
        drawCircle(Color(0xFF006A67), radius * 0.27f, center + knob)
    }
}
