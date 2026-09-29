"""Reprocess the recordings represented in the existing feature table.

The original table supplies labels and the recording list only. Raw samples and
motion-affected windows are retained; missing physiology remains explicitly
unavailable. The original feature table is never overwritten.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, filtfilt
from scipy.stats import entropy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ppg_preprocessing import (  # noqa: E402
    PPGConfig,
    create_windows,
    extract_preprocessed_features,
    load_signals,
    plot_ppg_comparison,
    prepare_recording,
)

FS = 51.2
WINDOW_SEC = 30.0
OVERLAP = 0.5
LEGACY_PPG_FEATURES = ["mean_hr", "rmssd", "sdnn", "pnn50"]
METADATA_COLUMNS = [
    "file", "subject_id", "session_type", "hydration_status", "fasting_duration_hr"
]


def extract_gsr_features(values: np.ndarray) -> dict:
    """Preserve the revised notebook's 1 Hz filtering and histogram features."""
    series = pd.Series(values, dtype=float).replace([np.inf, -np.inf], np.nan)
    if not series.notna().any():
        return {name: np.nan for name in ("gsr_mean", "gsr_var", "gsr_entropy")}
    filled = series.interpolate(limit_direction="both").to_numpy()
    b, a = butter(2, 1.0 / (FS / 2), btype="low")
    cleaned = filtfilt(b, a, filled) if len(filled) > 3 * max(len(a), len(b)) else filled
    histogram, _ = np.histogram(cleaned, bins=10, density=True)
    histogram = histogram[histogram > 0]
    return {
        "gsr_mean": float(np.mean(cleaned)),
        "gsr_var": float(np.var(cleaned)),
        "gsr_entropy": float(entropy(histogram)) if len(histogram) else 0.0,
    }


def finite_legacy_features(frame: pd.DataFrame, suffix: str = "") -> pd.Series:
    columns = [name + suffix for name in LEGACY_PPG_FEATURES]
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    return pd.Series(np.isfinite(values.to_numpy()).all(axis=1), index=frame.index)


def json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_summary(path: Path, summary: dict) -> None:
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=json_value, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def expected_windows(sample_count: int) -> int:
    size = round(WINDOW_SEC * FS)
    step = round(size * (1 - OVERLAP))
    if sample_count <= 0:
        return 0
    if sample_count < size:
        return 1
    complete = 1 + (sample_count - size) // step
    covered_end = (complete - 1) * step + size
    return complete + int(covered_end < sample_count)


def comparison_summary(baseline: pd.DataFrame, reprocessed: pd.DataFrame) -> dict:
    keys = ["file", "window_id"]
    joined = baseline[keys + LEGACY_PPG_FEATURES].merge(
        reprocessed[keys + LEGACY_PPG_FEATURES],
        on=keys,
        how="outer",
        suffixes=("_before", "_after"),
        indicator=True,
        validate="one_to_one",
    )
    matched = joined.loc[joined["_merge"].eq("both")]
    before = finite_legacy_features(matched, "_before")
    after = finite_legacy_features(matched, "_after")
    new_keys = joined.loc[joined["_merge"].eq("right_only"), keys]
    unmatched_new = reprocessed.merge(new_keys, on=keys, validate="one_to_one")
    return {
        "matching": "file and window_id; preserving formerly missing sensor rows can shift exact window boundaries",
        "availability_definition": "mean_hr, rmssd, sdnn and pnn50 are all finite",
        "matched_windows": int(len(matched)),
        "available_before_matched": int(before.sum()),
        "available_after_matched": int(after.sum()),
        "unavailable_before_available_after": int((~before & after).sum()),
        "available_before_unavailable_after": int((before & ~after).sum()),
        "unavailable_both": int((~before & ~after).sum()),
        "baseline_windows_without_matching_new_id": int(joined["_merge"].eq("left_only").sum()),
        "new_windows_without_baseline_id": int(len(unmatched_new)),
        "unmatched_new_partial_tails": int(unmatched_new["window_samples"].lt(round(FS * WINDOW_SEC)).sum()),
        "unmatched_new_full_windows": int(unmatched_new["window_samples"].eq(round(FS * WINDOW_SEC)).sum()),
        "unmatched_new_available": int(finite_legacy_features(unmatched_new).sum()),
        "unmatched_new_status_counts": unmatched_new["ppg_status"].value_counts().to_dict(),
        "interpretation": "Feature availability is not a measurement of denoising accuracy or physiological correctness.",
    }


