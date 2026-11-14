# Eksperimen hybrid SEHAT — hasil aktual

Eksperimen offline menggunakan ExtraTreesRegressor (35 trees, depth 8, min leaf 4, seed 42), tanpa tuning. Evaluasi Leave-One-SEHAT-Subject-Out: semua sesi subjek uji dikeluarkan dari training. Empat model memakai window uji yang identik. Prediksi window dirata-ratakan per rekaman; metrik utama memberi setiap rekaman bobot sama.

## Data dan kualitas

device_source  files  subjects  sessions  labeled_records  samples  candidate_windows  accepted_windows  rejected_windows  ppg_available_windows  samples_in_accepted_windows  samples_outside_full_windows  gsr_interpolated_samples  window_pass_pct  sample_coverage_pass_pct  usable_recordings  usable_subjects  usable_windows
        SEHAT     15         5        15               15   230400                285               279                 6                    211                       225792                             0                       509        97.894737                 98.000000                 15                5             279
      Shimmer    124        11       124               45 10032887              11986             11925                61                   1743                      9505536                        505847                         0        99.491073                 94.743776                 39                6            4047

Jumlah CSV Shimmer mentah=124, tabel label fastingTimes=6 (total 130); SEHAT mentah=12. Angka tersebut diverifikasi pada manifest. QC dilakukan terhadap seluruh raw recording, termasuk Shimmer tanpa label; hanya label eksplisit yang valid masuk regresi.

Persentase lolos dihitung dari kandidat window **penuh** di setiap continuous run. Sampel di tail/run pendek tidak diperlakukan sebagai window parsial; jumlahnya ada pada `samples_outside_full_windows`. Sample coverage menghitung gabungan indeks sampel window lolos, sehingga overlap tidak dihitung dua kali. Lolos kualitas sinyal tidak otomatis berarti memiliki label regresi.

### Konflik metadata

- `20261107130818_S16_S16_F02_raw.csv`: raw menyebut S15/S15_F02. Pengguna mengonfirmasi subjek sebenarnya **S16**; manifest memakai S16/S16_F02 dan mempertahankan raw_subject_id/raw_session_id serta alasan koreksi.
- `20261112060931_S13_S13_F05_raw.csv`: raw menyebut session S13_F04. Rekaman **tetap dipakai** sebagai F05 dengan recording_id dari relative path dan timestamp; raw metadata tidak diubah.
- Label Shimmer digabung exact pada (subject_id, RecordingTime), bukan timestamp lintas subjek atau nearest matching. Nonfasting tanpa label tidak diisi nol. Lihat `audit/excluded_recordings.csv` untuk seluruh pengecualian.

## Preprocessing dan fitur

Loader Shimmer mempertahankan header empat baris, PPG calibrated mV, GSR calibrated uS, serta device Timestamp_CAL. Timestamp sistem yang stuck bukan alasan otomatis menghapus file bila device timestamp valid. Loader SEHAT membaca IR counts, GSR uS, elapsed_us, dan gyro deg/s. Tidak ada penyamaan amplitudo PPG raw antarperangkat.

Timestamp tidak diurutkan ulang atau dideduplikasi diam-diam: nilai nonfinite, nonpositive dt, dan penyimpangan dt >50% periode nominal memisahkan continuous run. FS median dan FS berdasarkan elapsed dicatat per file. Timestamp SEHAT adalah grid buatan firmware: fs nominal tepat bukan bukti clock MAX30102/FIFO atau waktu serial benar-benar bebas jitter.

Beberapa file Shimmer memiliki sampling/timestamp tidak sesuai konfigurasi nominal; lihat `sampling_rate_flag`, `short_runs_not_filtered`, dan `samples_outside_full_windows`. Run yang lebih pendek dari 1536 sampel kontinu tidak difilter dan tidak menghasilkan window. Tidak mempercepat sinyal 0.2/10.24Hz seolah-olah 51.2Hz.

