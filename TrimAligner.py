"""
TrimAligner — Maya UV strip / trim-sheet aligner.

Copyright (C) 2026 Trey McNair

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Install: put this folder on PYTHONPATH (or sys.path), then:
    import TrimAligner
    TrimAligner.show()

Presets are stored in trim_aligner_presets.json next to this script.
"""
from __future__ import absolute_import, print_function

import json
import math
import os

import maya.cmds as cmds
import maya.OpenMayaUI as omui

# -----------------------------------------------------------------------------
# Qt (Maya 2022–2024: PySide2 / Maya 2025+: PySide6)
# -----------------------------------------------------------------------------
try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance

__version__ = "2.7"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRESETS_PATH = os.path.join(_SCRIPT_DIR, "trim_aligner_presets.json")

_DEFAULT_PRESETS = {
    "active": "Default 2048",
    "presets": {
        "Default 2048": {
            "texture_size": 2048,
            "strip_pixel_heights": [32, 32, 64, 128, 256, 512, 1024],
        },
        "Default 4096": {
            "texture_size": 4096,
            "strip_pixel_heights": [64, 64, 128, 256, 512, 1024, 2048],
        },
    },
}


# -----------------------------------------------------------------------------
# Preset / strip config (JSON next to this .py)
# -----------------------------------------------------------------------------
class StripConfig(object):
    """Active trim-sheet layout derived from the selected preset."""

    def __init__(self, texture_size=2048, strip_pixel_heights=None):
        self.texture_size = int(texture_size)
        heights = strip_pixel_heights or [32, 32, 64, 128, 256, 512, 1024]
        self.strip_pixel_heights = [int(h) for h in heights]
        self._rebuild()

    def _rebuild(self):
        size = float(self.texture_size) if self.texture_size else 1.0
        self.strip_uv_heights = [h / size for h in self.strip_pixel_heights]
        self.strip_y_positions = [
            sum(self.strip_uv_heights[i + 1 :]) for i in range(len(self.strip_uv_heights))
        ]

    def copy(self):
        return StripConfig(self.texture_size, list(self.strip_pixel_heights))


class PresetStore(object):
    """Load/save named presets from trim_aligner_presets.json beside this script."""

    def __init__(self, path=_PRESETS_PATH):
        self.path = path
        self.active = "Default 2048"
        self.presets = {}
        self.load()

    def load(self):
        data = None
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
            except Exception as e:
                cmds.warning("[TrimAligner] Failed to read presets: {}".format(e))
        if not isinstance(data, dict) or not data.get("presets"):
            data = json.loads(json.dumps(_DEFAULT_PRESETS))
        self.presets = {}
        for name, preset in (data.get("presets") or {}).items():
            if not isinstance(preset, dict):
                continue
            try:
                self.presets[name] = StripConfig(
                    preset.get("texture_size", 2048),
                    preset.get("strip_pixel_heights"),
                )
            except Exception:
                continue
        if not self.presets:
            self.presets = {
                k: StripConfig(v["texture_size"], v["strip_pixel_heights"])
                for k, v in _DEFAULT_PRESETS["presets"].items()
            }
        self.active = data.get("active") or next(iter(self.presets))
        if self.active not in self.presets:
            self.active = next(iter(self.presets))

    def save(self):
        payload = {
            "active": self.active,
            "presets": {
                name: {
                    "texture_size": cfg.texture_size,
                    "strip_pixel_heights": list(cfg.strip_pixel_heights),
                }
                for name, cfg in self.presets.items()
            },
        }
        try:
            with open(self.path, "w") as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
            return True
        except Exception as e:
            cmds.warning("[TrimAligner] Failed to save presets: {}".format(e))
            return False

    def get_active(self):
        return self.presets[self.active]

    def set_active(self, name):
        if name in self.presets:
            self.active = name
            return True
        return False

    def upsert(self, name, config):
        self.presets[name] = config.copy()
        self.active = name

    def delete(self, name):
        if name not in self.presets or len(self.presets) <= 1:
            return False
        del self.presets[name]
        if self.active == name:
            self.active = next(iter(self.presets))
        return True

    def names(self):
        return sorted(self.presets.keys())


