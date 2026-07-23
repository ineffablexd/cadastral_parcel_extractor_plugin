import csv
import gc
import math
import os
import re
import time
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from qgis.PyQt.QtCore import QCoreApplication, QObject, QSettings, Qt, QThread, QVariant, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QTextCursor
from qgis.PyQt.QtWidgets import QAction, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureRequest, QgsField, QgsFields, QgsGeometry, QgsPalLayerSettings, QgsProcessingFeedback, QgsProject, QgsRectangle, QgsVectorFileWriter, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsWkbTypes
from qgis.gui import QgsFieldComboBox, QgsProjectionSelectionWidget

def get_processing():
    try:
        import processing
        return processing
    except ImportError:
        import sys
        import qgis.core
        prefix = qgis.core.QgsApplication.prefixPath()
        candidates = [os.path.join(prefix, 'python', 'plugins'), '/usr/share/qgis/python/plugins', '/usr/lib/qgis/plugins']
        for path in candidates:
            if os.path.exists(path) and path not in sys.path:
                sys.path.append(path)
        import processing
        return processing
VOLTAGE_PRESETS: Dict[str, float] = {'Custom': 25.0, '132 kV': 27.0, '220 kV': 35.0, '400 kV': 52.0, '765 kV': 67.0, '1200 kV': 89.0}

def detect_voltage_from_name(name: str) -> Optional[str]:
    if not name:
        return None
    name_clean = re.sub('[_\\-\\.\\s]+', ' ', name.lower())
    preset_values = [1200, 765, 400, 220, 132]
    for v in preset_values:
        pattern = '(?<!\\d)' + str(v) + '\\s*(?:kv|kilovolt)?(?!\\d)'
        if re.search(pattern, name_clean):
            return f'{v} kV'
    return None

class AdvancedBufferSettings:

    def __init__(self, segments: int=5, end_cap_style: int=0, join_style: int=0, miter_limit: float=2.0, dissolve: bool=False, fix_geometries: bool=True) -> None:
        self.segments: int = segments
        self.end_cap_style: int = end_cap_style
        self.join_style: int = join_style
        self.miter_limit: float = miter_limit
        self.dissolve: bool = dissolve
        self.fix_geometries: bool = fix_geometries

    def clone(self) -> 'AdvancedBufferSettings':
        return AdvancedBufferSettings(segments=self.segments, end_cap_style=self.end_cap_style, join_style=self.join_style, miter_limit=self.miter_limit, dissolve=self.dissolve, fix_geometries=self.fix_geometries)

