package com.example.canmotor.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.ParcelUuid
import android.os.Build
import com.example.canmotor.protocol.BleProtocol
import java.util.UUID

/** Thin Android API adapter; callbacks are forwarded by the owning service. */
@SuppressLint("MissingPermission")
class AndroidBleTransport(
    context: Context,
    private val scanCallback: android.bluetooth.le.ScanCallback,
    private val gattCallback: android.bluetooth.BluetoothGattCallback,
) : GattTransport {
    private val adapter: BluetoothAdapter =
        context.getSystemService(BluetoothManager::class.java).adapter
    private val scanner get() = requireNotNull(adapter.bluetoothLeScanner) {
        "Bluetooth LE scanner unavailable"
    }
    private val appContext = context.applicationContext
    private var gatt: BluetoothGatt? = null

    override fun startFilteredScan(serviceUuid: UUID) {
        scanner.startScan(
            listOf(ScanFilter.Builder().setServiceUuid(ParcelUuid(serviceUuid)).build()),
            ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(),
            scanCallback)
    }
    override fun stopScan() = scanner.stopScan(scanCallback)
    override fun connect(address: String) {
        gatt?.close()
        gatt = adapter.getRemoteDevice(address).connectGatt(appContext, false, gattCallback,
            android.bluetooth.BluetoothDevice.TRANSPORT_LE)
    }
    override fun discoverServices() { gatt?.discoverServices() }
    override fun readCharacteristic(uuid: UUID) { characteristic(uuid)?.let { gatt?.readCharacteristic(it) } }
    override fun enableNotifications(uuid: UUID) {
        val characteristic = characteristic(uuid) ?: return
        gatt?.setCharacteristicNotification(characteristic, true)
        val cccd = characteristic.getDescriptor(UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")) ?: return
        val currentGatt = gatt ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            currentGatt.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
        } else {
            @Suppress("DEPRECATION")
            cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            @Suppress("DEPRECATION")
            currentGatt.writeDescriptor(cccd)
        }
    }
    override fun writeWithoutResponse(uuid: UUID, value: ByteArray): Boolean {
        val characteristic = characteristic(uuid) ?: return false
        val currentGatt = gatt ?: return false
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            currentGatt.writeCharacteristic(characteristic, value,
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE) == BluetoothStatusCodes.SUCCESS
        } else {
            @Suppress("DEPRECATION")
            characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            @Suppress("DEPRECATION")
            characteristic.value = value
            @Suppress("DEPRECATION")
            currentGatt.writeCharacteristic(characteristic)
        }
    }
    override fun disconnect() { gatt?.disconnect(); gatt?.close(); gatt = null }
    private fun characteristic(uuid: UUID) =
        gatt?.getService(BleProtocol.SERVICE_UUID)?.getCharacteristic(uuid)
}
