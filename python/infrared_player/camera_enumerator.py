from __future__ import annotations

import json
import subprocess
from typing import Iterable

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    cv2 = None

from .models import CameraDevice


class CameraEnumerator:
    def __init__(self, max_indices: int = 10) -> None:
        self.max_indices = max_indices

    def list_devices(self) -> list[CameraDevice]:
        indices = self._probe_camera_indices()
        names = self._read_windows_camera_names()
        devices: list[CameraDevice] = []
        for position, camera_index in enumerate(indices):
            fallback = f"Camera {camera_index}"
            display_name = names[position] if position < len(names) else fallback
            devices.append(
                CameraDevice(
                    display_name=display_name,
                    camera_index=camera_index,
                    backend_hint="CAP_MSMF",
                )
            )
        return devices

    def _probe_camera_indices(self) -> list[int]:
        if cv2 is None:
            return []

        api_preference = getattr(cv2, "CAP_MSMF", 0)
        indices: list[int] = []
        for index in range(self.max_indices):
            cap = cv2.VideoCapture(index, api_preference)
            try:
                if cap.isOpened():
                    indices.append(index)
            finally:
                cap.release()
        return indices

    def _read_windows_camera_names(self) -> list[str]:
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                "$devices = Get-CimInstance Win32_PnPEntity | "
                "Where-Object { $_.PNPClass -in @('Camera','Image') -and $_.Name } | "
                "Select-Object -ExpandProperty Name; "
                "$devices | ConvertTo-Json -Compress"
            ),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return []

        output = completed.stdout.strip()
        if not output:
            return []
        try:
            decoded = json.loads(output)
        except json.JSONDecodeError:
            return []

        if isinstance(decoded, str):
            return [decoded]
        if isinstance(decoded, list):
            return _unique_names(name for name in decoded if isinstance(name, str))
        return []


def _unique_names(names: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result