class AdvancedBufferDialog(QDialog):

    def __init__(self, parent: Optional[QWidget]=None, settings: Optional[AdvancedBufferSettings]=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Advanced Buffer Settings')
        self.resize(360, 280)
        self._settings = settings.clone() if settings else AdvancedBufferSettings()
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        seg_layout = QHBoxLayout()
        seg_layout.addWidget(QLabel('Buffer Segments:'))
        self.spin_segments = QSpinBox()
        self.spin_segments.setRange(1, 100)
        seg_layout.addWidget(self.spin_segments)
        layout.addLayout(seg_layout)
        cap_layout = QHBoxLayout()
        cap_layout.addWidget(QLabel('End Cap Style:'))
        self.combo_end_cap = QComboBox()
        self.combo_end_cap.addItems(['Round', 'Flat', 'Square'])
        cap_layout.addWidget(self.combo_end_cap)
        layout.addLayout(cap_layout)
        join_layout = QHBoxLayout()
        join_layout.addWidget(QLabel('Join Style:'))
        self.combo_join_style = QComboBox()
        self.combo_join_style.addItems(['Round', 'Miter', 'Bevel'])
        join_layout.addWidget(self.combo_join_style)
        layout.addLayout(join_layout)
        miter_layout = QHBoxLayout()
        miter_layout.addWidget(QLabel('Miter Limit:'))
        self.spin_miter = QDoubleSpinBox()
        self.spin_miter.setRange(1.0, 50.0)
        self.spin_miter.setSingleStep(0.5)
        miter_layout.addWidget(self.spin_miter)
        layout.addLayout(miter_layout)
        self.chk_dissolve = QCheckBox('Dissolve Buffer Output')
        layout.addWidget(self.chk_dissolve)
        self.chk_fix_geom = QCheckBox('Fix Geometries before Buffer')
        layout.addWidget(self.chk_fix_geom)
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton('OK')
        btn_ok.clicked.connect(self._accept_settings)
        btn_cancel = QPushButton('Cancel')
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _load_settings(self) -> None:
        self.spin_segments.setValue(self._settings.segments)
        self.combo_end_cap.setCurrentIndex(self._settings.end_cap_style)
        self.combo_join_style.setCurrentIndex(self._settings.join_style)
        self.spin_miter.setValue(self._settings.miter_limit)
        self.chk_dissolve.setChecked(self._settings.dissolve)
        self.chk_fix_geom.setChecked(self._settings.fix_geometries)

    def _accept_settings(self) -> None:
        self._settings.segments = self.spin_segments.value()
        self._settings.end_cap_style = self.combo_end_cap.currentIndex()
        self._settings.join_style = self.combo_join_style.currentIndex()
        self._settings.miter_limit = self.spin_miter.value()
        self._settings.dissolve = self.chk_dissolve.isChecked()
        self._settings.fix_geometries = self.chk_fix_geom.isChecked()
        self.accept()

    def get_settings(self) -> AdvancedBufferSettings:
        return self._settings

class UTMHelper:

    @staticmethod
    def calculate_utm_epsg(extent: QgsRectangle, source_crs: QgsCoordinateReferenceSystem) -> int:
        center = extent.center()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if source_crs != wgs84:
            transform = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
            center = transform.transform(center)
        lon = center.x()
        lat = center.y()
        zone = math.floor((lon + 180.0) / 6.0) + 1
        zone = max(1, min(60, zone))
        if lat >= 0:
            return 32600 + zone
        return 32700 + zone

class PowerCorridorProcessor(QObject):
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int, str)
    line_finished_signal = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def process(self, cadastral_layer: QgsVectorLayer, layer_configs: List[Dict[str, Any]], auto_utm: bool, manual_crs: QgsCoordinateReferenceSystem, output_folder: str, label_field: str, merge_outputs: bool) -> Dict[str, Any]:
        self._is_cancelled = False
        start_time = time.time()
        results: List[Dict[str, Any]] = []
        line_names_list: List[str] = []
        affected_layers_mem: List[QgsVectorLayer] = []
        clipped_layers_mem: List[QgsVectorLayer] = []
        total_parcels_affected = 0
        total_area_affected = 0.0
        if not cadastral_layer or not cadastral_layer.isValid():
            raise ValueError('Invalid Cadastral polygon layer specified.')
        if not os.path.exists(output_folder):
            os.makedirs(output_folder, exist_ok=True)
        num_layers = len(layer_configs)
        for idx, config in enumerate(layer_configs):
            if self._is_cancelled:
                self.log_signal.emit('Processing cancelled by user.', 'warning')
                break
            layer_name = config['layer'].name()
            sanitized_name = self._sanitize(layer_name)
            line_names_list.append(layer_name)
            pct_base = int(idx / num_layers * 90)
            self.progress_signal.emit(pct_base + 2, f'Starting corridor analysis for {layer_name} ({idx + 1}/{num_layers})...')
            self.log_signal.emit(f'--- Processing Corridor Layer ({idx + 1}/{num_layers}): {layer_name} ---', 'info')
            target_crs = self._determine_crs(config['layer'], auto_utm, manual_crs, config['crs_override'])
            self.log_signal.emit(f'Target CRS: {target_crs.authid()} ({target_crs.description()})', 'info')
            self.progress_signal.emit(pct_base + 10, f'Projecting line layer {layer_name}...')
            proj_line = self._reproject_layer(config['layer'], target_crs, 'memory:', f'{layer_name}_Projected')
            adv: AdvancedBufferSettings = config['advanced']
            input_line = proj_line
            if adv.fix_geometries:
                self.progress_signal.emit(pct_base + 20, f'Fixing line geometries for {layer_name}...')
                input_line = self._fix_geometries(proj_line)
            self.progress_signal.emit(pct_base + 35, f"Buffering line corridor ({config['buffer_width']} m)...")
            buffer_layer = self._create_buffer(input_line, config['buffer_width'], adv, 'memory:', f'{layer_name}_Buffer')
            self.progress_signal.emit(pct_base + 50, 'Aligning Cadastral layer projection...')
            proj_cadastral = self._reproject_layer(cadastral_layer, target_crs, 'memory:', 'Cadastral_Projected')
            self.progress_signal.emit(pct_base + 65, f'Extracting touching cadastral parcels for {layer_name}...')
            affected_layer = self._extract_parcels(proj_cadastral, buffer_layer, 'memory:', f'{layer_name}_Affected_Parcels')
            affected_layer.setName(f'{layer_name}_Affected_Parcels')
            if merge_outputs:
                affected_layers_mem.append(affected_layer)
            self.progress_signal.emit(pct_base + 75, f'Clipping cadastral buffer polygons for {layer_name}...')
            clipped_layer = self._clip_layer(proj_cadastral, buffer_layer, 'memory:', f'{layer_name}_Clipped_Cadastral')
            clipped_layer.setName(f'{layer_name}_Clipped_Cadastral')
            if merge_outputs:
                clipped_layers_mem.append(clipped_layer)
            self.progress_signal.emit(pct_base + 85, f'Exporting KMZ & CSV files for {layer_name}...')
            kmz_affected_path = os.path.join(output_folder, f'{sanitized_name}_Affected_Parcels.kmz')
            self.export_to_kmz_with_labels(affected_layer, label_field, kmz_affected_path, outline_color='ff00ffff', line_width=2.0)
            kmz_clipped_path = os.path.join(output_folder, f'{sanitized_name}_Clipped_Cadastral.kmz')
            self.export_to_kmz_with_labels(clipped_layer, label_field, kmz_clipped_path, outline_color='ff0000ff', line_width=2.5)
            csv_path = os.path.join(output_folder, f'{sanitized_name}_Clipped_Cadastral.csv')
            self._export_clipped_csv(clipped_layer, csv_path)
            count = affected_layer.featureCount()
            area_sqm = sum((f.geometry().area() for f in affected_layer.getFeatures()))
            total_parcels_affected += count
            total_area_affected += area_sqm
            aff_prims = [{'wkt': f.geometry().asWkt(), 'attrs': [None if v is None or str(v) == 'NULL' else v if isinstance(v, (int, float, str)) else str(v) for v in f.attributes()]} for f in affected_layer.getFeatures() if f.hasGeometry() and (not f.geometry().isEmpty())]
            clip_prims = [{'wkt': f.geometry().asWkt(), 'attrs': [None if v is None or str(v) == 'NULL' else v if isinstance(v, (int, float, str)) else str(v) for v in f.attributes()]} for f in clipped_layer.getFeatures() if f.hasGeometry() and (not f.geometry().isEmpty())]
            line_payload = {'line_name': layer_name, 'crs_auth': target_crs.authid(), 'count': count, 'area_ha': area_sqm / 10000.0, 'affected_primitives': aff_prims, 'clipped_primitives': clip_prims}
            self.line_finished_signal.emit(line_payload)
            self.log_signal.emit(f"Layer '{layer_name}': Found {count} affected parcels ({area_sqm / 10000.0:.2f} ha). Saved KMZs & CSV.", 'info')
            results.append({'layer': layer_name, 'voltage': config['voltage'], 'buffer': config['buffer_width'], 'parcels': count, 'area_sqm': area_sqm, 'area_ha': area_sqm / 10000.0, 'affected_kmz': kmz_affected_path, 'clipped_kmz': kmz_clipped_path, 'clipped_csv': csv_path})
            if not merge_outputs:
                del affected_layer
                del clipped_layer
            del proj_line
            del buffer_layer
            del proj_cadastral
            gc.collect()
        if merge_outputs and len(affected_layers_mem) > 1 and (not self._is_cancelled):
            self.progress_signal.emit(95, 'Merging output layers across queue...')
            self.log_signal.emit('Merging affected and clipped layer sets...', 'info')
            self._merge_and_stack_output_layers(affected_layers_mem, clipped_layers_mem, label_field, output_folder)
        self.progress_signal.emit(100, 'Processing complete!')
        elapsed = time.time() - start_time
        res_summary = {'total_layers': len(results), 'total_parcels': total_parcels_affected, 'total_area_ha': total_area_affected / 10000.0, 'elapsed_seconds': elapsed, 'output_folder': output_folder, 'label_field': label_field, 'line_names': line_names_list}
        return res_summary

    def _determine_crs(self, layer: QgsVectorLayer, auto_utm: bool, manual_crs: QgsCoordinateReferenceSystem, override_crs: Optional[QgsCoordinateReferenceSystem]) -> QgsCoordinateReferenceSystem:
        if override_crs and override_crs.isValid():
            return override_crs
        if auto_utm:
            epsg = UTMHelper.calculate_utm_epsg(layer.extent(), layer.crs())
            return QgsCoordinateReferenceSystem(f'EPSG:{epsg}')
        return manual_crs if manual_crs.isValid() else QgsCoordinateReferenceSystem('EPSG:3857')

    def _reproject_layer(self, layer: QgsVectorLayer, target_crs: QgsCoordinateReferenceSystem, output_dest: str, layer_name: str) -> QgsVectorLayer:
        if layer.crs() == target_crs and output_dest == 'memory:':
            return layer
        out_spec = f'memory:{layer_name}' if output_dest == 'memory:' else output_dest
        params = {'INPUT': layer, 'TARGET_CRS': target_crs, 'OUTPUT': out_spec}
        res = get_processing().run('native:reprojectlayer', params)
        out_layer = res['OUTPUT']
        if isinstance(out_layer, str):
            out_layer = QgsVectorLayer(out_layer, layer_name, 'ogr')
        return out_layer

    def _fix_geometries(self, layer: QgsVectorLayer) -> QgsVectorLayer:
        params = {'INPUT': layer, 'OUTPUT': 'memory:Fixed_Geom'}
        res = get_processing().run('native:fixgeometries', params)
        out_layer = res['OUTPUT']
        if isinstance(out_layer, str):
            out_layer = QgsVectorLayer(out_layer, 'Fixed_Geom', 'ogr')
        return out_layer

    def _create_buffer(self, layer: QgsVectorLayer, distance: float, adv: AdvancedBufferSettings, output_dest: str, layer_name: str) -> QgsVectorLayer:
        out_spec = f'memory:{layer_name}' if output_dest == 'memory:' else output_dest
        params = {'INPUT': layer, 'DISTANCE': distance, 'SEGMENTS': adv.segments, 'END_CAP_STYLE': adv.end_cap_style, 'JOIN_STYLE': adv.join_style, 'MITER_LIMIT': adv.miter_limit, 'DISSOLVE': adv.dissolve, 'OUTPUT': out_spec}
        res = get_processing().run('native:buffer', params)
        out_layer = res['OUTPUT']
        if isinstance(out_layer, str):
            out_layer = QgsVectorLayer(out_layer, layer_name, 'ogr')
        return out_layer

    def _extract_parcels(self, cadastral_layer: QgsVectorLayer, buffer_layer: QgsVectorLayer, output_dest: str='memory:', layer_name: str='Affected_Parcels') -> QgsVectorLayer:
        params = {'INPUT': cadastral_layer, 'PREDICATE': [0], 'INTERSECT': buffer_layer, 'OUTPUT': output_dest}
        res = get_processing().run('native:extractbylocation', params)
        out_layer = res['OUTPUT']
        if isinstance(out_layer, str):
            out_layer = QgsVectorLayer(out_layer, layer_name, 'ogr')
        return out_layer

    def _clip_layer(self, cadastral_layer: QgsVectorLayer, buffer_layer: QgsVectorLayer, output_dest: str='memory:', layer_name: str='Clipped_Cadastral') -> QgsVectorLayer:
        params = {'INPUT': cadastral_layer, 'OVERLAY': buffer_layer, 'OUTPUT': output_dest}
        res = get_processing().run('native:clip', params)
        out_layer = res['OUTPUT']
        if isinstance(out_layer, str):
            out_layer = QgsVectorLayer(out_layer, layer_name, 'ogr')
        return out_layer

    def _apply_labeling(self, layer: QgsVectorLayer, label_field: str) -> None:
        if not layer or not layer.isValid() or (not label_field):
            return
        if label_field in [f.name() for f in layer.fields()]:
            label_settings = QgsPalLayerSettings()
            label_settings.fieldName = label_field
            label_settings.enabled = True
            text_format = label_settings.format()
            text_format.setSize(10)
            text_format.setColor(QColor('black'))
            buffer = text_format.buffer()
            buffer.setEnabled(True)
            buffer.setSize(1.5)
            buffer.setColor(QColor('white'))
            text_format.setBuffer(buffer)
            label_settings.setFormat(text_format)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
            layer.setLabelsEnabled(True)
            layer.triggerRepaint()

    def _export_clipped_csv(self, layer: QgsVectorLayer, csv_path: str) -> None:
        if not layer or not layer.isValid():
            return
        fields = [field.name() for field in layer.fields()]
        with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
            writer = csv.writer(cf)
            writer.writerow(fields)
            for feat in layer.getFeatures():
                writer.writerow([feat[name] for name in fields])

    @staticmethod
    def _geometry_to_kml_polygon(geom: QgsGeometry) -> str:
        if geom.isEmpty():
            return ''
        if not geom.isMultipart():
            poly = geom.asPolygon()
            if not poly:
                return ''
            outer = ' '.join([f'{pt.x():.7f},{pt.y():.7f},0' for pt in poly[0]])
            outer_xml = f'<outerBoundaryIs><LinearRing><coordinates>{outer}</coordinates></LinearRing></outerBoundaryIs>'
            inner_xmls = []
            for ring in poly[1:]:
                inner_coords = ' '.join([f'{pt.x():.7f},{pt.y():.7f},0' for pt in ring])
                inner_xmls.append(f'<innerBoundaryIs><LinearRing><coordinates>{inner_coords}</coordinates></LinearRing></innerBoundaryIs>')
            return f"<Polygon>{outer_xml}{''.join(inner_xmls)}</Polygon>"
        else:
            mpoly = geom.asMultiPolygon()
            if not mpoly:
                return ''
            poly_xmls = []
            for poly in mpoly:
                outer = ' '.join([f'{pt.x():.7f},{pt.y():.7f},0' for pt in poly[0]])
                outer_xml = f'<outerBoundaryIs><LinearRing><coordinates>{outer}</coordinates></LinearRing></outerBoundaryIs>'
                inner_xmls = []
                for ring in poly[1:]:
                    inner_coords = ' '.join([f'{pt.x():.7f},{pt.y():.7f},0' for pt in ring])
                    inner_xmls.append(f'<innerBoundaryIs><LinearRing><coordinates>{inner_coords}</coordinates></LinearRing></innerBoundaryIs>')
                poly_xmls.append(f"<Polygon>{outer_xml}{''.join(inner_xmls)}</Polygon>")
            return ''.join(poly_xmls)

    def export_to_kmz_with_labels(self, layer: QgsVectorLayer, label_field_name: str, output_kmz_path: str, outline_color: str='ff0000ff', line_width: float=2.5) -> bool:
        if not layer or not layer.isValid():
            return False
        try:
            wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
            transform = None
            if layer.crs() != wgs84 and layer.crs().isValid():
                transform = QgsCoordinateTransform(layer.crs(), wgs84, QgsProject.instance())
            layer_name = layer.name()
            style_id = 'OutlineStyle'
            kml_header = f'<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n  <Document>\n    <name>{layer_name}</name>\n    <Style id="{style_id}">\n      <IconStyle>\n        <scale>0</scale>\n      </IconStyle>\n      <LabelStyle>\n        <color>ffffffff</color>\n        <scale>1.1</scale>\n      </LabelStyle>\n      <LineStyle>\n        <color>{outline_color}</color>\n        <width>{line_width}</width>\n      </LineStyle>\n      <PolyStyle>\n        <fill>0</fill>\n        <outline>1</outline>\n      </PolyStyle>\n    </Style>\n'
            placemarks = []
            fields = [f.name() for f in layer.fields()]
            has_label = label_field_name in fields if label_field_name else False
            for feat in layer.getFeatures():
                if not feat.hasGeometry() or feat.geometry().isEmpty():
                    continue
                geom = QgsGeometry(feat.geometry())
                if transform:
                    geom.transform(transform)
                poly_xml = self._geometry_to_kml_polygon(geom)
                if not poly_xml:
                    continue
                pt_geom = geom.pointOnSurface()
                if pt_geom.isEmpty():
                    pt_geom = geom.centroid()
                pt_xy = pt_geom.asPoint()
                point_xml = f'<Point><coordinates>{pt_xy.x():.7f},{pt_xy.y():.7f},0</coordinates></Point>'
                label_val = ''
                if has_label:
                    raw_val = feat[label_field_name]
                    label_val = str(raw_val) if raw_val is not None else ''
                escaped_val = label_val.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                pm = f'    <Placemark>\n      <name>{escaped_val}</name>\n      <styleUrl>#{style_id}</styleUrl>\n      <MultiGeometry>\n        {point_xml}\n        {poly_xml}\n      </MultiGeometry>\n    </Placemark>'
                placemarks.append(pm)
            kml_footer = '  </Document>\n</kml>'
            full_kml = kml_header + '\n'.join(placemarks) + '\n' + kml_footer
            temp_kml = output_kmz_path.rsplit('.', 1)[0] + '_temp.kml'
            with open(temp_kml, 'w', encoding='utf-8') as f:
                f.write(full_kml)
            if output_kmz_path.lower().endswith('.kmz'):
                with zipfile.ZipFile(output_kmz_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(temp_kml, 'doc.kml')
                if os.path.exists(temp_kml):
                    os.remove(temp_kml)
            else:
                if os.path.exists(output_kmz_path):
                    os.remove(output_kmz_path)
                os.rename(temp_kml, output_kmz_path)
            return os.path.exists(output_kmz_path)
        except Exception as e:
            self.log_signal.emit(f'Warning: Failed KMZ export to {output_kmz_path}: {str(e)}', 'warning')
            return False

    def _merge_and_stack_output_layers(self, affected_layers_list: List[QgsVectorLayer], clipped_layers_list: List[QgsVectorLayer], label_field: str, output_folder: str) -> None:
        res_affected = get_processing().run('native:mergevectorlayers', {'LAYERS': affected_layers_list, 'OUTPUT': 'memory:Merged_Affected_Parcels'})
        merged_affected = res_affected['OUTPUT']
        if isinstance(merged_affected, str):
            merged_affected = QgsVectorLayer(merged_affected, 'Merged_Affected_Parcels', 'ogr')
        merged_affected.setName('Merged_Affected_Parcels')
        res_clipped = get_processing().run('native:mergevectorlayers', {'LAYERS': clipped_layers_list, 'OUTPUT': 'memory:Merged_Clipped_Buffer_Cadastral'})
        merged_clipped = res_clipped['OUTPUT']
        if isinstance(merged_clipped, str):
            merged_clipped = QgsVectorLayer(merged_clipped, 'Merged_Clipped_Buffer_Cadastral', 'ogr')
        merged_clipped.setName('Merged_Clipped_Buffer_Cadastral')
        self._apply_labeling(merged_clipped, label_field)
        merged_csv_path = os.path.join(output_folder, 'Merged_Clipped_Buffer_Cadastral.csv')
        self._export_clipped_csv(merged_clipped, merged_csv_path)
        kmz_merged_clipped = os.path.join(output_folder, 'Merged_Clipped_Buffer_Cadastral.kmz')
        self.export_to_kmz_with_labels(merged_clipped, label_field, kmz_merged_clipped, outline_color='ff0000ff', line_width=2.5)
        kmz_merged_affected = os.path.join(output_folder, 'Merged_Affected_Parcels.kmz')
        self.export_to_kmz_with_labels(merged_affected, label_field, kmz_merged_affected, outline_color='ff00ffff', line_width=2.0)

    @staticmethod
    def _sanitize(name: str) -> str:
        return ''.join((c if c.isalnum() or c in ('_', '-') else '_' for c in name))

class ProcessingWorkerThread(QThread):
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str, str)
    line_finished_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, processor: PowerCorridorProcessor, cadastral_layer: QgsVectorLayer, layer_configs: List[Dict[str, Any]], auto_utm: bool, manual_crs: QgsCoordinateReferenceSystem, output_folder: str, label_field: str, load_outputs: bool, merge_outputs: bool) -> None:
        super().__init__()
        self.processor = processor
        self.cadastral_layer = cadastral_layer
        self.layer_configs = layer_configs
        self.auto_utm = auto_utm
        self.manual_crs = manual_crs
        self.output_folder = output_folder
        self.label_field = label_field
        self.load_outputs = load_outputs
        self.merge_outputs = merge_outputs
        self.processor.progress_signal.connect(self.progress_signal.emit)
        self.processor.log_signal.connect(self.log_signal.emit)
        self.processor.line_finished_signal.connect(self.line_finished_signal.emit)

    def run(self) -> None:
        try:
            res_summary = self.processor.process(cadastral_layer=self.cadastral_layer, layer_configs=self.layer_configs, auto_utm=self.auto_utm, manual_crs=self.manual_crs, output_folder=self.output_folder, label_field=self.label_field, merge_outputs=self.merge_outputs)
            self.finished_signal.emit(res_summary)
        except Exception as err:
            self.error_signal.emit(str(err))

