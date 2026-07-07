import os

import piexif
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea,
    QLabel, QSlider, QComboBox, QGridLayout, QFileDialog, QFrame, QMenu,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap, QImage, QPainter, QColor, QFont
from PIL import Image as PilImage

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_gps(path: str) -> bool:
    if os.path.splitext(path)[1].lower() not in ('.jpg', '.jpeg', '.tif', '.tiff'):
        return False
    try:
        exif = piexif.load(path)
        gps  = exif.get('GPS', {})
        return bool(gps) and piexif.GPSIFD.GPSLatitude in gps
    except Exception:
        return False


def _draw_gps_badge(px: QPixmap) -> QPixmap:
    w  = px.width()
    bw = max(24, w // 5)
    bh = max(12, w // 9)
    fs = max(7, w // 14)

    out = QPixmap(px)
    p   = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    x, y = w - bw - 2, 2
    p.setBrush(QColor(52, 168, 83))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(x, y, bw, bh, 3, 3)
    f = QFont(); f.setPixelSize(fs); f.setBold(True)
    p.setFont(f)
    p.setPen(Qt.white)
    p.drawText(x, y, bw, bh, Qt.AlignCenter, 'GPS')
    p.end()
    return out


# ---------------------------------------------------------------------------
# Background thumbnail loader
# ---------------------------------------------------------------------------

class ThumbnailLoader(QThread):
    thumbnail_ready = pyqtSignal(int, QPixmap, bool)   # idx, pixmap, has_gps

    def __init__(self, photos: list, size: int):
        super().__init__()
        self._photos    = list(photos)
        self._size      = size
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for i, (path, _) in enumerate(self._photos):
            if self._cancelled:
                return
            px = QPixmap()
            try:
                img = PilImage.open(path)
                img.thumbnail((self._size, self._size), PilImage.LANCZOS)
                img  = img.convert('RGBA')
                data = img.tobytes('raw', 'RGBA')
                qi   = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
                px   = QPixmap.fromImage(qi)
            except Exception:
                pass
            self.thumbnail_ready.emit(i, px, _check_gps(path))


# ---------------------------------------------------------------------------
# Single thumbnail tile
# ---------------------------------------------------------------------------

class PhotoTile(QFrame):
    double_clicked    = pyqtSignal(str)
    exclude_requested = pyqtSignal(str)

    def __init__(self, path: str, name: str, size: int):
        super().__init__()
        self.path      = path
        self._size     = size
        self._px       = QPixmap()
        self._has_gps  = False
        self._excluded = False

        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setLineWidth(1)
        self._sync_width()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        lay.setAlignment(Qt.AlignCenter)

        self.img_lbl = QLabel()
        self.img_lbl.setAlignment(Qt.AlignCenter)
        self.img_lbl.setFixedSize(size, size)
        self.img_lbl.setStyleSheet('background:#1e1e1e; border-radius:3px;')

        short = name if len(name) <= 22 else name[:19] + '…'
        self.name_lbl = QLabel(short)
        self.name_lbl.setAlignment(Qt.AlignCenter)
        self.name_lbl.setToolTip(name)

        lay.addWidget(self.img_lbl)
        lay.addWidget(self.name_lbl)
        self._update_frame_style()

    def _sync_width(self):
        self.setFixedWidth(self._size + 16)

    # ------------------------------------------------------------------

    def set_pixmap(self, px: QPixmap, has_gps: bool = False):
        self._px      = px
        self._has_gps = has_gps
        self._apply()

    def _apply(self):
        if not self._px.isNull():
            s = self._px.scaled(self._size, self._size,
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if self._excluded:
                # Convert to greyscale
                grey = s.toImage().convertToFormat(QImage.Format_Grayscale8)
                s    = QPixmap.fromImage(grey.convertToFormat(QImage.Format_ARGB32))
            elif self._has_gps:
                s = _draw_gps_badge(s)
            self.img_lbl.setPixmap(s)
        else:
            self.img_lbl.clear()
            self.img_lbl.setText('?')
        self._update_frame_style()

    def _update_frame_style(self):
        if self._excluded:
            self.setStyleSheet('QFrame { border: 1px dashed #555; }')
            self.name_lbl.setStyleSheet(
                'font-size:10px; color:#666; text-decoration:line-through;')
        else:
            self.setStyleSheet('')
            self.name_lbl.setStyleSheet('font-size:10px;')

    def update_size(self, sz: int):
        self._size = sz
        self._sync_width()
        self.img_lbl.setFixedSize(sz, sz)
        self._apply()

    # ------------------------------------------------------------------

    def mouseDoubleClickEvent(self, _e):
        self.double_clicked.emit(self.path)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self._excluded:
            act = menu.addAction('↩  Вернуть фото')
        else:
            act = menu.addAction('✕  Исключить фото')
        if menu.exec_(event.globalPos()) == act:
            self.exclude_requested.emit(self.path)


# ---------------------------------------------------------------------------
# Photo panel (left side)
# ---------------------------------------------------------------------------

class PhotoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder_path: str | None = None
        self.photos: list            = []
        self._tiles: list            = []
        self._thumb_size             = 120
        self._loader: ThumbnailLoader | None = None

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._reload_thumbs)

        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        tb = QHBoxLayout()
        self.folder_btn = QPushButton('📂  Выбрать папку')
        self.folder_btn.clicked.connect(self._pick_folder)
        tb.addWidget(self.folder_btn)
        tb.addSpacing(8)
        tb.addWidget(QLabel('Размер:'))
        self.size_sl = QSlider(Qt.Horizontal)
        self.size_sl.setRange(60, 280)
        self.size_sl.setValue(120)
        self.size_sl.setMaximumWidth(120)
        self.size_sl.valueChanged.connect(self._on_size_change)
        tb.addWidget(self.size_sl)
        tb.addSpacing(12)
        tb.addWidget(QLabel('Сортировка:'))
        self.sort_cb = QComboBox()
        self.sort_cb.addItems(['Имя ↑', 'Имя ↓', 'Дата ↑', 'Дата ↓', 'Размер ↑', 'Размер ↓'])
        self.sort_cb.currentIndexChanged.connect(self._sort_and_render)
        tb.addWidget(self.sort_cb)
        tb.addStretch()
        lay.addLayout(tb)

        self.path_label = QLabel('')
        self.path_label.setStyleSheet('font-size:10px; color:#888;')
        lay.addWidget(self.path_label)

        self.scroll   = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._grid_w  = QWidget()
        self._grid_l  = QGridLayout(self._grid_w)
        self._grid_l.setSpacing(8)
        self._grid_l.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self._grid_w)
        lay.addWidget(self.scroll)

        self.summary = QLabel('Фотографий: 0')
        lay.addWidget(self.summary)

    # ------------------------------------------------------------------
    # Folder / load

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Выбрать папку с фотографиями')
        if not folder:
            return
        self.folder_path = folder
        self.folder_btn.setText(os.path.basename(folder) or folder)
        self.path_label.setText(folder)
        self.path_label.setToolTip(folder)
        self._load_photos(folder)

    def _load_photos(self, folder: str):
        self.photos = []
        try:
            for name in os.listdir(folder):
                if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                    self.photos.append((os.path.join(folder, name), name))
        except OSError:
            pass
        self._sort_and_render()

    # ------------------------------------------------------------------
    # Sort

    def _sort_and_render(self):
        idx     = self.sort_cb.currentIndex()
        reverse = idx % 2 == 1
        keys    = [
            lambda x: x[1].lower(),
            lambda x: x[1].lower(),
            lambda x: os.path.getmtime(x[0]),
            lambda x: os.path.getmtime(x[0]),
            lambda x: os.path.getsize(x[0]),
            lambda x: os.path.getsize(x[0]),
        ]
        self.photos.sort(key=keys[idx], reverse=reverse)
        self._render_grid()

    # ------------------------------------------------------------------
    # Grid

    def _render_grid(self):
        self._cancel_loader()
        for t in self._tiles:
            self._grid_l.removeWidget(t)
            t.setParent(None)
        self._tiles.clear()

        for path, name in self.photos:
            t = PhotoTile(path, name, self._thumb_size)
            t.double_clicked.connect(self._open_full)
            t.exclude_requested.connect(self._toggle_exclude)
            self._tiles.append(t)

        self._relayout()
        self._update_summary()

        if self.photos:
            self._reload_thumbs()

    def _relayout(self):
        while self._grid_l.count():
            self._grid_l.takeAt(0)
        vp_w = self.scroll.viewport().width()
        cols = max(1, vp_w // (self._thumb_size + 24))
        for i, t in enumerate(self._tiles):
            self._grid_l.addWidget(t, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    # ------------------------------------------------------------------
    # Thumbnails

    def _cancel_loader(self):
        if self._loader and self._loader.isRunning():
            self._loader.cancel()
            self._loader.wait(200)

    def _reload_thumbs(self):
        self._cancel_loader()
        self._loader = ThumbnailLoader(self.photos, self._thumb_size)
        self._loader.thumbnail_ready.connect(self._on_thumb)
        self._loader.start()

    def _on_thumb(self, idx: int, px: QPixmap, has_gps: bool):
        if idx < len(self._tiles):
            self._tiles[idx].set_pixmap(px, has_gps)

    # ------------------------------------------------------------------
    # Size slider

    def _on_size_change(self, sz: int):
        self._thumb_size = sz
        for t in self._tiles:
            t.update_size(sz)
        self._relayout()
        self._debounce.start(350)

    # ------------------------------------------------------------------
    # Exclude / restore

    def _toggle_exclude(self, path: str):
        for t in self._tiles:
            if t.path == path:
                t._excluded = not t._excluded
                t._apply()
                break
        self._update_summary()

    def _update_summary(self):
        total = len(self.photos)
        excl  = sum(1 for t in self._tiles if t._excluded)
        if excl:
            self.summary.setText(f'Фотографий: {total}  (исключено: {excl})')
        else:
            self.summary.setText(f'Фотографий: {total}')

    # ------------------------------------------------------------------
    # Full viewer

    def _open_full(self, path: str):
        from dialogs import FullImageDialog
        dlg = FullImageDialog(path, self)
        dlg.exec_()

    # ------------------------------------------------------------------
    # Public API

    def get_photos(self) -> list:
        excl = {t.path for t in self._tiles if t._excluded}
        return [(p, n) for p, n in self.photos if p not in excl]

    def get_folder(self) -> str | None:
        return self.folder_path