GSR: NaN/Inf dicatat sebelum perbaikan; nilai <=0 ditandai invalid. Hanya gap internal <=0.25 s yang diinterpolasi, tanpa extrapolasi tepi atau melintasi putus timestamp. Window ditolak bila >5% raw missing, masih ada gap, >5% nonpositive, atau >5% ADC rail. Butterworth order 2 low-pass 1 Hz per window dipertahankan dari notebook lama; varians ddof=0, entropy histogram 10 bin log natural. Flat GSR positif ditandai, tidak otomatis ditolak karena belum ada bukti terpisah bahwa nilai konstan selalu artefak.

PPG: high-pass .5 Hz order 4, gyro-adaptive low-pass 4/2.5 Hz, moving average .15 s; parameter utama helper lama dipertahankan. SEHAT menandai rail 0/262143 dan isolated spikes dengan Hampel .25 s, 8 MAD, minimal deviasi 2% baseline lokal; kemudian hanya gap <=.25 s diperbaiki. Tidak ada batas absolut kontak jari yang dipindahkan dari sensor lain. DC, span, flatline, outlier, rail dan RR rejection dilaporkan; kualitas kontak tidak dapat dipastikan tanpa ground truth.

HeartPy memakai 40–180 bpm, quotient RR cleaning, high-precision 1000 Hz. Fitur PPG tersedia hanya saat lengkap dan RR rejected <=30%. PPG gagal: mean_hr/rmssd/sdnn/pnn50/n_peaks menjadi NaN dan ppg_available=0. Nilai diagnostik sebelum gating tetap tersimpan; n_peaks mengikuti total peaklist HeartPy, bukan jumlah RR yang lolos. pnn50 dalam %, rmssd/sdnn dalam ms. Gyro bukan predictor; >100 deg/s selama >20% window dianggap severe motion dan window ditolak. Threshold ini aturan engineering tetap sebelum fitting, bukan batas klinis atau hasil tuning skor test.

Window 1536 sampel=30 s, hop768=15 s. Tidak ada partial window. PPG difilter per continuous run, GSR per window seperti referensi; definisi sembilan fitur sama, tetapi QC lebih ketat dan normalisasi berbeda dari notebook lama. A adalah Shimmer-only dengan pipeline baru yang konsisten, sehingga bukan reproduksi angka personal-zscore notebook lama.

### Distribusi dan normalisasi

device_source     feature  n_recordings          min      q25   median      q75       max
      Shimmer    gsr_mean            39 8.586563e-02 0.189697 0.518715 3.593259 56.928287
        SEHAT    gsr_mean            15 2.060672e+00 2.880504 4.800003 8.257917 17.033437
      Shimmer     gsr_var            39 4.242682e-07 0.000013 0.000276 0.027712  1.578053
        SEHAT     gsr_var            15 1.095542e-02 0.048131 0.071064 0.210943  0.850362
      Shimmer gsr_entropy            39 1.870551e+00 1.983521 2.058608 2.126883  2.296464
        SEHAT gsr_entropy            15 1.617090e+00 1.942137 2.041133 2.089956  2.132846

Tidak menggunakan personal z-score: subjek baru tidak membutuhkan histori. Tidak memakai log1p, karena transformasi nonlinear mengubah distribusi random thresholds ExtraTrees dan belum dievaluasi pada validasi terpisah. Statistik min/quartile tersedia pada CSV; grafik symlog hanya tampilan. GSR tetap dalam satuan fisik; konduktansi uS dari rangkaian berbeda belum berarti kalibrasinya setara. Median imputasi sembilan fitur hanya dari training fold; fitur yang seluruh training-nya missing memakai fallback0 dari SimpleImputer keep_empty_features=True. Flag ppg_available membedakan imputasi dan pengukuran. Tidak ada metadata, target, atau statistik personal test sebagai predictor.

Median lintas rekaman dari median gsr_mean: Shimmer=0.518715 uS, SEHAT=4.800003 uS. Sebanyak 7/15 label SEHAT berada di bawah label training Shimmer terkecil (2.245278 jam). Model pohon Shimmer-only tidak dapat mengekstrapolasi prediksi di bawah rentang target training; perbaikan hybrid bisa mencerminkan kecocokan rentang target dan protokol, selain fitur sensor.

