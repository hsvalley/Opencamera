from __future__ import annotations

from typing import Optional

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    cv2 = None

from .infrared import IR_HEIGHT, IR_UVC_WIDTH
from .models import CameraDevice, CameraKind


class CaptureController:
    def __init__(self) -> None:
        self._cap = None
        self._camera: Optional[CameraDevice] = None
        self._kind: CameraKind = CameraKind.NORMAL

    def open(self, camera: CameraDevice, kind: CameraKind) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is not installed. Please install opencv-python.")

        self.release()
        api_preference = getattr(cv2, camera.backend_hint, cv2.CAP_ANY) if camera.backend_hint else cv2.CAP_ANY
        cap = cv2.VideoCapture(camera.camera_index, api_preference)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Unable to open camera {camera.display_name}")

        if kind is CameraKind.INFRARED:
            self._configure_infrared_capture(cap)

        self._cap = cap
        self._camera = camera
        self._kind = kind

    def read(self):
        if self._cap is None:
            return False, None
        return self._cap.read()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap = None
        self._camera = None

    def current_camera(self) -> Optional[CameraDevice]:
        return self._camera

    @staticmethod
    def _configure_infrared_capture(cap) -> None:
        if cv2 is None:
            return
        if hasattr(cv2, "CAP_PROP_CONVERT_RGB"):
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        if hasattr(cv2, "CAP_PROP_FRAME_WIDTH"):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, IR_UVC_WIDTH)
        if hasattr(cv2, "CAP_PROP_FRAME_HEIGHT"):
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, IR_HEIGHT)
        if hasattr(cv2, "CAP_PROP_FOURCC"):
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUY2"))