_store = PresetStore()


def get_config():
    return _store.get_active()


def reload_presets():
    _store.load()
    return _store.get_active()


# -----------------------------------------------------------------------------
# UV helpers
# -----------------------------------------------------------------------------
def get_selected_uv_shells():
    uv_shells = []
    sel = cmds.ls(selection=True, flatten=True)
    if not sel:
        return uv_shells
    uv_sel = cmds.polyListComponentConversion(sel, toUV=True)
    uv_sel = cmds.filterExpand(uv_sel, sm=35)
    if not uv_sel:
        return uv_shells
    cmds.select(clear=True)
    visited = set()
    for uv in uv_sel:
        if uv in visited:
            continue
        cmds.select(uv)
        cmds.polySelectConstraint(m=2, type=0x0010, shell=True)
        shell_uvs = cmds.ls(selection=True, flatten=True)
        cmds.polySelectConstraint(disable=True)
        if shell_uvs:
            shell_uvs = list(set(shell_uvs) & set(uv_sel))
            if shell_uvs:
                uv_shells.append(shell_uvs)
                visited.update(shell_uvs)
    return uv_shells


def get_uv_bbox(uvs):
    coords = [cmds.polyEditUV(u, q=True) for u in uvs]
    us, vs = zip(*coords)
    return min(us), max(us), min(vs), max(vs)


def best_fit_strip(v_height, config=None):
    config = config or get_config()
    heights = config.strip_uv_heights
    return min(range(len(heights)), key=lambda i: abs(v_height - heights[i]))


def align_uv_shell(uvs, strip_index, offset_u=0.0, config=None):
    config = config or get_config()
    umin, umax, vmin, vmax = get_uv_bbox(uvs)
    current_height = vmax - vmin
    if current_height <= 0:
        return
    target_height = config.strip_uv_heights[strip_index]
    scale = target_height / current_height
    center_u = (umin + umax) / 2.0
    center_v = (vmin + vmax) / 2.0
    cmds.polyEditUV(uvs, scaleU=scale, scaleV=scale, pivotU=center_u, pivotV=center_v)
    umin, _, vmin, _ = get_uv_bbox(uvs)
    cmds.polyEditUV(
        uvs,
        u=-1.0 - umin + offset_u,
        v=config.strip_y_positions[strip_index] - vmin,
    )


def with_undo(func):
    def wrapper(*args, **kwargs):
        cmds.undoInfo(openChunk=True)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)

    return wrapper


@with_undo
def auto_align_uvs():
    config = get_config()
    shells = get_selected_uv_shells()
    if not shells:
        return
    for shell in shells:
        _, _, vmin, vmax = get_uv_bbox(shell)
        strip_index = best_fit_strip(vmax - vmin, config)
        align_uv_shell(shell, strip_index, config=config)
    cmds.select([uv for shell in shells for uv in shell], r=True)


@with_undo
def shift_strip(up=True):
    config = get_config()
    shells = get_selected_uv_shells()
    if not shells:
        return
    last = len(config.strip_uv_heights) - 1
    for shell in shells:
        _, _, vmin, vmax = get_uv_bbox(shell)
        index = best_fit_strip(vmax - vmin, config)
        new_index = max(0, index - 1) if up else min(last, index + 1)
        if new_index != index:
            align_uv_shell(shell, new_index, config=config)
    cmds.select([uv for shell in shells for uv in shell], r=True)