## Hasil LOSO pada SEHAT

              model  n_recordings   MAE_hr  RMSE_hr        R2  target_min_hr  target_max_hr  macro_subject_MAE_hr
     A_Shimmer_only            15 4.688992 5.627618 -1.946692       1.034718       9.629812              5.424750
B_Hybrid_unweighted            15 3.210378 3.610402 -0.212821       1.034718       9.629812              3.322066
  C_Hybrid_weighted            15 2.858798 3.401708 -0.076663       1.034718       9.629812              3.162460
       D_SEHAT_only            15 2.491909 2.947612  0.191600       1.034718       9.629812              2.152245

              model subject_id  n_recordings   MAE_hr  RMSE_hr        R2  target_min_hr  target_max_hr
     A_Shimmer_only        S12             2 5.775967 6.241691       NaN       1.230339       5.275029
     A_Shimmer_only        S13             7 3.217476 4.693090 -0.781840       1.300721       9.629812
     A_Shimmer_only        S14             2 7.203222 7.215399       NaN       1.034718       1.962393
     A_Shimmer_only        S15             2 5.717656 5.744813       NaN       1.427739       4.480752
     A_Shimmer_only        S16             2 5.209429 6.034419       NaN       1.371714       6.905173
B_Hybrid_unweighted        S12             2 3.647508 3.993335       NaN       1.230339       5.275029
B_Hybrid_unweighted        S13             7 2.987000 3.117035  0.213979       1.300721       9.629812
B_Hybrid_unweighted        S14             2 3.374601 3.416037       NaN       1.034718       1.962393
B_Hybrid_unweighted        S15             2 3.192908 4.020054       NaN       1.427739       4.480752
B_Hybrid_unweighted        S16             2 3.408314 4.469900       NaN       1.371714       6.905173
  C_Hybrid_weighted        S12             2 2.626482 2.875634       NaN       1.230339       5.275029
  C_Hybrid_weighted        S13             7 2.251474 2.422320  0.525306       1.300721       9.629812
  C_Hybrid_weighted        S14             2 4.901528 4.903474       NaN       1.034718       1.962393
  C_Hybrid_weighted        S15             2 2.971714 4.084895       NaN       1.427739       4.480752
  C_Hybrid_weighted        S16             2 3.061104 4.153398       NaN       1.371714       6.905173
       D_SEHAT_only        S12             2 1.335682 1.812012       NaN       1.230339       5.275029
       D_SEHAT_only        S13             7 3.171237 3.592152 -0.043903       1.300721       9.629812
       D_SEHAT_only        S14             2 1.158757 1.200679       NaN       1.034718       1.962393
       D_SEHAT_only        S15             2 1.975228 2.002455       NaN       1.427739       4.480752
       D_SEHAT_only        S16             2 3.120321 3.356462       NaN       1.371714       6.905173

Model dengan MAE recording terkecil: **D_SEHAT_only**. MAE=2.491909 jam, RMSE=2.947612 jam, R²=0.191600. Selisih MAE terhadap A = 2.197083 jam (positif berarti MAE berkurang).

Penambahan data SEHAT pada B mengubah MAE sebesar -1.478614 jam terhadap A; C sebesar -1.830194 jam (nilai negatif berarti lebih baik). Ini perbedaan aktual pada cohort ini, bukan bukti keunggulan umum hybrid atau penambahan informasi fisiologis yang kausal.

Baseline konstan terbaik menurut MAE: constant_SEHAT_train_record_mean, MAE=3.232587 jam. Model terpilih mengungguli baseline sederhana ini pada MAE; perbandingan ini penting sebelum menyimpulkan manfaat fitur fisiologis.

B menyatukan semua window tanpa bobot. C menyeimbangkan total massa domain, lalu subjek dalam domain, rekaman dalam subjek, dan window dalam rekaman: w=N/(D*S_d*R_ds*n_dsr). Seluruh jumlah dihitung ulang dari training fold; imputasi median C tetap median training tanpa bobot agar preprocessing sama antararm. D hanya subjek SEHAT lain; datanya sangat kecil.

