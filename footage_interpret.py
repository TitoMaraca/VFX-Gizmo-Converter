"""
Footage Interpret for Nuke - elige un colorspace y aplicalo a todos los Reads seleccionados.

Uso: selecciona los Reads -> menu  Interpret > Set colorspace...  -> elige el colorspace -> OK.
"""
import nuke

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

SHORTCUT = ""   # ej: "Ctrl+Alt+I". Vacio = sin atajo.


def _name(item):
    """Nuke 17 devuelve los items como 'Nombre<TAB>Ruta/del/menu'. El valor real es solo el Nombre."""
    return str(item).split("\t")[0].strip()


def _norm(item):
    return _name(item).lower()


def _selected_reads():
    return [n for n in nuke.selectedNodes() if n.Class() == "Read"]


def _matching_value(knob, wanted):
    """Devuelve el NOMBRE exacto (sin la ruta del menu) del colorspace pedido, o None si no existe."""
    names = [_name(v) for v in knob.values()]
    w = _name(wanted)
    if w in names:
        return w
    for v in names:
        if v.lower() == w.lower():
            return v
    last = w.split("/")[-1].strip().lower()   # por si pegaron una ruta tipo Carpeta/Nombre
    for v in names:
        if v.lower() == last:
            return v
    return None


def apply_colorspace(reads, colorspace, auto_alpha=False):
    """Aplica el colorspace (y auto alpha si se pidio). Devuelve la lista de fallos."""
    failed = []
    nuke.Undo.begin("Set colorspace")
    try:
        for n in reads:
            try:
                k = n["colorspace"]
                value = _matching_value(k, colorspace)
                if value is None:
                    failed.append("%s: colorspace no disponible" % n.name())
                    continue
                if n.knob("raw") and n["raw"].value():
                    n["raw"].setValue(False)  # con raw activo el colorspace se ignora
                k.setValue(value)
                if auto_alpha and n.knob("auto_alpha"):
                    n["auto_alpha"].setValue(True)
            except Exception as e:
                failed.append("%s: %s" % (n.name(), e))
    finally:
        nuke.Undo.end()
    return failed


def _run(dlg):
    return dlg.exec() if hasattr(dlg, "exec") else dlg.exec_()


class ColorspaceDialog(QtWidgets.QDialog):
    """Ventana con buscador + colorspaces organizados por categorias (Colorspaces > ACES / Input / Output / Utility)."""

    def __init__(self, reads, n_all, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set colorspace")
        self.setMinimumSize(480, 580)
        self.n_sel, self.n_all = len(reads), n_all
        lay = QtWidgets.QVBoxLayout(self)
        self.count = QtWidgets.QLabel("")
        lay.addWidget(self.count)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Buscar colorspace...  (ej: ARRI, ACEScg, Rec.709)")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        folders = {}
        root = self.tree.invisibleRootItem()

        def folder_item(parts):
            key, parent = "", root
            for part in parts:
                key += "/" + part
                it = folders.get(key)
                if it is None:
                    it = QtWidgets.QTreeWidgetItem(parent, [part])
                    it.setFlags(Qt.ItemIsEnabled)      # las carpetas no se seleccionan
                    folders[key] = it
                parent = it
            return parent

        self._current_leaf = None
        cur = _name(reads[0]["colorspace"].value())
        seen = set()
        for item in reads[0]["colorspace"].values():
            raw = str(item)
            nm = _name(raw)
            if not nm or nm in seen:
                continue
            seen.add(nm)
            path = raw.split("\t")[1].strip() if "\t" in raw else ""
            segs = [x.strip() for x in path.split("/") if x.strip()]
            if segs and segs[-1].lower() == nm.lower():
                segs = segs[:-1]                       # el ultimo segmento es el propio colorspace
            leaf = QtWidgets.QTreeWidgetItem(folder_item(segs), [nm])
            leaf.setData(0, Qt.UserRole, nm)
            if path:
                leaf.setToolTip(0, path)
            if nm == cur:
                self._current_leaf = leaf
        lay.addWidget(self.tree, 1)

        if self._current_leaf is not None:             # abre las carpetas hasta el colorspace actual
            p = self._current_leaf.parent()
            while p is not None:
                p.setExpanded(True)
                p = p.parent()
            self.tree.setCurrentItem(self._current_leaf)
            self.tree.scrollToItem(self._current_leaf, QtWidgets.QAbstractItemView.PositionAtCenter)
        self.tree.itemDoubleClicked.connect(self._double_click)

        self.alpha = QtWidgets.QCheckBox("Auto alpha")
        lay.addWidget(self.alpha)
        self.everyone = QtWidgets.QCheckBox("Aplicar a TODOS los Reads del script (no solo los seleccionados)")
        self.everyone.setChecked(self.n_sel == 0)
        self.everyone.toggled.connect(self._update_count)
        lay.addWidget(self.everyone)
        self._update_count()
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.search.setFocus()

    @staticmethod
    def _is_leaf(item):
        return item is not None and item.data(0, Qt.UserRole) is not None

    def _double_click(self, item, column=0):
        if self._is_leaf(item):
            self.accept()

    def _filter(self, text):
        text = text.strip().lower()

        def visit(item):
            if item.childCount() == 0:
                vis = (not text) or (self._is_leaf(item) and text in item.text(0).lower())
                item.setHidden(not vis)
                return vis
            any_vis = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    any_vis = True
            item.setHidden(not any_vis)
            if text and any_vis:
                item.setExpanded(True)
            return any_vis

        def first_leaf(item):
            for i in range(item.childCount()):
                c = item.child(i)
                if c.isHidden():
                    continue
                if self._is_leaf(c):
                    return c
                found = first_leaf(c)
                if found is not None:
                    return found
            return None

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))
        if text:
            f = first_leaf(root)
            if f is not None:
                self.tree.setCurrentItem(f)

    def _update_count(self, *args):
        if self.everyone.isChecked():
            self.count.setText("Se aplicara a: <b>%d Read(s)</b> (todos los del script)" % self.n_all)
        else:
            self.count.setText("Se aplicara a: <b>%d Read(s)</b> (los seleccionados)" % self.n_sel)

    def colorspace(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if self._is_leaf(it) and not it.isHidden() else ""


def set_colorspace():
    selected = _selected_reads()
    everything = nuke.allNodes("Read", recurseGroups=True)
    if not selected and not everything:
        nuke.message("No hay Reads en el script.")
        return
    base = selected or everything
    dlg = ColorspaceDialog(base, len(everything), QtWidgets.QApplication.activeWindow())
    if not _run(dlg):
        return
    cs = dlg.colorspace()
    if not cs:
        nuke.message("No elegiste ningun colorspace.")
        return
    reads = everything if dlg.everyone.isChecked() else selected
    if not reads:
        nuke.message("No hay Reads seleccionados.")
        return
    failed = apply_colorspace(reads, cs, dlg.alpha.isChecked())
    if failed:
        nuke.message("No se pudo en %d Read(s):\n" % len(failed) + "\n".join(failed[:15]))
    else:
        nuke.tprint("Interpret: colorspace '%s' aplicado a %d Read(s)." % (cs, len(reads)))


def install():
    if not nuke.GUI:
        return
    m = nuke.menu("Nuke").addMenu("Interpret")
    m.addCommand("Set colorspace...", "import footage_interpret; footage_interpret.set_colorspace()", SHORTCUT)
