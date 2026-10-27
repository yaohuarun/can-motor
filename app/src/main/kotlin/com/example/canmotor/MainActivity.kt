package com.example.canmotor

import android.Manifest
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp
import java.util.Locale
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.example.canmotor.ble.AndroidBleTransport
import com.example.canmotor.ble.ConnectionStage
import com.example.canmotor.ble.GattClientController
import com.example.canmotor.control.ControlUiState
import com.example.canmotor.control.ControlUiStateReducer
import com.example.canmotor.control.JoystickController
import com.example.canmotor.control.LatestCommandSender
import com.example.canmotor.control.VirtualJoystick
import com.example.canmotor.control.MotionAction
import com.example.canmotor.control.MotionButtons
import com.example.canmotor.protocol.BleProtocol
import com.example.canmotor.protocol.StopReason

class MainActivity : ComponentActivity() {
    private lateinit var client: GattClientController
    private lateinit var transport: AndroidBleTransport
    private val joystick = JoystickController()
    private val sender = LatestCommandSender(joystick)
    private val reducer = ControlUiStateReducer()
    private val screenState = mutableStateOf(ControlUiState())
    private var stageTimeout: Job? = null
    private var timedStage: ConnectionStage? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        if (grants.values.all { it }) startScan() else updateFailure("蓝牙权限被拒绝")
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            client.onScanResult(result.device.address)
            refreshStage()
        }
        override fun onScanFailed(errorCode: Int) {
            client.onFailure("扫描失败：$errorCode")
            refreshStage()
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            if (status == BluetoothGatt.GATT_INSUFFICIENT_AUTHENTICATION ||
                status == BluetoothGatt.GATT_INSUFFICIENT_ENCRYPTION) {
                client.onAuthenticationFailure()
            } else if (status == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
                client.onConnected()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                if (status == BluetoothGatt.GATT_SUCCESS) client.onDisconnected()
                else client.onFailure("蓝牙连接失败：$status，请检查工控机蓝牙和配对状态")
                sender.stop()
                reducer.reset()
            }
            refreshStage()
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            client.onServicesDiscovered(status == BluetoothGatt.GATT_SUCCESS &&
                gatt.getService(BleProtocol.SERVICE_UUID) != null)
            refreshStage()
        }

        override fun onCharacteristicRead(gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic, value: ByteArray, status: Int) {
            handleCharacteristic(characteristic, value, status)
        }
        @Suppress("DEPRECATION")
        override fun onCharacteristicRead(gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic, status: Int) {
            handleCharacteristic(characteristic, characteristic.value ?: byteArrayOf(), status)
        }
        override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor,
                                       status: Int) {
            client.onNotificationsEnabled(status == BluetoothGatt.GATT_SUCCESS)
            refreshStage()
        }
        override fun onCharacteristicChanged(gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic, value: ByteArray) {
            handleStatus(characteristic, value)
        }
        @Suppress("DEPRECATION")
        override fun onCharacteristicChanged(gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic) {
            handleStatus(characteristic, characteristic.value ?: byteArrayOf())
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        transport = AndroidBleTransport(this, scanCallback, gattCallback)
        client = GattClientController(transport)
        setContent { MaterialTheme { MotorControlScreen(screenState, ::scanWithPermission,
            ::disconnect, ::stopNow, ::updateJoystick, ::startAction) } }
    }

    override fun onStop() {
        stageTimeout?.cancel()
        timedStage = null
        stopNow()
        sender.stop()
        if (::client.isInitialized) client.disconnect()
        reducer.reset()
        publishState()
        super.onStop()
    }

    override fun onDestroy() {
        sender.stop()
        if (::client.isInitialized) client.disconnect()
        super.onDestroy()
    }

    private fun handleCharacteristic(characteristic: BluetoothGattCharacteristic,
                                     value: ByteArray, status: Int) {
        if (status == BluetoothGatt.GATT_SUCCESS && characteristic.uuid == BleProtocol.CAPABILITIES_UUID) {
            client.onCapabilities(value)
        } else if (status != BluetoothGatt.GATT_SUCCESS) {
            client.onFailure("读取能力失败：$status")
        }
        refreshStage()
    }

    private fun handleStatus(characteristic: BluetoothGattCharacteristic, value: ByteArray) {
        if (characteristic.uuid != BleProtocol.STATUS_UUID) return
        client.onStatus(value)
        val status = client.latestStatus ?: return
        if (reducer.state.sessionId != status.sessionId) {
            joystick.center()
            reducer.beginSession(status.sessionId)
        }
        reducer.acceptStatus(status)
        startSenderIfReady()
        publishState()
    }

    private fun startSenderIfReady() {
        if (client.stage != ConnectionStage.READY || reducer.state.sessionId == 0L) return
        sender.start(
            scope = lifecycleScope,
            session = { reducer.state.sessionId },
            armed = { reducer.state.armed },
            send = { client.send(it) },
            onLinkFailure = {
                sender.stop()
                client.onFailure("BLE command writes have failed for at least 150 ms")
                reducer.connectionChanged(client.stage)
                publishState()
            },
        )
    }

    private fun scanWithPermission() {
        val permissions = requiredPermissions()
        if (permissions.all { ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED }) {
            startScan()
        } else permissionLauncher.launch(permissions)
    }

    private fun startScan() {
        client.startScan()
        refreshStage()
    }

    private fun disconnect() {
        stageTimeout?.cancel()
        timedStage = null
        sender.stop(); joystick.center(); client.disconnect()
        reducer.reset(); publishState()
    }

    private fun stopNow() {
        joystick.center()
        if (client.stage == ConnectionStage.READY && reducer.state.sessionId != 0L) {
            client.send(BleProtocol.encodeCommand(joystick.nextCommand(reducer.state.sessionId, false)))
        }
    }

    private fun updateJoystick(x: Float, y: Float) {
        val capability = client.capabilities ?: return
        joystick.update(x, y, capability.maxLinearSpeed, capability.maxAngularSpeed)
    }

    private fun startAction(action: MotionAction) {
        if (client.stage != ConnectionStage.READY || !reducer.state.armed) return
        val capability = client.capabilities ?: return
        joystick.action(action, capability.maxLinearSpeed, capability.maxAngularSpeed)
    }

    private fun refreshStage() {
        reducer.connectionChanged(client.stage)
        publishState()
        runOnUiThread {
            val stage = client.stage
            if (stage != timedStage) {
                stageTimeout?.cancel()
                timedStage = stage
                if (stage in listOf(ConnectionStage.SCANNING, ConnectionStage.CONNECTING,
                        ConnectionStage.DISCOVERING, ConnectionStage.READING_CAPABILITIES,
                        ConnectionStage.SUBSCRIBING)) {
                    stageTimeout = lifecycleScope.launch {
                        delay(if (stage == ConnectionStage.SCANNING) 30_000L else 15_000L)
                        timedStage = null
                        client.onStageTimeout(stage)
                        reducer.connectionChanged(client.stage)
                        publishState()
                    }
                }
            }
        }
    }
    private fun updateFailure(message: String) {
        screenState.value = screenState.value.copy(connection = ConnectionStage.FAILED,
            message = message)
    }
    private fun publishState() = runOnUiThread {
        screenState.value = reducer.state.copy(message = client.failure,
            maxLinearSpeed = client.capabilities?.maxLinearSpeed)
    }
    private fun requiredPermissions(): Array<String> = if (Build.VERSION.SDK_INT >= 31) {
        arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
    } else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
}