@with_undo
def smart_pack_strips(padding=0.01):
    config = get_config()
    shells = get_selected_uv_shells()
    if not shells:
        return
    buckets = {i: [] for i in range(len(config.strip_uv_heights))}
    for shell in shells:
        _, _, vmin, vmax = get_uv_bbox(shell)
        index = best_fit_strip(vmax - vmin, config)
        buckets[index].append(shell)
    for index, group in buckets.items():
        u_offset = 0.0
        for shell in group:
            umin, umax, _, _ = get_uv_bbox(shell)
            width = umax - umin
            align_uv_shell(shell, index, offset_u=u_offset, config=config)
            u_offset += width + padding
    cmds.select([uv for shell in shells for uv in shell], r=True)


def rotate_uvs(uvs, angle_deg, pivot_u, pivot_v):
    angle_rad = math.radians(angle_deg)
    cos_theta = math.cos(angle_rad)
    sin_theta = math.sin(angle_rad)
    for uv in uvs:
        u, v = cmds.polyEditUV(uv, q=True)
        du = u - pivot_u
        dv = v - pivot_v
        u_rot = du * cos_theta - dv * sin_theta + pivot_u
        v_rot = du * sin_theta + dv * cos_theta + pivot_v
        cmds.polyEditUV(uv, u=u_rot - u, v=v_rot - v)


@with_undo
def rotate_to_best_fit():
    shells = get_selected_uv_shells()
    if not shells:
        return
    for shell in shells:
        best_angle = 0
        min_height = float("inf")
        umin, umax, vmin, vmax = get_uv_bbox(shell)
        pivot_u = (umin + umax) / 2.0
        pivot_v = (vmin + vmax) / 2.0
        original = {uv: cmds.polyEditUV(uv, q=True) for uv in shell}

        def _restore():
            for uv, (u, v) in original.items():
                cu, cv = cmds.polyEditUV(uv, q=True)
                cmds.polyEditUV(uv, u=u - cu, v=v - cv)

        for angle in range(0, 180, 10):
            _restore()
            rotate_uvs(shell, angle, pivot_u, pivot_v)
            _, _, vmin_t, vmax_t = get_uv_bbox(shell)
            height = vmax_t - vmin_t
            if height < min_height:
                min_height = height
                best_angle = angle
        for angle in range(best_angle - 5, best_angle + 6):
            if angle < 0 or angle >= 180:
                continue
            _restore()
            rotate_uvs(shell, angle, pivot_u, pivot_v)
            _, _, vmin_t, vmax_t = get_uv_bbox(shell)
            height = vmax_t - vmin_t
            if height < min_height:
                min_height = height
                best_angle = angle
        _restore()
        rotate_uvs(shell, best_angle, pivot_u, pivot_v)
    cmds.select([uv for shell in shells for uv in shell], r=True)


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def get_maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def _parse_heights(text):
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise ValueError("Enter at least one strip height in pixels.")
    heights = [int(p) for p in parts]
    if any(h <= 0 for h in heights):
        raise ValueError("Strip heights must be positive integers.")
    return heights