R² per subjek hanya dihitung bila sedikitnya tiga rekaman dan variasi target memadai; fold dua rekaman diberi NaN. R² pooled tersedia tetapi sangat dipengaruhi rentang target sempit dan sedikit rekaman. Window beririsan bukan sampel independen.

### Selisih per subjek dan ketidakpastian

              model                                contrast  subjects  delta_macro_MAE_hr   lower95   upper95  subjects_improved  bootstrap_replicates                                                                                     caution
B_Hybrid_unweighted model minus A; macro subject MAE, hours         5           -2.102684 -3.148556 -1.003458                  5                 10000 exploratory five-subject bootstrap, not confirmatory; correlated sessions retained together
  C_Hybrid_weighted model minus A; macro subject MAE, hours         5           -2.262290 -2.826651 -1.558454                  5                 10000 exploratory five-subject bootstrap, not confirmatory; correlated sessions retained together
       D_SEHAT_only model minus A; macro subject MAE, hours         5           -3.272505 -4.942386 -1.333622                  5                 10000 exploratory five-subject bootstrap, not confirmatory; correlated sessions retained together

Bootstrap mengambil ulang lima subjek sebagai cluster, bukan window; interval tersebut deskriptif dan tidak membuktikan signifikansi atau generalisasi populasi. Pemilihan model terbaik memakai LOSO yang sama, sehingga estimasi terpilih bersifat eksploratif dan optimistis. Tidak ada klaim test final independen. Constant mean baselines training-only ada di `audit/constant_baseline_metrics.csv` untuk menilai manfaat dibanding prediksi durasi rata-rata sederhana.

## Diagnostik sampling dan filter

          method feature  paired_windows  both_valid_windows  availability_disagreements  median_absolute_difference  max_absolute_difference
reconstructed_50 mean_hr             285                 214                           6                    0.016667                 1.974506
reconstructed_50   rmssd             285                 214                           6                    1.303411                11.894751
reconstructed_50    sdnn             285                 214                           6                    0.600526                21.151603
reconstructed_50   pnn50             285                 214                           6                    2.857143                17.069597
reconstructed_50 n_peaks             285                 214                           6                    1.000000                23.000000
  roundtrip_51.2 mean_hr             285                 214                           3                    0.007872                 0.906421
  roundtrip_51.2   rmssd             285                 214                           3                    1.296711                16.878473
  roundtrip_51.2    sdnn             285                 214                           3                    0.471694                11.545635
  roundtrip_51.2   pnn50             285                 214                           3                    2.762515                14.634146
  roundtrip_51.2 n_peaks             285                 214                           3                    0.000000                 2.000000

Data FIFO 50 Hz sebelum interpolasi tidak disimpan. Perbandingan stored51.2, reconstructed50, dan roundtrip51.2 mengukur sensitivitas pada sinyal yang sudah terinterpolasi; tidak bisa memulihkan ground truth atau membuktikan interpolasi firmware tidak merusak HRV. Pasangan fitur hanya dihitung ketika kedua window lolos kualitas; perubahan availability juga dilaporkan. Sinyal sintetis dengan beat time diketahui memberi kontrol tambahan (`audit/ppg_synthetic_known_beats.csv`), bukan validasi fisiologis manusia.

n_peaks tetap jumlah kandidat HeartPy sesuai referensi, sehingga dapat berubah lebih besar daripada mean_hr sesudah RR cleaning. Perbedaan jumlah peak/HRV pada uji resampling harus diperiksa sebelum deployment; availability yang lolos bukan jaminan tiap peak benar. Sinyal sintetis mencakup RR konstan dan bervariasi serta tiga fase sampling.

GSR low-pass 1 Hz: median rasio variance filtered/raw=0.690431; median absolute mean shift=0.000258 uS. Pembanding 2 Hz dicatat tanpa memilih cutoff dari skor regresi. Tidak ada jaminan komponen fisiologis tertentu dipertahankan tanpa referensi atau protokol validasi.

## Batasan dan eksperimen berikutnya