@Composable
fun MotorControlScreen(state: State<ControlUiState>, onScan: () -> Unit,
                       onDisconnect: () -> Unit, onStop: () -> Unit,
                       onJoystick: (Float, Float) -> Unit,
                       onAction: (MotionAction) -> Unit = {}) {
    val value = state.value
    val ready = value.connection == ConnectionStage.READY && value.armed
    Scaffold(containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        bottomBar = {
            Surface(shadowElevation = 8.dp) {
                Button(onClick = onStop,
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(16.dp).height(56.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) {
                    Text("立即停止", style = MaterialTheme.typography.titleMedium)
                }
            }
        }) { insets ->
        Column(Modifier.fillMaxSize().padding(insets).verticalScroll(rememberScrollState())
            .padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text("电机控制", style = MaterialTheme.typography.headlineSmall)
                    Text("CAN Motor · BLE", style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (value.connection == ConnectionStage.IDLE || value.connection == ConnectionStage.FAILED) {
                    Button(onClick = onScan) { Text("扫描连接") }
                } else OutlinedButton(onClick = onDisconnect) { Text("断开连接") }
            }
            Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(when (value.connection) {
                            ConnectionStage.IDLE -> "未连接"
                            ConnectionStage.READY -> "蓝牙已连接"
                            ConnectionStage.FAILED -> "连接失败"
                            ConnectionStage.SCANNING -> "正在扫描网关…"
                            ConnectionStage.CONNECTING -> "正在建立蓝牙连接…"
                            ConnectionStage.DISCOVERING -> "正在发现控制服务…"
                            ConnectionStage.READING_CAPABILITIES -> "正在读取网关能力…"
                            ConnectionStage.SUBSCRIBING -> "正在订阅状态…"
                        }, style = MaterialTheme.typography.titleMedium)
                        Text(if (ready) "已解锁" else "未解锁",
                            color = if (ready) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    HorizontalDivider()
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        Column(Modifier.weight(1f)) {
                            Text("目标线速度", style = MaterialTheme.typography.labelMedium)
                            Text(String.format(Locale.ROOT, "%.2f m/s", value.targetLinear), style = MaterialTheme.typography.titleLarge)
                        }
                        Column(Modifier.weight(1f)) {
                            Text("目标角速度", style = MaterialTheme.typography.labelMedium)
                            Text(String.format(Locale.ROOT, "%.2f rad/s", value.targetAngular), style = MaterialTheme.typography.titleLarge)
                        }
                    }
                    Text("停车：${value.stopReason}  ·  故障 左/右：${value.leftFault.toString(16)} / ${value.rightFault.toString(16)}",
                        style = MaterialTheme.typography.bodySmall)
                    Text("会话 ${value.sessionId}  ·  确认 ${value.acceptedSequence}",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    value.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            }
            Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("摇杆控制", style = MaterialTheme.typography.titleMedium)
                    Text("上下前后 · 左右转向 · 松手停车", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    VirtualJoystick(onPosition = onJoystick, onRelease = onStop)
                }
            }
            Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("快捷动作", style = MaterialTheme.typography.titleMedium)
                    Text("直线速度 0.50 m/s · 按住运行，松开停车", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    value.maxLinearSpeed?.takeIf { it < 0.5f }?.let {
                        Text(String.format(Locale.ROOT, "网关限速：直线动作实际为 %.2f m/s", it),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                    }
                    MotionButtons(ready, onAction, onStop)
                }
            }
        }
    }
}

@Preview(showBackground = true)
@Composable private fun PreviewIdle() { MaterialTheme { MotorControlScreen(
    remember { mutableStateOf(ControlUiState()) }, {}, {}, {}, { _, _ -> }) } }
@Preview(name = "Armed", showBackground = true)
@Composable private fun PreviewArmed() { MaterialTheme { MotorControlScreen(
    remember { mutableStateOf(ControlUiState(ConnectionStage.READY, 42, true, 18, 0.12f, 0.3f)) },
    {}, {}, {}, { _, _ -> }) } }
@Preview(name = "Safe stop", showBackground = true)
@Composable private fun PreviewSafeStop() { MaterialTheme { MotorControlScreen(
    remember { mutableStateOf(ControlUiState(ConnectionStage.READY, 42, false, 18,
        stopReason = StopReason.WATCHDOG, leftFault = 10)) }, {}, {}, {}, { _, _ -> }) } }
