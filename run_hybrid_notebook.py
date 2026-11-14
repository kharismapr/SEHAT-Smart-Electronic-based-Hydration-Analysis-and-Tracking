"""Create and execute the requested notebook with the active project Python.

Usage: python run_hybrid_notebook.py [--workers 3] [--create-only]
Notebook dependencies may be installed locally in results/.python_deps.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "hybrid_retraining_results"
DEPS = OUT / ".python_deps"
if DEPS.is_dir():
    sys.path.insert(0, str(DEPS))
import nbformat
from nbclient import NotebookClient


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_notebook():
    cells = []
    md = lambda s: cells.append(nbformat.v4.new_markdown_cell(s))
    code = lambda s: cells.append(nbformat.v4.new_code_cell(s))
    md("""# SEHAT: eksperimen hybrid retraining aktual

Perbandingan A Shimmer-only, B hybrid, C hybrid berbobot domain/subjek/rekaman,
dan D SEHAT-only. Model Extra Trees tetap 35 trees, depth8, min leaf4, seed42.
Evaluasi **Leave-One-SEHAT-Subject-Out**, prediksi mean per recording, tanpa
personal z-score dan tanpa tuning test. Raw CSV, notebook referensi, dan firmware
tetap utuh. Semua artefak baru berada di `hybrid_retraining_results`.

Notebook utama referensi: `TRAIN_SEHAT_revisi copy.ipynb`; nama `copy(1)` tidak
tersedia. Implementasi dapat ditinjau pada `hybrid_retraining.py`. Parameter QC
ditentukan sebelum model fitting; hasil terpilih tetap studi eksploratif.
""")
    code(f'''from pathlib import Path
import os, sys
PROJECT_ROOT = Path({str(ROOT)!r})
assert PROJECT_ROOT.is_dir()
sys.path.insert(0, str(PROJECT_ROOT))
from IPython.display import display, Image, Markdown
import pandas as pd
import hybrid_retraining as h
config = h.Config(project_root=str(PROJECT_ROOT))
print("Python:", sys.executable)
print("Project root:", PROJECT_ROOT)
display(pd.Series(h.asdict(config), name="fixed_configuration"))''')
    md("""## 1. Validasi dataset dan provenance label

Shimmer: empat baris header, calibrated PPG mV dan GSR uS; label exact join
subject + timestamp dari fastingTimes. Tidak mengisi nonfasting dengan nol.
SEHAT: IR counts, GSR uS, metadata internal divalidasi terhadap filename/waktu.
Koreksi S16_F02 mengikuti konfirmasi pengguna, F05 tetap disimpan meski raw F04.
Identitas unik memakai relative path dan timestamp; raw tidak ditulis ulang.
""")
    code('''manifest = h.inventory(config)
display(manifest.groupby(["device_source", "subject_id"]).agg(files=("file", "size"), labeled=("label_valid", "sum")))
display(manifest.loc[manifest.metadata_conflict, ["file", "subject_id", "raw_subject_id", "session_id", "raw_session_id", "metadata_issues"]])''')
    md("""## 2. Preprocessing sensor dan window penuh

Timestamp breaks membatasi filtering; tidak melakukan sort/dedup diam-diam.
Window 30 detik, overlap50%. GSR gap internal <=.25s saja diperbaiki, raw
missing >5% atau unresolved gap menolak window. Filter GSR lama 1Hz order2
per window dipertahankan. PPG .5Hz baseline, low-pass4/2.5Hz, smoothing.15s,
HeartPy dengan quality flags. MAX30102 memiliki pemeriksaan rail dan spike
relatif terhadap baseline lokal. PPG gagal menjadi lima NaN + availability0.
Gyro dipakai untuk QC/filtering saja. Lihat config dan laporan untuk threshold.

Semua raw recording diaudit; CSV fitur training memuat label valid + QC-pass.
Tabel QC window menyimpan juga kandidat yang ditolak dan rekaman tanpa label.
""")
    code('''windows, data, qc, examples = h.extract_datasets(manifest, config, workers=int(os.environ.get("SEHAT_HYBRID_WORKERS", "3")))
display(pd.read_csv(config.out / "quality_control_per_domain.csv"))
display(data.groupby("device_source").agg(subjects=("subject_id", "nunique"), recordings=("recording_id", "nunique"), windows=("window_id", "size"), ppg_available=("ppg_available", "mean")))''')
    md("""## 3. Empat eksperimen dengan subjek uji identik

Semua statistik imputasi berasal dari training fold. Tidak menggunakan
personal z-score, metadata predictor, log transform, atau random window split.
C menggunakan bobot hierarki domain -> subjek -> rekaman -> window yang
dihitung ulang dari training. Metrik utama berbasis rekaman; macro subject MAE
juga dilaporkan. R² fold dengan <3 rekaman tidak disajikan sebagai angka stabil.
""")
    code('''oof, records, per_subject, summary, best_name = h.evaluate(data, config)
display(summary)
display(per_subject)
display(records[["model", "subject_id", "session_id", "y_true", "y_pred", "absolute_error_hr", "windows"]])''')
    md("## 4. Grafik sinyal, distribusi fitur, prediksi dan residual")
    code('''h.plot_signals(examples, config)
record_features = h.plot_evaluation(data, records, per_subject, summary, config)
for name in ["signals_shimmer", "signals_sehat", "feature_distributions", "actual_vs_predicted", "errors_per_subject", "model_comparison"]:
    display(Image(filename=str(config.out / "figures" / (name + ".png"))))''')
    md("""## 5. Sensitivitas preprocessing tanpa pemilihan dari skor test