class PresetSettingsDialog(QtWidgets.QDialog):
    """Edit texture size + strip heights; save/load named presets from JSON."""

    def __init__(self, parent=None):
        super(PresetSettingsDialog, self).__init__(parent or get_maya_main_window())
        self.setWindowTitle("TrimAligner — Strip Config")
        self.setMinimumWidth(360)
        self._building = False
        self._build_ui()
        self._refresh_preset_list()
        self._load_active_into_form()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("Preset:"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_picked)
        preset_row.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_row)

        form = QtWidgets.QFormLayout()
        self.texture_size = QtWidgets.QSpinBox()
        self.texture_size.setRange(16, 16384)
        self.texture_size.setSingleStep(256)
        form.addRow("Texture size (px):", self.texture_size)

        self.heights_edit = QtWidgets.QLineEdit()
        self.heights_edit.setPlaceholderText("32, 32, 64, 128, 256, 512, 1024")
        form.addRow("Strip heights (top → bottom):", self.heights_edit)
        layout.addLayout(form)

        hint = QtWidgets.QLabel(
            "Heights are pixels on the trim sheet. Sum should usually equal texture size.\n"
            "Saved to: {}".format(os.path.basename(_PRESETS_PATH))
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        self.sum_label = QtWidgets.QLabel("")
        layout.addWidget(self.sum_label)
        self.heights_edit.textChanged.connect(self._update_sum)
        self.texture_size.valueChanged.connect(self._update_sum)

        btn_row = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Save")
        save_as_btn = QtWidgets.QPushButton("Save As…")
        delete_btn = QtWidgets.QPushButton("Delete")
        save_btn.clicked.connect(self._save_current)
        save_as_btn.clicked.connect(self._save_as)
        delete_btn.clicked.connect(self._delete_current)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(save_as_btn)
        btn_row.addWidget(delete_btn)
        layout.addLayout(btn_row)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        apply_btn = QtWidgets.QPushButton("Apply & Close")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        apply_btn.clicked.connect(self._apply_and_close)
        cancel_btn.clicked.connect(self.reject)
        close_row.addWidget(cancel_btn)
        close_row.addWidget(apply_btn)
        layout.addLayout(close_row)

    def _refresh_preset_list(self, select_name=None):
        self._building = True
        self.preset_combo.clear()
        names = _store.names()
        self.preset_combo.addItems(names)
        name = select_name or _store.active
        idx = self.preset_combo.findText(name)
        if idx < 0:
            idx = 0
        self.preset_combo.setCurrentIndex(idx)
        self._building = False

    def _load_active_into_form(self):
        cfg = _store.get_active()
        self.texture_size.setValue(cfg.texture_size)
        self.heights_edit.setText(", ".join(str(h) for h in cfg.strip_pixel_heights))
        self._update_sum()

    def _on_preset_picked(self, _index):
        if self._building:
            return
        name = self.preset_combo.currentText()
        if _store.set_active(name):
            self._load_active_into_form()

    def _config_from_form(self):
        heights = _parse_heights(self.heights_edit.text())
        return StripConfig(self.texture_size.value(), heights)

    def _update_sum(self):
        try:
            heights = _parse_heights(self.heights_edit.text())
            total = sum(heights)
            size = self.texture_size.value()
            note = "OK" if total == size else "differs from texture size"
            self.sum_label.setText("Strip sum: {} px ({})".format(total, note))
        except Exception:
            self.sum_label.setText("Strip sum: —")

    def _save_current(self):
        try:
            cfg = self._config_from_form()
        except ValueError as e:
            cmds.warning("[TrimAligner] {}".format(e))
            return
        name = self.preset_combo.currentText() or _store.active
        _store.upsert(name, cfg)
        if _store.save():
            self._refresh_preset_list(name)
            self._load_active_into_form()

    def _save_as(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Preset As", "Preset name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            cmds.warning("[TrimAligner] Preset name cannot be empty.")
            return
        try:
            cfg = self._config_from_form()
        except ValueError as e:
            cmds.warning("[TrimAligner] {}".format(e))
            return
        _store.upsert(name, cfg)
        if _store.save():
            self._refresh_preset_list(name)
            self._load_active_into_form()

    def _delete_current(self):
        name = self.preset_combo.currentText()
        if len(_store.presets) <= 1:
            cmds.warning("[TrimAligner] Cannot delete the last preset.")
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Preset",
            "Delete preset \"{}\"?".format(name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        if _store.delete(name) and _store.save():
            self._refresh_preset_list(_store.active)
            self._load_active_into_form()

    def _apply_and_close(self):
        try:
            cfg = self._config_from_form()
        except ValueError as e:
            cmds.warning("[TrimAligner] {}".format(e))
            return
        name = self.preset_combo.currentText() or _store.active
        _store.upsert(name, cfg)
        _store.save()
        self.accept()


class UVStripAligner(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(UVStripAligner, self).__init__(parent or get_maya_main_window())
        self.setWindowTitle("TrimAligner v{}".format(__version__))
        self.setMinimumWidth(340)
        self.build_ui()
        self._refresh_status()

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QHBoxLayout()
        self.preset_label = QtWidgets.QLabel("")
        header.addWidget(self.preset_label, 1)
        config_btn = QtWidgets.QToolButton()
        config_btn.setText("Cfg")
        config_btn.setToolTip("Edit strip config / presets")
        config_btn.setFixedSize(28, 28)
        config_btn.clicked.connect(self._open_settings)
        header.addWidget(config_btn)
        layout.addLayout(header)

        layout.addWidget(QtWidgets.QLabel("Auto Trim Align:"))
        align_btn = QtWidgets.QPushButton("Auto-Align UV Shells")
        align_btn.clicked.connect(self._run_auto_align)
        layout.addWidget(align_btn)

        up_down_row = QtWidgets.QHBoxLayout()
        up_btn = QtWidgets.QPushButton("Shift Up")
        down_btn = QtWidgets.QPushButton("Shift Down")
        up_btn.clicked.connect(lambda: self._run_shift(True))
        down_btn.clicked.connect(lambda: self._run_shift(False))
        up_down_row.addWidget(up_btn)
        up_down_row.addWidget(down_btn)
        layout.addLayout(up_down_row)

        layout.addWidget(QtWidgets.QLabel("Smart Packing:"))
        pack_btn = QtWidgets.QPushButton("Smart Pack Strips")
        pack_btn.clicked.connect(self._run_pack)
        layout.addWidget(pack_btn)

        pad_row = QtWidgets.QHBoxLayout()
        pad_row.addWidget(QtWidgets.QLabel("Padding:"))
        self.padding_input = QtWidgets.QDoubleSpinBox()
        self.padding_input.setDecimals(4)
        self.padding_input.setSingleStep(0.005)
        self.padding_input.setRange(0.0, 10.0)
        self.padding_input.setValue(0.01)
        pad_row.addWidget(self.padding_input)
        layout.addLayout(pad_row)

        layout.addWidget(QtWidgets.QLabel("Best-Fit Tools:"))
        rotate_btn = QtWidgets.QPushButton("Best-Fit Rotation to Strip")
        rotate_btn.clicked.connect(self._run_rotate)
        layout.addWidget(rotate_btn)

        self.feedback = QtWidgets.QLabel("Ready.")
        self.feedback.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.feedback)

    def _refresh_status(self):
        cfg = get_config()
        self.preset_label.setText(
            "Preset: {}  |  {}px  |  {} strips".format(
                _store.active, cfg.texture_size, len(cfg.strip_pixel_heights)
            )
        )

    def _open_settings(self):
        dlg = PresetSettingsDialog(self)
        accepted = dlg.exec() if hasattr(dlg, "exec") else dlg.exec_()
        if accepted:
            self._refresh_status()
            self.feedback.setText("Preset: {}".format(_store.active))

    def _run_auto_align(self):
        auto_align_uvs()
        self.feedback.setText("Aligned.")

    def _run_shift(self, up):
        shift_strip(up)
        self.feedback.setText("Shifted {}.".format("up" if up else "down"))

    def _run_pack(self):
        smart_pack_strips(padding=self.padding_input.value())
        self.feedback.setText("Packed.")

    def _run_rotate(self):
        rotate_to_best_fit()
        self.feedback.setText("Rotated to best fit.")


_aligner_ui = None


def show_uv_aligner_ui():
    """Launch the TrimAligner window (TechArt / shelf entry point)."""
    global _aligner_ui
    reload_presets()
    try:
        _aligner_ui.close()
    except Exception:
        pass
    _aligner_ui = UVStripAligner()
    _aligner_ui.show()
    return _aligner_ui


def show():
    """Alias for show_uv_aligner_ui()."""
    return show_uv_aligner_ui()


# Script Editor convenience:
# show()
