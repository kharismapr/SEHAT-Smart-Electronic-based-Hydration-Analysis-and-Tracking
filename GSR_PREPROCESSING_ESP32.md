# Preprocessing GSR di ESP32

Buka [`GSR_Preprocessing_ESP32.ino`](GSR_Preprocessing_ESP32/GSR_Preprocessing_ESP32.ino)
di Arduino IDE. File pendamping
[`gsr_preprocessing_esp32.h`](GSR_Preprocessing_ESP32/gsr_preprocessing_esp32.h)
berada dalam folder sketch yang sama dan berisi filter serta ekstraksi fitur.
Pilih board ESP32 yang dipakai, sambungkan Grove GSR SIG ke `A0`, VCC ke 3V3,
dan GND ke GND. Ubah `GSR_PIN` bila wiring memakai pin ADC lain. Pastikan
tegangan output sensor tidak melebihi batas input ADC board.

Sketch membaca ADC Grove GSR, mengubahnya menjadi **konduktansi kulit dalam µS**,
lalu menjalankan pipeline pada **51,2 sampel/detik**. Notebook membaca kolom
`GSR_Skin_Conductance_CAL`, bukan nilai ADC atau resistansi mentah. Konversi
Grove ini memakai [rumus dan prosedur kalibrasi Seeed](https://wiki.seeedstudio.com/Grove-GSR_Sensor/):
`R_ohm = (1024 + 2 * ADC10) * 10000 / (ADC10_kalibrasi - ADC10)` lalu
`G_µS = 1000000 / R_ohm`. ADC ESP32 12-bit dipetakan ke skala 10-bit sebelum
memakai rumus tersebut. Konversi ini berlaku untuk **Grove GSR**, bukan setiap
sensor GSR; cocokkan dengan sensor dan ADC yang benar-benar terpasang.

## Pipeline yang diikuti

1. Kumpulkan 1536 sampel (30 detik); setelah itu keluarkan fitur setiap 768
   sampel (overlap 50%). Pada akhir rekaman, `flush()` mengeluarkan sisa window.
2. Ganti NaN/Inf dengan interpolasi linear; gap pada tepi memakai nilai valid
   terdekat. Jika semua sampel hilang, `valid == false` dan fitur tetap NaN.
3. Terapkan Butterworth low-pass orde 2, cutoff 1 Hz, dua arah dengan odd
   padding seperti `scipy.signal.filtfilt`. Window paling banyak 9 sampel tidak
   difilter, sesuai fungsi di notebook.
4. Hitung `gsr_mean`, `gsr_var` (varians populasi, `ddof=0`) dan `gsr_entropy`
   (histogram 10 bin, log natural). Nama fitur sama dengan notebook.
5. Bila model membutuhkan z-score per subjek, panggil `normalizeFeatures()`
   memakai mean dan standar deviasi **dari window kalibrasi/training subjek**.
   Notebook memakai `pandas.std()` (`ddof=1`); nilai ini tidak boleh dihitung
   dari window inferensi yang sedang diproses.

Pemilihan filter dan tiga fitur pada langkah 3–4 berasal dari
`TRAIN_SEHAT_FINAL.ipynb` (bagian **GSR**, sel `lowpass_filter_gsr` dan
`extract_gsr_features`). Paper `[3] referensi utama.pdf`, §4.1.4 dan Tabel 2,
menjelaskan konduktansi GSR dalam µS tetapi **tidak menetapkan filter 1 Hz**;
angka filter tersebut adalah pilihan pada notebook. Paper merata-ratakan fitur
pada interval 1 menit, sedangkan notebook yang menjadi dasar model proyek
memakai window 30 detik.

## Cara tes di Arduino IDE

1. Buka file `.ino`, pilih board ESP32 dan port, lalu upload. Pilih baud
   **115200** di Serial Monitor.
2. **Lepas elektroda dari jari.** Atur potensiometer Grove sampai ADC tanpa
   jari mencapai nilai minimum yang stabil. Kirim huruf `c` di Serial Monitor.
   Sketch menyimpan rata-rata 32 pembacaan sebagai kalibrasi; nilai itu hanya
   tersimpan selama perangkat menyala. Kirim `r` untuk mengulang kalibrasi.
3. Pasang elektroda pada jari. Monitor menampilkan `ADC10` dan `GSR_us` tiap
   detik. Fitur `gsr_mean`, `gsr_var`, dan `gsr_entropy` muncul setelah 30 detik,
   kemudian tiap 15 detik. Jika `GSR_us=nan`, periksa kalibrasi, wiring, dan
   apakah pembacaan dengan jari lebih rendah daripada nilai kalibrasi.
4. Pada akhir satu rekaman, kirim `f` untuk mengeluarkan window terakhir yang
   belum lengkap dan memulai rekaman baru.

Untuk model yang dilatih dengan notebook, cek kesesuaian skala Grove terhadap
kolom Shimmer terkalibrasi sebelum menggunakan fitur untuk inferensi. ADC ESP32
memiliki galat dan nonlinieritas; kalibrasi tanpa jari dari Seeed membantu
konversi Grove tetapi tidak otomatis menyamakan kedua perangkat.

`Processor` menggunakan sekitar 18,5 KB RAM dan tidak mengalokasikan heap.
Karena filtfilt memakai seluruh isi window, fitur pertama keluar sesudah 30
detik; berikutnya setiap 15 detik. Jika loop ESP32 tertinggal dari jadwal,
pengambilan sampel harus ditangani dengan timer/buffer agar jarak waktu aktual
tetap 51,2 Hz. Pemrosesan ini tidak memisahkan komponen tonic dan phasic.
