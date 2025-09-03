# macan_stable_remover.py

import sys
import os
import tempfile
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

# =============================================================================
# BAGIAN 1: FUNGSI PROSESOR TERISOLASI
# Fungsi ini akan dijalankan di proses yang benar-benar terpisah untuk
# menjamin tidak ada konflik dengan GUI PyQt.
# =============================================================================
def process_image_in_subprocess(image_bytes):
    """
    Mengimpor dan menjalankan fungsi 'remove' di dalam prosesnya sendiri.
    Ini adalah inti dari stabilitas aplikasi.
    """
    try:
        # Impor dilakukan di sini agar hanya terjadi di dalam subprocess
        from backgroundremover.bg import remove as remove_bg
        
        # Panggil fungsi dari library
        result_bytes = remove_bg(image_bytes)
        
        # Mengembalikan hasil (sebagai bytes) dan tidak ada error
        return bytes(result_bytes), None
    except Exception as e:
        import traceback
        # Jika gagal, kembalikan pesan error yang lengkap
        return None, (str(e), traceback.format_exc())

# =============================================================================
# BAGIAN 2: Impor & Kelas-kelas PyQt6
# =============================================================================
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QMessageBox,
    QSizePolicy, QFrame
)
from PyQt6.QtGui import QPixmap, QIcon, QFont
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal

class Worker(QObject):
    """
    Worker yang mengatur pemrosesan di latar belakang.
    Tugasnya: membaca file, memanggil subprocess, menyimpan hasilnya ke file
    temporer, dan mengirim sinyal berisi path file hasil.
    """
    finished = pyqtSignal(str)  # Sinyal sukses, mengirimkan path file hasil
    error = pyqtSignal(str)     # Sinyal error, mengirimkan pesan
    progress = pyqtSignal(str)  # Sinyal untuk update status di UI

    def __init__(self, input_path):
        super().__init__()
        self.input_path = input_path

    def run(self):
        try:
            self.progress.emit("Membaca file gambar...")
            with open(self.input_path, 'rb') as f:
                img_bytes = f.read()

            self.progress.emit("Memulai proses penghapusan background...")
            
            # Gunakan ProcessPoolExecutor untuk stabilitas maksimal
            with ProcessPoolExecutor(max_workers=1) as executor:
                future = executor.submit(process_image_in_subprocess, img_bytes)
                result_bytes, error_info = future.result()

            if error_info:
                error_str, traceback_str = error_info
                print("--- Error dari Subprocess ---\n", traceback_str)
                self.error.emit(f"Gagal memproses gambar: {error_str}")
                return

            if not result_bytes:
                self.error.emit("Proses tidak menghasilkan data gambar.")
                return

            self.progress.emit("Menyimpan hasil...")
            
            # Buat nama file output yang unik di folder temporer sistem
            base_name = os.path.splitext(os.path.basename(self.input_path))[0]
            # tempfile.gettempdir() akan mencari folder temp (misal: C:\Users\User\AppData\Local\Temp)
            save_path = os.path.join(tempfile.gettempdir(), f"{base_name}_result.png")

            with open(save_path, 'wb') as f:
                f.write(result_bytes)

            # Kirim sinyal bahwa proses selesai dengan path file hasilnya
            self.finished.emit(save_path)

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            self.error.emit(f"Terjadi kesalahan: {e}")


