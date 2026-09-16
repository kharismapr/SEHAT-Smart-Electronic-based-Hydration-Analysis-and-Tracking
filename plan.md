### 1\. Algoritma Model yang Digunakan

Sistem SEHAT akan menggunakan algoritma **Random Forest** (berbasis *ensemble tree*)[4][5]. Algoritma ini dipilih karena beberapa alasan utama:

* Memiliki performa terbaik dalam memprediksi status hidrasi dari data sensor *wearable*[4][6].
* Sangat andal dalam menangani hubungan non-linear antar variabel multisensor[5].
* Memiliki ketahanan yang tinggi terhadap pencilan (*outlier*) yang sering muncul akibat gangguan gerakan tubuh (*motion artifacts*) saat perangkat digunakan[5][6].

### 2\. Fitur Masukan (Multisensor)

Model ML ini akan mengolah kombinasi data sensor fisiologis dan lingkungan yang saling melengkapi[7]:

* **Sensor PPG (MAX30102):** Digunakan untuk mengukur detak jantung (*Heart Rate*) dan mengekstrak metrik *Heart Rate Variability* (HRV), khususnya nilai **RMSSD** (*Root Mean Square of Successive Differences*)[8][9]. Penurunan nilai RMSSD menjadi indikasi dehidrasi karena adanya peningkatan aktivitas sistem saraf simpatis[9][10].
* **Sensor GSR (Grove GSR Sensor):** Mengukur konduktansi listrik kulit yang dipengaruhi aktivitas kelenjar keringat[11][12]. Tubuh yang terdehidrasi akan mengalami penurunan produksi keringat, yang secara langsung menurunkan nilai konduktansi kulit[12]. Fitur statistik yang diekstrak meliputi nilai *mean*, varians, dan entropi[13].
* **Sensor Lingkungan (Suhu &amp; Kelembapan BMP280/AHT20):** Berperan sebagai kalibrator eksternal[13][14]. Data ini penting untuk mencegah bias model, sehingga sistem dapat membedakan apakah peningkatan detak jantung disebabkan oleh suhu lingkungan yang panas atau murni karena dehidrasi internal[14].

### 3\. Tahapan Pra-pemrosesan Data (Preprocessing)

Sebelum data sensor diumpankan ke model Random Forest, sinyal biologis mentah harus disaring terlebih dahulu agar bebas dari *noise*[15]:

* **Filtrasi PPG:** Sinyal PPG akan disaring menggunakan **filter Butterworth bandpass orde dua** pada rentang frekuensi 0,5–4 Hz untuk mengeliminasi gangguan gerakan tangan dan interferensi cahaya[15][16].
* **Windowing:** Analisis HRV dilakukan pada segmen sinyal berdurasi 30 detik dengan *overlap* 50% guna menjaga responsivitas pembacaan[10].
* **Normalisasi Min-Max:** Seluruh fitur masukan akan dinormalisasi agar berada dalam rentang nilai yang seragam[10]. Jika ada nilai lapangan ekstrim di luar distribusi data pelatihan, fitur akan dipotong (*clipped*) ke batas terdekat sebelum normalisasi dilakukan[17].

### 4\. Target Klasifikasi Status Hidrasi

Model ML akan mengklasifikasikan status hidrasi pengguna ke dalam tiga tingkatan diagnosis[5][18]:

1. **Well Hydrated** (nonfasting dan waktu terakhir minum < 10 jam)
2. **At Risk of Dehydration** (ketika waktu terakhir minum 10 jam atau lebih)

### 5\. Strategi Deployment (TinyML)

Model yang telah dilatih dan divalidasi akan dioptimasi menggunakan teknik **kuantisasi dan pemangkasan (** **pruning** **)** guna meminimalkan konsumsi memori tanpa mengorbankan akurasi secara signifikan[19][20]. Model yang sudah ramping ini kemudian ditanamkan langsung (*embedded*) ke dalam mikrokontroler **ESP32 XIAO**[20][21]. Inferensi lokal ini menjamin latensi yang sangat rendah serta menjaga kerahasiaan privasi data medis pengguna[3][22].

### 6\. Target Performa &amp; Evaluasi

Performa model akan dievaluasi menggunakan metrik *confusion matrix*, akurasi, presisi, *recall*, dan *F1-Score*[23][24]. Target minimum keberhasilan yang ditetapkan adalah:

* **Akurasi global:** **≥ 85%**[23][24]
* **F1-Score rata-rata tertimbang:** **≥ 78%**