class PowerCorridorDialog(QDialog):

    def __init__(self, parent: Optional[QWidget]=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Cadastral Parcel Extractor')
        self.resize(850, 680)
        self.processor = PowerCorridorProcessor()
        self.worker: Optional[ProcessingWorkerThread] = None
        self._adv_settings_map: Dict[int, AdvancedBufferSettings] = {}
        self._setup_ui()
        self._populate_layers()
        self._load_settings()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        master_group = QGroupBox('Master Projection & Buffer Settings')
        master_layout = QVBoxLayout(master_group)
        row1 = QHBoxLayout()
        self.chk_auto_utm = QCheckBox('Auto Detect Master UTM Zone')
        self.chk_auto_utm.setChecked(True)
        self.chk_auto_utm.toggled.connect(self._toggle_utm)
        row1.addWidget(self.chk_auto_utm)
        row1.addWidget(QLabel('Master CRS:'))
        self.crs_widget = QgsProjectionSelectionWidget(self)
        self.crs_widget.setOptionVisible(QgsProjectionSelectionWidget.CrsNotSet, False)
        self.crs_widget.setEnabled(False)
        row1.addWidget(self.crs_widget, 1)
        master_layout.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Preset Line Voltage:'))
        self.combo_master_voltage = QComboBox()
        self.combo_master_voltage.addItems(list(VOLTAGE_PRESETS.keys()))
        self.combo_master_voltage.setCurrentText('220 kV')
        self.combo_master_voltage.currentTextChanged.connect(self._on_master_voltage_changed)
        row2.addWidget(self.combo_master_voltage)
        row2.addWidget(QLabel('Master Buffer Width (m):'))
        self.spin_master_buffer = QDoubleSpinBox()
        self.spin_master_buffer.setRange(0.1, 10000.0)
        self.spin_master_buffer.setValue(25.0)
        self.spin_master_buffer.setSingleStep(1.0)
        row2.addWidget(self.spin_master_buffer)
        master_layout.addLayout(row2)
        main_layout.addWidget(master_group)
        cad_group = QGroupBox('Target Cadastral Layer & Label Settings')
        cad_layout = QHBoxLayout(cad_group)
        cad_layout.addWidget(QLabel('Cadastral Layer:'))
        self.combo_cadastral = QComboBox()
        self.combo_cadastral.currentIndexChanged.connect(self._on_cadastral_layer_changed)
        cad_layout.addWidget(self.combo_cadastral, 1)
        cad_layout.addWidget(QLabel('Label Field:'))
        self.label_field_combo = QgsFieldComboBox(self)
        cad_layout.addWidget(self.label_field_combo, 1)
        main_layout.addWidget(cad_group)
        table_group = QGroupBox('Transmission Line Corridor Queue')
        table_layout = QVBoxLayout(table_group)
        tbl_ctrl_layout = QHBoxLayout()
        btn_add = QPushButton('Add Line Layer')
        btn_add.setIcon(QIcon.fromTheme('list-add'))
        btn_add.clicked.connect(self._add_table_row)
        tbl_ctrl_layout.addWidget(btn_add)
        btn_refresh = QPushButton('Refresh Layers')
        btn_refresh.setIcon(QIcon.fromTheme('view-refresh'))
        btn_refresh.clicked.connect(self._populate_layers)
        tbl_ctrl_layout.addWidget(btn_refresh)
        tbl_ctrl_layout.addStretch()
        table_layout.addLayout(tbl_ctrl_layout)
        self.table_layers = QTableWidget()
        self.table_layers.setMinimumHeight(190)
        self.table_layers.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table_layers.setColumnCount(7)
        self.table_layers.setHorizontalHeaderLabels(['Enable', 'Input Layer', 'Voltage Preset', 'Buffer (m)', 'Projection', 'Advanced', 'Remove'])
        self.table_layers.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table_layout.addWidget(self.table_layers)
        main_layout.addWidget(table_group)
        out_group = QGroupBox('Output Folder & Layer Options')
        out_layout = QVBoxLayout(out_group)
        out_path_layout = QHBoxLayout()
        out_path_layout.addWidget(QLabel('Output Directory:'))
        self.txt_out_folder = QLineEdit()
        btn_browse = QPushButton('Select Folder...')
        btn_browse.clicked.connect(self._browse_output_folder)
        out_path_layout.addWidget(self.txt_out_folder, 1)
        out_path_layout.addWidget(btn_browse)
        out_layout.addLayout(out_path_layout)
        chk_layout = QHBoxLayout()
        self.chk_load_output = QCheckBox('Load created layers into QGIS')
        self.chk_load_output.setChecked(True)
        self.chk_merge_all = QCheckBox('Merge output cadastral layers')
        chk_layout.addWidget(self.chk_load_output)
        chk_layout.addWidget(self.chk_merge_all)
        chk_layout.addStretch()
        out_layout.addLayout(chk_layout)
        main_layout.addWidget(out_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        self.lbl_status = QLabel('Ready')
        main_layout.addWidget(self.lbl_status)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(120)
        main_layout.addWidget(self.txt_log)
        btn_box = QHBoxLayout()
        self.btn_run = QPushButton('Process & Extract Parcels')
        self.btn_run.setStyleSheet('font-weight: bold; padding: 6px;')
        self.btn_run.clicked.connect(self._execute_processing)
        self.btn_cancel = QPushButton('Cancel')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_processing)
        btn_close = QPushButton('Close')
        btn_close.clicked.connect(self.close)
        btn_box.addWidget(self.btn_run)
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(btn_close)
        main_layout.addLayout(btn_box)

    def _toggle_utm(self, checked: bool) -> None:
        self.crs_widget.setEnabled(not checked)

    def _on_master_voltage_changed(self, text: str) -> None:
        if text in VOLTAGE_PRESETS and text != 'Custom':
            val = VOLTAGE_PRESETS[text]
            self.spin_master_buffer.setValue(val)

    def _on_cadastral_layer_changed(self) -> None:
        cad_id = self.combo_cadastral.currentData()
        cad_layer = QgsProject.instance().mapLayer(cad_id) if cad_id else None
        if cad_layer and isinstance(cad_layer, QgsVectorLayer) and cad_layer.isValid():
            self.label_field_combo.setLayer(cad_layer)
            idx = self.label_field_combo.findText('PIN', Qt.MatchCaseSensitive)
            if idx == -1:
                idx = self.label_field_combo.findText('PIN', Qt.MatchContains)
            if idx != -1:
                self.label_field_combo.setCurrentIndex(idx)

    def _populate_layers(self) -> None:
        self.combo_cadastral.clear()
        polygon_layers = []
        line_layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            if layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                polygon_layers.append(layer)
            elif layer.geometryType() == QgsWkbTypes.LineGeometry:
                line_layers.append(layer)
        for lyr in polygon_layers:
            self.combo_cadastral.addItem(lyr.name(), lyr.id())
        if not polygon_layers:
            self._append_log('No polygon vector layers found in current project.', 'warning')
        else:
            self._on_cadastral_layer_changed()
        for r in range(self.table_layers.rowCount()):
            cb = self.table_layers.cellWidget(r, 1)
            if isinstance(cb, QComboBox):
                cur = cb.currentData()
                cb.clear()
                for l in line_layers:
                    cb.addItem(l.name(), l.id())
                idx = cb.findData(cur)
                if idx >= 0:
                    cb.setCurrentIndex(idx)
                self._auto_detect_voltage_for_row(r)

    def _auto_detect_voltage_for_row(self, row: int) -> None:
        combo_line = self.table_layers.cellWidget(row, 1)
        if isinstance(combo_line, QComboBox):
            layer_name = combo_line.currentText()
            detected = detect_voltage_from_name(layer_name)
            if detected and detected in VOLTAGE_PRESETS:
                combo_volt = self.table_layers.cellWidget(row, 2)
                spin_buf = self.table_layers.cellWidget(row, 3)
                if isinstance(combo_volt, QComboBox):
                    combo_volt.setCurrentText(detected)
                if isinstance(spin_buf, QDoubleSpinBox):
                    spin_buf.setValue(VOLTAGE_PRESETS[detected])

    def _on_row_layer_changed_for_sender(self, index: int) -> None:
        combo = self.sender()
        if not combo:
            return
        for r in range(self.table_layers.rowCount()):
            if self.table_layers.cellWidget(r, 1) == combo:
                self._auto_detect_voltage_for_row(r)
                break

    def _add_table_row(self) -> None:
        r = self.table_layers.rowCount()
        self.table_layers.insertRow(r)
        self._adv_settings_map[r] = AdvancedBufferSettings()
        chk_item = QTableWidgetItem()
        chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        chk_item.setCheckState(Qt.Checked)
        self.table_layers.setItem(r, 0, chk_item)
        combo_line = QComboBox()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                if layer.geometryType() == QgsWkbTypes.LineGeometry:
                    combo_line.addItem(layer.name(), layer.id())
        combo_line.currentIndexChanged.connect(self._on_row_layer_changed_for_sender)
        self.table_layers.setCellWidget(r, 1, combo_line)
        combo_volt = QComboBox()
        combo_volt.addItems(list(VOLTAGE_PRESETS.keys()))
        combo_volt.setCurrentText(self.combo_master_voltage.currentText())
        combo_volt.currentTextChanged.connect(self._on_row_voltage_changed_for_sender)
        self.table_layers.setCellWidget(r, 2, combo_volt)
        spin_buf = QDoubleSpinBox()
        spin_buf.setRange(0.1, 10000.0)
        spin_buf.setValue(self.spin_master_buffer.value())
        self.table_layers.setCellWidget(r, 3, spin_buf)
        crs_wdg = QgsProjectionSelectionWidget()
        crs_wdg.setOptionVisible(QgsProjectionSelectionWidget.CrsNotSet, True)
        master_crs = self.crs_widget.crs()
        if master_crs.isValid():
            crs_wdg.setCrs(master_crs)
        else:
            crs_wdg.setCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
        self.table_layers.setCellWidget(r, 4, crs_wdg)
        btn_adv = QPushButton('Advanced')
        btn_adv.clicked.connect(self._open_advanced_dialog_for_sender)
        self.table_layers.setCellWidget(r, 5, btn_adv)
        btn_rem = QPushButton('Remove')
        btn_rem.clicked.connect(self._remove_table_row_for_sender)
        self.table_layers.setCellWidget(r, 6, btn_rem)
        self._auto_detect_voltage_for_row(r)

    def _on_row_voltage_changed_for_sender(self, voltage_text: str) -> None:
        combo = self.sender()
        if not combo:
            return
        for r in range(self.table_layers.rowCount()):
            if self.table_layers.cellWidget(r, 2) == combo:
                if voltage_text in VOLTAGE_PRESETS and voltage_text != 'Custom':
                    spin = self.table_layers.cellWidget(r, 3)
                    if isinstance(spin, QDoubleSpinBox):
                        spin.setValue(VOLTAGE_PRESETS[voltage_text])
                break

    def _open_advanced_dialog_for_sender(self) -> None:
        button = self.sender()
        if not button:
            return
        for r in range(self.table_layers.rowCount()):
            if self.table_layers.cellWidget(r, 5) == button:
                self._open_advanced_dialog(r)
                break

    def _remove_table_row_for_sender(self) -> None:
        button = self.sender()
        if not button:
            return
        for r in range(self.table_layers.rowCount()):
            if self.table_layers.cellWidget(r, 6) == button:
                self._remove_table_row(r)
                break

    def _open_advanced_dialog(self, row: int) -> None:
        cur_settings = self._adv_settings_map.get(row, AdvancedBufferSettings())
        dlg = AdvancedBufferDialog(self, cur_settings)
        if dlg.exec_() == QDialog.Accepted:
            self._adv_settings_map[row] = dlg.get_settings()
            self._append_log(f'Updated advanced options for queue item #{row + 1}.', 'info')

    def _remove_table_row(self, row: int) -> None:
        self.table_layers.removeRow(row)
        new_map = {}
        for r in range(self.table_layers.rowCount()):
            new_map[r] = self._adv_settings_map.get(r, AdvancedBufferSettings())
        self._adv_settings_map = new_map

    def _browse_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, 'Select Output Directory', self.txt_out_folder.text())
        if folder:
            self.txt_out_folder.setText(folder)

    def _execute_processing(self) -> None:
        cad_id = self.combo_cadastral.currentData()
        cad_layer = QgsProject.instance().mapLayer(cad_id) if cad_id else None
        if not cad_layer or not cad_layer.isValid():
            QMessageBox.critical(self, 'Validation Error', 'Please select a valid Cadastral polygon layer.')
            return
        out_folder = self.txt_out_folder.text().strip()
        if not out_folder:
            QMessageBox.critical(self, 'Validation Error', 'Please select an output folder.')
            return
        label_field = self.label_field_combo.currentText().strip()
        layer_configs: List[Dict[str, Any]] = []
        for r in range(self.table_layers.rowCount()):
            item = self.table_layers.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                cb_layer = self.table_layers.cellWidget(r, 1)
                cb_volt = self.table_layers.cellWidget(r, 2)
                sp_buf = self.table_layers.cellWidget(r, 3)
                crs_w = self.table_layers.cellWidget(r, 4)
                lyr_id = cb_layer.currentData() if isinstance(cb_layer, QComboBox) else None
                line_lyr = QgsProject.instance().mapLayer(lyr_id) if lyr_id else None
                if line_lyr and line_lyr.isValid():
                    layer_configs.append({'layer': line_lyr, 'voltage': cb_volt.currentText() if isinstance(cb_volt, QComboBox) else 'Custom', 'buffer_width': sp_buf.value() if isinstance(sp_buf, QDoubleSpinBox) else 25.0, 'crs_override': crs_w.crs() if isinstance(crs_w, QgsProjectionSelectionWidget) and crs_w.crs().isValid() else None, 'advanced': self._adv_settings_map.get(r, AdvancedBufferSettings())})
        if not layer_configs:
            QMessageBox.warning(self, 'Validation Error', 'No enabled line layers configured in queue table.')
            return
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self._append_log('Starting Power Corridor Processing Job...', 'info')
        self.worker = ProcessingWorkerThread(processor=self.processor, cadastral_layer=cad_layer, layer_configs=layer_configs, auto_utm=self.chk_auto_utm.isChecked(), manual_crs=self.crs_widget.crs(), output_folder=out_folder, label_field=label_field, load_outputs=self.chk_load_output.isChecked(), merge_outputs=self.chk_merge_all.isChecked())
        self.worker.progress_signal.connect(self._update_progress)
        self.worker.log_signal.connect(self._append_log)
        self.worker.line_finished_signal.connect(self._on_single_line_finished)
        self.worker.finished_signal.connect(self._on_processing_finished)
        self.worker.error_signal.connect(self._on_processing_error)
        self.worker.start()

    def _cancel_processing(self) -> None:
        if self.processor:
            self.processor.cancel()
        self._append_log('Cancellation requested...', 'warning')

    def _apply_qgis_polygon_style(self, layer: QgsVectorLayer, is_clipped: bool=True) -> None:
        if not layer or not layer.isValid():
            return
        symbol = layer.renderer().symbol()
        if not symbol:
            return
        sl = symbol.symbolLayer(0)
        if is_clipped:
            symbol.setColor(QColor(255, 0, 0, 40))
            if sl:
                sl.setStrokeColor(QColor(220, 38, 38))
                sl.setStrokeWidth(1.2)
        else:
            symbol.setColor(QColor(245, 158, 11, 25))
            if sl:
                sl.setStrokeColor(QColor(217, 119, 6))
                sl.setStrokeWidth(0.8)
        layer.triggerRepaint()

    def _on_single_line_finished(self, line_data: dict) -> None:
        if not self.chk_load_output.isChecked():
            return
        root = QgsProject.instance().layerTreeRoot()
        label_field = self.label_field_combo.currentText().strip()
        cad_id = self.combo_cadastral.currentData()
        cad_layer = QgsProject.instance().mapLayer(cad_id) if cad_id else None
        cad_fields = cad_layer.fields() if cad_layer and cad_layer.isValid() else None
        line_name = line_data['line_name']
        crs_auth = line_data['crs_auth']
        aff_prims = line_data['affected_primitives']
        clip_prims = line_data['clipped_primitives']
        clip_mem = QgsVectorLayer(f'Polygon?crs={crs_auth}', f'{line_name}_Clipped_Cadastral', 'memory')
        dp_clip = clip_mem.dataProvider()
        if cad_fields:
            dp_clip.addAttributes(cad_fields)
            clip_mem.updateFields()
        clip_feats = []
        for prim in clip_prims:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromWkt(prim['wkt']))
            f.setAttributes(prim['attrs'])
            clip_feats.append(f)
        dp_clip.addFeatures(clip_feats)
        clip_mem.updateExtents()
        self._apply_qgis_polygon_style(clip_mem, is_clipped=True)
        self.processor._apply_labeling(clip_mem, label_field)
        aff_mem = QgsVectorLayer(f'Polygon?crs={crs_auth}', f'{line_name}_Affected_Parcels', 'memory')
        dp_aff = aff_mem.dataProvider()
        if cad_fields:
            dp_aff.addAttributes(cad_fields)
            aff_mem.updateFields()
        aff_feats = []
        for prim in aff_prims:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromWkt(prim['wkt']))
            f.setAttributes(prim['attrs'])
            aff_feats.append(f)
        dp_aff.addFeatures(aff_feats)
        aff_mem.updateExtents()
        self._apply_qgis_polygon_style(aff_mem, is_clipped=False)
        QgsProject.instance().addMapLayer(clip_mem, False)
        QgsProject.instance().addMapLayer(aff_mem, False)
        root.insertLayer(0, clip_mem)
        root.insertLayer(1, aff_mem)

    def _on_processing_finished(self, res: dict) -> None:
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._save_settings()
        msg = f"Processing Complete!\n\n• Lines Processed: {res['total_layers']}\n• Total Affected Parcels: {res['total_parcels']}\n• Total Affected Area: {res['total_area_ha']:.2f} ha\n• Processing Time: {res['elapsed_seconds']:.2f} s\n• Output Folder: {res['output_folder']}\n• Output Files: Outlined KMZ & CSV files for Google Earth & Land Scheduling"
        QMessageBox.information(self, 'Success', msg)

    def _on_processing_error(self, err_msg: str) -> None:
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._append_log(f'Error during execution: {err_msg}', 'error')
        QMessageBox.critical(self, 'Processing Error', f'Failed to execute analysis:\n{err_msg}')

    def _append_log(self, message: str, level: str='info') -> None:
        timestamp = datetime.now().strftime('%H:%M:%S')
        color = '#ef4444' if level == 'error' else '#f59e0b' if level == 'warning' else '#10b981'
        html = f"<font color='gray'>[{timestamp}]</font> <font color='{color}'><b>{message}</b></font>"
        self.txt_log.append(html)
        self.txt_log.moveCursor(QTextCursor.End)

    def _update_progress(self, percentage: int, status_text: str) -> None:
        self.progress_bar.setValue(percentage)
        self.lbl_status.setText(status_text)

    def _save_settings(self) -> None:
        st = QSettings('PowerCorridorPlugin', 'PowerCorridor')
        st.setValue('auto_utm', self.chk_auto_utm.isChecked())
        st.setValue('manual_crs', self.crs_widget.crs().authid())
        st.setValue('master_voltage', self.combo_master_voltage.currentText())
        st.setValue('master_buffer', self.spin_master_buffer.value())
        st.setValue('output_folder', self.txt_out_folder.text())
        st.setValue('geometry', self.saveGeometry())

    def _load_settings(self) -> None:
        st = QSettings('PowerCorridorPlugin', 'PowerCorridor')
        self.chk_auto_utm.setChecked(st.value('auto_utm', True, type=bool))
        crs_auth = st.value('manual_crs', 'EPSG:3857', type=str)
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem(crs_auth))
        m_volt = st.value('master_voltage', '220 kV', type=str)
        if m_volt in VOLTAGE_PRESETS:
            self.combo_master_voltage.setCurrentText(m_volt)
        m_buf = st.value('master_buffer', 25.0, type=float)
        self.spin_master_buffer.setValue(m_buf)
        default_out = os.path.expanduser('~/PowerCorridor_Outputs')
        self.txt_out_folder.setText(st.value('output_folder', default_out, type=str))
        geom = st.value('geometry')
        if geom:
            self.restoreGeometry(geom)
        if self.table_layers.rowCount() == 0:
            self._add_table_row()

