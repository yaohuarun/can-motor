"""厂商 ControlCAN Windows DLL / Linux SO 的 ctypes 适配层。"""
import ctypes as C
import os
import platform
from pathlib import Path
import time


def library_path(dll_path=None):
    if dll_path:
        return Path(dll_path).expanduser().resolve(strict=True)
    root = Path(__file__).parent / 'libs'
    bits = C.sizeof(C.c_void_p) * 8
    if platform.system() == 'Windows':
        path = root / ('x64' if bits == 64 else 'x86') / 'ControlCAN.dll'
    elif platform.system() == 'Linux':
        machine = platform.machine().lower()
        if machine in ('x86_64', 'amd64', 'i386', 'i686', 'x86'):
            arch = 'x86_64' if bits == 64 else 'x86'
        elif machine in ('aarch64', 'arm64') or machine.startswith('arm'):
            arch = 'aarch64' if bits == 64 else 'arm'
        else:
            raise RuntimeError(f'无内置Linux库匹配架构{machine}，请用--library指定厂商SO')
        path = root / 'linux' / arch / 'libcontrolcan.so'
    else:
        raise RuntimeError('厂商后端仅支持Windows和Linux')
    return path.resolve(strict=True)


class CanObject(C.Structure):
    _fields_ = [('ID', C.c_uint32), ('TimeStamp', C.c_uint32),
                ('TimeFlag', C.c_uint8), ('SendType', C.c_uint8),
                ('RemoteFlag', C.c_uint8), ('ExternFlag', C.c_uint8),
                ('DataLen', C.c_uint8), ('Data', C.c_uint8 * 8),
                ('Reserved', C.c_uint8 * 3)]


class InitConfig(C.Structure):
    _fields_ = [('AccCode', C.c_uint32), ('AccMask', C.c_uint32),
                ('Reserved', C.c_uint32), ('Filter', C.c_uint8),
                ('Timing0', C.c_uint8), ('Timing1', C.c_uint8), ('Mode', C.c_uint8)]


class ControlCanBus:
    def __init__(self, channel=0, device=0, dll_path=None):
        path = library_path(dll_path)
        self._dll_dir = None
        self._opened = False
        self.channel, self.device = channel, device
        try:
            if platform.system() == 'Windows':
                self._dll_dir = os.add_dll_directory(str(path.parent))
                self.dll = C.WinDLL(str(path))
            else:
                self.dll = C.CDLL(str(path))
            u = C.c_uint32
            signatures = {
                'VCI_OpenDevice': [u, u, u], 'VCI_CloseDevice': [u, u],
                'VCI_InitCAN': [u, u, u, C.POINTER(InitConfig)],
                'VCI_StartCAN': [u, u, u], 'VCI_ResetCAN': [u, u, u],
                'VCI_Transmit': [u, u, u, C.POINTER(CanObject), u],
                'VCI_Receive': [u, u, u, C.POINTER(CanObject), u, C.c_int32],
            }
            for name, args in signatures.items():
                fn = getattr(self.dll, name)
                fn.argtypes, fn.restype = args, u
            self._check(self.dll.VCI_OpenDevice(4, device, 0), 'OpenDevice')
            self._opened = True
            config = InitConfig(0, 0xFFFFFFFF, 0, 1, 0x00, 0x1C, 0)
            self._check(self.dll.VCI_InitCAN(4, device, channel, C.byref(config)), 'InitCAN')
            self._check(self.dll.VCI_StartCAN(4, device, channel), 'StartCAN')
        except Exception:
            self.shutdown()
            raise

    @staticmethod
    def _check(result, operation):
        if result != 1:
            raise RuntimeError(f'ControlCAN {operation}失败，返回0x{result:08X}；'
                               '检查厂商USB驱动、接线和其他程序占用')

    def send(self, msg, timeout=None):
        if msg.dlc > 8:
            raise ValueError('仅支持Classic CAN，DLC最大8')
        obj = CanObject()
        obj.ID, obj.DataLen = msg.arbitration_id, msg.dlc
        obj.ExternFlag, obj.RemoteFlag = msg.is_extended_id, msg.is_remote_frame
        obj.SendType = 0  # 正常发送，非自收自发
        obj.Data[:len(msg.data)] = msg.data
        self._check(self.dll.VCI_Transmit(4, self.device, self.channel, C.byref(obj), 1),
                    'Transmit')
        # 此API没有逐次发送超时参数；返回1也不能替代电机反馈确认。

    def recv(self, timeout=None):
        import can
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            obj = CanObject()
            count = self.dll.VCI_Receive(4, self.device, self.channel, C.byref(obj), 1, 0)
            if count == 0xFFFFFFFF:
                raise RuntimeError('ControlCAN Receive失败')
            if count == 1:
                if obj.DataLen > 8:
                    raise RuntimeError('ControlCAN收到非法DLC')
                return can.Message(arbitration_id=obj.ID, data=bytes(obj.Data[:obj.DataLen]),
                                   dlc=obj.DataLen, is_extended_id=bool(obj.ExternFlag),
                                   is_remote_frame=bool(obj.RemoteFlag), channel=self.channel)
            if count != 0:
                raise RuntimeError(f'ControlCAN Receive返回异常数量{count}')
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.001)

    def shutdown(self):
        try:
            if self._opened:
                self._opened = False
                try:
                    self.dll.VCI_ResetCAN(4, self.device, self.channel)
                finally:
                    self.dll.VCI_CloseDevice(4, self.device)
        finally:
            if self._dll_dir is not None:
                self._dll_dir.close()
                self._dll_dir = None


def open_bus(backend, channel, device, dll_path=None):
    if backend == 'controlcan':
        return ControlCanBus(channel, device, dll_path)
    import can
    from motor_control import prepare_usb_backend
    prepare_usb_backend()
    return can.Bus(interface='canalystii', channel=channel, device=device,
                   bitrate=500000, ignore_config=True)
