# Hasil eksperimen hybrid SEHAT

Mulai dari [EXPERIMENT_REPORT.md](EXPERIMENT_REPORT.md), [evaluation_models.csv](evaluation_models.csv), dan [dataset_counts.csv](dataset_counts.csv).

Notebook utama adalah [TRAIN_SEHAT_hybrid.ipynb](../TRAIN_SEHAT_hybrid.ipynb). Salinan isi notebook hybrid sebelum pekerjaan ini ada di [original_notebooks/TRAIN_SEHAT_hybrid_before_experiment.ipynb](original_notebooks/TRAIN_SEHAT_hybrid_before_experiment.ipynb). Notebook referensi, raw CSV, firmware, dan model `.h` tidak diubah.

Untuk menjalankan ulang dengan Python proyek:

```powershell
python run_hybrid_notebook.py --workers 3
```

Launcher [run_hybrid_notebook.py](../run_hybrid_notebook.py) menentukan root dari lokasi filenya; notebook menyimpan root absolut sebagai `pathlib.Path`. Modul [hybrid_retraining.py](../hybrid_retraining.py) berisi loader, QC, ekstraksi, LOSO, plotting, dan validasi. Jalankan launcher dari root proyek atau berikan path absolut ke launcher. Dependensi tercatat di [requirements.txt](requirements.txt); `nbformat` dan `nbclient` dipasang lokal dalam `.python_deps` untuk run ini.

Artefak utama:

- `dataset_manifest.csv`, `audit/column_schema.csv`, `audit/metadata_conflicts.csv`: inventaris dan provenance.
- `features_shimmer.csv`, `features_sehat.csv`, `features_hybrid.csv`: sembilan fitur + metadata untuk window QC-pass berlabel valid.
- `window_quality_control.csv`: seluruh kandidat window penuh, termasuk yang ditolak dan tanpa label.
- `quality_control_per_file.csv`, `quality_control_per_subject.csv`, `quality_control_per_domain.csv`: kualitas dan coverage sinyal. Persentase window dan coverage sampel berbeda karena overlap.
- `oof_predictions_windows.csv`, `oof_predictions_recordings.csv`: prediksi aktual dari fold subjek yang ditahan, bukan model refit final.
- `evaluation_models.csv`, `evaluation_per_subject.csv`: metrik recording dan subjek.
- `audit/fold_manifest.csv`, `audit/fold_imputation_statistics.csv`, `audit/fold_training_weights.csv`: audit split, imputasi, bobot.
- `figures/`: sinyal sebelum/sesudah, distribusi fitur, actual vs predicted, residual dan perbandingan model.
- `audit/ppg_resampling*`, `audit/ppg_synthetic_known_beats.csv`, `audit/gsr_filter_sensitivity.csv`: diagnostik preprocessing yang tidak dipilih berdasarkan skor test.
- `models/best_model_pipeline.joblib`: model terpilih + objek imputasi, direfit pada seluruh training yang sesuai strategi pemenang. Gunakan sembilan kolom sesuai `models/inference_contract.json`.
- `models/fold_*.joblib`: model OOF untuk setiap subjek dan strategi.
- `config.json`, `experiment_summary.json`, `validation.json`, `notebook_execution.json`: konfigurasi, ringkasan dan bukti eksekusi/integritas.

`cache/` adalah cache ekstraksi per file yang diverifikasi dengan hash raw, metadata, konfigurasi dan kode. `.python_deps/` dan `.runtime/` mendukung eksekusi lokal; folder ini bukan hasil ilmiah dan tidak diperlukan saat membagikan tabel, grafik, laporan dan model.

Hasil bersifat eksploratif pada lima subjek. Pemilihan pemenang memakai fold yang sama dengan pelaporan. Label durasi puasa Shimmer dan waktu sejak minum SEHAT belum terbukti identik. Model Python belum layak diekspor ke firmware sebelum kesamaan preprocessing dan fitur embedded diuji.