class PowerCorridorPlugin:

    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action: Optional[QAction] = None
        self.dlg: Optional[PowerCorridorDialog] = None
        self.menu_name = 'Ineffable Tools'

    def initGui(self) -> None:
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path)
        self.action = QAction('Cadastral Parcel Extractor', self.iface.mainWindow())
        self.action.setIcon(icon)
        self.action.setStatusTip('Extract complete cadastral land parcels touched by line corridors')
        self.action.triggered.connect(self.run)
        main_menu = self.iface.mainWindow().menuBar()
        found_menu = None
        for action in main_menu.actions():
            if action.text() == self.menu_name:
                found_menu = action.menu()
                break
        if not found_menu:
            found_menu = QMenu(self.menu_name, self.iface.mainWindow())
            main_menu.addMenu(found_menu)
        found_menu.addAction(self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self) -> None:
        main_menu = self.iface.mainWindow().menuBar()
        for action in main_menu.actions():
            if action.text() == self.menu_name:
                menu = action.menu()
                if menu and self.action:
                    menu.removeAction(self.action)
                break
        if self.action:
            self.iface.removeToolBarIcon(self.action)

    def run(self) -> None:
        if not self.dlg:
            self.dlg = PowerCorridorDialog(self.iface.mainWindow())
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

def qInitResources() -> None:
    pass

def qCleanupResources() -> None:
    pass
