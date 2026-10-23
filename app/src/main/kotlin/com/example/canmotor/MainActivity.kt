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
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import com.example.canmotor.protocol.BleProtocol
import com.example.canmotor.protocol.StopReason

class MainActivity : ComponentActivity() {
    private lateinit var client: GattClientController
    private lateinit var transport: AndroidBleTransport
    private val joystick = JoystickController()
    private val sender = LatestCommandSender(joystick)
    private val reducer = ControlUiStateReducer()
    private val screenState = mutableStateOf(ControlUiState())

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
                client.onDisconnected()
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
            ::disconnect, ::stopNow, ::updateJoystick) } }
    }

    override fun onStop() {
        stopNow()
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
        if (reducer.state.sessionId == 0L) reducer.beginSession(status.sessionId)
        reducer.acceptStatus(status)
        startSenderIfReady()
        publishState()
    }

    private fun startSenderIfReady() {
        if (client.stage != ConnectionStage.READY || reducer.state.sessionId == 0L) return
        sender.start(lifecycleScope, { reducer.state.sessionId }, { reducer.state.armed }) {
            client.send(it)
        }
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

    private fun refreshStage() {
        reducer.connectionChanged(client.stage)
        publishState()
    }
    private fun updateFailure(message: String) {
        screenState.value = screenState.value.copy(connection = ConnectionStage.FAILED,
            message = message)
    }
    private fun publishState() = runOnUiThread {
        screenState.value = reducer.state.copy(message = client.failure)
    }
    private fun requiredPermissions(): Array<String> = if (Build.VERSION.SDK_INT >= 31) {
        arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
    } else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
}

@Composable
fun MotorControlScreen(state: State<ControlUiState>, onScan: () -> Unit,
                       onDisconnect: () -> Unit, onStop: () -> Unit,
                       onJoystick: (Float, Float) -> Unit) {
    val value = state.value
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally,
           verticalArrangement = Arrangement.Center) {
        Text("CAN Motor BLE")
        Text("连接阶段：${value.connection}")
        Text("会话：${value.sessionId}")
        Text(if (value.armed) "已解锁" else "等待手柄回中")
        Text("确认序号：${value.acceptedSequence}")
        Text("目标：${value.targetLinear} m/s, ${value.targetAngular} rad/s")
        Text("停车原因：${value.stopReason}")
        Text("左/右故障：0x${value.leftFault.toString(16)} / 0x${value.rightFault.toString(16)}")
        value.message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        VirtualJoystick(onPosition = onJoystick)
        if (value.connection == ConnectionStage.IDLE || value.connection == ConnectionStage.FAILED) {
            Button(onClick = onScan) { Text("扫描并连接") }
        } else Button(onClick = onDisconnect) { Text("断开连接") }
        Button(onClick = onStop) { Text("立即停止") }
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