1. Target bukan pengukuran hidrasi langsung. Shimmer memakai durasi sejak awal puasa yang dilaporkan; SEHAT memakai waktu sejak terakhir minum. Protokol puasa bisa sekaligus melarang makanan/minuman, tetapi metadata ini tidak membuktikan last-drink time identik. Hybrid ini adalah transfer proxy label, bukan label klinis yang harmonis. Pertahankan provenance; kumpulkan label durasi minum terstandar dan referensi hidrasi jika tersedia pada studi berikutnya.
2. Lima subjek dan 12 sesi SEHAT membatasi kesimpulan. S13 memiliki lebih banyak sesi dan satu durasi panjang; pooled metric dan macro-subject metric sama-sama dilaporkan. Waktu/sesi/protokol mungkin berhubungan dengan target dan kontak sensor. Tambahkan peserta baru serta sesi berulang pada rentang target yang seimbang dengan urutan pengukuran diacak.
   Target adalah durasi saat awal rekaman yang dipertahankan konstan untuk seluruh window, mengikuti evaluasi satu target per recording. Durasi sesungguhnya bertambah selama pengukuran (sekitar .0833 jam pada sesi SEHAT lima menit, lebih besar pada rekaman Shimmer panjang). Angka desimal logger bukan presisi biologis. Sensitivitas pengaruh setiap sesi pada agregasi OOF tersedia, tanpa mengubah hasil utama atau melatih ulang model.
3. ID S1–S11 Shimmer dan S12–S16 SEHAT diasumsikan peserta berbeda. Tidak ada pemetaan identitas eksternal untuk membuktikannya. Tidak ada sensor reference simultan untuk memisahkan domain shift dari variasi fisiologis/elektroda.
4. QC menguji hanya data yang diterima; missingness/penolakan bisa tidak acak. Laporkan coverage bersama error, termasuk PPG yang diimputasi. Raw CSV utuh; pengecualian dapat ditinjau ulang tanpa kehilangan data.
5. Deployment belum ekuivalen: Python HeartPy berbeda dari peak detector embedded; filtering full-run zero-phase memakai konteks masa depan dan threshold gyro per run, sedangkan firmware memakai window. Firmware lama menginterpolasi GSR panjang/tepi dan personal-normalizes; harus diselaraskan dengan kontrak baru melalui golden-window comparison sebelum ekspor model. Tidak ada model .h atau firmware yang diubah.
6. Simpan FIFO asli 50 Hz dan timestamp sensor/clock aktual; ukur peak timing terhadap referensi denyut, evaluasi RR/HRV sebelum dan sesudah resampling. Kalibrasi GSR lintas perangkat dan periksa kestabilan kontak. Setelah protokol tetap, gunakan cohort prospektif baru atau nested subject validation untuk konfirmasi pemilihan strategi.

## Artefak dan reproduksi

Notebook `TRAIN_SEHAT_hybrid.ipynb` dijalankan berurutan melalui nbclient menggunakan Python proyek. `run_hybrid_notebook.py` membuat/menjalankan notebook; cache per file memerlukan hash raw, konfigurasi, dan kode ekstraksi yang sama. Hasil pertama dihitung dari raw. `validation.json` menyimpan pemeriksaan integritas. Manifest dan per-file QC menyimpan SHA256 raw; validasi akhir membaca ulang seluruh file untuk membuktikan tidak diubah.

Model Python terpilih dan objek preprocessing berada di `models/best_model_pipeline.joblib`; `models/inference_contract.json` mencatat urutan, unit, median, dan kebijakan missing. Refit final memakai semua data yang sesuai strategi terpilih; metrik di atas tetap berasal dari model fold OOF, bukan refit final.

Sumber teknis: [imputation](https://scikit-learn.org/1.6/modules/generated/sklearn.impute.SimpleImputer.html); [extra_trees](https://scikit-learn.org/1.6/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html); [filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html); [heartpy](https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/heartpy.heartpy.html)

Referensi lokal: `TRAIN_SEHAT_revisi copy.ipynb` (nama copy(1) tidak ditemukan), `ppg_preprocessing.py`, `MAX30102_PREPROCESSING_ESP32.md`, `GSR_PREPROCESSING_ESP32.md`, serta raw acquisition firmware (hanya dibaca).