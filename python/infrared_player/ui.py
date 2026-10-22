from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QImage, QPixmap
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - optional runtime dependency
    raise RuntimeError("PySide6 is not installed. Please install PySide6.") from exc

from .camera_enumerator import CameraEnumerator
from .capture_controller import CaptureController
from .frame_router import FrameRouter
from .infrared import (
    decode_infrared_payload,
    save_calibration_grid_bin,
    save_ooc_txt,
    save_temp14_bin,
)
from .models import CameraDevice, CameraKind, DisplayState, InfraredFrame


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("红外摄像头播放软件")
        self.resize(1360, 760)

        self.enumerator = CameraEnumerator()
        self.capture = CaptureController()
        self.router = FrameRouter()
        self.display_state = DisplayState()
        self.devices: list[CameraDevice] = []

        self.camera_type_combo = QComboBox()
        self.camera_type_combo.addItems([kind.value for kind in CameraKind])
        self.camera_device_combo = QComboBox()
        self.refresh_button = QPushButton("刷新摄像头")

        self.normal_checkbox = QCheckBox("显示普通画面")
        self.normal_checkbox.setChecked(True)
        self.gray_checkbox = QCheckBox("显示灰度图")
        self.gray_checkbox.setChecked(True)
        self.pseudo_checkbox = QCheckBox("显示伪彩图")
        self.pseudo_checkbox.setChecked(True)

        self.calibration_n_label = QLabel("校准采样 N")
        self.calibration_n_combo = QComboBox()
        self.calibration_n_combo.addItems([str(n) for n in (8, 4, 2)])
        self.calibration_n_combo.setCurrentText("8")

        self.calibrate_button = QPushButton("校准")
        self._pending_calibration = False

        self.capture_button = QPushButton("抓图")
        self._pending_capture = False

        self.grab_button = QPushButton("抓ooc")
        self._pending_grab = False

        self.status_label = QLabel("准备就绪")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.normal_view = self._create_view("普通摄像头画面")
        self.gray_view = self._create_view("红外灰度图")
        self.pseudo_view = self._create_view("红外伪彩图")

        self._build_layout()
        self._connect_signals()
        self._update_controls()
        self.refresh_devices()

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.capture.release()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("摄像头类型"))
        controls.addWidget(self.camera_type_combo)
        controls.addWidget(QLabel("摄像头设备"))
        controls.addWidget(self.camera_device_combo, stretch=1)
        controls.addWidget(self.refresh_button)

        toggles = QHBoxLayout()
        toggles.addWidget(self.normal_checkbox)
        toggles.addWidget(self.gray_checkbox)
        toggles.addWidget(self.pseudo_checkbox)
        toggles.addWidget(self.calibration_n_label)
        toggles.addWidget(self.calibration_n_combo)
        toggles.addWidget(self.calibrate_button)
        toggles.addWidget(self.capture_button)
        toggles.addWidget(self.grab_button)
        toggles.addStretch(1)

        views = QHBoxLayout()
        views.addWidget(self.normal_view, stretch=1)
        views.addWidget(self.gray_view, stretch=1)
        views.addWidget(self.pseudo_view, stretch=1)

        layout = QVBoxLayout(root)
        layout.addLayout(controls)
        layout.addLayout(toggles)
        layout.addLayout(views, stretch=1)
        layout.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.camera_type_combo.currentIndexChanged.connect(self._on_camera_type_changed)
        self.camera_device_combo.currentIndexChanged.connect(self._on_camera_device_changed)
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.normal_checkbox.toggled.connect(self._on_display_state_changed)
        self.gray_checkbox.toggled.connect(self._on_display_state_changed)
        self.pseudo_checkbox.toggled.connect(self._on_display_state_changed)
        self.calibrate_button.clicked.connect(self._on_calibrate)
        self.calibration_n_combo.currentTextChanged.connect(self._on_calibration_n_changed)
        self.capture_button.clicked.connect(self._on_capture)
        self.grab_button.clicked.connect(self._on_grab)

    def _create_view(self, title: str) -> QLabel:
        label = QLabel(title)
        label.setMinimumSize(320, 240)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "QLabel { background: #13161b; color: #d5d9e0; border: 1px solid #39404a; }"
        )
        return label

    def refresh_devices(self) -> None:
        self.devices = self.enumerator.list_devices()
        current_index = self.camera_device_combo.currentIndex()
        self.camera_device_combo.blockSignals(True)
        self.camera_device_combo.clear()
        for device in self.devices:
            self.camera_device_combo.addItem(device.display_name, userData=device)
        self.camera_device_combo.blockSignals(False)

        if not self.devices:
            self.capture.release()
            self._clear_views()
            self.status_label.setText("未检测到摄像头")
            return

        restored = min(max(current_index, 0), len(self.devices) - 1)
        self.camera_device_combo.blockSignals(True)
        self.camera_device_combo.setCurrentIndex(restored)
        self.camera_device_combo.blockSignals(False)
        self._reopen_camera()

    def _on_camera_type_changed(self) -> None:
        self._update_controls()
        self._clear_views()
        self._reopen_camera()

    def _on_camera_device_changed(self) -> None:
        self._clear_views()
        self._reopen_camera()

    def _on_display_state_changed(self) -> None:
        self.display_state = replace(
            self.display_state,
            show_normal=self.normal_checkbox.isChecked(),
            show_gray=self.gray_checkbox.isChecked(),
            show_pseudo=self.pseudo_checkbox.isChecked(),
        )
        self._update_controls()
        self._clear_views()

    def _on_calibrate(self) -> None:
        self._pending_calibration = True
        self.status_label.setText("正在校准，请确保镜头对准均匀温度表面...")

    def _on_calibration_n_changed(self, text: str) -> None:
        processor = self.router.infrared_processor
        processor.calibration_n = int(text)
        processor.calibration_map = None
        self.status_label.setText("校准采样间隔已更改，请重新校准")

    def _on_capture(self) -> None:
        self._pending_capture = True
        self.status_label.setText("正在抓图...")

    def _on_grab(self) -> None:
        self._pending_grab = True
        self.status_label.setText("正在抓取原始数据...")

    def _update_controls(self) -> None:
        kind = self.current_camera_kind()
        is_normal = kind is CameraKind.NORMAL
        self.normal_checkbox.setVisible(is_normal)
        self.gray_checkbox.setVisible(not is_normal)
        self.pseudo_checkbox.setVisible(not is_normal)
        self.normal_view.setVisible(is_normal and self.normal_checkbox.isChecked())
        self.gray_view.setVisible((not is_normal) and self.gray_checkbox.isChecked())
        self.pseudo_view.setVisible((not is_normal) and self.pseudo_checkbox.isChecked())
        self.calibration_n_label.setVisible(not is_normal)
        self.calibration_n_combo.setVisible(not is_normal)
        self.calibrate_button.setVisible(not is_normal)
        self.capture_button.setVisible(not is_normal)
        self.grab_button.setVisible(not is_normal)

    def _reopen_camera(self) -> None:
        device = self.current_device()
        if device is None:
            self.capture.release()
            self.status_label.setText("请选择可用摄像头")
            return

        try:
            self.capture.open(device, self.current_camera_kind())
        except Exception as exc:  # pragma: no cover - runtime error handling
            self.capture.release()
            self.status_label.setText(f"打开摄像头失败: {exc}")
            return

        self.router.infrared_processor.calibration_map = None
        self.status_label.setText(f"已打开: {device.display_name}")

    def _on_timer(self) -> None:
        ok, frame = self.capture.read()
        if not ok or frame is None:
            current = self.capture.current_camera()
            if current is not None:
                self.status_label.setText(f"读取帧失败: {current.display_name}")
            return

        kind = self.current_camera_kind()

        if self._pending_calibration and kind is CameraKind.INFRARED:
            try:
                processor = self.router.infrared_processor
                processor.calibrate(frame)
                data_dir = Path("data")
                data_dir.mkdir(parents=True, exist_ok=True)
                out_path = data_dir / f"grid_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
                save_calibration_grid_bin(processor.calibration_map, processor.calibration_n, out_path)
                self.status_label.setText(f"校准完成，已保存: {out_path}")
            except Exception as exc:
                self.status_label.setText(f"校准失败: {exc}")
            self._pending_calibration = False

        if self._pending_capture and kind is CameraKind.INFRARED:
            try:
                temp14 = self.router.infrared_processor.calibrated_temp14(frame)
                data_dir = Path("data")
                data_dir.mkdir(parents=True, exist_ok=True)
                out_path = data_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
                save_temp14_bin(temp14, out_path)
                self.status_label.setText(f"已保存: {out_path}")
            except Exception as exc:
                self.status_label.setText(f"抓图失败: {exc}")
            self._pending_capture = False

        if self._pending_grab and kind is CameraKind.INFRARED:
            try:
                temp14 = decode_infrared_payload(frame)
                data_dir = Path("data")
                data_dir.mkdir(parents=True, exist_ok=True)
                out_path = data_dir / f"ooc{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                save_ooc_txt(temp14, out_path)
                self.status_label.setText(f"已保存: {out_path}")
            except Exception as exc:
                self.status_label.setText(f"抓取失败: {exc}")
            self._pending_grab = False

        try:
            routed = self.router.route(kind, frame)
        except Exception as exc:
            self.status_label.setText(f"处理帧失败: {exc}")
            self._clear_views()
            return

        if kind is CameraKind.NORMAL:
            if self.normal_checkbox.isChecked():
                self._set_image(self.normal_view, routed["normal_rgb"])
        else:
            infrared: InfraredFrame = routed["infrared"]
            if self.gray_checkbox.isChecked():
                self._set_image(self.gray_view, infrared.gray8)
            if self.pseudo_checkbox.isChecked():
                self._set_image(self.pseudo_view, infrared.pseudo_rgb)

    def current_device(self) -> CameraDevice | None:
        index = self.camera_device_combo.currentIndex()
        if index < 0 or index >= len(self.devices):
            return None
        return self.devices[index]

    def current_camera_kind(self) -> CameraKind:
        return CameraKind(self.camera_type_combo.currentText())

    def _clear_views(self) -> None:
        for label, title in (
            (self.normal_view, "普通摄像头画面"),
            (self.gray_view, "红外灰度图"),
            (self.pseudo_view, "红外伪彩图"),
        ):
            label.setPixmap(QPixmap())
            label.setText(title)

    def _set_image(self, label: QLabel, image: np.ndarray) -> None:
        qimage = _to_qimage(image)
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(scaled)
        label.setText("")


def _to_qimage(image: np.ndarray) -> QImage:
    if image.ndim == 2:
        contiguous = np.ascontiguousarray(image)
        return QImage(
            contiguous.data,
            contiguous.shape[1],
            contiguous.shape[0],
            contiguous.strides[0],
            QImage.Format_Grayscale8,
        ).copy()

    if image.ndim == 3 and image.shape[2] == 3:
        contiguous = np.ascontiguousarray(image)
        return QImage(
            contiguous.data,
            contiguous.shape[1],
            contiguous.shape[0],
            contiguous.strides[0],
            QImage.Format_RGB888,
        ).copy()

    raise ValueError(f"Unsupported image shape: {image.shape}")
