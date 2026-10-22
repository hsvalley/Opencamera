from __future__ import annotations

from pathlib import Path

import numpy as np

from .c_bridge import (
    CBridge,
    IR_BYTES_PER_LOGICAL_PIXEL,
    IR_HEIGHT,
    IR_UVC_WIDTH,
    IR_WIDTH,
)
from .models import InfraredFrame

# 图像尺寸常量从 c_bridge 导入（与 c_model/config.h 一致），此处再导出以保持
# 原有 `from .infrared import IR_*` 的导入方式不变。
__all__ = [
    "IR_WIDTH",
    "IR_HEIGHT",
    "IR_UVC_WIDTH",
    "IR_BYTES_PER_LOGICAL_PIXEL",
    "InfraredProcessor",
    "decode_infrared_payload",
    "save_temp14_bin",
    "bgr_to_rgb",
]


class InfraredProcessor:
    """红外处理：中间计算全部委托给 c_model（经 CBridge），跨帧状态在 C 内保持。"""

    def __init__(self) -> None:
        self.calibration_map: np.ndarray | None = None
        self._bridge = CBridge()
        lut = _load_gray2rgb_lut()
        if lut is not None:
            self._bridge.set_lut(*lut)

    def calibrate(self, frame: np.ndarray) -> None:
        """从当前原始帧计算校准误差图（各像素与均值的差，int16）。"""
        temp14 = self._bridge.decode(frame)
        mean = int(round(float(temp14.mean())))
        self.calibration_map = (temp14.astype(np.int32) - mean).astype(np.int16)

    def calibrated_temp14(self, frame: np.ndarray) -> np.ndarray:
        """返回校准后（未滤波）的 14-bit 原始温度数据。"""
        temp14 = self._bridge.decode(frame)
        if self.calibration_map is not None:
            temp14 = _apply_calibration(temp14, self.calibration_map)
        return temp14

    def process(self, frame: np.ndarray) -> InfraredFrame:
        temp14, gray8, pseudo_rgb, clip_min, clip_max = self._bridge.process(
            frame, self.calibration_map
        )
        return InfraredFrame(
            temp14=temp14,
            gray8=gray8,
            pseudo_rgb=pseudo_rgb,
            clip_min=clip_min,
            clip_max=clip_max,
        )

    def set_filter_mode(self, mode: int) -> None:
        """滤波方式：0=高斯，1=中值。"""
        self._bridge.set_filter_mode(mode)

    def set_clip_calc_mode(self, mode: int) -> None:
        """极值截取计算方式：0=滑动窗口平均，1=低通。"""
        self._bridge.set_clip_calc_mode(mode)

    def set_hist_reverse(self, reverse: bool) -> None:
        self._bridge.set_hist_reverse(reverse)


def decode_infrared_payload(frame: np.ndarray) -> np.ndarray:
    """Python 参考实现：从原始字节流重建 14-bit 温度图（202 行，与 c_model 采样一致）。

    生产路径走 CBridge.decode（C sampling_run），此函数仅用于测试比对与参考。
    """
    payload = np.ascontiguousarray(frame).view(np.uint8).reshape(-1)
    expected_size = IR_WIDTH * IR_HEIGHT * IR_BYTES_PER_LOGICAL_PIXEL
    if payload.size != expected_size:
        raise ValueError(
            f"Unexpected infrared payload size: {payload.size}, expected {expected_size}"
        )

    pixels = payload.reshape(IR_HEIGHT, IR_WIDTH, IR_BYTES_PER_LOGICAL_PIXEL)
    nibbles = pixels >> 4
    value16 = (
        (nibbles[:, :, 0].astype(np.uint16) << 12)
        | (nibbles[:, :, 1].astype(np.uint16) << 8)
        | (nibbles[:, :, 2].astype(np.uint16) << 4)
        | nibbles[:, :, 3].astype(np.uint16)
    )
    return value16 & 0x3FFF


def _apply_calibration(temp14: np.ndarray, calibration_map: np.ndarray) -> np.ndarray:
    """用校准误差图校正原始温度数据（与 C bridge 内 int16 减法一致）。"""
    corrected = temp14.astype(np.int32) - calibration_map.astype(np.int32)
    return np.clip(corrected, 0, 0x3FFF).astype(np.uint16)


def save_temp14_bin(temp14: np.ndarray, path: Path) -> None:
    """将 14-bit 温度数据导出为大端序 .bin（每像素 2 字节，高位在前）。"""
    if temp14.dtype != np.uint16:
        temp14 = temp14.astype(np.uint16)
    path.write_bytes(temp14.astype(">u2").tobytes())


def _load_gray2rgb_lut() -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """加载当前工作目录下的 gray2rgb.txt 作为伪彩色查找表（R/G/B 三列）。"""
    lut_path = Path.cwd() / "gray2rgb.txt"
    if not lut_path.is_file():
        return None

    try:
        data = np.loadtxt(lut_path, delimiter=",", skiprows=1, dtype=np.uint8)
    except Exception:
        return None

    if data.ndim != 2 or data.shape != (256, 4):
        return None
    if not np.array_equal(data[:, 0], np.arange(256, dtype=np.uint8)):
        return None

    return data[:, 1], data[:, 2], data[:, 3]


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"Expected BGR frame, got shape {frame.shape}")
    return frame[:, :, ::-1].copy()
