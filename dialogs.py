import os
import csv
import io
import piexif
from datetime import datetime

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QRadioButton, QButtonGroup, QGroupBox, QHeaderView, QScrollArea,
    QCheckBox, QSpinBox, QApplication, QWidget, QSplitter, QMenu,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QPixmap, QImage, QColor, QPainter, QFont, QBrush
from PIL import Image as PilImage


# ---------------------------------------------------------------------------
# Shared utilities (imported by geo_panel too)
# ---------------------------------------------------------------------------

def _find_duplicates(rows: list) -> set:
    seen: dict = {}
    dups: set  = set()
    for i, row in enumerate(rows):
        key = tuple(v.strip() for v in row)
        if key in seen:
            dups.add(i)
            dups.add(seen[key])
        else:
            seen[key] = i
    return dups


_DUP_COLOR = QColor(220, 70, 70, 100)


def _apply_remove_empty(headers: list, data: list):
    if not data:
        return headers, data
    keep = [c for c in range(len(headers))
            if any(c < len(row) and row[c].strip() for row in data)]
    return [headers[c] for c in keep], \
           [[row[c] if c < len(row) else '' for c in keep] for row in data]


def _col_letter(n: int) -> str:
    """0-based index → Excel-style column letter: 0→A, 25→Z, 26→AA …"""
    s = ''
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------------------
# EXIF / overlay helpers for full-size viewer
# ---------------------------------------------------------------------------

def _dms_to_decimal(dms, ref) -> float | None:
    if not dms or len(dms) < 3:
        return None
    try:
        d = dms[0][0] / dms[0][1]
        m = dms[1][0] / dms[1][1]
        s = dms[2][0] / dms[2][1]
        result = d + m / 60 + s / 3600
        r = ref.decode('ascii', errors='ignore') if isinstance(ref, bytes) else str(ref)
        if r.strip().upper() in ('S', 'W'):
            result = -result
        return result
    except (ZeroDivisionError, IndexError, TypeError):
        return None


def _get_photo_exif_info(path: str) -> dict:
    info = {'filename': os.path.basename(path),
            'date': None, 'lat': None, 'lon': None, 'alt': None}
    try:
        exif = piexif.load(path)
        date_b = (exif.get('Exif', {}).get(piexif.ExifIFD.DateTimeOriginal) or
                  exif.get('0th',  {}).get(piexif.ImageIFD.DateTime))
        if date_b:
            info['date'] = date_b.decode('ascii', errors='ignore').strip()

        gps = exif.get('GPS', {})
        lat = _dms_to_decimal(gps.get(piexif.GPSIFD.GPSLatitude),
                               gps.get(piexif.GPSIFD.GPSLatitudeRef,  b'N'))
        lon = _dms_to_decimal(gps.get(piexif.GPSIFD.GPSLongitude),
                               gps.get(piexif.GPSIFD.GPSLongitudeRef, b'E'))
        if lat is not None:
            info['lat'] = lat
            info['lon'] = lon
        alt_raw = gps.get(piexif.GPSIFD.GPSAltitude)
        if alt_raw:
            av = alt_raw[0] / alt_raw[1]
            info['alt'] = -av if gps.get(piexif.GPSIFD.GPSAltitudeRef, 0) == 1 else av
    except Exception:
        pass

    if not info['date']:
        try:
            info['date'] = datetime.fromtimestamp(
                os.path.getmtime(path)).strftime('%Y:%m:%d %H:%M:%S')
        except Exception:
            pass
    return info


