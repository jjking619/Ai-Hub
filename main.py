import os
import sys
import webbrowser
import subprocess
import glob
import shutil
import platform
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from typing import Optional, List

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QLockFile, QSettings, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QPixmap, QImage, QColor
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
    QProgressBar,
    QStackedWidget,
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
        "opening": "正在启动: {name}",
        "force_stop": "强制停止",
        "running": "运行中: {name}",
        "no_preview": "暂无预览图",
        "preview_missing": "未找到可用图片",
        "proc_log": "子进程日志",
        "system_status": "系统状态",
        "memory": "内存与容量",
        "hardware": "硬件信息",
        "ram": "RAM",
        "disk": "磁盘",
        "cpu": "CPU",
        "npu": "NPU",
        "chip": "芯片",
        "device": "设备",
        "os": "系统",
        "kernel": "内核",
        "cpu_model": "CPU 型号",
        "unknown": "未知",
        "show_log": "显示日志",
        "hide_log": "隐藏日志",
        "notice": "提示",
        "error": "错误",
        "launch_failed": "启动失败",
        "already_running": "已有项目在运行，请先退出当前项目",
        "entry_missing": "入口不存在: {path}",
        "python_missing": "Python 不存在: {path}",
        "cannot_launch": "无法启动 {title}: {msg}",
        "launch_timeout": "启动超时，已强制停止: {title}",
        "hub_running": "AI Hub 已在运行，请勿重复启动。",
        "lang_button": "EN",
    },
    "en": {
        "modules": "Modules",
        "app_details": "App Details",
        "app_preview": "App Preview",
        "operation_guide": "Operation Guide",
        "open": "Open",
        "opening": "Starting: {name}",
        "force_stop": "Force Stop",
        "running": "Running: {name}",
        "no_preview": "No preview available",
        "preview_missing": "Preview image not found",
        "proc_log": "Process log",
        "system_status": "System Status",
        "memory": "Memory & Capacity",
        "hardware": "Hardware",
        "ram": "RAM",
        "disk": "Disk",
        "cpu": "CPU",
        "npu": "NPU",
        "chip": "Chip",
        "device": "Device",
        "os": "OS",
        "kernel": "Kernel",
        "cpu_model": "CPU Model",
        "unknown": "Unknown",
        "show_log": "Show log",
        "hide_log": "Hide log",
        "notice": "Notice",
        "error": "Error",
        "launch_failed": "Launch failed",
        "already_running": "Another app is already running. Close it first.",
        "entry_missing": "Entry not found: {path}",
        "python_missing": "Python not found: {path}",
        "cannot_launch": "Cannot launch {title}: {msg}",
        "launch_timeout": "Launch timeout, process was force-stopped: {title}",
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
    value = QSettings(SETTINGS_ORG, SETTINGS_APP).value("lang", "en")
    return "zh" if str(value).strip().lower().startswith("zh") else "en"


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
            "入口: 在 CasaOS 打开 Voice Assistant",
            "语音方式 1: 点击\"说一句\"按钮后说话",
            "语音方式 2: 呼叫\"小远同学\"唤醒后说话",
            "文本方式: 也可以直接打字输入",
            "文档: 住房合同在哪 / 合同甲方是谁 / 合同编号是多少 / 合同关键日期",
            "照片: 找海边的照片 / 找猫或动物的照片 / 相册自动分类 / 加复古滤镜",
            "影音: 下载测试视频 / 播放 oceans",
            "问NAS: 你能做什么 / NAS里有什么",
        ],
        "en": [
            "Entry: Open Voice Assistant in CasaOS",
            "Voice mode 1: Tap \"Say One Sentence\" and then speak",
            "Voice mode 2: Say wake word \"xiaoyuantongxue\" and then speak",
            "Text mode: You can also type directly",
            "Docs: Where is the housing contract / Who is Party A / What is the contract ID / Key contract dates",
            "Photos: Find beach photos / Find cat or animal photos / Auto classify album / Add vintage filter",
            "Media: Download test video / Play oceans",
            "Ask NAS: What can you do / What is in NAS",
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
                {"icon_path": "/home/pi/ai-hub/asset/gesture_fist.svg", "title": "握拳", "desc": "暂停 · 五指收起，拳面朝向摄像头"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_palm.svg", "title": "张开手掌", "desc": "播放 · 五指自然分开，掌心朝向摄像头"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_left.svg", "title": "食指左滑", "desc": "快退 5 秒 · 食指竖起比作“1”，整只手向左滑动"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_right.svg", "title": "食指右滑", "desc": "快进 5 秒 · 食指竖起比作“1”，整只手向右滑动"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_up.svg", "title": "食指上滑", "desc": "音量 +5% · 食指竖起比作“1”，整只手向上滑动"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_down.svg", "title": "食指下滑", "desc": "音量 -5% · 食指竖起比作“1”，整只手向下滑动"},
            ],
        },
        "en": {
            "show_icon": False,
            "tip": "Tip: Stand 0.5 - 1 m from camera, keep hand in frame center",
            "tip2": "Note: A brief cooldown follows each gesture, wait for feedback before next action",
            "cards": [
                {"icon_path": "/home/pi/ai-hub/asset/gesture_fist.svg", "title": "Fist", "desc": "Pause · Close all five fingers, fist facing the camera"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_palm.svg", "title": "Open Palm", "desc": "Play · Spread all five fingers, palm facing the camera"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_left.svg", "title": "Swipe Left", "desc": "Rewind 5s · Raise the index finger like “1” and move the whole hand left"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_right.svg", "title": "Swipe Right", "desc": "Forward 5s · Raise the index finger like “1” and move the whole hand right"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_up.svg", "title": "Swipe Up", "desc": "Volume +5% · Raise the index finger like “1” and move the whole hand up"},
                {"icon_path": "/home/pi/ai-hub/asset/gesture_down.svg", "title": "Swipe Down", "desc": "Volume -5% · Raise the index finger like “1” and move the whole hand down"},
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
            "tip": "提示: 打开项目后，点击\"说一句\"按钮说话，或呼叫\"小远同学\"唤醒",
            "tip2": "建议: 语音环境尽量安静；也可以直接使用文本输入",
            "cards": [
                {"title": "文档处理", "desc": "找文件 · 读合同 · 提要点\n例如：住房合同在哪？合同甲方是谁？"},
                {"title": "照片管理", "desc": "搜图 · 分类 · 建相册 · 加滤镜\n例如：找海边的照片，或把照片自动分类"},
                {"title": "影音管理", "desc": "下载 · 查找 · 播放\n例如：下载测试视频，或播放 oceans"},
                {"title": "NAS 问答", "desc": "随时提问，了解 NAS 内容与能力\n例如：你能做什么？NAS 里有什么？"},
            ],
        },
        "en": {
            "show_icon": False,
            "tip": "Tip: Open the project, tap \"Say One Sentence\" to speak, or use the wake word",
            "tip2": "Note: Use a quiet environment for better ASR, or type directly",
            "cards": [
                {"title": "Document Tasks", "desc": "Find files · Read contracts · Summarize\nExample: Where is the housing contract? Who is Party A?"},
                {"title": "Photo Management", "desc": "Search · Classify · Create albums · Filters\nExample: Find beach photos or classify the album"},
                {"title": "Media Management", "desc": "Download · Find · Play\nExample: Download the test video or play oceans"},
                {"title": "Ask NAS", "desc": "Ask about NAS content and capabilities\nExample: What can you do? What is in NAS?"},
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
        intro="智能NAS系统以CasaOS服务、OpenClaw智能体为核心，通过语音或文本下达指令，系统自动规划并调用工具，完成文件管理、相册整理、影音下载、知识问答与图片处理，带来“一句话搞定”的智能交互体验。",
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
        tip = (data.get("tip", "") or "").strip()
        tip2 = (data.get("tip2", "") or "").strip()
        if tip and tip2:
            merged_tip = f"{tip}\n{tip2}"
        else:
            merged_tip = tip or tip2
        self.guide_tip.setText(merged_tip)
        self.guide_tip2.clear()
        self.guide_tip2.setVisible(False)

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


class SystemStatusPanel(QGroupBox):
    def __init__(self, lang: str, parent=None):
        super().__init__(parent)
        self.lang = lang
        self._cpu_prev_total = 0
        self._cpu_prev_idle = 0

        self.setObjectName("systemStatusPanel")
        self._build_ui()
        self.set_language(lang)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.refresh()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.memory_group = QGroupBox()
        self.memory_group.setObjectName("statusSubGroup")
        mem_layout = QVBoxLayout(self.memory_group)
        mem_layout.setContentsMargins(12, 12, 12, 12)
        mem_layout.setSpacing(10)

        self.metric_rows = {
            "ram": self._create_metric_row("ram"),
            "disk": self._create_metric_row("disk"),
            "cpu": self._create_metric_row("cpu"),
        }
        for key in ("ram", "disk", "cpu"):
            row = self.metric_rows[key]
            mem_layout.addWidget(row["wrap"])

        self.hardware_group = QGroupBox()
        self.hardware_group.setObjectName("statusSubGroup")
        hw_layout = QGridLayout(self.hardware_group)
        hw_layout.setContentsMargins(12, 12, 12, 12)
        hw_layout.setHorizontalSpacing(10)
        hw_layout.setVerticalSpacing(8)
        hw_layout.setColumnMinimumWidth(0, 84)
        hw_layout.setColumnStretch(0, 0)
        hw_layout.setColumnStretch(1, 1)

        self.hw_labels = {
            "chip": QLabel(),
            "device": QLabel(),
            "os": QLabel(),
            "cpu_model": QLabel(),
        }
        self.hw_values = {
            "chip": QLabel(),
            "device": QLabel(),
            "os": QLabel(),
            "cpu_model": QLabel(),
        }

        keys = ("chip", "device", "os", "cpu_model")
        for row, key in enumerate(keys):
            name_label = self.hw_labels[key]
            name_label.setObjectName("statusLabel")
            name_label.setFixedWidth(86)
            value_label = self.hw_values[key]
            value_label.setObjectName("statusValueText")
            value_label.setWordWrap(False)
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            hw_layout.addWidget(name_label, row, 0, Qt.AlignVCenter)
            hw_layout.addWidget(value_label, row, 1, Qt.AlignVCenter)

        hw_layout.setColumnMinimumWidth(0, 86)
        hw_layout.setColumnStretch(1, 1)

        root.addWidget(self.memory_group, 2)
        root.addWidget(self.hardware_group, 3)

    def _create_metric_row(self, key: str):
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        name = QLabel()
        name.setObjectName("statusLabel")
        name.setFixedWidth(52)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar_name = {
            "ram": "statusBarRam",
            "disk": "statusBarDisk",
            "cpu": "statusBarCpu",
        }.get(key, "statusBar")
        bar.setObjectName(bar_name)

        value = QLabel("--")
        value_name = {
            "ram": "statusValueRam",
            "disk": "statusValueDisk",
            "cpu": "statusValueCpu",
        }.get(key, "statusValueText")
        value.setObjectName(value_name)
        value.setFixedWidth(56)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(name)
        layout.addWidget(bar, 1)
        layout.addWidget(value)
        return {"wrap": wrap, "name": name, "bar": bar, "value": value}

    def set_language(self, lang: str):
        self.lang = lang
        self.setTitle(T(lang, "system_status"))
        self.memory_group.setTitle(T(lang, "memory"))
        self.hardware_group.setTitle(T(lang, "hardware"))
        for key in ("ram", "disk", "cpu"):
            self.metric_rows[key]["name"].setText(T(lang, key))
        for key in ("chip", "device", "os", "cpu_model"):
            self.hw_labels[key].setText(f"{T(lang, key)}:")

    def refresh(self):
        ram_pct = self._read_ram_percent()
        disk_pct = self._read_disk_percent()
        cpu_pct = self._read_cpu_percent()

        self._set_metric("ram", ram_pct)
        self._set_metric("disk", disk_pct)
        self._set_metric("cpu", cpu_pct)

        # Showroom mode: keep hardware labels fixed and stable.
        self.hw_values["chip"].setText("Qualcomm QCS6490")
        self.hw_values["device"].setText("Quectel Pi H1")
        self.hw_values["os"].setText("Debian GNU/Linux 13 (trixie)")
        self.hw_values["cpu_model"].setText("4x Cortex-A55 + 4x Cortex-A78")

    def _set_metric(self, key: str, value: Optional[float]):
        row = self.metric_rows[key]
        if value is None:
            row["bar"].setValue(0)
            row["value"].setText("--")
            return
        pct = max(0, min(100, int(round(value))))
        row["bar"].setValue(pct)
        row["value"].setText(f"{pct}%")

    def _read_ram_percent(self) -> Optional[float]:
        info = {}
        try:
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    parts = v.strip().split()
                    if parts:
                        info[k] = int(parts[0])
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", 0)
            if total <= 0:
                return None
            used = max(0, total - avail)
            return used * 100.0 / total
        except Exception:
            return None

    def _read_disk_percent(self) -> Optional[float]:
        try:
            usage = shutil.disk_usage("/")
            if usage.total <= 0:
                return None
            return usage.used * 100.0 / usage.total
        except Exception:
            return None

    def _read_cpu_percent(self) -> Optional[float]:
        try:
            with open("/proc/stat", "r", encoding="utf-8", errors="ignore") as fp:
                first = fp.readline().strip()
            if not first.startswith("cpu "):
                return None
            values = [int(x) for x in first.split()[1:]]
            if len(values) < 4:
                return None
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            if self._cpu_prev_total == 0:
                self._cpu_prev_total = total
                self._cpu_prev_idle = idle
                return 0.0
            delta_total = total - self._cpu_prev_total
            delta_idle = idle - self._cpu_prev_idle
            self._cpu_prev_total = total
            self._cpu_prev_idle = idle
            if delta_total <= 0:
                return None
            return max(0.0, (delta_total - delta_idle) * 100.0 / delta_total)
        except Exception:
            return None

    def _read_npu_percent(self) -> Optional[float]:
        for path in (
            "/sys/class/qcom-npu/load",
            "/sys/class/devfreq/soc:qcom-npu/load",
            "/sys/class/devfreq/soc:qcom-nsp/load",
        ):
            try:
                if not os.path.exists(path):
                    continue
                text = open(path, "r", encoding="utf-8", errors="ignore").read().strip()
                if not text:
                    continue
                raw = float(text)
                return raw / 10.0 if raw > 100 else raw
            except Exception:
                continue
        return None

    def _read_device_info(self):
        unknown = T(self.lang, "unknown")
        model = ""
        for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
            try:
                if os.path.exists(path):
                    model = open(path, "r", encoding="utf-8", errors="ignore").read().replace("\x00", "").strip()
                    if model:
                        break
            except Exception:
                continue
        if not model:
            model = unknown

        if model.lower() == "quectel technologies, inc. quecpi alpha":
            model = "Quectel Pi H1"

        chip = unknown
        lower = model.lower()
        if "qcm" in lower:
            token = next((part for part in model.replace("/", " ").split() if part.lower().startswith("qcm")), "")
            chip = token.upper() if token else "QCM"
        elif "quecpi alpha" in lower:
            chip = "Qualcomm QCM6490"
        elif "sg560d" in lower:
            chip = "Qualcomm QCM6490"
        else:
            cpu_info = self._read_cpuinfo_map()
            for key in ("Hardware", "Model"):
                value = cpu_info.get(key, "")
                if value and value.lower() != "unknown":
                    chip = value
                    break

        return chip, model

    def _read_os_name(self) -> str:
        unknown = T(self.lang, "unknown")
        try:
            with open("/etc/os-release", "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    if line.startswith("PRETTY_NAME="):
                        value = line.split("=", 1)[1].strip().strip('"')
                        if value:
                            return value
        except Exception:
            pass
        return unknown

    def _read_cpuinfo_map(self):
        data = {}
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key and val and key not in data:
                        data[key] = val
        except Exception:
            pass
        return data

    def _read_cpu_model(self) -> str:
        unknown = T(self.lang, "unknown")
        data = self._read_cpuinfo_map()
        for key in ("model name", "Processor", "Hardware", "Model"):
            value = data.get(key, "").strip()
            if value:
                return value
        part_model = self._infer_cpu_model_from_parts()
        if part_model:
            return part_model
        machine = platform.machine().strip()
        if machine:
            return machine
        return unknown

    def _infer_cpu_model_from_parts(self) -> str:
        part_to_name = {
            "0xd03": "Cortex-A53",
            "0xd05": "Cortex-A55",
            "0xd08": "Cortex-A72",
            "0xd09": "Cortex-A73",
            "0xd0a": "Cortex-A75",
            "0xd0b": "Cortex-A76",
            "0xd0d": "Cortex-A77",
            "0xd41": "Cortex-A78",
        }
        counts = {}
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    if not line.startswith("CPU part"):
                        continue
                    raw = line.split(":", 1)[1].strip().lower()
                    name = part_to_name.get(raw)
                    if not name:
                        continue
                    counts[name] = counts.get(name, 0) + 1
        except Exception:
            return ""

        if not counts:
            return ""
        parts = [f"{count}x {name}" for name, count in sorted(counts.items(), key=lambda kv: kv[0])]
        return " + ".join(parts)


class HubWindow(QMainWindow):
    LAUNCH_OUTPUT_TIMEOUT_MS = 45000
    HANDOFF_DELAY_MS = 2200

    def __init__(self):
        super().__init__()
        self.apps = APP_SPECS
        self.active_process: Optional[QProcess] = None
        self.active_app: Optional[AppSpec] = None
        self._launch_watchdog = QTimer(self)
        self._launch_watchdog.setSingleShot(True)
        self._launch_watchdog.timeout.connect(self._on_launch_watchdog_timeout)
        self._handoff_timer = QTimer(self)
        self._handoff_timer.setSingleShot(True)
        self._handoff_timer.timeout.connect(self._handoff_to_child)
        self._launch_pending = False
        self._child_has_output = False
        self._handoff_done = False
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

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)

        self.logo_label = QLabel("QUECTEL")
        self.logo_label.setObjectName("brandLogo")
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setFixedSize(146, 44)

        logo_pix = QPixmap("/home/pi/ai-hub/asset/image.png")
        if not logo_pix.isNull():
            self.logo_label.setText("")
            self.logo_label.setStyleSheet("background: transparent; border: none;")
            logo_pix = self._make_logo_transparent(logo_pix)
            self.logo_label.setPixmap(logo_pix.scaled(140, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        title = QLabel("AI Hub")
        title.setStyleSheet("font-size: 23px; font-weight: 800;")
        brand_row.addWidget(self.logo_label)
        brand_row.addWidget(title)
        brand_row.addStretch()

        self.sub_label = QLabel(T(self.lang, "modules"))
        self.sub_label.setObjectName("muted")

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self.on_app_selected)

        for spec in self.apps:
            item = QListWidgetItem(f"{spec.order:02d}  {display_title(spec, self.lang)}")
            item.setData(Qt.UserRole, spec.app_id)
            self.list_widget.addItem(item)

        side_layout.addLayout(brand_row)
        side_layout.addWidget(self.sub_label)
        side_layout.addWidget(self.list_widget, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # App details: intro only, actions are moved to preview toolbar.
        self.header_group = QGroupBox()
        self.header_group.setObjectName("appDetailsPanel")
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
        self.desc_label.setObjectName("appDetailsText")
        self.desc_label.setWordWrap(True)
        self.badge_label = QLabel("")
        self.badge_label.setObjectName("statusValue")
        self.badge_label.setVisible(False)

        header_layout.addWidget(self.desc_label)
        header_layout.addWidget(self.badge_label, 0, Qt.AlignLeft)

        self.nas_panel = NasPanel(self)
        self.nas_panel.attach_toolbar_buttons(self.open_btn, self.lang_btn)

        self.log_toggle_btn = QPushButton(T(self.lang, "show_log"))
        self.log_toggle_btn.setObjectName("logToggleButton")
        self.log_toggle_btn.setFixedWidth(120)
        self.log_toggle_btn.clicked.connect(self.toggle_log_visibility)

        self.proc_log = QTextEdit()
        self.proc_log.setReadOnly(True)
        self.proc_log.document().setMaximumBlockCount(2000)
        self.proc_log.setMinimumHeight(110)
        self.proc_log.setPlaceholderText(T(self.lang, "proc_log"))

        self.system_panel = SystemStatusPanel(self.lang, self)
        self.log_stack = QStackedWidget()
        self.log_stack.addWidget(self.system_panel)
        self.log_stack.addWidget(self.proc_log)
        self.log_stack.setCurrentWidget(self.system_panel)

        content_layout.addWidget(self.header_group)
        content_layout.addWidget(self.nas_panel, 3)
        content_layout.addWidget(self.log_toggle_btn)
        content_layout.addWidget(self.log_stack, 1)
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
        self.system_panel.set_language(lang)
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
        showing_log = self.log_stack.currentWidget() is self.proc_log
        self.log_toggle_btn.setText(T(self.lang, "hide_log" if showing_log else "show_log"))

    def toggle_log_visibility(self):
        if self.log_stack.currentWidget() is self.proc_log:
            self.log_stack.setCurrentWidget(self.system_panel)
        else:
            self.log_stack.setCurrentWidget(self.proc_log)
        self._update_log_toggle()

    def toggle_language(self):
        self.lang = "en" if self.lang == "zh" else "zh"
        save_lang(self.lang)
        self._apply_language()

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow { background-color: #060b1a; }
            QWidget { color: #e2e8f0; font-family: 'DejaVu Sans'; font-size: 17px; }
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
            QGroupBox#appDetailsPanel::title {
                font-size: 21px;
                font-weight: 800;
            }
            QGroupBox#guidePanel {
                background-color: #111827;
                border: 1px solid #334155;
                border-radius: 16px;
            }
            QGroupBox#guidePanel::title {
                color: #f8fafc;
                font-size: 22px;
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
                font-size: 20px;
            }
            QLabel#appDetailsText {
                font-size: 19px;
                line-height: 1.5;
            }
            QLabel#guideTip {
                color: #dbeafe;
                border: 1px solid #3b82f6;
                border-radius: 8px;
                padding: 6px 8px;
                background-color: #1e3a8a;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#guideTipSecondary {
                color: #cbd5e1;
                border: 1px solid #475569;
                border-radius: 12px;
                padding: 9px 12px;
                background-color: #0f172a;
                font-size: 17px;
            }
            QFrame#guideCard {
                border: 1px solid #334155;
                border-radius: 14px;
                background-color: #0b1328;
            }
            QLabel#guideCardIcon {
                font-family: monospace;
                font-size: 28px;
                font-weight: 700;
                color: #dbeafe;
            }
            QLabel#guideCardTitle {
                font-size: 20px;
                font-weight: 800;
                color: #f8fafc;
            }
            QLabel#guideCardDesc {
                font-size: 18px;
                color: #cbd5e1;
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
                font-size: 20px;
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
                font-size: 17px;
                font-weight: 800;
                padding: 9px 18px;
                background-color: #2563eb;
                color: #f8fafc;
                border-color: #60a5fa;
            }
            QPushButton#openButton:hover { background-color: #1d4ed8; }
            QPushButton#openButton:pressed { background-color: #1e40af; }
            QPushButton#langButton {
                font-size: 16px;
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
            QLabel#brandLogo {
                color: #f8fafc;
                font-size: 14px;
                font-weight: 900;
                letter-spacing: 0.7px;
                background-color: #dc2626;
                border: 1px solid #fca5a5;
                border-radius: 8px;
                padding: 2px 8px;
            }
            QTextEdit {
                border: 1px solid #334155;
                border-radius: 10px;
                background-color: #020617;
                font-family: monospace;
            }
            QGroupBox#systemStatusPanel {
                background-color: #0b1328;
                border: 1px solid #334155;
                border-radius: 12px;
                margin-top: 10px;
            }
            QGroupBox#systemStatusPanel::title {
                font-size: 18px;
                font-weight: 800;
                left: 12px;
            }
            QGroupBox#statusSubGroup {
                background-color: #111827;
                border: 1px solid #374151;
                border-radius: 10px;
                margin-top: 8px;
            }
            QGroupBox#statusSubGroup::title {
                font-size: 15px;
                font-weight: 700;
                left: 10px;
            }
            QLabel#statusLabel {
                color: #bfdbfe;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#statusValueText {
                color: #e2e8f0;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#statusValueRam {
                color: #86efac;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#statusValueDisk {
                color: #7dd3fc;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#statusValueCpu {
                color: #fdba74;
                font-size: 14px;
                font-weight: 700;
            }
            QProgressBar#statusBar {
                border: 1px solid #334155;
                border-radius: 5px;
                background-color: #020617;
                height: 10px;
            }
            QProgressBar#statusBar::chunk {
                border-radius: 4px;
                background-color: #22c55e;
            }
            QProgressBar#statusBarRam {
                border: 1px solid #334155;
                border-radius: 5px;
                background-color: #020617;
                height: 10px;
            }
            QProgressBar#statusBarRam::chunk {
                border-radius: 4px;
                background-color: #22c55e;
            }
            QProgressBar#statusBarDisk {
                border: 1px solid #334155;
                border-radius: 5px;
                background-color: #020617;
                height: 10px;
            }
            QProgressBar#statusBarDisk::chunk {
                border-radius: 4px;
                background-color: #38bdf8;
            }
            QProgressBar#statusBarCpu {
                border: 1px solid #334155;
                border-radius: 5px;
                background-color: #020617;
                height: 10px;
            }
            QProgressBar#statusBarCpu::chunk {
                border-radius: 4px;
                background-color: #fb923c;
            }
            """
        )

    def _make_logo_transparent(self, pixmap: QPixmap) -> QPixmap:
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        width = image.width()
        height = image.height()
        min_x, min_y = width, height
        max_x, max_y = -1, -1
        for y in range(height):
            for x in range(width):
                c = image.pixelColor(x, y)
                if c.alpha() == 0:
                    continue
                delta = max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())
                if c.red() >= 228 and c.green() >= 228 and c.blue() >= 228 and delta <= 18:
                    image.setPixelColor(x, y, QColor(c.red(), c.green(), c.blue(), 0))
                    continue
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

                # The source artwork uses black lettering. Make it readable on
                # the dark shell while preserving the red brand mark.
                if c.red() <= 80 and c.green() <= 80 and c.blue() <= 80:
                    image.setPixelColor(x, y, QColor(241, 245, 249, c.alpha()))

        if max_x >= min_x and max_y >= min_y:
            padding = 4
            left = max(0, min_x - padding)
            top = max(0, min_y - padding)
            right = min(width, max_x + padding + 1)
            bottom = min(height, max_y + padding + 1)
            image = image.copy(left, top, right - left, bottom - top)
        return QPixmap.fromImage(image)

    def _set_badge(self, text: str, bg: str, fg: str = "#08111f"):
        self.badge_label.setText(text)
        self.badge_label.setVisible(bool(text))
        if text:
            self.badge_label.setStyleSheet(
                f"background-color: {bg}; color: {fg}; font-weight: 700; padding: 4px 10px; border-radius: 8px;"
            )

    def _handoff_to_child(self):
        if self._handoff_done:
            return
        if not self._is_process_running():
            return
        self._handoff_done = True
        self.hide()

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

    def _open_url_fullscreen_preferred(self, target_url: str) -> bool:
        candidates = ["firefox", "firefox-esr", "chromium-browser", "chromium", "google-chrome", "google-chrome-stable"]
        for binary in candidates:
            path = shutil.which(binary)
            if not path:
                continue
            if "firefox" in binary:
                launch_modes = (["--new-window", target_url],)
            else:
                launch_modes = (["--new-window", "--start-maximized", target_url], ["--new-window", target_url])
            for args in launch_modes:
                try:
                    subprocess.Popen(
                        [path, *args],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return True
                except Exception:
                    continue
        return False

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

    def force_stop_active(self):
        self._force_stop_active_process(log_prefix="[force-stop]")

    def _force_stop_active_process(self, log_prefix: str = "[stop]", bring_to_front: bool = True):
        if not self._is_process_running() or not self.active_process:
            return

        title = display_title(self.active_app, self.lang) if self.active_app else "-"
        self.proc_log.append(f"{log_prefix} {title}")
        self._launch_watchdog.stop()
        self._handoff_timer.stop()
        self._launch_pending = False
        self._handoff_done = False

        proc = self.active_process
        proc.terminate()
        if not proc.waitForFinished(2500):
            proc.kill()
            proc.waitForFinished(1500)

        self.active_process = None
        self.active_app = None
        if bring_to_front:
            self._bring_to_front()
        self.on_app_selected(self.list_widget.currentRow())

    def _on_launch_watchdog_timeout(self):
        if not self._launch_pending:
            return
        if not self._is_process_running():
            self._launch_pending = False
            return
        if self._child_has_output:
            self._launch_pending = False
            return

        title = display_title(self.active_app, self.lang) if self.active_app else "-"
        self._force_stop_active_process(log_prefix="[launch-timeout]")
        QMessageBox.warning(self, T(self.lang, "notice"), T(self.lang, "launch_timeout", title=title))

    def launch_selected(self):
        spec = self._selected_spec()
        if not spec:
            return

        if spec.kind == "services":
            target_url = spec.launch_url or "http://127.0.0.1:28083"
            if spec.app_id == "ai_nas":
                target_url = self._resolve_ai_nas_url(target_url)
            opened = False
            if spec.app_id == "ai_nas":
                opened = self._open_url_fullscreen_preferred(target_url)
            if not opened and not QDesktopServices.openUrl(QUrl(target_url)):
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
        self._handoff_done = False
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
        self._child_has_output = False
        self._launch_pending = True
        self._launch_watchdog.start(self.LAUNCH_OUTPUT_TIMEOUT_MS)
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
            self._launch_pending = False
            self._launch_watchdog.stop()
            self.on_app_selected(self.list_widget.currentRow())

    def _on_child_started(self):
        name = display_title(self.active_app, self.lang) if self.active_app else "-"
        self._set_badge(T(self.lang, "opening", name=name), "#f59e0b")
        self.open_btn.setEnabled(False)
        # Keep Hub visible briefly as a launch transition, then hand off to child app.
        self._handoff_timer.start(self.HANDOFF_DELAY_MS)

    def _on_child_error(self, _err):
        if not self.active_process:
            return
        self.proc_log.append(f"[error] {self.active_process.errorString()}")

    def _read_child_stdout(self):
        if not self.active_process:
            return
        text = bytes(self.active_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self._child_has_output = True
            self._launch_pending = False
            self._launch_watchdog.stop()
            self.proc_log.append(text.rstrip())
            self._handoff_to_child()

    def _read_child_stderr(self):
        if not self.active_process:
            return
        text = bytes(self.active_process.readAllStandardError()).decode("utf-8", errors="replace")
        if text:
            self._child_has_output = True
            self._launch_pending = False
            self._launch_watchdog.stop()
            self.proc_log.append(text.rstrip())
            self._handoff_to_child()

    def _on_child_finished(self, exit_code, _status):
        name = display_title(self.active_app, self.lang) if self.active_app else "-"
        self.proc_log.append(f"[finished] {name}, exit={exit_code}")
        self._launch_pending = False
        self._launch_watchdog.stop()
        self._handoff_timer.stop()
        self._handoff_done = False
        self.active_process = None
        self.active_app = None
        self._bring_to_front()
        self.on_app_selected(self.list_widget.currentRow())

    def closeEvent(self, event):
        if self._is_process_running() and self.active_process:
            self._force_stop_active_process(log_prefix="[window-close]", bring_to_front=False)
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            event.accept()
            return
        if key == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            event.accept()
            return
        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    lock = QLockFile("/tmp/ai-hub.lock")
    lock.setStaleLockTime(0)
    if not lock.tryLock(50):
        QMessageBox.warning(None, "AI Hub", T(load_lang(), "hub_running"))
        return 1

    window = HubWindow()
    window.showFullScreen()
    exit_code = app.exec()
    lock.unlock()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
