from __future__ import annotations

import logging
import sys

# WebEngine 必须在 QApplication 创建之前导入（Qt 要求共享 OpenGL 上下文）
from app.ui import plotly_charts  # noqa: F401
from PyQt6.QtCore import QLockFile, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.config import APP_NAME, DATA_DIR, DB_PATH, AppConfig, ensure_dirs
from app.database import Database
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme, make_app_icon
from app.utils import exe_display_name, setup_logging

log = logging.getLogger(__name__)

PRIVACY_TEXT = (
    "欢迎使用电脑使用行为溯源监测系统。\n\n"
    "请放心：\n"
    "· 本程序纯本地离线运行，不会联网上传任何数据；\n"
    "· 使用时长、软件记录、文件日志、流量统计全部保存在本机数据库中；\n"
    "· 你可以随时在「设置」里更改数据保存位置、清理历史记录。\n\n"
    "点击「开始使用」即表示你了解以上说明。"
)


def main() -> int:
    ensure_dirs()
    setup_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("LocalFirst")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon())

    lock = QLockFile(str(DATA_DIR / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(2000):
        QMessageBox.information(
            None, APP_NAME, "程序已经在运行。\n请从系统托盘打开主界面。"
        )
        return 1

    db = Database(DB_PATH)
    db.init_schema()
    config = AppConfig.load()
    apply_theme(app, config.theme)
    plotly_charts.ensure_plotly_js()
    try:
        db.purge_old_logs(config.retention_days)
    except Exception:
        log.exception("cannot purge old logs")
    try:
        db.refresh_app_names(exe_display_name)
    except Exception:
        log.exception("cannot refresh app names")

    if db.get_meta("privacy_ack") != "1":
        box = QMessageBox()
        box.setWindowTitle("隐私说明")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(PRIVACY_TEXT)
        box.addButton("开始使用", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        db.set_meta("privacy_ack", "1")

    window = MainWindow(db, config)
    window.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())