def save_recording(recording: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    columns = {
        "raw_ppg": "ppg",
        "cleaned_ppg": "ppg_clean",
        "timestamp_ms": "timestamp_ms",
        "motion_score": "ppg_motion_score",
        "motion_threshold": "ppg_motion_threshold",
        "high_motion": "ppg_high_motion",
        "interpolated": "ppg_interpolated",
        "missing": "ppg_missing",
        "gyro_missing": "ppg_gyro_missing",
        "timing_gap": "ppg_timing_gap",
    }
    arrays = {name: recording[column].to_numpy() for name, column in columns.items()}
    arrays["sample_rate"] = np.asarray(FS)
    np.savez_compressed(destination, **arrays)


def plot_candidate(recording: pd.DataFrame) -> tuple[float, float]:
    if recording.empty:
        return -1.0, 0.0
    high = recording["ppg_high_motion"].to_numpy(dtype=float)
    fraction = float(high.mean())
    # Prefer a recording containing both motion states and few timestamp gaps.
    score = fraction * (1 - fraction) * (1 - float(recording["ppg_timing_gap"].mean()))
    width = min(len(high), round(WINDOW_SEC * FS))
    local_fraction = uniform_filter1d(high, size=max(1, width), mode="nearest")
    mix = local_fraction * (1 - local_fraction)
    center = int(np.argmax(mix))
    start = max(0, min(center - width // 2, len(high) - width))
    return score, start / FS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=PROJECT_ROOT / "dataset_final_features.csv")
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "shimmer-raw-dataset-dehydration")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "artifacts" / "ppg")
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--limit-files", type=int, default=None, help="Process the first N baseline recordings for a smoke run.")
    args = parser.parse_args(argv)
    if args.limit_files is not None and args.limit_files < 1:
        parser.error("--limit-files must be positive")
    output_dir = args.output_dir.resolve()
    output_csv = args.output_csv or (
        output_dir / "features_preview.csv" if args.limit_files is not None
        else PROJECT_ROOT / "dataset_final_features_reprocessed.csv"
    )
    output_csv = output_csv.resolve()
    if output_csv == args.metadata.resolve() or output_csv == (PROJECT_ROOT / "dataset_final_features.csv").resolve():
        parser.error("The baseline feature table must not be overwritten.")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / ("summary_preview.json" if args.limit_files is not None else "summary.json")
    baseline = pd.read_csv(args.metadata)
    missing_columns = set(METADATA_COLUMNS + ["window_id"] + LEGACY_PPG_FEATURES) - set(baseline)
    if missing_columns:
        raise ValueError(f"Baseline table is missing columns: {sorted(missing_columns)}")
    if baseline.duplicated(["file", "window_id"]).any():
        raise ValueError("Baseline file/window_id pairs must be unique.")
    records = baseline[METADATA_COLUMNS].drop_duplicates()
    if records["file"].duplicated().any():
        raise ValueError("A baseline recording has inconsistent metadata or labels.")
    all_records = records.copy()
    records = records.iloc[:args.limit_files] if args.limit_files is not None else records
    raw_paths = [p for p in args.dataset.rglob("*.csv") if "fastingtime" not in p.name.lower()]
    raw_by_name = {}
    for path in raw_paths:
        if path.name in raw_by_name:
            raise ValueError(f"Ambiguous raw recording filename: {path.name}")
        raw_by_name[path.name] = path
    absent_raw = sorted(set(records["file"]) - set(raw_by_name))
    if absent_raw:
        raise FileNotFoundError(f"Baseline recordings absent from raw dataset: {absent_raw}")
    excluded_raw = sorted(set(raw_by_name) - set(all_records["file"]))
    selected_baseline = baseline[baseline["file"].isin(records["file"])].copy()
    summary = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "complete": False,
        "smoke_run": args.limit_files is not None,
        "metadata_source": str(args.metadata.resolve()),
        "output_csv": str(output_csv),
        "scope": {
            "baseline_recordings": len(all_records),
            "selected_recordings": len(records),
            "raw_recordings": len(raw_paths),
            "raw_recordings_outside_baseline": excluded_raw,
            "policy": "Only recordings represented in the baseline table are processed; labels are copied unchanged, including missing nonfasting fasting_duration_hr.",
        },
        "sample_rate_hz": FS,
        "preprocessing_config": asdict(PPGConfig()),
        "window_seconds": WINDOW_SEC,
        "overlap": OVERLAP,
        "baseline_windows_in_scope": len(selected_baseline),
        "file_audits": [],
        "file_failures": [],
    }
    start_time = time.monotonic()
    print(f"Scope: {len(records)}/{len(all_records)} baseline recordings; {len(selected_baseline)} previous windows.", flush=True)
    print(f"Raw files outside the baseline table: {len(excluded_raw)} (listed in summary).", flush=True)
    all_rows = []
    best_plot_score = -1.0
    for i, metadata in enumerate(records.to_dict("records"), 1):
        filename = metadata["file"]
        print(f"[{i}/{len(records)}] {filename}", flush=True)
        try:
            raw = load_signals(raw_by_name[filename])
            prepared = prepare_recording(raw, fs=FS)
            if len(prepared) != len(raw):
                raise AssertionError("Preprocessing changed the original sample count.")
            windows = create_windows(prepared, fs=FS, window_sec=WINDOW_SEC, overlap=OVERLAP)
            expected = expected_windows(len(raw))
            if len(windows) != expected:
                raise AssertionError(f"Expected {expected} windows including the tail, received {len(windows)}.")
            rows = []
            covered = np.zeros(len(raw), dtype=bool)
            for window_id, window in enumerate(windows):
                begin = int(window.index[0])
                end = int(window.index[-1]) + 1
                covered[begin:end] = True
                features = extract_preprocessed_features(window, fs=FS)
                features.update(extract_gsr_features(window["gsr"].to_numpy()))
                features.update(metadata)
                features.update({
                    "window_id": window_id,
                    "window_start_sample": begin,
                    "window_end_sample": end,
                    "window_samples": len(window),
                    "window_duration_sec": len(window) / FS,
                })
                rows.append(features)
            if not covered.all():
                raise AssertionError("Some recorded samples were not covered by any output window.")
            if not rows:
                raise ValueError("Recording contains no samples; cannot create a feature row.")
            frame = pd.DataFrame(rows)
            destination = output_dir / "cleaned" / str(metadata["subject_id"]) / str(metadata["session_type"]) / (Path(filename).stem + ".npz")
            save_recording(prepared, destination)
            audit = {
                "file": filename,
                "subject_id": metadata["subject_id"],
                "session_type": metadata["session_type"],
                "raw_samples": len(raw),
                "retained_samples": len(prepared),
                "window_covered_samples": int(covered.sum()),
                "finite_cleaned_samples": int(np.isfinite(prepared["ppg_clean"]).sum()),
                "missing_ppg_samples": int((~np.isfinite(raw["ppg"])).sum()),
                "unrepaired_missing_ppg_samples": int(prepared["ppg_missing"].sum()),
                "interpolated_ppg_samples": int(prepared["ppg_interpolated"].sum()),
                "missing_gyro_samples": int(prepared["ppg_gyro_missing"].sum()),
                "timing_gap_samples": int(prepared["ppg_timing_gap"].sum()),
                "high_motion_samples": int(prepared["ppg_high_motion"].sum()),
                "expected_windows": expected,
                "retained_windows": len(rows),
                "partial_tail_windows": int(frame["window_samples"].lt(round(WINDOW_SEC * FS)).sum()),
                "baseline_windows": int(selected_baseline["file"].eq(filename).sum()),
                "available_legacy_ppg_features": int(finite_legacy_features(frame).sum()),
                "heartpy_valid_windows": int(frame["ppg_feature_valid"].sum()),
                "heartpy_quality_ok_windows": int(frame["ppg_quality_ok"].sum()),
                "status_counts": frame["ppg_status"].value_counts().to_dict(),
                "cleaned_recording": str(destination),
            }
            summary["file_audits"].append(audit)
            all_rows.extend(rows)
            candidate_score, plot_start = plot_candidate(prepared)
            if candidate_score > best_plot_score:
                figure = plot_ppg_comparison(prepared, fs=FS, start_sec=plot_start, duration_sec=WINDOW_SEC)
                figure.savefig(output_dir / "ppg_comparison.png", dpi=160, bbox_inches="tight")
                plt.close(figure)
                best_plot_score = candidate_score
                summary["comparison_plot"] = {"file": filename, "start_sec": plot_start, "path": str(output_dir / "ppg_comparison.png")}
            print(f"  Samples retained: {len(prepared)}/{len(raw)}; windows: {len(rows)}/{expected}; HeartPy valid: {audit['heartpy_valid_windows']}", flush=True)
            summary["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
            write_summary(summary_path, summary)
        except Exception as error:
            summary["file_failures"].append({"file": filename, "error_type": type(error).__name__, "error": str(error)})
            summary["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
            write_summary(summary_path, summary)
            print(f"FAILED: {filename}: {error}. Audit saved to {summary_path}; feature CSV was not replaced.", file=sys.stderr, flush=True)
            raise

    result = pd.DataFrame(all_rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    summary.update({
        "complete": True,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - start_time, 3),
        "total_raw_samples": sum(item["raw_samples"] for item in summary["file_audits"]),
        "total_retained_samples": sum(item["retained_samples"] for item in summary["file_audits"]),
        "total_expected_windows": sum(item["expected_windows"] for item in summary["file_audits"]),
        "total_retained_windows": len(result),
        "heartpy_valid_windows": int(result["ppg_feature_valid"].sum()),
        "heartpy_quality_ok_windows": int(result["ppg_quality_ok"].sum()),
        "status_counts": result["ppg_status"].value_counts().to_dict(),
        "before_after": comparison_summary(selected_baseline, result),
    })
    write_summary(summary_path, summary)
    print(f"Saved {len(result)} retained windows to {output_csv}", flush=True)
    print(f"Audit: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
