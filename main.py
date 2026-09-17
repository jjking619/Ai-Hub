import os
import sys
import webbrowser
import subprocess
import glob
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from typing import Optional, List

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QLockFile, QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QGroupBox,
    QFrame,
    QTextEdit,
)

SETTINGS_ORG = "ai-hub"
SETTINGS_APP = "ai-hub"

STRINGS = {
    "zh": {
        "modules": "模块选择",
        "app_details": "应用详情",
        "app_preview": "项目界面",
        "operation_guide": "操作指南",
        "open": "打开项目",
        "running": "运行中: {name}",
        "no_preview": "暂无预览图",
        "preview_missing": "未找到可用图片",
        "proc_log": "子进程日志",
        "show_log": "显示日志",
        "hide_log": "隐藏日志",
        "notice": "提示",
        "error": "错误",
        "launch_failed": "启动失败",
        "already_running": "已有项目在运行，请先退出当前项目",
        "entry_missing": "入口不存在: {path}",
        "python_missing": "Python 不存在: {path}",
        "cannot_launch": "无法启动 {title}: {msg}",
        "hub_running": "AI Hub 已在运行，请勿重复启动。",
        "lang_button": "EN",
    },
    "en": {
        "modules": "Modules",
        "app_details": "App Details",
        "app_preview": "App Preview",
        "operation_guide": "Operation Guide",
        "open": "Open",
        "running": "Running: {name}",
        "no_preview": "No preview available",
        "preview_missing": "Preview image not found",
        "proc_log": "Process log",
        "show_log": "Show log",
        "hide_log": "Hide log",
        "notice": "Notice",
        "error": "Error",
        "launch_failed": "Launch failed",
        "already_running": "Another app is already running. Close it first.",
        "entry_missing": "Entry not found: {path}",
        "python_missing": "Python not found: {path}",
        "cannot_launch": "Cannot launch {title}: {msg}",
        "hub_running": "AI Hub is already running.",
        "lang_button": "中文",
    },
}


def T(lang: str, key: str, **kwargs) -> str:
    """Look up a UI string, falling back to Chinese and finally the key itself."""
    table = STRINGS.get(lang) or STRINGS["zh"]
    template = table.get(key) or STRINGS["zh"].get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def load_lang() -> str:
    value = QSettings(SETTINGS_ORG, SETTINGS_APP).value("lang", "zh")
    return "en" if str(value).strip().lower().startswith("en") else "zh"


def save_lang(lang: str) -> None:
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("lang", lang)


def display_title(spec: "AppSpec", lang: str) -> str:
    if lang == "en" and spec.title_en:
        return spec.title_en
    return spec.title


def display_intro(spec: "AppSpec", lang: str) -> str:
    if lang == "en" and spec.intro_en:
        return spec.intro_en
    return spec.intro


APP_GUIDES = {
    "gesture_remote": {
        "zh": [
            "手掌张开: 播放/暂停",
            "向右滑动: 快进 5 秒",
            "向左滑动: 回退 5 秒",
            "上下滑动: 音量增减",
        ],
        "en": [
            "Open palm: Play/Pause",
            "Swipe right: Forward 5s",
            "Swipe left: Backward 5s",
            "Swipe up/down: Volume +/-",
        ],
    },
    "eye_remote": {
        "zh": [
            "睁眼并注视屏幕: 继续播放",
            "闭眼: 自动暂停",
            "人脸离开摄像头: 自动暂停",
            "视线移开屏幕: 自动暂停",
        ],
        "en": [
            "Eyes open + gaze detected: Resume",
            "Eyes closed: Pause",
            "Face left camera: Pause",
            "Looking away: Pause",
        ],
    },
    "ranging": {
        "zh": [
            "双目标定已完成，进入测距模式后点击目标点",
            "顶部状态栏显示实时距离",
            "可切换左右预览与参数调优",
        ],
        "en": [
            "Stereo calibration is done; enter ranging mode and click target point",
            "Distance is shown on the top status bar",
            "Tune camera parameters for better accuracy",
        ],
    },
    "face_transform": {
        "zh": [
            "摄像头取景后抓拍人脸",
            "选择年龄变化/动漫化/性别转换",
            "等待云端处理并返回结果",
            "结果可继续预览或保存",
        ],
        "en": [
            "Capture a face frame from camera",
            "Choose aging/anime/gender-swap effect",
            "Wait for cloud processing",
            "Preview or save generated output",
        ],
    },
    "ai_nas": {
        "zh": [
            "操作方式: 在 CasaOS 打开Voice Assistant，直接输入文本指令",
            "语音方式: 先说唤醒词\"小远同学\"，再说出任务",
            "测试项1: 下载测试视频并播放",
            "测试项2: 帮我把家庭相册的照片分类，先预览",
            "测试项3: 把家庭相册下的照片加复古滤镜，先预览",
            "测试项4: 住房合同在哪",
        ],
        "en": [
            "How to use: Open the Voice Assistant from CasaOS and type commands directly",
            "Voice entry: Say wake word \"xiaoyuantongxue\" first, then speak your task",
            "Test 1: Download the test video and play it",
            "Test 2: Please classify the family album photos, preview first",
            "Test 3: Please add a vintage filter to the family album photos, preview first",
            "Test 4: Where is the housing contract?",
        ],
    },
}


