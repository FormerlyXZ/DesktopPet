"""Windows 音频检测——使用 comtypes 访问 Core Audio API"""
from PySide6.QtCore import QTimer, Signal, QObject


class AudioMonitor(QObject):
    """通过 QTimer 轮询 Windows 音频 API，带防抖的边沿触发"""

    audio_playing = Signal()
    audio_stopped = Signal()
    audio_muted = Signal()

    def __init__(self, parent=None, interval_ms: int = 500):
        super().__init__(parent)
        self._prev_playing = False
        self._prev_muted = False
        self._was_playing = False  # 独立标记，仅在 stopped 发出时清除
        self._pMeter = None
        self._pVolume = None

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

        # 防抖
        self._playing_debounce = 0
        self._playing_debounce_threshold = 3
        self._stopped_debounce = 0
        self._stopped_debounce_threshold = 2
        self._prev_volume_zero = False
        self._first_poll = True

        self._init_device()

    # ── COM 接口定义（comtypes vtable 自动布局）──

    @staticmethod
    def _define_interfaces():
        """定义 MMDevice API COM 接口（带缓存）"""
        if hasattr(AudioMonitor, '_iface_cache'):
            return AudioMonitor._iface_cache

        from ctypes import c_float, c_uint, c_int, POINTER
        import comtypes
        from comtypes import GUID, HRESULT, COMMETHOD

        class IAudioMeterInformation(comtypes.IUnknown):
            _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
            _methods_ = [
                COMMETHOD([], HRESULT, 'GetPeakValue', (['out'], POINTER(c_float), 'pfPeak')),
                COMMETHOD([], HRESULT, 'GetMeteringChannelCount', (['out'], POINTER(c_uint), 'pnChannelCount')),
                COMMETHOD([], HRESULT, 'QueryHardwareSupport', (['out'], POINTER(c_uint), 'pdwHardwareSupportMask')),
            ]

        class IAudioEndpointVolume(comtypes.IUnknown):
            _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
            _methods_ = [
                COMMETHOD([], HRESULT, 'RegisterControlChangeNotify', (['in'], POINTER(comtypes.IUnknown), 'pNotify')),
                COMMETHOD([], HRESULT, 'UnregisterControlChangeNotify', (['in'], POINTER(comtypes.IUnknown), 'pNotify')),
                COMMETHOD([], HRESULT, 'GetChannelCount', (['out'], POINTER(c_uint), 'pnChannelCount')),
                COMMETHOD([], HRESULT, 'SetMasterVolumeLevel', (['in'], c_float, 'fLevelDB'), (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'SetMasterVolumeLevelScalar', (['in'], c_float, 'fLevel'), (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'GetMasterVolumeLevel', (['out'], POINTER(c_float), 'pfLevelDB')),
                COMMETHOD([], HRESULT, 'GetMasterVolumeLevelScalar', (['out'], POINTER(c_float), 'pfLevel')),
                COMMETHOD([], HRESULT, 'SetChannelVolumeLevel', (['in'], c_uint, 'nChannel'), (['in'], c_float, 'fLevelDB'), (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'SetChannelVolumeLevelScalar', (['in'], c_uint, 'nChannel'), (['in'], c_float, 'fLevel'), (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'GetChannelVolumeLevel', (['in'], c_uint, 'nChannel'), (['out'], POINTER(c_float), 'pfLevelDB')),
                COMMETHOD([], HRESULT, 'GetChannelVolumeLevelScalar', (['in'], c_uint, 'nChannel'), (['out'], POINTER(c_float), 'pfLevel')),
                COMMETHOD([], HRESULT, 'SetMute', (['in'], c_int, 'bMute'), (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'GetMute', (['out'], POINTER(c_int), 'pbMute')),
                COMMETHOD([], HRESULT, 'GetVolumeStepInfo', (['out'], POINTER(c_uint), 'pnStep'), (['out'], POINTER(c_uint), 'pnStepCount')),
                COMMETHOD([], HRESULT, 'VolumeStepUp', (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'VolumeStepDown', (['in'], POINTER(GUID), 'pguidEventContext')),
                COMMETHOD([], HRESULT, 'QueryHardwareSupport', (['out'], POINTER(c_uint), 'pdwHardwareSupportMask')),
                COMMETHOD([], HRESULT, 'GetVolumeRange', (['out'], POINTER(c_float), 'pflVolumeMindB'), (['out'], POINTER(c_float), 'pflVolumeMaxdB'), (['out'], POINTER(c_float), 'pflVolumeIncrementdB')),
            ]

        class IMMDevice(comtypes.IUnknown):
            _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
            _methods_ = [
                COMMETHOD([], HRESULT, 'Activate', (['in'], POINTER(GUID), 'iid'), (['in'], c_uint, 'dwClsCtx'), (['in'], POINTER(comtypes.IUnknown), 'pActivationParams'), (['out'], POINTER(comtypes.POINTER(comtypes.IUnknown)), 'ppInterface')),
                COMMETHOD([], HRESULT, 'OpenPropertyStore', (['in'], c_uint, 'stgmAccess'), (['out'], POINTER(comtypes.POINTER(comtypes.IUnknown)), 'ppProperties')),
                COMMETHOD([], HRESULT, 'GetId', (['out'], POINTER(comtypes.POINTER(c_uint)), 'ppstrId')),
                COMMETHOD([], HRESULT, 'GetState', (['out'], POINTER(c_uint), 'pdwState')),
            ]

        class IMMDeviceEnumerator(comtypes.IUnknown):
            _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
            _methods_ = [
                COMMETHOD([], HRESULT, 'EnumAudioEndpoints', (['in'], c_uint, 'dataFlow'), (['in'], c_uint, 'dwStateMask'), (['out'], POINTER(comtypes.POINTER(comtypes.IUnknown)), 'ppDevices')),
                COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint', (['in'], c_uint, 'dataFlow'), (['in'], c_uint, 'role'), (['out'], POINTER(comtypes.POINTER(IMMDevice)), 'ppEndpoint')),
                COMMETHOD([], HRESULT, 'GetDevice', (['in'], POINTER(c_uint), 'pwstrId'), (['out'], POINTER(comtypes.POINTER(IMMDevice)), 'ppDevice')),
                COMMETHOD([], HRESULT, 'RegisterEndpointNotificationCallback', (['in'], POINTER(comtypes.IUnknown), 'pClient')),
                COMMETHOD([], HRESULT, 'UnregisterEndpointNotificationCallback', (['in'], POINTER(comtypes.IUnknown), 'pClient')),
            ]

        AudioMonitor._iface_cache = (IAudioMeterInformation, IAudioEndpointVolume, IMMDeviceEnumerator, IMMDevice)
        return AudioMonitor._iface_cache

    def _init_device(self):
        try:
            import comtypes
            IAMInfo, IAEV, IMMDE, IMMD = self._define_interfaces()

            comtypes.CoInitialize()

            # MMDeviceEnumerator 的 CLSID（注意：不是 interface._iid_）
            CLSID_MMDeviceEnumerator = comtypes.GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")

            # 创建 IMMDeviceEnumerator
            pEnum = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator, interface=IMMDE, clsctx=comtypes.CLSCTX_ALL,
            )
            if not pEnum:
                return

            # 获取默认音频设备（comtypes 自动返回 out 参数）
            pDev = pEnum.GetDefaultAudioEndpoint(0, 0)  # eRender, eConsole
            if not pDev:
                return

            # 获取 IAudioMeterInformation（comtypes 自动返回 out 参数）
            pMeter = pDev.Activate(
                comtypes.byref(IAMInfo._iid_), comtypes.CLSCTX_ALL, None,
            )
            if pMeter:
                self._pMeter = pMeter.QueryInterface(IAMInfo)

            # 获取 IAudioEndpointVolume
            pVolume = pDev.Activate(
                comtypes.byref(IAEV._iid_), comtypes.CLSCTX_ALL, None,
            )
            if pVolume:
                self._pVolume = pVolume.QueryInterface(IAEV)

        except Exception:
            import traceback
            traceback.print_exc()

    def start(self):
        self._first_poll = True
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _poll(self):
        playing = self._is_playing()
        muted = self._is_muted()
        vol_zero = self._is_volume_zero()

        if playing:
            self._playing_debounce += 1
            self._stopped_debounce = 0
        else:
            self._playing_debounce = 0
            self._stopped_debounce += 1

        playing_debounced = self._playing_debounce >= self._playing_debounce_threshold
        stopped_debounced = self._stopped_debounce >= self._stopped_debounce_threshold

        if playing_debounced:
            self._was_playing = True

        if not self._first_poll:
            if playing_debounced and not self._prev_playing:
                self.audio_playing.emit()
            if stopped_debounced and self._was_playing and not playing_debounced:
                self.audio_stopped.emit()
                self._was_playing = False
            vol_changed_to_zero = vol_zero and not self._prev_volume_zero
            muted_changed = muted and not self._prev_muted
            if muted_changed or vol_changed_to_zero:
                self.audio_muted.emit()

        self._prev_playing = playing_debounced
        self._prev_muted = muted
        self._prev_volume_zero = vol_zero
        self._first_poll = False

    def _is_playing(self) -> bool:
        if self._pMeter is None:
            return False
        try:
            peak = self._pMeter.GetPeakValue()  # comtypes 直接返回 out 参数
            return peak is not None and peak > 0.01
        except Exception:
            return False

    def _is_muted(self) -> bool:
        if self._pVolume is None:
            return False
        try:
            muted = self._pVolume.GetMute()  # comtypes 直接返回 out 参数
            return muted is not None and muted != 0
        except Exception:
            return False

    def _is_volume_zero(self) -> bool:
        if self._pVolume is None:
            return False
        try:
            vol = self._pVolume.GetMasterVolumeLevelScalar()  # comtypes 直接返回 out 参数
            return vol is not None and vol < 0.005
        except Exception:
            return False