def _draw_info_overlay(px: QPixmap, info: dict) -> QPixmap:
    """Semi-transparent info box: filename, date, coordinates."""
    lines = [info['filename']]
    ds = info.get('date', '')
    if ds:
        try:
            lines.append(datetime.strptime(ds.strip(), '%Y:%m:%d %H:%M:%S')
                         .strftime('%d.%m.%Y   %H:%M:%S'))
        except ValueError:
            lines.append(ds)
    lat, lon, alt = info.get('lat'), info.get('lon'), info.get('alt')
    if lat is not None and lon is not None:
        coord = f'{lat:+.6f},  {lon:+.6f}'
        if alt is not None:
            coord += f'   ↑ {alt:.1f} м'
        lines.append(coord)

    out = QPixmap(px)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)

    fs = max(12, min(18, px.width() // 55))
    font = QFont('Consolas', fs)
    p.setFont(font)
    fm = p.fontMetrics()
    line_h = fm.height() + 4
    pad = 10
    block_h = len(lines) * line_h + pad * 2
    block_w = max(fm.horizontalAdvance(l) for l in lines) + pad * 2
    x, y = pad, px.height() - block_h - pad

    p.setBrush(QColor(0, 0, 0, 170))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(x, y, block_w, block_h, 6, 6)

    p.setPen(Qt.white)
    for i, line in enumerate(lines):
        p.drawText(x + pad, y + pad + fm.ascent() + i * line_h, line)

    p.end()
    return out


# ---------------------------------------------------------------------------
# Delimiter / import dialog
# ---------------------------------------------------------------------------

class DelimiterDialog(QDialog):
    _DELIMS = [(',', 'Запятая  ,'), (';', 'Точка с зап.  ;'),
               ('\t', 'Табуляция'), (' ', 'Пробел'), ('|', 'Черта  |')]

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.headers: list = []
        self.data:    list = []
        self.setWindowTitle('Настройка импорта геоданных')
        self.setMinimumSize(1100, 640)
        w = parent.width() if parent else 1100
        self.resize(w, 680)
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        dg = QGroupBox('Разделитель')
        dl = QHBoxLayout(dg)
        self._bg = QButtonGroup(self)
        for i, (ch, lbl) in enumerate(self._DELIMS):
            btn = QRadioButton(lbl)
            if i == 0:
                btn.setChecked(True)
            self._bg.addButton(btn, i)
            dl.addWidget(btn)
        self._custom_btn  = QRadioButton('Другой:')
        self._custom_edit = QLineEdit()
        self._custom_edit.setMaximumWidth(36)
        self._bg.addButton(self._custom_btn, len(self._DELIMS))
        dl.addWidget(self._custom_btn)
        dl.addWidget(self._custom_edit)
        dl.addStretch()
        self._bg.buttonClicked.connect(lambda _: self._refresh())
        self._custom_edit.textChanged.connect(lambda _: self._refresh())
        lay.addWidget(dg)

        opt = QHBoxLayout()
        self._header_cb = QCheckBox('Первая строка — заголовки')
        self._header_cb.setChecked(True)
        self._header_cb.stateChanged.connect(lambda _: self._refresh())
        opt.addWidget(self._header_cb)
        opt.addSpacing(20)
        self._rm_empty_cb = QCheckBox('Удалить пустые столбцы')
        self._rm_empty_cb.stateChanged.connect(lambda _: self._refresh())
        opt.addWidget(self._rm_empty_cb)
        opt.addSpacing(20)
        opt.addWidget(QLabel('Пропустить строк с начала:'))
        self._skip_spin = QSpinBox()
        self._skip_spin.setRange(0, 999)
        self._skip_spin.setMaximumWidth(60)
        self._skip_spin.valueChanged.connect(lambda _: self._refresh())
        opt.addWidget(self._skip_spin)
        opt.addStretch()
        lay.addLayout(opt)

        lay.addWidget(QLabel('Предпросмотр (первые 20 строк; красным — дубликаты):'))
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview.setMaximumHeight(200)
        lay.addWidget(self.preview)

        cg = QGroupBox('Столбцы с координатами')
        cl = QHBoxLayout(cg)
        self._lat_cb = QComboBox()
        self._lon_cb = QComboBox()
        self._alt_cb = QComboBox()
        for lbl, w in [('Широта *:', self._lat_cb), ('Долгота *:', self._lon_cb),
                       ('Высота (опц.):', self._alt_cb)]:
            cl.addWidget(QLabel(lbl))
            cl.addWidget(w)
        cl.addStretch()
        lay.addWidget(cg)

        # Display column selector
        dg2 = QGroupBox('Столбцы в таблицу сопоставления')
        dg2_lay = QVBoxLayout(dg2)
        dg2_lay.setContentsMargins(6, 4, 6, 4)
        self._disp_scroll = QScrollArea()
        self._disp_scroll.setFixedHeight(34)
        self._disp_scroll.setWidgetResizable(True)
        self._disp_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._disp_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._disp_inner  = QWidget()
        self._disp_layout = QHBoxLayout(self._disp_inner)
        self._disp_layout.setContentsMargins(2, 1, 2, 1)
        self._disp_layout.setSpacing(10)
        self._disp_layout.addStretch()
        self._disp_scroll.setWidget(self._disp_inner)
        dg2_lay.addWidget(self._disp_scroll)
        self._disp_checks: dict = {}
        lay.addWidget(dg2)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('Применить')
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _delimiter(self) -> str:
        bid = self._bg.checkedId()
        if bid < len(self._DELIMS):
            return self._DELIMS[bid][0]
        return self._custom_edit.text() or ','

    def _refresh(self):
        sep = self._delimiter()
        try:
            with open(self.file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                content = f.read()
        except Exception:
            return

        rows_raw = list(csv.reader(io.StringIO(content), delimiter=sep))
        rows_raw = rows_raw[self._skip_spin.value():]

        if not rows_raw:
            self.headers, self.data = [], []
            self._update_preview()
            return

        if self._header_cb.isChecked():
            self.headers = [h.strip() for h in rows_raw[0]]
            raw_data = rows_raw[1:]
        else:
            max_c = max((len(r) for r in rows_raw), default=0)
            self.headers = [_col_letter(i) for i in range(max_c)]
            raw_data = rows_raw

        if self._rm_empty_cb.isChecked():
            self.headers, raw_data = _apply_remove_empty(self.headers, raw_data)

        self.data = raw_data
        self._update_preview()

    def _update_preview(self):
        self.preview.setColumnCount(len(self.headers))
        self.preview.setHorizontalHeaderLabels(self.headers)
        preview_rows = self.data[:20]
        self.preview.setRowCount(len(preview_rows))

        for r, row in enumerate(preview_rows):
            for c, val in enumerate(row[:len(self.headers)]):
                self.preview.setItem(r, c, QTableWidgetItem(val.strip()))

        for r in _find_duplicates(preview_rows):
            for c in range(len(self.headers)):
                item = self.preview.item(r, c)
                if item:
                    item.setBackground(_DUP_COLOR)

        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        for cb in (self._lat_cb, self._lon_cb):
            prev = cb.currentText()
            cb.clear()
            cb.addItems(self.headers)
            idx = cb.findText(prev)
            if idx >= 0:
                cb.setCurrentIndex(idx)

        prev_alt = self._alt_cb.currentText()
        self._alt_cb.clear()
        self._alt_cb.addItem('(нет)')
        self._alt_cb.addItems(self.headers)
        idx = self._alt_cb.findText(prev_alt)
        if idx >= 0:
            self._alt_cb.setCurrentIndex(idx)

        for i, h in enumerate(self.headers):
            hl = h.lower()
            if any(k in hl for k in ('lat', 'шир', 'latitude')):
                self._lat_cb.setCurrentIndex(i)
            elif any(k in hl for k in ('lon', 'lng', 'долг', 'longitude')):
                self._lon_cb.setCurrentIndex(i)
            elif any(k in hl for k in ('alt', 'ele', 'высо', 'height', 'altitude')):
                self._alt_cb.setCurrentIndex(i + 1)

        # Rebuild display-column checkboxes keyed by column index (handles duplicate names)
        first_time           = len(self._disp_checks) == 0
        prev_indices         = set(self._disp_checks.keys())
        prev_checked_indices = {i for i, cb in self._disp_checks.items() if cb.isChecked()}
        self._disp_checks.clear()
        while self._disp_layout.count():
            item = self._disp_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, h in enumerate(self.headers):
            cb = QCheckBox(h)
            # First load → all checked; known index → preserve state; new index → checked
            cb.setChecked(first_time or (i not in prev_indices) or (i in prev_checked_indices))
            self._disp_checks[i] = cb
            self._disp_layout.addWidget(cb)
        self._disp_layout.addStretch()

    def _on_ok(self):
        if self._lat_cb.count() == 0 or self._lon_cb.count() == 0:
            return
        self.accept()

    def get_result(self):
        alt_idx = self._alt_cb.currentIndex() - 1
        cols = {
            'lat': self._lat_cb.currentIndex(),
            'lon': self._lon_cb.currentIndex(),
            'alt': alt_idx if alt_idx >= 0 else None,
        }
        display_cols = sorted(i for i, cb in self._disp_checks.items() if cb.isChecked())
        return self._delimiter(), self.headers, self.data, cols, display_cols


# ---------------------------------------------------------------------------
# Match table dialog
# ---------------------------------------------------------------------------

class MatchDialog(QDialog):
    def __init__(self, photos, geo_rows, headers, columns,
                 display_cols=None, parent=None):
        super().__init__(parent)
        self.photos      = photos
        self.geo_rows    = geo_rows
        self.headers     = headers
        self.columns     = columns
        # display_cols: column indices to show (from checkboxes in geo panel)
        self.display_cols = display_cols if display_cols is not None else list(range(len(headers)))
        self.setWindowTitle('Сопоставление фото ↔ геоданные')
        self.setMinimumSize(900, 580)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        n = min(len(self.photos), len(self.geo_rows))
        info = QLabel(
            f'Фото: <b>{len(self.photos)}</b> &nbsp;|&nbsp; '
            f'Строк геоданных: <b>{len(self.geo_rows)}</b> &nbsp;|&nbsp; '
            f'Будет обработано: <b>{n}</b>'
        )
        info.setTextFormat(Qt.RichText)
        lay.addWidget(info)

        li  = self.columns['lat']
        oi  = self.columns['lon']
        ai  = self.columns.get('alt')
        has_alt = ai is not None

        # Extra cols: checked cols minus the required lat/lon/alt
        req = {li, oi, *([ai] if has_alt else [])}
        extra = [c for c in self.display_cols if c not in req]

        h_labels = ['#', 'Фотография', 'Широта', 'Долгота']
        if has_alt:
            h_labels.append('Высота')
        for c in extra:
            h_labels.append(self.headers[c] if c < len(self.headers) else f'Col{c}')

        t = QTableWidget(n, len(h_labels))
        t.setHorizontalHeaderLabels(h_labels)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.verticalHeader().setVisible(False)

        for i in range(n):
            _, fname = self.photos[i]
            row = self.geo_rows[i]
            t.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            t.setItem(i, 1, QTableWidgetItem(fname))
            t.setItem(i, 2, QTableWidgetItem(row[li].strip() if li < len(row) else ''))
            t.setItem(i, 3, QTableWidgetItem(row[oi].strip() if oi < len(row) else ''))
            off = 4
            if has_alt:
                t.setItem(i, off, QTableWidgetItem(row[ai].strip() if ai < len(row) else ''))
                off += 1
            for j, c in enumerate(extra):
                t.setItem(i, off + j, QTableWidgetItem(row[c].strip() if c < len(row) else ''))

        # Initial size then allow manual resize
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setMinimumSectionSize(60)
        lay.addWidget(t)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('Записать геотеги')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


# ---------------------------------------------------------------------------
# Full-size image viewer
# ---------------------------------------------------------------------------

class FullImageDialog(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        scroll.setWidget(lbl)
        lay.addWidget(scroll)

        close_btn = QPushButton('Закрыть')
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn)

        px = self._load_pixmap(path)
        if not px.isNull():
            screen = QApplication.primaryScreen().availableGeometry()
            max_w = int(screen.width()  * 0.9)
            max_h = int(screen.height() * 0.88)
            scaled = px.scaled(max_w - 40, max_h - 60,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # Draw overlay with EXIF info
            info = _get_photo_exif_info(path)
            scaled = _draw_info_overlay(scaled, info)
            lbl.setPixmap(scaled)
            lbl.resize(scaled.size())
            self.resize(scaled.width() + 40, scaled.height() + 60)
        else:
            lbl.setText('Не удалось загрузить изображение')
            self.resize(400, 300)

    @staticmethod
    def _load_pixmap(path: str) -> QPixmap:
        px = QPixmap(path)
        if not px.isNull():
            return px
        try:
            img = PilImage.open(path).convert('RGBA')
            data = img.tobytes('raw', 'RGBA')
            qi = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            return QPixmap.fromImage(qi)
        except Exception:
            return QPixmap()


# ---------------------------------------------------------------------------
# Batch rename dialog
# ---------------------------------------------------------------------------

class RenameDialog(QDialog):
    _DATE_FMTS = [
        ('YYYY-MM-DD',  '%Y-%m-%d'),
        ('YYYYMMDD',    '%Y%m%d'),
        ('DD.MM.YYYY',  '%d.%m.%Y'),
        ('YYYY_MM_DD',  '%Y_%m_%d'),
    ]
    _TIME_FMTS = [
        ('HHmmss',    '%H%M%S'),
        ('HH-mm-ss',  '%H-%M-%S'),
        ('HH.mm.ss',  '%H.%M.%S'),
    ]
    _PRESETS = [
        ('{name}_{n}',        'Имя + номер'),
        ('{n}',               'Только номер'),
        ('{date}_{time}_{n}', 'Дата + время + номер'),
        ('{date}_{n}',        'Дата + номер'),
        ('{date}_{name}',     'Дата + имя'),
        ('photo_{n}',         'photo_ + номер'),
        ('IMG_{n}',           'IMG_ + номер'),
    ]

    def __init__(self, photos: list, parent=None):
        super().__init__(parent)
        self._photos     = list(photos)   # [(path, name), ...]
        self._exif_cache = {}
        self.setWindowTitle('Пакетное переименование')
        self.setMinimumSize(860, 600)
        if parent:
            self.resize(max(parent.width(), 860), 680)
        self._build_ui()
        self._update_preview()

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # Template
        tg = QGroupBox('Шаблон имени')
        tl = QVBoxLayout(tg)

        pr = QHBoxLayout()
        pr.addWidget(QLabel('Быстрый выбор:'))
        self._preset_cb = QComboBox()
        for tmpl, label in self._PRESETS:
            self._preset_cb.addItem(label, tmpl)
        self._preset_cb.activated.connect(
            lambda idx: self._tmpl_edit.setText(self._preset_cb.itemData(idx)))
        pr.addWidget(self._preset_cb, 1)
        tl.addLayout(pr)

        tr = QHBoxLayout()
        tr.addWidget(QLabel('Шаблон:'))
        self._tmpl_edit = QLineEdit(self._PRESETS[0][0])
        self._tmpl_edit.textChanged.connect(self._update_preview)
        tr.addWidget(self._tmpl_edit, 1)
        tl.addLayout(tr)

        hint = QLabel(
            '<small>Токены:&nbsp; <b>{n}</b> — номер, &nbsp;'
            '<b>{date}</b> — дата EXIF, &nbsp;'
            '<b>{time}</b> — время EXIF, &nbsp;'
            '<b>{name}</b> — исходное имя без расширения, &nbsp;'
            '<b>{ext}</b> — расширение без точки</small>'
        )
        hint.setTextFormat(Qt.RichText)
        tl.addWidget(hint)
        lay.addWidget(tg)

        # Numbering
        ng = QGroupBox('Нумерация  {n}')
        nl = QHBoxLayout(ng)
        for lbl, attr, val, mn, mx in [
            ('Начать с:',    '_start_spin', 1, 0, 999999),
            ('Шаг:',         '_step_spin',  1, 1, 1000),
            ('Разрядность:', '_pad_spin',   3, 1, 8),
        ]:
            nl.addWidget(QLabel(lbl))
            sp = QSpinBox()
            sp.setRange(mn, mx)
            sp.setValue(val)
            sp.setMaximumWidth(72)
            sp.valueChanged.connect(self._update_preview)
            setattr(self, attr, sp)
            nl.addWidget(sp)
            nl.addSpacing(20)
        nl.addStretch()
        lay.addWidget(ng)

        # Date / time / extension
        fg = QGroupBox('Форматы даты и времени')
        fl = QHBoxLayout(fg)
        fl.addWidget(QLabel('Дата:'))
        self._date_cb = QComboBox()
        for lbl, _ in self._DATE_FMTS:
            self._date_cb.addItem(lbl)
        self._date_cb.currentIndexChanged.connect(self._update_preview)
        fl.addWidget(self._date_cb)

        fl.addSpacing(20)
        fl.addWidget(QLabel('Время:'))
        self._time_cb = QComboBox()
        for lbl, _ in self._TIME_FMTS:
            self._time_cb.addItem(lbl)
        self._time_cb.currentIndexChanged.connect(self._update_preview)
        fl.addWidget(self._time_cb)

        fl.addSpacing(20)
        fl.addWidget(QLabel('Расширение:'))
        self._ext_cb = QComboBox()
        self._ext_cb.addItems(['Как в оригинале', 'Нижний регистр (.jpg)', 'Верхний регистр (.JPG)'])
        self._ext_cb.currentIndexChanged.connect(self._update_preview)
        fl.addWidget(self._ext_cb)
        fl.addStretch()
        lay.addWidget(fg)

        # Preview table
        lay.addWidget(QLabel('Предпросмотр (красным — конфликты новых имён):'))
        self._prev_tbl = QTableWidget()
        self._prev_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self._prev_tbl.setColumnCount(2)
        self._prev_tbl.setHorizontalHeaderLabels(['Исходное имя', 'Новое имя'])
        self._prev_tbl.verticalHeader().setVisible(False)
        self._prev_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self._prev_tbl, 1)

        # Warning + buttons
        self._warn_lbl = QLabel('')
        self._warn_lbl.setStyleSheet('color:#d32f2f; font-weight:bold;')
        lay.addWidget(self._warn_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._apply_btn = QPushButton('Переименовать')
        self._apply_btn.setMinimumHeight(32)
        self._apply_btn.setMinimumWidth(140)
        self._apply_btn.clicked.connect(self._apply)
        cancel_btn = QPushButton('Отмена')
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Name building

    def _load_exif_date(self, path: str):
        if path not in self._exif_cache:
            self._exif_cache[path] = _get_photo_exif_info(path).get('date')
        return self._exif_cache[path]

    def _make_name(self, path: str, orig: str, n: int) -> str:
        stem, ext = os.path.splitext(orig)
        tmpl = self._tmpl_edit.text().strip() or '{name}_{n}'

        ext_mode = self._ext_cb.currentIndex()
        if ext_mode == 1:
            ext = ext.lower()
        elif ext_mode == 2:
            ext = ext.upper()

        num_str = str(n).zfill(self._pad_spin.value())

        date_str = time_str = ''
        raw = self._load_exif_date(path)
        if raw:
            try:
                dt = datetime.strptime(raw.strip(), '%Y:%m:%d %H:%M:%S')
                date_str = dt.strftime(self._DATE_FMTS[self._date_cb.currentIndex()][1])
                time_str = dt.strftime(self._TIME_FMTS[self._time_cb.currentIndex()][1])
            except ValueError:
                pass

        new = (tmpl
               .replace('{n}',    num_str)
               .replace('{date}', date_str or 'nodate')
               .replace('{time}', time_str or 'notime')
               .replace('{name}', stem)
               .replace('{ext}',  ext.lstrip('.')))

        if '{ext}' not in tmpl:
            new += ext

        for ch in r'\/:*?"<>|':
            new = new.replace(ch, '_')
        return new.strip() or orig

    def _build_plan(self) -> list:
        n, step = self._start_spin.value(), self._step_spin.value()
        result = []
        for path, name in self._photos:
            result.append((path, name, self._make_name(path, name, n)))
            n += step
        return result

    # ------------------------------------------------------------------
    # Preview

    def _update_preview(self):
        plan      = self._build_plan()
        new_names = [r[2] for r in plan]
        dups      = {nm for nm in new_names if new_names.count(nm) > 1}

        self._prev_tbl.setRowCount(len(plan))
        for r, (_, old, new) in enumerate(plan):
            self._prev_tbl.setItem(r, 0, QTableWidgetItem(old))
            it = QTableWidgetItem(new)
            if new in dups:
                it.setForeground(QBrush(QColor(210, 40, 40)))
            self._prev_tbl.setItem(r, 1, it)

        if dups:
            self._warn_lbl.setText(f'⚠  Дублирующиеся имена: {len(dups)} — исправьте шаблон.')
            self._apply_btn.setEnabled(False)
        else:
            self._warn_lbl.setText('')
            self._apply_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Apply

    def _apply(self):
        import uuid
        plan   = self._build_plan()
        if not plan:
            return

        folder   = os.path.dirname(plan[0][0])
        existing = set(os.listdir(folder))
        old_set  = {name for _, name, _ in plan}
        conflicts = [new for _, old, new in plan
                     if old != new and new in existing and new not in old_set]

        if conflicts:
            reply = QMessageBox.question(
                self, 'Конфликты имён',
                f'{len(conflicts)} новых имён уже существуют в папке.\nПерезаписать?',
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # Two-pass rename (avoids A→B / B→A collisions)
        tmp_map = {}
        errors  = []
        for path, old, new in plan:
            if old == new:
                continue
            tmp = os.path.join(folder,
                               f'_rntmp_{uuid.uuid4().hex}{os.path.splitext(old)[1]}')
            try:
                os.rename(path, tmp)
                tmp_map[tmp] = os.path.join(folder, new)
            except OSError as e:
                errors.append(f'{old}: {e}')

        for tmp, final in tmp_map.items():
            try:
                os.rename(tmp, final)
            except OSError as e:
                errors.append(f'{os.path.basename(final)}: {e}')

        done = len(tmp_map) - len(errors)
        if errors:
            QMessageBox.warning(self, 'Ошибки переименования',
                                f'Переименовано: {done}/{len(tmp_map)}\n\n' +
                                '\n'.join(errors[:15]))
        else:
            QMessageBox.information(self, 'Готово', f'Переименовано {done} файлов.')

        self.accept()


# ---------------------------------------------------------------------------
# Map dialog
# ---------------------------------------------------------------------------

class MapDialog(QDialog):
    def __init__(self, geo_data: list, columns: dict, headers: list,
                 display_cols=None, parent=None):
        super().__init__(parent)
        self.geo_data     = geo_data
        self.columns      = columns
        self.headers      = headers
        self.display_cols = display_cols if display_cols is not None \
                            else list(range(len(headers)))
        self._tmp_path    = None
        self._points      = []   # [(idx, lat, lon, alt, orig_row), ...]
        self._excluded    = set()
        self._hover_idx   = -1
        self.setWindowTitle('Карта геоточек')
        self.setMinimumSize(1100, 680)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self._extract_points()
        self._build_ui()
        self._render_map()
        self._fill_table()

    # ------------------------------------------------------------------
    # Data

    def _extract_points(self):
        li = self.columns.get('lat', 0)
        oi = self.columns.get('lon', 1)
        ai = self.columns.get('alt')
        for i, row in enumerate(self.geo_data):
            try:
                lat = float(row[li].strip())
                lon = float(row[oi].strip())
                alt = None
                if ai is not None and ai < len(row):
                    try:
                        alt = float(row[ai].strip())
                    except ValueError:
                        pass
                self._points.append((i + 1, lat, lon, alt, row))
            except (ValueError, IndexError):
                pass

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self):
        from PyQt5.QtWebEngineWidgets import QWebEngineView

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)

        self._web = QWebEngineView()
        splitter.addWidget(self._web)

        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setMouseTracking(True)
        self._table.viewport().setMouseTracking(True)
        self._table.cellEntered.connect(self._on_hover)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context)
        self._table.viewport().installEventFilter(self)
        self._table.setMinimumWidth(200)
        self._table.setMaximumWidth(320)
        splitter.addWidget(self._table)

        splitter.setSizes([820, 260])
        lay.addWidget(splitter, 1)

        close_btn = QPushButton('Закрыть')
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn)

    def _fill_table(self):
        valid_cols = [i for i in self.display_cols if i < len(self.headers)]
        labels = ['#'] + [self.headers[i] for i in valid_cols]
        self._table.setColumnCount(len(labels))
        self._table.setHorizontalHeaderLabels(labels)
        self._table.setRowCount(len(self._points))
        self._table.verticalHeader().setVisible(False)

        for r, (idx, lat, lon, alt, orig_row) in enumerate(self._points):
            self._table.setItem(r, 0, QTableWidgetItem(str(idx)))
            for c, ci in enumerate(valid_cols):
                val = orig_row[ci].strip() if ci < len(orig_row) else ''
                self._table.setItem(r, c + 1, QTableWidgetItem(val))

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)

    # ------------------------------------------------------------------
    # Map rendering

    def _render_map(self):
        import folium
        import json
        import tempfile
        from PyQt5.QtCore import QUrl
        from branca.element import Element

        if not self._points:
            self._web.setHtml(
                '<body style="font-family:sans-serif;text-align:center;padding-top:80px">'
                '<h2>Нет координат для отображения</h2></body>'
            )
            return

        center_lat = sum(p[1] for p in self._points) / len(self._points)
        center_lon = sum(p[2] for p in self._points) / len(self._points)

        m = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles=None)

        # Google Hybrid (satellite + labels) — default layer
        folium.TileLayer(
            tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
            attr='Google',
            name='Спутник (Google)',
            max_zoom=21,
        ).add_to(m)
        folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(m)
        folium.TileLayer('CartoDB positron', name='Светлая').add_to(m)
        folium.TileLayer('CartoDB dark_matter', name='Тёмная').add_to(m)
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/'
                  'World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Спутник (Esri)',
        ).add_to(m)
        folium.LayerControl(position='topright', collapsed=False).add_to(m)

        m.get_root().html.add_child(Element(
            '<style>.leaflet-control-attribution{display:none!important}</style>'
        ))

        # Custom JS markers with highlight / exclude support
        map_var     = m.get_name()
        points_json = json.dumps([
            {'idx': idx, 'lat': lat, 'lng': lon, 'alt': alt}
            for idx, lat, lon, alt, _row in self._points
        ])

        js = f"""<script>
(function() {{
    var tid = setInterval(function() {{
        if (typeof {map_var} !== 'undefined') {{
            clearInterval(tid);
            _initMarkers();
        }}
    }}, 50);

    function _initMarkers() {{
        var pts = {points_json};
        window._markers  = {{}};
        window._excluded = {{}};

        pts.forEach(function(p) {{
            var tip = '#' + p.idx + '  ' + p.lat.toFixed(6) + ', ' + p.lng.toFixed(6);
            if (p.alt !== null) tip += '  ↑' + p.alt.toFixed(1) + 'м';
            window._markers[p.idx] = L.circleMarker([p.lat, p.lng], {{
                radius: 6, color: '#c0392b', fillColor: '#e74c3c',
                fillOpacity: 0.85, weight: 2, opacity: 1
            }}).addTo({map_var}).bindTooltip(tip);
        }});

        window.highlightMarker = function(i) {{
            var mk = window._markers[i];
            if (mk && !window._excluded[i]) {{
                mk.setStyle({{radius: 11, color: '#e67e22', fillColor: '#f1c40f',
                              fillOpacity: 1, weight: 3, opacity: 1}});
                mk.bringToFront();
            }}
        }};
        window.resetMarker = function(i) {{
            var mk = window._markers[i];
            if (mk && !window._excluded[i]) {{
                mk.setStyle({{radius: 6, color: '#c0392b', fillColor: '#e74c3c',
                              fillOpacity: 0.85, weight: 2, opacity: 1}});
            }}
        }};
        window.toggleExclude = function(i) {{
            var mk = window._markers[i];
            if (!mk) return;
            if (window._excluded[i]) {{
                delete window._excluded[i];
                mk.setStyle({{radius: 6, color: '#c0392b', fillColor: '#e74c3c',
                              fillOpacity: 0.85, weight: 2, opacity: 1}});
            }} else {{
                window._excluded[i] = true;
                mk.setStyle({{radius: 5, color: '#666', fillColor: '#999',
                              fillOpacity: 0.3, weight: 1, opacity: 0.4}});
            }}
        }};
    }}
}})();
</script>"""

        m.get_root().html.add_child(Element(js))

        if self._tmp_path and os.path.exists(self._tmp_path):
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False)
        tmp.close()
        m.save(tmp.name)
        self._tmp_path = tmp.name
        self._web.setUrl(QUrl.fromLocalFile(tmp.name))

    # ------------------------------------------------------------------
    # Hover / exclude interactions

    def eventFilter(self, obj, event):
        if obj is self._table.viewport() and event.type() == QEvent.Leave:
            self._reset_hover()
        return super().eventFilter(obj, event)

    def _on_hover(self, row, col):
        item = self._table.item(row, 0)
        if not item:
            return
        idx = int(item.text())
        if idx == self._hover_idx:
            return
        self._reset_hover()
        if idx in self._excluded:
            return
        self._hover_idx = idx
        self._web.page().runJavaScript(f'window.highlightMarker({idx})')

    def _reset_hover(self):
        if self._hover_idx >= 0:
            self._web.page().runJavaScript(f'window.resetMarker({self._hover_idx})')
            self._hover_idx = -1

    def _on_context(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        idx  = int(item.text())
        menu = QMenu(self)
        if idx in self._excluded:
            act = menu.addAction('↩  Вернуть точку')
        else:
            act = menu.addAction('✕  Исключить точку')
        if menu.exec_(self._table.viewport().mapToGlobal(pos)) == act:
            self._toggle_point(row, idx)

    def _toggle_point(self, row: int, idx: int):
        self._web.page().runJavaScript(f'window.toggleExclude({idx})')
        if idx in self._excluded:
            self._excluded.discard(idx)
            for c in range(self._table.columnCount()):
                it = self._table.item(row, c)
                if it:
                    it.setForeground(QBrush())
        else:
            self._excluded.add(idx)
            if self._hover_idx == idx:
                self._reset_hover()
            grey = QBrush(QColor(130, 130, 130))
            for c in range(self._table.columnCount()):
                it = self._table.item(row, c)
                if it:
                    it.setForeground(grey)

    def get_excluded(self) -> set:
        return set(self._excluded)

    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._tmp_path and os.path.exists(self._tmp_path):
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
        super().closeEvent(event)