APP_CARD_GUIDES = {
    "gesture_remote": {
        "zh": {
            "show_icon": False,
            "tip": "提示: 请在摄像头前方 0.5 ~ 1 米处操作，手部置于画面中央",
            "tip2": "建议: 每个手势动作后有短暂冷却，请等待反馈再进行下一次操作",
            "cards": [
                {"icon_path": "/home/pi/ai-hub/asset/gesture_fist.svg", "title": "握拳", "desc": "暂停"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_palm.svg", "title": "张开手掌", "desc": "播放"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_left.svg", "title": "食指左滑", "desc": "抬起食指，整只手向左滑动（快退 5 秒）"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_right.svg", "title": "食指右滑", "desc": "抬起食指，整只手向右滑动（快进 5 秒）"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_up.svg", "title": "食指上滑", "desc": "音量 +5%"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_down.svg", "title": "食指下滑", "desc": "音量 -5%"},
            ],
        },
        "en": {
            "show_icon": False,
            "tip": "Tip: Stand 0.5 - 1 m from camera, keep hand in frame center",
            "tip2": "Note: A brief cooldown follows each gesture, wait for feedback before next action",
            "cards": [
                {"icon_path": "/home/pi/ai-hub/asset/gesture_fist.svg", "title": "Fist", "desc": "Pause"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_palm.svg", "title": "Open Palm", "desc": "Play"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_left.svg", "title": "Swipe Left", "desc": "Raise index finger and move whole hand left (Rewind 5s)"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_right.svg", "title": "Swipe Right", "desc": "Raise index finger and move whole hand right (Forward 5s)"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_up.svg", "title": "Swipe Up", "desc": "Volume +5%"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_down.svg", "title": "Swipe Down", "desc": "Volume -5%"},
            ],
        },
    },
    "eye_remote": {
    "zh": {
            "show_icon": False,
        "tip": "提示: 请在摄像头前方 0.5 ~ 1 米处操作",
        "cards": [
                {"title": "睁眼", "desc": "注视屏幕: 继续播放"},
                {"title": "闭眼", "desc": "闭眼: 自动暂停"},
                {"title": "人脸离开", "desc": "人脸离开摄像头: 暂停"},
                {"title": "视线移开", "desc": "视线移开: 自动暂停"},
        ],
    },
    "en": {
            "show_icon": False,
        "tip": "Tip: Stand 0.5 - 1 m from camera",
        "cards": [
                {"title": "Eyes Open", "desc": "Gaze detected: Resume"},
                {"title": "Eyes Closed", "desc": "Eyes closed: Pause"},
                {"title": "Face Left", "desc": "Face left camera: Pause"},
                {"title": "Looking Away", "desc": "Gaze away: Pause"},
        ],
    },
    },
    "ranging": {
        "zh": {
            "show_icon": False,
            "tip": "提示: 已完成双目标定，可直接开始测距",
            "tip2": "建议: 尽量点击目标边缘清晰区域以提升稳定性",
            "cards": [
                {"title": "步骤 1", "desc": "点击Start Ranging Mode进入测量模式"},
                {"title": "步骤 2", "desc": "在画面中点击目标位置"},
                {"title": "步骤 3", "desc": "查看顶部状态栏距离结果"},
            ],
        },
        "en": {
            "show_icon": False,
            "tip": "Tip: Calibration is done, you can start ranging directly",
            "tip2": "Note: Click clear object edges for more stable ranging",
            "cards": [
                {"title": "Step 1", "desc": "Enter ranging mode"},
                {"title": "Step 2", "desc": "Click the target point in preview"},
                {"title": "Step 3", "desc": "Read distance from the top status bar"},
            ],
        },
    },
    "face_transform": {
        "zh": {
            "show_icon": False,
            "tip": "提示: 保持人脸位于画面中心并确保环境光均匀",
            "tip2": "建议: 云端密钥已配置，可直接选择效果并开始生成",
            "cards": [
                {"title": "步骤 1", "desc": "摄像头取景并抓拍人脸"},
                {"title": "步骤 2", "desc": "选择年龄变化、动漫化或性别转换"},
                {"title": "步骤 3", "desc": "等待云端返回处理结果"},
                {"title": "步骤 4", "desc": "预览并保存生成图像"},
            ],
        },
        "en": {
            "show_icon": False,
            "tip": "Tip: Keep the face centered with even lighting",
            "tip2": "Note: Cloud credentials are ready, choose an effect and generate directly",
            "cards": [
                {"title": "Step 1", "desc": "Capture a clear face frame from camera"},
                {"title": "Step 2", "desc": "Choose aging, anime, or gender-swap effect"},
                {"title": "Step 3", "desc": "Wait for cloud processing result"},
                {"title": "Step 4", "desc": "Preview and save generated output"},
            ],
        },
    },
    "ai_nas": {
        "zh": {
            "show_icon": False,
            "tip": "提示: 在 CasaOS 中打开对话助手，可直接输入文本指令",
            "tip2": "语音方式: 先说唤醒词“小远同学”，再说任务",
            "cards": [
                {"title": "测试项 1", "desc": "下载测试视频并播放"},
                {"title": "测试项 2", "desc": "帮我把家庭相册的照片分类，先预览"},
                {"title": "测试项 3", "desc": "把家庭相册下的照片加复古滤镜，先预览"},
                {"title": "测试项 4", "desc": "住房合同在哪"},
            ],
        },
        "en": {
            "show_icon": False,
            "tip": "Tip: Open the web assistant in CasaOS or type commands directly",
            "tip2": "Voice entry: Say wake word xiaoyuantongxue, then speak your task",
            "cards": [
                {"title": "Test 1", "desc": "Download the test video and play it"},
                {"title": "Test 2", "desc": "Please classify family album photos, preview first"},
                {"title": "Test 3", "desc": "Please add a vintage filter, preview first"},
                {"title": "Test 4", "desc": "Where is the housing contract?"},
            ],
        },
    },
}


def display_guide(spec: "AppSpec", lang: str) -> str:
    table = APP_GUIDES.get(spec.app_id, {})
    lines = table.get(lang) or table.get("zh") or []
    return "\n".join([f"- {line}" for line in lines])


@dataclass
class AppSpec:
    app_id: str
    order: int
    title: str
    title_en: str
    intro: str
    intro_en: str
    kind: str  # process | services
    python_bin: str = ""
    cwd: str = ""
    script: str = ""
    launch_url: str = ""
    preview_image: str = ""


APP_SPECS: List[AppSpec] = [
    AppSpec(
        app_id="gesture_remote",
        order=1,
        title="手势遥控器",
        title_en="Gesture Remote",
        intro="基于实时手势识别的无接触式视频控制方案，支持手掌检测和滑动手势，可在本地完成播放、暂停、快进、回退与音量调节，适合在展示场景和家用娱乐中实现自然交互。",
        intro_en="A touch-free video control solution powered by real-time hand tracking. It detects palm posture and swipe gestures to play, pause, seek, and adjust volume locally with low latency and a natural interaction experience.",
        kind="process",
        python_bin="/home/pi/.pyenv/versions/3.10.15/bin/python",
        cwd="/home/pi/demo-gesture-remote-control/src",
        script="/home/pi/demo-gesture-remote-control/src/main.py",
        preview_image="/home/pi/demo-gesture-remote-control/docs/assets/main.png",
    ),
    AppSpec(
        app_id="eye_remote",
        order=2,
        title="眼控遥控器",
        title_en="Eye Remote",
        intro="利用实时眼部状态检测和视线判断技术，用户注视屏幕时自动继续播放，闭眼或移开视线时自动暂停，适合无手操作的视频观看与沉浸式体验。",
        intro_en="Uses real-time eye-state and gaze detection to keep a video playing while you look at the screen and pause automatically when you blink or look away, enabling hands-free and immersive viewing.",
        kind="process",
        python_bin="/home/pi/.pyenv/versions/3.10.15/bin/python",
        cwd="/home/pi/demo-eye-remote-control/src",
        script="/home/pi/demo-eye-remote-control/src/main.py",
        preview_image="/home/pi/demo-eye-remote-control/assets/interface.png",
    ),
    AppSpec(
        app_id="ranging",
        order=3,
        title="双目测距",
        title_en="Stereo Ranging",
        intro="结合双目摄像头、标定参数与 SGBM 立体匹配算法，支持点击任意目标区域实时测量与相机的真实距离，并可切换左右相机预览与参数调优，适合教学、实验和原型评估场景。",
        intro_en="Combines dual-camera input, calibration parameters, and SGBM stereo matching to measure the real-world distance of any clicked point while supporting left/right preview and parameter tuning for higher accuracy in teaching, experiments, and prototyping.",
        kind="process",
        python_bin="/home/pi/.pyenv/versions/3.10.15/bin/python",
        cwd="/home/pi/demo-camera-distance-measurement/src",
        script="/home/pi/demo-camera-distance-measurement/src/main.py",
        preview_image="/home/pi/demo-camera-distance-measurement/assets/test1.png",
    ),
    AppSpec(
        app_id="face_transform",
        order=4,
        title="人脸变换",
        title_en="Face Transform",
        intro="基于 USB 摄像头实时采集人脸图像，并调用腾讯云视觉能力实现年龄变化、动漫化和性别转换三类特效，适合创意展示、互动体验与快速原型验证。",
        intro_en="Captures live face images from a USB camera and applies Tencent Cloud image effects to generate age transformation, anime-style portrait, and gender-swapped results for creative demos and interactive prototyping.",
        kind="process",
        python_bin="/bin/bash",
        cwd="/home/pi/Project/demo-face-transform/src",
        script="/home/pi/Project/demo-face-transform/src/start.sh",
        preview_image="/home/pi/Project/demo-face-transform/docs/assets/face1.png",
    ),
    AppSpec(
        app_id="ai_nas",
        order=5,
        title="智能NAS系统",
        title_en="Smart NAS",
        intro="围绕 CasaOS 与 OpenClaw 构建的智能 NAS 助手，整合文件管理、知识检索、媒体下载和语音交互能力，支持自然语言发起任务，帮助用户快速完成内容查找、资源获取与日常办公协同。",
        intro_en="A smart NAS assistant built on CasaOS and OpenClaw, combining file management, knowledge search, media download, and voice interaction. It can handle natural-language tasks to help users search, retrieve, and manage digital content efficiently.",
        kind="services",
        launch_url="http://127.0.0.1:28083",
        preview_image="/home/pi/ai-nas/assets/image.png",
    ),
]


class _ImageLabel(QLabel):
    """Label that keeps a source pixmap scaled to its own current size.

    Scaling is driven by the label's own resizeEvent (not the parent's), because a
    parent's resizeEvent can still observe the child's previous geometry.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = QPixmap()
        self._scaled_size = None

    def _sync_height_with_aspect(self):
        if self._source.isNull():
            self.setMaximumHeight(16777215)
            return
        w = self.width()
        if w <= 1 or self._source.width() <= 0:
            return
        target_h = max(160, int(w * self._source.height() / self._source.width()))
        if self.maximumHeight() != target_h:
            self.setMaximumHeight(target_h)

    def set_source(self, pixmap: QPixmap):
        self._source = pixmap if pixmap is not None else QPixmap()
        self._scaled_size = None
        if self._source.isNull():
            self.setMaximumHeight(16777215)
            super().clear()
            return
        self._sync_height_with_aspect()
        self._rescale()

    def _rescale(self):
        if self._source.isNull():
            return
        self._sync_height_with_aspect()
        size = self.size()
        if size.width() <= 1 or size.height() <= 1 or size == self._scaled_size:
            return
        self._scaled_size = size
        super().setPixmap(self._source.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()


class NasPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self.current_spec: Optional[AppSpec] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.preview_group = QGroupBox(T(self.lang, "app_preview"))
        preview_layout = QVBoxLayout(self.preview_group)

        split_row = QHBoxLayout()
        split_row.setSpacing(12)

        image_wrap = QWidget()
        image_layout = QVBoxLayout(image_wrap)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(8)

        image_toolbar = QHBoxLayout()
        image_toolbar.setContentsMargins(0, 0, 0, 6)
        image_toolbar.setSpacing(8)

        self.image_title = QLabel("")
        self.image_title.setStyleSheet("font-size: 21px; font-weight: 800;")

        self.image_actions = QWidget()
        self.image_actions_layout = QHBoxLayout(self.image_actions)
        self.image_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.image_actions_layout.setSpacing(8)

        image_toolbar.addWidget(self.image_title)
        image_toolbar.addStretch()
        image_toolbar.addWidget(self.image_actions)

        self.image_view = _ImageLabel()
        self.image_view.setAlignment(Qt.AlignCenter)
        self.image_view.setMinimumHeight(220)
        self.image_view.setMinimumWidth(420)
        self.image_view.setStyleSheet(
            "border: 1px dashed #334155; border-radius: 12px; background-color: #020617; color: #94a3b8;"
        )
        self.image_note = QLabel("")
        self.image_note.setWordWrap(True)
        self.image_note.setObjectName("muted")

        image_layout.addLayout(image_toolbar)
        image_layout.addWidget(self.image_view, 0, Qt.AlignTop)
        image_layout.addWidget(self.image_note)
        image_layout.addStretch()

        self.guide_group = QGroupBox(T(self.lang, "operation_guide"))
        self.guide_group.setObjectName("guidePanel")
        self.guide_group.setMinimumWidth(340)
        guide_layout = QVBoxLayout(self.guide_group)
        guide_layout.setContentsMargins(14, 14, 14, 14)
        guide_layout.setSpacing(10)

        self.guide_tip = QLabel("")
        self.guide_tip.setObjectName("guideTip")
        self.guide_tip.setWordWrap(True)
        self.guide_tip.setAlignment(Qt.AlignCenter)
        self.guide_tip.setVisible(False)

        self.guide_tip2 = QLabel("")
        self.guide_tip2.setObjectName("guideTipSecondary")
        self.guide_tip2.setWordWrap(True)
        self.guide_tip2.setAlignment(Qt.AlignCenter)
        self.guide_tip2.setVisible(False)

        self.guide_label = QLabel("")
        self.guide_label.setObjectName("guideText")
        self.guide_label.setWordWrap(True)
        self.guide_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.guide_cards_wrap = QWidget()
        self.guide_cards_wrap.setVisible(False)
        self.guide_cards_layout = QGridLayout(self.guide_cards_wrap)
        self.guide_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.guide_cards_layout.setHorizontalSpacing(12)
        self.guide_cards_layout.setVerticalSpacing(12)

        self.guide_cards = []
        for index in range(6):
            card = QFrame()
            card.setObjectName("guideCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 14, 14, 14)
            card_layout.setSpacing(6)

            icon = QLabel("")
            icon.setObjectName("guideCardIcon")
            icon.setAlignment(Qt.AlignCenter)
            icon.setMinimumHeight(60)
            title = QLabel("")
            title.setObjectName("guideCardTitle")
            title.setWordWrap(True)
            desc = QLabel("")
            desc.setObjectName("guideCardDesc")
            desc.setWordWrap(True)

            card_layout.addWidget(icon)
            card_layout.addWidget(title)
            card_layout.addWidget(desc)
            card_layout.addStretch()

            row = index // 2
            col = index % 2
            self.guide_cards_layout.addWidget(card, row, col)
            self.guide_cards.append({"frame": card, "icon": icon, "title": title, "desc": desc})

        guide_layout.addWidget(self.guide_tip)
        guide_layout.addWidget(self.guide_tip2)
        guide_layout.addWidget(self.guide_label)
        guide_layout.addWidget(self.guide_cards_wrap, 1)
        guide_layout.addStretch()

        split_row.addWidget(image_wrap, 3, Qt.AlignTop)
        split_row.addWidget(self.guide_group, 2)

        preview_layout.addLayout(split_row)
        preview_layout.addStretch()

        layout.addWidget(self.preview_group, 1)

    def attach_toolbar_buttons(self, *buttons):
        while self.image_actions_layout.count():
            item = self.image_actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for button in buttons:
            if button is not None:
                self.image_actions_layout.addWidget(button)

    def set_language(self, lang: str):
        self.lang = lang
        self.preview_group.setTitle(T(lang, "app_preview"))
        self.guide_group.setTitle(T(lang, "operation_guide"))
        if self.current_spec:
            self.set_project(self.current_spec)

    def set_project(self, spec: AppSpec):
        self.current_spec = spec
        self.image_title.setText(display_title(spec, self.lang))
        self.guide_label.setText(display_guide(spec, self.lang))
        self._update_guide_mode(spec)

        image_path = spec.preview_image.strip() if spec.preview_image else ""
        pixmap = QPixmap(image_path) if image_path and os.path.exists(image_path) else QPixmap()
        self.image_view.set_source(pixmap)

        if pixmap.isNull():
            self.image_view.setText(T(self.lang, "no_preview"))
            self.image_note.setText(T(self.lang, "preview_missing"))
            self.image_note.setVisible(True)
            return

        self.image_note.clear()
        self.image_note.setVisible(False)

    def _update_guide_mode(self, spec: AppSpec):
        card_table = APP_CARD_GUIDES.get(spec.app_id)
        use_cards = bool(card_table)

        self.guide_label.setVisible(not use_cards)
        self.guide_cards_wrap.setVisible(use_cards)
        self.guide_tip.setVisible(use_cards)
        self.guide_tip2.setVisible(False)

        if not use_cards:
            self.guide_tip.clear()
            self.guide_tip2.clear()
            for card in self.guide_cards:
                card["frame"].setVisible(False)
            return

        data = card_table.get(self.lang) or card_table.get("zh") or {}
        self.guide_tip.setText(data.get("tip", ""))
        tip2 = data.get("tip2", "")
        self.guide_tip2.setText(tip2)
        self.guide_tip2.setVisible(bool(tip2))

        show_icon = bool(data.get("show_icon", True))
        cards = data.get("cards", [])
        for index, card in enumerate(self.guide_cards):
            if index < len(cards):
                item = cards[index]
                card["icon"].setVisible(show_icon)
                icon_path = item.get("icon_path", "")
                if icon_path and os.path.exists(icon_path):
                    pm = QPixmap(icon_path)
                    if not pm.isNull():
                        card["icon"].setPixmap(pm.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        card["icon"].setText("")
                    else:
                        card["icon"].setPixmap(QPixmap())
                        card["icon"].setText(item.get("icon", ""))
                else:
                    card["icon"].setPixmap(QPixmap())
                    card["icon"].setText(item.get("icon", ""))
                card["title"].setText(item.get("title", ""))
                card["desc"].setText(item.get("desc", ""))
                card["frame"].setVisible(True)
            else:
                card["frame"].setVisible(False)


class HubWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.apps = APP_SPECS
        self.active_process: Optional[QProcess] = None
        self.active_app: Optional[AppSpec] = None
        self.lang = load_lang()

        self._build_ui()
        self._apply_language()
        self._apply_style()
        self._stop_conflicting_autostart_services()

    def _build_ui(self):
        self.setWindowTitle("AI Hub")
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo:
            self.setGeometry(geo.x() + 40, geo.y() + 30, int(geo.width() * 0.9), int(geo.height() * 0.9))

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        sidebar = QGroupBox()
        sidebar.setFixedWidth(280)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 16, 16, 16)
        side_layout.setSpacing(10)

        title = QLabel("AI Hub")
        title.setStyleSheet("font-size: 23px; font-weight: 800;")
        self.sub_label = QLabel(T(self.lang, "modules"))
        self.sub_label.setObjectName("muted")

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self.on_app_selected)

        for spec in self.apps:
            item = QListWidgetItem(f"{spec.order:02d}  {display_title(spec, self.lang)}")
            item.setData(Qt.UserRole, spec.app_id)
            self.list_widget.addItem(item)

        side_layout.addWidget(title)
        side_layout.addWidget(self.sub_label)
        side_layout.addWidget(self.list_widget, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # App details: intro only, actions are moved to preview toolbar.
        self.header_group = QGroupBox()
        header_layout = QVBoxLayout(self.header_group)

        self.open_btn = QPushButton(T(self.lang, "open"))
        self.open_btn.setObjectName("openButton")
        self.open_btn.setMinimumWidth(132)
        self.open_btn.setMinimumHeight(40)
        self.open_btn.clicked.connect(self.launch_selected)

        self.lang_btn = QPushButton(T(self.lang, "lang_button"))
        self.lang_btn.setObjectName("langButton")
        self.lang_btn.setFixedWidth(92)
        self.lang_btn.setMinimumHeight(40)
        self.lang_btn.clicked.connect(self.toggle_language)

        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        self.badge_label = QLabel("")
        self.badge_label.setObjectName("statusValue")

        header_layout.addWidget(self.desc_label)

        self.nas_panel = NasPanel(self)
        self.nas_panel.attach_toolbar_buttons(self.open_btn, self.lang_btn)

        self.log_toggle_btn = QPushButton(T(self.lang, "show_log"))
        self.log_toggle_btn.setObjectName("logToggleButton")
        self.log_toggle_btn.setFixedWidth(120)
        self.log_toggle_btn.clicked.connect(self.toggle_log_visibility)

        self.proc_log = QTextEdit()
        self.proc_log.setReadOnly(True)
        self.proc_log.setMinimumHeight(110)
        self.proc_log.setPlaceholderText(T(self.lang, "proc_log"))
        self.proc_log.setVisible(True)

        content_layout.addWidget(self.header_group)
        content_layout.addWidget(self.nas_panel, 3)
        content_layout.addWidget(self.log_toggle_btn)
        content_layout.addWidget(self.proc_log, 1)
        self._update_log_toggle()

        root.addWidget(sidebar)
        root.addWidget(content, 1)

        self.list_widget.setCurrentRow(0)

    def _apply_language(self):
        lang = self.lang
        self.header_group.setTitle(T(lang, "app_details"))
        self.sub_label.setText(T(lang, "modules"))
        self.open_btn.setText(T(lang, "open"))
        self.lang_btn.setText(T(lang, "lang_button"))
        self.proc_log.setPlaceholderText(T(lang, "proc_log"))
        self.nas_panel.set_language(lang)
        self._update_log_toggle()

        row = self.list_widget.currentRow()
        self.list_widget.blockSignals(True)
        for index, spec in enumerate(self.apps):
            item = self.list_widget.item(index)
            if item:
                item.setText(f"{spec.order:02d}  {display_title(spec, lang)}")
        self.list_widget.blockSignals(False)

        self.on_app_selected(row)

    def _update_log_toggle(self):
        self.log_toggle_btn.setText(T(self.lang, "hide_log" if self.proc_log.isVisible() else "show_log"))

    def toggle_log_visibility(self):
        self.proc_log.setVisible(not self.proc_log.isVisible())
        self._update_log_toggle()

    def toggle_language(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        save_lang(self.lang)
        self._apply_language()

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow { background-color: #060b1a; }
            QWidget { color: #e2e8f0; font-family: 'DejaVu Sans'; font-size: 15px; }
            QGroupBox {
                color: #f8fafc;
                font-weight: 600;
                border: 1px solid #233152;
                border-radius: 16px;
                margin-top: 10px;
                padding-top: 12px;
                background-color: #0f172a;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; }
            QGroupBox#guidePanel {
                background-color: #111827;
                border: 1px solid #334155;
                border-radius: 16px;
            }
            QGroupBox#guidePanel::title {
                color: #f8fafc;
                font-size: 18px;
                font-weight: 800;
                left: 14px;
            }
            QLabel#muted { color: #94a3b8; }
            QLabel#statusValue {
                font-weight: 700;
                padding: 4px 10px;
                border-radius: 8px;
                background-color: #1e293b;
            }
            QLabel#guideText {
                color: #e2e8f0;
                line-height: 1.55;
                font-size: 17px;
            }
            QLabel#guideTip {
                color: #0f172a;
                border: 1px solid #bfdbfe;
                border-radius: 12px;
                padding: 10px 12px;
                background-color: #eff6ff;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#guideTipSecondary {
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 12px;
                padding: 9px 12px;
                background-color: #f8fafc;
                font-size: 15px;
            }
            QFrame#guideCard {
                border: 1px solid #cbd5e1;
                border-radius: 14px;
                background-color: #f8fafc;
            }
            QLabel#guideCardIcon {
                font-family: monospace;
                font-size: 28px;
                font-weight: 700;
                color: #111827;
            }
            QLabel#guideCardTitle {
                font-size: 19px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#guideCardDesc {
                font-size: 16px;
                color: #334155;
            }
            QListWidget {
                border: 1px solid #334155;
                border-radius: 12px;
                background-color: #0b1328;
                padding: 6px;
            }
            QListWidget::item {
                border: 1px solid #334155;
                margin: 4px;
                padding: 10px;
                border-radius: 10px;
                background-color: #111b33;
                min-height: 28px;
            }
            QListWidget::item:selected {
                background-color: #1d4ed8;
                border-color: #60a5fa;
                color: #eff6ff;
            }
            QPushButton {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #273449; }
            QPushButton:pressed { background-color: #111827; }
            QPushButton:disabled { color: #64748b; border-color: #1e293b; }
            QPushButton#openButton {
                font-size: 16px;
                font-weight: 800;
                padding: 9px 18px;
                background-color: #2563eb;
                color: #f8fafc;
                border-color: #60a5fa;
            }
            QPushButton#openButton:hover { background-color: #1d4ed8; }
            QPushButton#openButton:pressed { background-color: #1e40af; }
            QPushButton#langButton {
                font-size: 15px;
                font-weight: 700;
                padding: 8px 12px;
                background-color: #1e3a8a;
                color: #dbeafe;
                border-color: #60a5fa;
            }
            QPushButton#langButton:hover { background-color: #1e40af; }
            QPushButton#logToggleButton {
                background-color: #0f172a;
                color: #cbd5e1;
                border-color: #475569;
                max-width: 140px;
            }
            QPushButton#logToggleButton:hover { background-color: #1e293b; }
            QTextEdit {
                border: 1px solid #334155;
                border-radius: 10px;
                background-color: #020617;
                font-family: monospace;
            }
            """
        )

    def _set_badge(self, text: str, bg: str, fg: str = "#08111f"):
        self.badge_label.setText(text)
        self.badge_label.setVisible(bool(text))
        if text:
            self.badge_label.setStyleSheet(
                f"background-color: {bg}; color: {fg}; font-weight: 700; padding: 4px 10px; border-radius: 8px;"
            )

    def _bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _stop_conflicting_autostart_services(self):
        for name in ["gesture-remote-control", "eye-remote-control"]:
            try:
                subprocess.run(
                    ["systemctl", "--user", "stop", name],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                pass

    def _selected_spec(self) -> Optional[AppSpec]:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.apps):
            return None
        return self.apps[row]

    def _resolve_preferred_camera(self):
        # Prefer UGREEN index0 node for single-camera apps.
        patterns = [
            "/dev/v4l/by-id/*UGREEN*video-index0",
            "/dev/v4l/by-id/*Ugreen*video-index0",
            "/dev/v4l/by-id/*ugreen*video-index0",
        ]
        candidates = []
        for pat in patterns:
            candidates.extend(sorted(glob.glob(pat)))

        if candidates:
            dev = os.path.realpath(candidates[0])
            base = os.path.basename(dev)
            idx = ""
            if base.startswith("video"):
                idx = base.replace("video", "", 1)
            return dev, idx

        # Fallback to the first by-id index0 if UGREEN keyword is unavailable.
        generic = sorted(glob.glob("/dev/v4l/by-id/*video-index0"))
        if generic:
            dev = os.path.realpath(generic[0])
            base = os.path.basename(dev)
            idx = ""
            if base.startswith("video"):
                idx = base.replace("video", "", 1)
            return dev, idx

        return "", ""

    def _resolve_ai_nas_url(self, fallback_url: str) -> str:
        try:
            result = subprocess.run(
                ["./oc.sh", "casaos-url"],
                cwd="/home/pi/ai-nas",
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
            )
            candidate = (result.stdout or "").strip().splitlines()
            if candidate:
                base_url = candidate[-1].strip()
                if base_url.startswith("http://") or base_url.startswith("https://"):
                    base_parts = urlsplit(base_url)
                    fallback_parts = urlsplit(fallback_url or "http://127.0.0.1:28083")
                    target_port = fallback_parts.port
                    host = base_parts.hostname or fallback_parts.hostname or "127.0.0.1"
                    scheme = fallback_parts.scheme or base_parts.scheme or "http"
                    if target_port:
                        netloc = f"{host}:{target_port}"
                    else:
                        netloc = host
                    return urlunsplit((scheme, netloc, fallback_parts.path, fallback_parts.query, fallback_parts.fragment))
        except Exception:
            pass
        return fallback_url or "http://127.0.0.1:28083"

    def on_app_selected(self, _row: int):
        spec = self._selected_spec()
        if not spec:
            return
        lang = self.lang
        self.desc_label.setText(display_intro(spec, lang))
        self.nas_panel.set_project(spec)

        running = self._is_process_running()
        self.open_btn.setEnabled(not running)
        if running:
            name = display_title(self.active_app, lang) if self.active_app else "-"
            self._set_badge(T(lang, "running", name=name), "#f59e0b")
        else:
            self._set_badge("", "#38bdf8")

    def _is_process_running(self) -> bool:
        return self.active_process is not None and self.active_process.state() != QProcess.NotRunning

    def launch_selected(self):
        spec = self._selected_spec()
        if not spec:
            return

        if spec.kind == "services":
            target_url = spec.launch_url or "http://127.0.0.1:28083"
            if spec.app_id == "ai_nas":
                target_url = self._resolve_ai_nas_url(target_url)
            if not QDesktopServices.openUrl(QUrl(target_url)):
                webbrowser.open(target_url)
            self.proc_log.append(f"[open] {target_url}")
            return

        if self._is_process_running():
            QMessageBox.warning(self, T(self.lang, "notice"), T(self.lang, "already_running"))
            return

        python_bin = spec.python_bin if os.path.exists(spec.python_bin) else sys.executable
        if not os.path.exists(spec.script):
            QMessageBox.critical(self, T(self.lang, "error"), T(self.lang, "entry_missing", path=spec.script))
            return
        if not os.path.exists(python_bin):
            QMessageBox.critical(self, T(self.lang, "error"), T(self.lang, "python_missing", path=python_bin))
            return

        self.active_process = QProcess(self)
        self.active_app = spec
        self.active_process.setProgram(python_bin)
        self.active_process.setArguments([spec.script])
        self.active_process.setWorkingDirectory(spec.cwd)
        env = QProcessEnvironment.systemEnvironment()
        if spec.app_id in ("gesture_remote", "eye_remote", "face_transform"):
            cam_dev, cam_idx = self._resolve_preferred_camera()
            if cam_dev:
                env.insert("AI_HUB_CAMERA_DEVICE", cam_dev)
            if cam_idx:
                env.insert("AI_HUB_CAMERA_INDEX", cam_idx)
        self.active_process.setProcessEnvironment(env)

        self.active_process.readyReadStandardOutput.connect(self._read_child_stdout)
        self.active_process.readyReadStandardError.connect(self._read_child_stderr)
        self.active_process.started.connect(self._on_child_started)
        self.active_process.errorOccurred.connect(self._on_child_error)
        self.active_process.finished.connect(self._on_child_finished)

        self.proc_log.append(f"$ {python_bin} {spec.script}")
        self.active_process.start()

        if not self.active_process.waitForStarted(5000):
            msg = self.active_process.errorString()
            QMessageBox.critical(
                self,
                T(self.lang, "launch_failed"),
                T(self.lang, "cannot_launch", title=display_title(spec, self.lang), msg=msg),
            )
            self.active_process = None
            self.active_app = None
            self.on_app_selected(self.list_widget.currentRow())

    def _on_child_started(self):
        name = display_title(self.active_app, self.lang) if self.active_app else "-"
        self._set_badge(T(self.lang, "running", name=name), "#f59e0b")
        self.open_btn.setEnabled(False)
        self.hide()

    def _on_child_error(self, _err):
        if not self.active_process:
            return
        self.proc_log.append(f"[error] {self.active_process.errorString()}")

    def _read_child_stdout(self):
        if not self.active_process:
            return
        text = bytes(self.active_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self.proc_log.append(text.rstrip())

    def _read_child_stderr(self):
        if not self.active_process:
            return
        text = bytes(self.active_process.readAllStandardError()).decode("utf-8", errors="replace")
        if text:
            self.proc_log.append(text.rstrip())

    def _on_child_finished(self, exit_code, _status):
        name = display_title(self.active_app, self.lang) if self.active_app else "-"
        self.proc_log.append(f"[finished] {name}, exit={exit_code}")
        self.active_process = None
        self.active_app = None
        self._bring_to_front()
        self.on_app_selected(self.list_widget.currentRow())

    def closeEvent(self, event):
        if self._is_process_running() and self.active_process:
            self.active_process.terminate()
            if not self.active_process.waitForFinished(2500):
                self.active_process.kill()
                self.active_process.waitForFinished(1500)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    lock = QLockFile("/tmp/ai-hub.lock")
    lock.setStaleLockTime(0)
    if not lock.tryLock(50):
        QMessageBox.warning(None, "AI Hub", T(load_lang(), "hub_running"))
        return 1

    window = HubWindow()
    window.show()
    exit_code = app.exec()
    lock.unlock()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
