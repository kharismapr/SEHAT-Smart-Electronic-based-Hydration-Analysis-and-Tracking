"""Train only SEHAT recordings and export the unchanged ESP32 model interface.

Run from any directory: python scripts/export_et_sehat_only.py
The firmware still passes the nine S1-normalized features to
hydration_et_predict(input, 9), and receives fasting duration in hours.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import re
import sys

import joblib
import numpy as np
import pandas as pd
import sklearn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hybrid_retraining as h  # noqa: E402

OUTPUT_NAME = "sehat_only_results"
FIRMWARE = ROOT / "SEHAT_GSR_PPG_ESP32_ML"
HEADER = FIRMWARE / "et_sehat_only.h"


def read_legacy_scaler():
    source = (FIRMWARE / "s1_scaler.h").read_text(encoding="utf-8")
    values = []
    for name in ["kMean", "kStd"]:
        match = re.search(rf"\b{name}\[8\]\s*=\s*\{{([^}}]+)\}}", source)
        if match is None:
            raise ValueError(f"Cannot read {name} from s1_scaler.h")
        array = np.array([float(v.strip()) for v in match[1].split(",") if v.strip()])
        if array.shape != (8,) or not np.isfinite(array).all():
            raise ValueError(f"Invalid legacy scaler {name}")
        values.append(array)
    if not (values[1] > 0).all():
        raise ValueError("Legacy standard deviations must be positive")
    return values


def extract_sehat(manifest, config, workers):
    rows = manifest.to_dict("records")
    windows, qc = [], []

    def consume(result, row):
        windows.extend(result[0])
        qc.append(result[1])
        print(f"[{len(qc)}/{len(rows)}] {row['file']}: "
              f"{result[1]['accepted_windows']}/{result[1]['candidate_windows']} windows", flush=True)

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(h.process_file, row, config) for row in rows]
            for row, future in zip(rows, futures):
                consume(future.result(), row)
    else:
        for row in rows:
            consume(h.process_file(row, config), row)
    windows = pd.DataFrame(windows).sort_values(["recording_id", "window_start_sample"]).reset_index(drop=True)
    qc = pd.DataFrame(qc).sort_values("file").reset_index(drop=True)
    windows["training_eligible"] = windows.qc_pass & windows.training_record_eligible
    data = windows.loc[windows.training_eligible].copy().reset_index(drop=True)
    if data.empty or data.subject_id.nunique() < 3:
        raise ValueError("At least three subjects with usable SEHAT windows are required")
    assert data.device_source.eq("SEHAT").all()
    assert not data.duplicated(["recording_id", "window_id"]).any()
    assert data.window_samples.eq(round(config.fs * config.window_sec)).all()
    assert data.groupby("recording_id").fasting_duration_hr.nunique().eq(1).all()
    assert np.isfinite(data.fasting_duration_hr).all() and data.fasting_duration_hr.ge(0).all()
    assert data.loc[data.ppg_available.eq(0), h.PPG_FEATURES].isna().all().all()
    # Copied recordings must not become separate training/evaluation examples.
    if qc.signal_sha256.duplicated().any():
        raise ValueError("Duplicate SEHAT signal recordings detected")
    windows.to_csv(config.out / "window_quality_control.csv", index=False)
    qc.to_csv(config.out / "quality_control_per_file.csv", index=False)
    data.to_csv(config.out / "features_sehat.csv", index=False)
    qc.loc[qc.exclusion_reason.ne("")].to_csv(config.out / "audit/excluded_recordings.csv", index=False)
    return data, qc


def evaluate_sehat(data, config):
    predictions, folds = [], []
    for subject in sorted(data.subject_id.unique()):
        train = data.loc[data.subject_id.ne(subject)]
        test = data.loc[data.subject_id.eq(subject)]
        assert set(train.recording_id).isdisjoint(test.recording_id)
        model = h.fit_model(train, "D_SEHAT_only", config)
        result = test[["subject_id", "session_id", "recording_id", "window_id", "file", "ppg_available", "fasting_duration_hr"]].copy()
        result = result.rename(columns={"fasting_duration_hr": "y_true"})
        result["y_pred"] = model.predict(test[h.FEATURES])
        predictions.append(result)
        folds.append(dict(test_subject=subject, train_subjects=sorted(train.subject_id.unique()),
                          train_recordings=int(train.recording_id.nunique()), train_windows=len(train),
                          test_recordings=int(test.recording_id.nunique()), test_windows=len(test),
                          imputation_medians=model.named_steps["imputer"].statistics_.tolist()))
    windows = pd.concat(predictions, ignore_index=True)
    records = windows.groupby(["subject_id", "session_id", "recording_id", "file"], as_index=False).agg(
        y_true=("y_true", "first"), y_pred=("y_pred", "mean"), windows=("window_id", "size"))
    records["absolute_error_hr"] = (records.y_pred - records.y_true).abs()
    per_subject = pd.DataFrame([dict(subject_id=s, **h.metrics(g)) for s, g in records.groupby("subject_id")])
    metrics = dict(model="D_SEHAT_only", **h.metrics(records),
                   macro_subject_MAE_hr=float(per_subject.MAE_hr.mean()),
                   validation="Leave-One-SEHAT-Subject-Out; mean accepted-window prediction per recording")
    windows.to_csv(config.out / "oof_predictions_windows.csv", index=False)
    records.to_csv(config.out / "oof_predictions_recordings.csv", index=False)
    per_subject.to_csv(config.out / "evaluation_per_subject.csv", index=False)
    h.write_json(config.out / "evaluation.json", metrics)
    h.write_json(config.out / "audit/folds.json", folds)
    return metrics


def c_double(value):
    text = format(float(value), ".17g")
    return text if "." in text or "e" in text else text + ".0"


def export_header(pipeline, contract):
    model = pipeline.named_steps["model"]
    lines = [
        "#pragma once", "", "// Generated by scripts/export_et_sehat_only.py. Do not edit by hand.",
        "// Training: SEHAT only; ExtraTreesRegressor, 35 trees, depth 8, min leaf 4, seed 42.",
        f"// {contract['training_recordings']} recordings; {contract['training_windows']} accepted 30-second windows.",
        f"// Training feature CSV SHA-256: {contract['training_features_sha256']}",
        "// Input order: gsr_mean, gsr_var, gsr_entropy, mean_hr, rmssd, sdnn,",
        "//              pnn50, n_peaks, ppg_available.",
        "// hydration_et_predict accepts the EXISTING s1_features.h normalized vector.",
        "// It reverses the legacy z-score internally; do not normalize a second time.",
        "// ppg_available=0 replaces all five PPG inputs with SEHAT training medians.",
        "// Output: estimated fasting duration in hours, unchanged from the old API.",
        "// Include this header INSTEAD OF et_hydration_model_S1.h (same function name).",
        "// Sensor preprocessing/peak detection is unchanged; host parity is not board validation.",
        "", "#include <cmath>", "#include <cstdint>", '#include "s1_scaler.h"', "",
        "namespace sehat_only {", "constexpr int32_t kFeatureCount = 9;",
        f"constexpr int32_t kTreeCount = {len(model.estimators_)};",
        "static constexpr double kTrainingMedians[kFeatureCount] = {",
        "    " + ", ".join(c_double(v) for v in pipeline.named_steps["imputer"].statistics_),
        "};", "", "namespace detail {",
    ]
    for index, estimator in enumerate(model.estimators_):
        tree = estimator.tree_
        lines.append(f"static inline double tree_{index}(const float *features) {{")

        def emit(node, level):
            indent = "  " * level
            left, right = tree.children_left[node], tree.children_right[node]
            if left == right:
                lines.append(f"{indent}return {c_double(tree.value[node, 0, 0])};")
                return
            lines.append(f"{indent}if (features[{tree.feature[node]}] <= {c_double(tree.threshold[node])}) {{")
            emit(left, level + 1)
            lines.append(f"{indent}}} else {{")
            emit(right, level + 1)
            lines.append(f"{indent}}}")

        emit(0, 1)
        lines.extend(["}", ""])
    lines.extend([
        "}  // namespace detail", "",
        "// Raw-unit entry point for comparison with the notebook's Python pipeline.",
        "// NaNs receive training medians; infinities are invalid as in sklearn.",
        "static inline float predictRaw(const float *features, int32_t features_length) {",
        "  if (features == nullptr || features_length != kFeatureCount) return NAN;",
        "  float values[kFeatureCount];",
        "  for (int32_t i = 0; i < kFeatureCount; ++i) {",
        "    if (std::isnan(features[i])) values[i] = static_cast<float>(kTrainingMedians[i]);",
        "    else if (!std::isfinite(features[i])) return NAN;",
        "    else values[i] = features[i];",
        "  }", "  double sum = 0.0;",
    ])
    lines.extend(f"  sum += detail::tree_{i}(values);" for i in range(len(model.estimators_)))
    lines.extend([
        "  return static_cast<float>(sum / kTreeCount);", "}",
        "}  // namespace sehat_only", "",
        "// Drop-in caller contract: identical argument order, length, and output units.",
        "// float32 in the old header is a typedef of float in the existing sketch.",
        "static inline float hydration_et_predict(const float *features, int32_t features_length) {",
        "  if (features == nullptr || features_length != sehat_only::kFeatureCount) return NAN;",
        "  const float available = features[8];",
        "  if (available != 0.0f && available != 1.0f) return NAN;",
        "  float raw[sehat_only::kFeatureCount];",
        "  for (int32_t i = 0; i < 8; ++i) {",
        "    if (i >= 3 && available == 0.0f) { raw[i] = NAN; continue; }",
        "    if (!std::isfinite(features[i])) return NAN;",
        "    raw[i] = static_cast<float>(static_cast<double>(features[i]) *",
        "                                sehat_s1::kStd[i] + sehat_s1::kMean[i]);",
        "    if (!std::isfinite(raw[i])) return NAN;",
        "  }",
        "  raw[8] = available;",
        "  return sehat_only::predictRaw(raw, sehat_only::kFeatureCount);",
        "}", "",
    ])
    HEADER.write_text("\n".join(lines), encoding="utf-8")


def train_and_export(workers=3):
    config = h.Config(project_root=str(ROOT), output_name=OUTPUT_NAME)
    # Protect the I/O and feature pipeline the user asked to preserve.
    protected = [p for p in FIRMWARE.iterdir() if p.suffix in {".ino", ".h"} and p != HEADER]
    before = {p: h.file_hash(p) for p in protected}
    manifest = h.inventory(config, include_shimmer=False)
    assert manifest.device_source.eq("SEHAT").all()
    data, qc = extract_sehat(manifest, config, workers)
    metrics = evaluate_sehat(data, config)
    pipeline = h.fit_model(data, "D_SEHAT_only", config)
    model_path = config.out / "models/et_sehat_only_pipeline.joblib"
    joblib.dump(pipeline, model_path, compress=3)
    means, stds = read_legacy_scaler()
    contract = dict(
        model="D_SEHAT_only", estimator="ExtraTreesRegressor",
        parameters=pipeline.named_steps["model"].get_params(),
        raw_recordings=len(manifest), training_recordings=int(data.recording_id.nunique()),
        training_windows=len(data), subjects=sorted(data.subject_id.unique()),
        features_in_order=h.FEATURES,
        units=["uS", "uS^2", "nats", "beats/min", "ms", "ms", "percent", "count/30sec", "binary"],
        training_scaling="none; frozen training median imputation",
        imputation_medians=dict(zip(h.FEATURES, pipeline.named_steps["imputer"].statistics_.tolist())),
        firmware_entry_point="hydration_et_predict(const float *features, int32_t features_length)",
        firmware_input="Existing s1_features.h output: first eight legacy S1 z-scores; ninth binary availability flag",
        legacy_mean=means.tolist(), legacy_std=stds.tolist(),
        legacy_scaler_sha256=h.file_hash(FIRMWARE / "s1_scaler.h"),
        ppg_unavailable="flag=0 ignores the five normalized PPG placeholders; uses the frozen SEHAT training medians",
        output="estimated fasting duration in hours",
        header=str(HEADER.relative_to(ROOT)),
        model_sha256=h.file_hash(model_path),
        training_features_sha256=h.file_hash(config.out / "features_sehat.csv"),
        raw_hashes=dict(zip(manifest.file, manifest.raw_sha256)),
        code_hashes={p: h.file_hash(ROOT / p) for p in ["hybrid_retraining.py", "ppg_preprocessing.py", "scripts/export_et_sehat_only.py"]},
        evaluation=metrics, python=sys.version, sklearn=sklearn.__version__,
        preprocessing_config=asdict(config),
        validation_limit="LOSO covers five subjects. Embedded PPG peaks approximate HeartPy; board/sensor validation is still required.",
    )
    export_header(pipeline, contract)
    contract["header_sha256"] = h.file_hash(HEADER)
    h.write_json(config.out / "models/inference_contract.json", contract)
    if before != {p: h.file_hash(p) for p in protected}:
        raise AssertionError("Existing firmware/model/scaler files changed during export")
    if any(h.file_hash(Path(row.path)) != row.raw_sha256 for row in manifest.itertuples()):
        raise AssertionError("Raw recording changed during training; rerun on a stable snapshot")
    (config.out / "README.md").write_text(
        "# SEHAT-only Extra Trees export\n\n"
        f"Training: {len(manifest)} raw recordings, {contract['training_recordings']} retained recordings, "
        f"{len(data)} accepted windows, {len(contract['subjects'])} subjects. No Shimmer training data.\n\n"
        "Uses the hybrid notebook's fixed preprocessing/QC and Extra Trees configuration. "
        "LOSO fits its imputer on each training fold; the deployment model is refit on all accepted SEHAT windows.\n\n"
        f"Recording-level LOSO MAE: {metrics['MAE_hr']:.6f} h; RMSE: {metrics['RMSE_hr']:.6f} h. "
        "See evaluation_per_subject.csv and oof_predictions_recordings.csv.\n\n"
        "Replace only the model include in SEHAT_GSR_PPG_ESP32_ML.ino with `#include \"et_sehat_only.h\"`. "
        "Keep s1_features.h, s1_scaler.h, the nine-feature order, the existing hydration_et_predict(input, 9) call, "
        "and hours output. The new header internally reverses the old scaler and applies its trained imputer. "
        "Include one model header at a time. The checked-in sketch is unchanged.\n\n"
        "Regenerate: `python scripts/export_et_sehat_only.py`. "
        "Verify: `python tests/verify_sehat_only_export.py`.\n\n"
        "Host numerical checks do not validate the ESP32 board or equivalence of HeartPy and the embedded peak detector. "
        "This is an estimated duration proxy evaluated on five subjects.\n",
        encoding="utf-8",
    )
    print(f"Exported {HEADER}\n{metrics}", flush=True)
    return contract


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    train_and_export(workers=args.workers)
