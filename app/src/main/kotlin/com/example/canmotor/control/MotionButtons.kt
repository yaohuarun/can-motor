package com.example.canmotor.control

import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.*

@Composable
fun MotionButtons(enabled: Boolean, onAction: (MotionAction) -> Unit, onStop: () -> Unit) {
    var active by remember { mutableStateOf<MotionAction?>(null) }
    val currentAction by rememberUpdatedState(onAction)
    val currentStop by rememberUpdatedState(onStop)
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        MotionAction.entries.chunked(2).forEach { actions ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                actions.forEach { action ->
                    val source = remember { MutableInteractionSource() }
                    val pressed by source.collectIsPressedAsState()
                    LaunchedEffect(pressed, enabled) {
                        if (pressed && enabled && active == null) {
                            active = action
                            try {
                                currentAction(action)
                                kotlinx.coroutines.awaitCancellation()
                            } finally {
                                currentStop()
                                active = null
                            }
                        }
                    }
                    Button(onClick = {}, interactionSource = source,
                        modifier = Modifier.weight(1f).heightIn(min = 56.dp),
                        shape = RoundedCornerShape(12.dp),
                        enabled = enabled && (active == null || active == action)) {
                        Text(action.label)
                    }
                }
            }
        }
    }
}
