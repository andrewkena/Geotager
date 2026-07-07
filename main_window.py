import os

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QMessageBox, QProgressDialog, QActionGroup, QAction,
    QApplication, QDialog, QTextBrowser,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor

from photo_panel import PhotoPanel
from geo_panel   import GeoPanel

VERSION = '0.2'
AUTHOR  = 'andrewkena'


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
        self.setWindowTitle(f'Geotager  v{VERSION}')
        self.setMinimumSize(1100, 650)
        self._build_menu()
        self._build_ui()

    # ------------------------------------------------------------------
    # Menu

    def _build_menu(self):
        # Файл
        file_menu = self.menuBar().addMenu('Файл')

        open_photos = QAction('Открыть папку с фотографиями…', self)
        open_photos.setShortcut('Ctrl+O')
        open_photos.triggered.connect(lambda: self.photo_panel._pick_folder())
        file_menu.addAction(open_photos)

        open_geo = QAction('Открыть файл геопривязки…', self)
        open_geo.setShortcut('Ctrl+G')
        open_geo.triggered.connect(lambda: self.geo_panel._pick_file())
        file_menu.addAction(open_geo)

        # Вид
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

        # Справка
        help_menu = self.menuBar().addMenu('Справка')
        guide_act = QAction('Инструкция', self)
        guide_act.setShortcut('F1')
        guide_act.triggered.connect(self._show_guide)
        help_menu.addAction(guide_act)
        help_menu.addSeparator()
        about_act = QAction('О программе', self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

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

    def _show_guide(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Инструкция — Geotager')
        dlg.setMinimumSize(620, 540)
        dlg.resize(660, 580)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(f'''
<html><body style="font-family:sans-serif; font-size:13px; line-height:1.55;">
<h2 style="margin-bottom:4px;">Geotager v{VERSION} — Руководство пользователя</h2>
<hr style="border:none; border-top:1px solid #888; margin-bottom:10px;">

<h3>Назначение программы</h3>
<p>Geotager записывает GPS-координаты из текстового файла в EXIF-метаданные
фотографий. Координаты сопоставляются последовательно: первая строка геоданных
→ первому фото, вторая → второму и т.&nbsp;д. Оригинальные файлы не изменяются —
результат сохраняется в подпапку <b>geotag/</b>.</p>

<h3>Шаг 1. Фотографии</h3>
<p>Выберите папку через <b>Файл → Открыть папку с фотографиями</b> или кнопку
<b>Выбрать папку</b> (<i>Ctrl+O</i>). Поддерживаются форматы JPEG, PNG, TIFF,
BMP, WebP.</p>
<ul>
  <li>Слайдер <b>Размер</b> изменяет масштаб миниатюр.</li>
  <li>Список <b>Сортировка</b> — порядок обработки фото.</li>
  <li><b>Правая кнопка мыши</b> по фото → <i>Исключить фото</i> (серое, перечёркнутое).
      Повторно — вернуть обратно.</li>
  <li><b>Двойной клик</b> — полноэкранный просмотр с EXIF-данными.</li>
</ul>

<h3>Шаг 2. Файл геоданных</h3>
<p>Выберите файл через <b>Файл → Открыть файл геопривязки</b> или кнопку
<b>Выбрать файл</b> (<i>Ctrl+G</i>). В диалоге настройте:</p>
<ul>
  <li><b>Разделитель</b> — запятая, точка с запятой, табуляция или пробел.</li>
  <li><b>Пропустить строк</b> — количество строк заголовка в начале файла.</li>
  <li><b>Удалить пустые столбцы</b> — убирает столбцы без данных.</li>
  <li><b>Столбцы данных</b> — укажите, какой столбец содержит широту,
      долготу и высоту (высота необязательна).</li>
  <li><b>Показывать в таблице</b> — отметьте столбцы для отображения
      при сопоставлении.</li>
</ul>
<p>Строки с дублирующимися координатами подсвечиваются жёлтым цветом.</p>

<h3>Шаг 3. Карта</h3>
<p>Кнопка <b>Показать на карте</b> открывает интерактивную карту
(подложка — Google Спутник, можно переключить в правом верхнем углу).</p>
<ul>
  <li>Список точек расположен справа от карты.</li>
  <li><b>Наведение</b> на строку списка — маркер подсвечивается на карте.</li>
  <li><b>Правая кнопка мыши</b> по строке → <i>Исключить точку</i>: маркер
      становится серым. Повторно — вернуть.</li>
</ul>

<h3>Шаг 4. Запись геотегов</h3>
<p>Нажмите <b>Сопоставить и записать геотеги →</b>. Откроется таблица с
попарным соответствием фото и геоточек. Проверьте и подтвердите — файлы
сохранятся в папку <b>geotag/</b> внутри папки с фотографиями.</p>
<p>Если файлы уже существуют, программа запросит подтверждение на перезапись.</p>

<h3>Горячие клавиши</h3>
<table cellspacing="0" cellpadding="3">
  <tr><td><b>Ctrl+O</b></td><td>&nbsp;Открыть папку с фотографиями</td></tr>
  <tr><td><b>Ctrl+G</b></td><td>&nbsp;Открыть файл геопривязки</td></tr>
  <tr><td><b>F1</b></td><td>&nbsp;Инструкция</td></tr>
</table>
</body></html>''')

        lay.addWidget(browser, 1)

        close_btn = QPushButton('Закрыть')
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)

        dlg.exec_()

    def _show_about(self):
        QMessageBox.information(
            self, 'О программе',
            f'<b>Geotager</b> v{VERSION}<br>'
            f'Автор: {AUTHOR}<br><br>'
            f'Запись GPS-координат в EXIF фотографий.',
        )

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
