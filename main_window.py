import os

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QMessageBox, QProgressDialog, QActionGroup, QAction,
    QApplication,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor

from photo_panel import PhotoPanel
from geo_panel   import GeoPanel


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------

def _make_dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(53, 53, 53))
    p.setColor(QPalette.WindowText,      Qt.white)
    p.setColor(QPalette.Base,            QColor(35, 35, 35))
    p.setColor(QPalette.AlternateBase,   QColor(45, 45, 45))
    p.setColor(QPalette.ToolTipBase,     QColor(25, 25, 25))
    p.setColor(QPalette.ToolTipText,     Qt.white)
    p.setColor(QPalette.Text,            Qt.white)
    p.setColor(QPalette.Button,          QColor(60, 60, 60))
    p.setColor(QPalette.ButtonText,      Qt.white)
    p.setColor(QPalette.BrightText,      Qt.red)
    p.setColor(QPalette.Link,            QColor(42, 130, 218))
    p.setColor(QPalette.Highlight,       QColor(42, 130, 218))
    p.setColor(QPalette.HighlightedText, Qt.black)
    p.setColor(QPalette.Disabled, QPalette.Text,       QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    return p


def _make_light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(240, 240, 240))
    p.setColor(QPalette.WindowText,      Qt.black)
    p.setColor(QPalette.Base,            Qt.white)
    p.setColor(QPalette.AlternateBase,   QColor(233, 231, 227))
    p.setColor(QPalette.ToolTipBase,     Qt.white)
    p.setColor(QPalette.ToolTipText,     Qt.black)
    p.setColor(QPalette.Text,            Qt.black)
    p.setColor(QPalette.Button,          QColor(240, 240, 240))
    p.setColor(QPalette.ButtonText,      Qt.black)
    p.setColor(QPalette.Highlight,       QColor(0, 120, 215))
    p.setColor(QPalette.HighlightedText, Qt.white)
    return p


def _is_system_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
        ) as k:
            val, _ = winreg.QueryValueEx(k, 'AppsUseDarkTheme')
            return bool(val)
    except Exception:
        return False


def apply_theme(theme: str):
    app = QApplication.instance()
    if not app:
        return
    app.setStyle('Fusion')
    resolved = 'dark' if (theme == 'system' and _is_system_dark()) else \
               ('dark' if theme == 'dark' else 'light')
    app.setPalette(_make_dark_palette() if resolved == 'dark' else _make_light_palette())


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Geotager')
        self.setMinimumSize(1100, 650)
        self._build_menu()
        self._build_ui()

    # ------------------------------------------------------------------
    # Menu

    def _build_menu(self):
        view = self.menuBar().addMenu('Вид')
        theme_menu = view.addMenu('Тема')
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for label, key in [('Системная', 'system'), ('Светлая', 'light'), ('Тёмная', 'dark')]:
            a = QAction(label, self, checkable=True)
            a.setData(key)
            self._theme_group.addAction(a)
            theme_menu.addAction(a)
            if key == 'system':
                a.setChecked(True)
        self._theme_group.triggered.connect(lambda a: apply_theme(a.data()))

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)
        self.photo_panel = PhotoPanel()
        self.geo_panel   = GeoPanel()
        splitter.addWidget(self.photo_panel)
        splitter.addWidget(self.geo_panel)
        splitter.setSizes([560, 540])
        lay.addWidget(splitter, 1)

        btn_row = QHBoxLayout()
        self.match_btn = QPushButton('Сопоставить и записать геотеги  →')
        self.match_btn.setMinimumHeight(40)
        self.match_btn.setStyleSheet('font-size:13px; font-weight:bold; padding: 0 24px;')
        self.match_btn.clicked.connect(self._on_match)
        btn_row.addStretch()
        btn_row.addWidget(self.match_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Match / write

    def _on_match(self):
        photos = self.photo_panel.get_photos()
        headers, geo_data, columns = self.geo_panel.get_data()

        if not photos:
            QMessageBox.warning(self, 'Нет фотографий',
                                'Сначала выберите папку с фотографиями.')
            return
        if not geo_data:
            QMessageBox.warning(self, 'Нет геоданных',
                                'Сначала загрузите файл с геоданными.')
            return

        display_cols = self.geo_panel.get_display_columns()

        from dialogs import MatchDialog
        dlg = MatchDialog(photos, geo_data, headers, columns, display_cols, self)
        if dlg.exec_() != dlg.Accepted:
            return

        self._write_tags(photos, geo_data, columns)

    def _write_tags(self, photos, geo_data, columns):
        from geo_writer import write_gps_exif

        folder  = self.photo_panel.get_folder()
        out_dir = os.path.join(folder, 'geotag')
        count   = min(len(photos), len(geo_data))

        # Confirmation if output files already exist
        if os.path.isdir(out_dir):
            existing = [photos[i][1] for i in range(count)
                        if os.path.exists(os.path.join(out_dir, photos[i][1]))]
            if existing:
                reply = QMessageBox.question(
                    self, 'Перезапись геоданных',
                    f'В папке geotag/ уже {len(existing)} файл(ов).\n'
                    f'Перезаписать их с новыми геоданными?',
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

        os.makedirs(out_dir, exist_ok=True)

        prog = QProgressDialog('Записываю геоданные…', 'Отмена', 0, count, self)
        prog.setWindowTitle('Geotager')
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        errors, done = [], 0
        for i in range(count):
            if prog.wasCanceled():
                break
            prog.setValue(i)
            src, fname = photos[i]
            dst = os.path.join(out_dir, fname)
            row = geo_data[i]
            try:
                lat = float(row[columns['lat']].strip())
                lon = float(row[columns['lon']].strip())
                alt = None
                if columns.get('alt') is not None:
                    try:
                        alt = float(row[columns['alt']].strip())
                    except (ValueError, IndexError, TypeError):
                        pass
                write_gps_exif(src, dst, lat, lon, alt)
                done += 1
            except Exception as exc:
                errors.append(f'{fname}: {exc}')
        prog.setValue(count)

        if errors:
            QMessageBox.warning(
                self, 'Готово с ошибками',
                f'Обработано: {done}/{count}\n\nОшибки ({len(errors)}):\n' +
                '\n'.join(errors[:15]),
            )
        else:
            # Custom dialog with "Open folder" button
            msg = QMessageBox(self)
            msg.setWindowTitle('Готово')
            msg.setIcon(QMessageBox.Information)
            msg.setText(f'Успешно записано: {done} фото')
            msg.setInformativeText(f'Папка: {out_dir}')
            ok_btn   = msg.addButton('OK', QMessageBox.AcceptRole)
            open_btn = msg.addButton('Открыть папку', QMessageBox.ActionRole)
            msg.setDefaultButton(ok_btn)
            msg.exec_()
            if msg.clickedButton() == open_btn:
                os.startfile(out_dir)
