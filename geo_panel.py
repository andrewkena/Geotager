import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QFileDialog, QHeaderView,
)

from dialogs import _find_duplicates, _DUP_COLOR


class GeoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.headers:       list = []
        self.geo_data:      list = []
        self.columns:       dict = {}
        self._display_cols: list = []
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        tb = QHBoxLayout()
        self.file_btn = QPushButton('📄  Выбрать файл геоданных')
        self.file_btn.clicked.connect(self._pick_file)
        tb.addWidget(self.file_btn)

        self.map_btn = QPushButton('🗺  Показать на карте')
        self.map_btn.setEnabled(False)
        self.map_btn.clicked.connect(self._open_map)
        tb.addWidget(self.map_btn)
        tb.addStretch()
        lay.addLayout(tb)

        self.path_label = QLabel('')
        self.path_label.setStyleSheet('font-size:10px; color:#888;')
        self.path_label.setWordWrap(False)
        lay.addWidget(self.path_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table)

        self.summary = QLabel('Строк данных: 0')
        lay.addWidget(self.summary)

    # ------------------------------------------------------------------

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Выбрать файл с геоданными', '',
            'Текстовые файлы (*.txt *.csv *.tsv *.dat);;Все файлы (*.*)',
        )
        if not path:
            return

        from dialogs import DelimiterDialog
        dlg = DelimiterDialog(path, self)
        if dlg.exec_() != dlg.Accepted:
            return

        _, self.headers, self.geo_data, self.columns, self._display_cols = dlg.get_result()
        self._file_path = path
        self.file_btn.setText(os.path.basename(path))
        self.path_label.setText(path)
        self.path_label.setToolTip(path)
        self.map_btn.setEnabled(bool(self.geo_data))
        self._show_data()

    def _show_data(self):
        vis = self._display_cols if self._display_cols else list(range(len(self.headers)))
        vis = [i for i in vis if i < len(self.headers)]
        col_names = [self.headers[i] for i in vis]

        self.table.setColumnCount(len(col_names))
        self.table.setHorizontalHeaderLabels(col_names)
        self.table.setRowCount(len(self.geo_data))

        for r, row in enumerate(self.geo_data):
            for c, ci in enumerate(vis):
                val = row[ci].strip() if ci < len(row) else ''
                self.table.setItem(r, c, QTableWidgetItem(val))

        dups = _find_duplicates(self.geo_data)
        for r in dups:
            for c in range(len(col_names)):
                item = self.table.item(r, c)
                if item:
                    item.setBackground(_DUP_COLOR)

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        dup_note = f'  (дубликатов: {len(dups) // 2})' if dups else ''
        self.summary.setText(f'Строк данных: {len(self.geo_data)}{dup_note}')

    def _open_map(self):
        from dialogs import MapDialog
        dlg = MapDialog(self.geo_data, self.columns, self.headers,
                        self._display_cols, self)
        dlg.exec_()
        excluded = dlg.get_excluded()
        if excluded:
            self.geo_data = [row for i, row in enumerate(self.geo_data)
                             if (i + 1) not in excluded]
            self._show_data()

    # ------------------------------------------------------------------
    # Public API

    def get_data(self):
        return self.headers, self.geo_data, self.columns

    def get_display_columns(self) -> list:
        return self._display_cols
