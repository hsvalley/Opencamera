from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import numpy as np

# 图像尺寸（与 c_model/config.h 保持一致，单一真源）
IR_WIDTH = 260
IR_HEIGHT = 202
IR_UVC_WIDTH = IR_WIDTH * 2
IR_BYTES_PER_LOGICAL_PIXEL = 4

_c_uint8_p = ctypes.POINTER(ctypes.c_uint8)
_c_uint16_p = ctypes.POINTER(ctypes.c_uint16)
_c_int16_p = ctypes.POINTER(ctypes.c_int16)


def _find_dll() -> Path:
    """定位 c_model_bridge.dll：打包时在 _MEIPASS，开发时在 c_bridge/。"""
    meipass = getattr(sys, "_MEIPASS", None)
    candidates: list[Path] = []
    if meipass:
        candidates.append(Path(meipass) / "c_model_bridge.dll")
    candidates.append(Path(__file__).resolve().parents[2] / "c_bridge" / "c_model_bridge.dll")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "未找到 c_model_bridge.dll，请先运行 OpenCamera_c/c_bridge/build_dll.ps1 编译。"
    )


class CBridge:
    """c_model 流水线的 ctypes 封装，帧级接口，内部维护跨帧状态。"""

    def __init__(self) -> None:
        self._lib = ctypes.CDLL(str(_find_dll()))
        self._declare()
        self._lib.bridge_init()

    def _declare(self) -> None:
        lib = self._lib
        lib.bridge_init.argtypes = []
        lib.bridge_init.restype = None

        lib.bridge_set_clip_mode.argtypes = [ctypes.c_int]
        lib.bridge_set_clip_mode.restype = None
        lib.bridge_set_clip_user.argtypes = [ctypes.c_uint16, ctypes.c_uint16]
        lib.bridge_set_clip_user.restype = None
        lib.bridge_set_clip_dynamic.argtypes = [ctypes.c_uint8, ctypes.c_uint16]
        lib.bridge_set_clip_dynamic.restype = None
        lib.bridge_set_hist_reverse.argtypes = [ctypes.c_uint8]
        lib.bridge_set_hist_reverse.restype = None
        lib.bridge_set_filter_mode.argtypes = [ctypes.c_int]
        lib.bridge_set_filter_mode.restype = None
        lib.bridge_set_clip_calc_mode.argtypes = [ctypes.c_int]
        lib.bridge_set_clip_calc_mode.restype = None

        lib.bridge_set_lut.argtypes = [_c_uint8_p, _c_uint8_p, _c_uint8_p]
        lib.bridge_set_lut.restype = None

        lib.bridge_decode.argtypes = [_c_uint8_p, ctypes.c_uint32, _c_uint16_p]
        lib.bridge_decode.restype = ctypes.c_uint32

        lib.bridge_process.argtypes = [
            _c_uint8_p,
            ctypes.c_uint32,
            _c_int16_p,
            _c_uint16_p,
            _c_uint8_p,
            _c_uint8_p,
            _c_uint16_p,
            _c_uint16_p,
        ]
        lib.bridge_process.restype = ctypes.c_int

    @staticmethod
    def _flatten(frame: np.ndarray) -> tuple[ctypes.POINTER(ctypes.c_uint8), int]:
        """把任意 cv2 帧视图展平为原始字节流指针，与 Python decode 一致。"""
        payload = np.ascontiguousarray(frame).view(np.uint8).reshape(-1)
        return payload.ctypes.data_as(_c_uint8_p), payload.size

    def decode(self, frame: np.ndarray) -> np.ndarray:
        """模块 1 采样：原始帧 -> 紧凑 14-bit 温度图 (IR_HEIGHT, IR_WIDTH)。"""
        payload = np.ascontiguousarray(frame).view(np.uint8).reshape(-1)
        temp14 = np.empty((IR_HEIGHT, IR_WIDTH), dtype=np.uint16)
        n = self._lib.bridge_decode(
            payload.ctypes.data_as(_c_uint8_p),
            payload.size,
            temp14.ctypes.data_as(_c_uint16_p),
        )
        if n != IR_WIDTH * IR_HEIGHT:
            raise ValueError(f"采样输出 {n} 像素，期望 {IR_WIDTH * IR_HEIGHT}")
        return temp14

    def process(
        self, frame: np.ndarray, calib_map: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
        """完整流水线，返回 (temp14, gray8, rgb, min, max)。"""
        payload = np.ascontiguousarray(frame).view(np.uint8).reshape(-1)
        temp14 = np.empty((IR_HEIGHT, IR_WIDTH), dtype=np.uint16)
        gray8 = np.empty((IR_HEIGHT, IR_WIDTH), dtype=np.uint8)
        rgb = np.empty((IR_HEIGHT, IR_WIDTH, 3), dtype=np.uint8)

        calib_ptr = None
        if calib_map is not None:
            calib_ptr = np.ascontiguousarray(calib_map, dtype=np.int16).ctypes.data_as(_c_int16_p)

        min_out = ctypes.c_uint16()
        max_out = ctypes.c_uint16()
        rc = self._lib.bridge_process(
            payload.ctypes.data_as(_c_uint8_p),
            payload.size,
            calib_ptr,
            temp14.ctypes.data_as(_c_uint16_p),
            gray8.ctypes.data_as(_c_uint8_p),
            rgb.ctypes.data_as(_c_uint8_p),
            ctypes.byref(min_out),
            ctypes.byref(max_out),
        )
        if rc != 0:
            raise ValueError("C 流水线处理失败：输入字节流尺寸不足")
        return temp14, gray8, rgb, int(min_out.value), int(max_out.value)

    def set_clip_user(self, mn: int, mx: int) -> None:
        self._lib.bridge_set_clip_user(mn, mx)

    def set_clip_dynamic(self, n_frames: int, step: int) -> None:
        self._lib.bridge_set_clip_dynamic(n_frames, step)

    def set_hist_reverse(self, reverse: bool) -> None:
        self._lib.bridge_set_hist_reverse(1 if reverse else 0)

    def set_filter_mode(self, mode: int) -> None:
        """滤波方式：0=高斯，1=中值。"""
        self._lib.bridge_set_filter_mode(mode)

    def set_clip_calc_mode(self, mode: int) -> None:
        """极值截取计算方式：0=滑动窗口平均，1=低通。"""
        self._lib.bridge_set_clip_calc_mode(mode)

    def set_lut(self, r: np.ndarray, g: np.ndarray, b: np.ndarray) -> None:
        self._lib.bridge_set_lut(
            np.ascontiguousarray(r, dtype=np.uint8).ctypes.data_as(_c_uint8_p),
            np.ascontiguousarray(g, dtype=np.uint8).ctypes.data_as(_c_uint8_p),
            np.ascontiguousarray(b, dtype=np.uint8).ctypes.data_as(_c_uint8_p),
        )