PPG source50Hz sebelum interpolasi firmware tidak tersimpan. Rekonstruksi50Hz
dan roundtrip51.2Hz hanya mengukur sensitivitas tambahan interpolasi, bukan
membuktikan akurasi HRV asli. Kontrol sintetis memakai beat times diketahui.
GSR1Hz dibanding2Hz untuk melihat perubahan mean/variance; filter tidak dipilih
dari skor test. Tidak ada klaim kesetaraan fisiologis kedua domain.
""")
    code('''sensitivity, gsr_sensitivity = h.sensor_sensitivity(manifest, windows, config)
display(sensitivity)
display(gsr_sensitivity[["variance_ratio_1hz_raw", "variance_ratio_2hz_raw", "absolute_mean_shift_1hz"]].describe())
display(pd.read_csv(config.out / "audit/ppg_synthetic_known_beats.csv"))''')
    md("""## 6. Baseline durasi konstan dan ketidakpastian tingkat subjek

Bootstrap memperlakukan subjek sebagai cluster. Dengan lima subjek saja,
interval bersifat deskriptif. Memilih pemenang pada LOSO yang sama memberi
hasil eksploratif; konfirmasi memerlukan cohort baru atau validasi tersarang.
""")
    code('''uncertainty = h.auxiliary_evaluation(data, records, per_subject, config)
display(pd.read_csv(config.out / "audit/constant_baseline_metrics.csv"))
display(uncertainty)''')
    md("""## 7. Validasi integritas, model Python, dan laporan akhir

Pemeriksaan meliputi subjek/rekaman disjoint, kesamaan test empat model,
frozen training medians, bobot, partial-window policy, metadata provenance,
roundtrip serialisasi model, perhitungan ulang metrik, dan hash seluruh raw.
Model final direfit sesudah evaluasi; metrik yang dilaporkan tetap OOF.
Firmware dan model TinyML .h tidak diekspor/diubah.
""")
    code('''validation = h.validate_results(manifest, windows, data, records, summary, config)
counts = h.write_report(manifest, windows, data, qc, summary, per_subject, best_name, sensitivity, gsr_sensitivity, uncertainty, config)
display(counts)
display(summary)
print("Model terpilih (eksploratif):", best_name)
print("Pipeline + preprocessing:", config.out / "models/best_model_pipeline.joblib")
print("Laporan:", config.out / "EXPERIMENT_REPORT.md")
display(Markdown((config.out / "EXPERIMENT_REPORT.md").read_text(encoding="utf-8")))''')
    nb = nbformat.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3 (SEHAT project)", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": sys.version.split()[0]},
    })
    return nb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--create-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    target = ROOT / "TRAIN_SEHAT_hybrid.ipynb"
    backup = OUT / "original_notebooks/TRAIN_SEHAT_hybrid_before_experiment.ipynb"
    backup.parent.mkdir(exist_ok=True)
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)
    protected = [ROOT / "TRAIN_SEHAT_revisi copy.ipynb", ROOT / "ppg_preprocessing.py"]
    protected.extend(ROOT.glob("*.h"))
    protected.extend(ROOT.rglob("*.ino"))
    before = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    nb = create_notebook()
    nbformat.write(nb, target)
    if args.create_only:
        print(target)
        return
    runtime = OUT / ".runtime"
    runtime.mkdir(exist_ok=True)
    os.environ["JUPYTER_RUNTIME_DIR"] = str(runtime)
    os.environ["IPYTHONDIR"] = str(runtime / "ipython")
    os.environ["MPLCONFIGDIR"] = str(runtime / "matplotlib")
    os.environ["SEHAT_HYBRID_WORKERS"] = str(args.workers)
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(DEPS), os.environ.get("PYTHONPATH", "")])
    started = datetime.now(timezone.utc).isoformat()
    execution = {"started_utc": started, "python": sys.executable, "status": "running", "workers": args.workers}
    (OUT / "notebook_execution.json").write_text(json.dumps(execution, indent=2))
    def save_progress(cell, cell_index, **kwargs):
        nbformat.write(nb, target)
        print(f"Executed cell {cell_index + 1}/{len(nb.cells)}", flush=True)
        if cell.get("outputs"):
            streams = "".join(o.get("text", "") for o in cell.outputs if o.output_type == "stream")
            print(streams[-5000:], flush=True)
    client = NotebookClient(nb, timeout=7200, kernel_name="python3", allow_errors=False,
                            resources={"metadata": {"path": str(ROOT)}}, on_cell_executed=save_progress)
    try:
        client.execute()
        assert all(c.execution_count is not None for c in nb.cells if c.cell_type == "code")
        assert not any(o.output_type == "error" for c in nb.cells if c.cell_type == "code" for o in c.outputs)
        for path, value in before.items():
            assert digest(ROOT / path) == value, f"Protected input changed: {path}"
        execution.update(status="completed", finished_utc=datetime.now(timezone.utc).isoformat(),
                         code_cells_executed=sum(c.cell_type == "code" for c in nb.cells), protected_input_hashes=before,
                         notebook_sha256=digest(target))
        print("Notebook completed without errors; reference notebook and firmware hashes unchanged.", flush=True)
    except BaseException as exc:
        execution.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        nbformat.write(nb, target)
        execution["notebook_sha256"] = digest(target)
        (OUT / "notebook_execution.json").write_text(json.dumps(execution, indent=2))


if __name__ == "__main__":
    main()