class ImageResultViewer(QWidget):
    """
    Sebuah QWidget (jendela) baru yang simpel, khusus untuk menampilkan
    gambar hasil. Jendela ini terpisah total dari jendela utama.
    """
    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path
        self.setWindowTitle(f"Hasil Gambar - {os.path.basename(self.image_path)}")
        self.setMinimumSize(400, 400)

        layout = QVBoxLayout(self)
        self.image_label = QLabel("Memuat gambar...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        pixmap = QPixmap(self.image_path)
        if pixmap.isNull():
             self.image_label.setText("Gagal memuat gambar hasil.")
        else:
             self.image_label.setPixmap(pixmap.scaled(
                self.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            ))
        
        # Set background jendela agar gambar transparan terlihat jelas
        self.setStyleSheet("background-color: #505050;")

    def resizeEvent(self, event):
        # Agar gambar ikut di-resize saat jendela diubah ukurannya
        if hasattr(self, 'image_label') and self.image_label.pixmap():
            self.image_label.setPixmap(QPixmap(self.image_path).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        super().resizeEvent(event)


class DropArea(QLabel):
    """
    Widget area untuk drag and drop file gambar.
    """
    image_dropped = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setLineWidth(2)
        
        # Setup Tampilan Teks
        font = QFont("Segoe UI", 16)
        font.setBold(True)
        self.setFont(font)
        self.setText("👇\n\nJatuhkan File Gambar ke Sini\n(.jpg, .png, .webp)")

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls() and len(mime_data.urls()) == 1:
            url = mime_data.urls()[0]
            # Cek ekstensi file
            if url.isLocalFile() and url.toLocalFile().lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                event.acceptProposedAction()

    def dropEvent(self, event):
        file_path = event.mimeData().urls()[0].toLocalFile()
        self.image_dropped.emit(file_path)


class MainWindow(QWidget):
    """
    Jendela utama aplikasi.
    """
    def __init__(self):
        super().__init__()
        self.result_viewer = None # Untuk menampung jendela hasil
        self._setup_ui()
        self._apply_stylesheet()
        
    def _setup_ui(self):
        self.setWindowTitle("Macan Background Remover (Stable)")
        self.setMinimumSize(500, 400)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Area Drop
        self.drop_area = DropArea()
        self.drop_area.image_dropped.connect(self.start_processing)
        main_layout.addWidget(self.drop_area, 1) # Ambil sisa ruang

        # Label Status
        self.status_label = QLabel("Siap menerima gambar...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedHeight(30)
        main_layout.addWidget(self.status_label)
        
    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #2E3440;
                color: #ECEFF4;
                font-family: Segoe UI;
                font-size: 10pt;
            }
            DropArea {
                background-color: #3B4252;
                border: 2px dashed #4C566A;
                border-radius: 15px;
                color: #D8DEE9;
            }
        """)

    def start_processing(self, file_path):
        self.drop_area.setEnabled(False) # Nonaktifkan drop area saat proses
        self.drop_area.setText(" Sedang Memproses... ")
        
        self.thread = QThread()
        self.worker = Worker(file_path)
        self.worker.moveToThread(self.thread)

        # Hubungkan sinyal dari worker ke fungsi di main window
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_processing_finished)
        self.worker.error.connect(self.on_processing_error)
        self.worker.progress.connect(self.status_label.setText)
        
        # Atur agar thread dan worker bersih-bersih setelah selesai
        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.worker.deleteLater)

        self.thread.start()

    def on_processing_finished(self, result_path):
        self.status_label.setText(f"Berhasil! Hasil disimpan di: {result_path}")
        self.reset_ui()

        # Tampilkan notifikasi
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setText("Proses penghapusan background berhasil!")
        msg_box.setInformativeText("Klik OK untuk melihat hasil di jendela baru.")
        msg_box.setWindowTitle("Sukses")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        
        # Jika user klik OK, panggil fungsi untuk menampilkan hasil
        if msg_box.exec() == QMessageBox.StandardButton.Ok:
            self.show_result(result_path)

    def on_processing_error(self, message):
        self.status_label.setText("Gagal memproses gambar.")
        self.reset_ui()
        QMessageBox.critical(self, "Error", message)
    
    def show_result(self, image_path):
        # Buat instance jendela baru dan tampilkan
        self.result_viewer = ImageResultViewer(image_path)
        self.result_viewer.show()

    def reset_ui(self):
        self.drop_area.setEnabled(True)
        self.drop_area.setText("👇\n\nJatuhkan File Gambar ke Sini\n(.jpg, .png, .webp)")

# =============================================================================
# BAGIAN 3: EKSEKUSI APLIKASI
# =============================================================================
if __name__ == '__main__':
    # Baris ini SANGAT PENTING untuk multiprocessing agar tidak error
    # terutama saat dijadikan file .exe di Windows.
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())