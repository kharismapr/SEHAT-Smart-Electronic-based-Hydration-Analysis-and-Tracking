"""Reproducible, offline SEHAT/Shimmer hybrid regression experiment.

Raw files, the reference notebook, and firmware are read-only inputs.
All learned preprocessing is fitted on training folds, never per test subject.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import importlib.metadata
import inspect
import json
import re
import sys
import time
import warnings

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt
from scipy.stats import entropy
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline

from ppg_preprocessing import PPGConfig, load_signals, preprocess_ppg, extract_ppg_features

FEATURES = ["gsr_mean", "gsr_var", "gsr_entropy", "mean_hr", "rmssd", "sdnn", "pnn50", "n_peaks", "ppg_available"]
PPG_FEATURES = FEATURES[3:8]
MODELS = ["A_Shimmer_only", "B_Hybrid_unweighted", "C_Hybrid_weighted", "D_SEHAT_only"]
IDENTITY_CORRECTIONS = {
    "20261107130818_S16_S16_F02_raw.csv": {
        "subject_id": "S16", "session_id": "S16_F02",
        "reason": "User confirmed in chat 2026-11-12: actual subject S16; filename is correct. Raw internal S15/S15_F02 retained in audit.",
    }
}
SOURCES = {
    "imputation": "https://scikit-learn.org/1.6/modules/generated/sklearn.impute.SimpleImputer.html",
    "extra_trees": "https://scikit-learn.org/1.6/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html",
    "filter": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html",
    "heartpy": "https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/heartpy.heartpy.html",
}


@dataclass(frozen=True)
class Config:
    project_root: str = r"D:\ima\SEM7\DESPRO 2\ML"
    output_name: str = "hybrid_retraining_results"
    fs: float = 51.2
    window_sec: float = 30.0
    overlap: float = 0.5
    max_gap_sec: float = 0.25
    max_gsr_missing_fraction: float = 0.05
    max_ppg_bad_fraction: float = 0.05
    gsr_cutoff_hz: float = 1.0
    gsr_filter_order: int = 2
    severe_motion_dps: float = 100.0
    max_severe_motion_fraction: float = 0.20
    max_rr_rejected_fraction: float = 0.30
    # Threshold is relative to the local signal plus 2% of DC, independent of target.
    ppg_hampel_mad: float = 8.0
    ppg_hampel_window_sec: float = 0.25
    ppg_min_spike_dc_fraction: float = 0.02
    n_estimators: int = 35
    max_depth: int = 8
    min_samples_leaf: int = 4
    random_state: int = 42

    @property
    def root(self):
        return Path(self.project_root).resolve()

    @property
    def out(self):
        return self.root / self.output_name

    @property
    def shimmer(self):
        return self.root / "shimmer-raw-dataset-dehydration" / "shimmer-raw-dataset-dehydration"

    @property
    def sehat(self):
        return self.root / "Data Acquisition" / "sehat_raw_data"


def write_json(path, value):
    def convert(x):
        if isinstance(x, (np.integer, np.floating, np.bool_)):
            return x.item()
        if isinstance(x, Path):
            return str(x)
        raise TypeError(type(x).__name__)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=convert), encoding="utf-8")


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def runs(mask):
    edges = np.diff(np.r_[False, np.asarray(mask, dtype=bool), False].astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def repair_short_gaps(values, fs, max_gap_sec):
    """Only bounded interior runs; no edge extrapolation or partial long-gap fill."""
    values = np.asarray(values, float).copy()
    values[~np.isfinite(values)] = np.nan
    repaired = np.zeros(len(values), bool)
    for start, end in runs(~np.isfinite(values)):
        if start > 0 and end < len(values) and (end - start) / fs <= max_gap_sec:
            values[start:end] = np.linspace(values[start - 1], values[end], end - start + 2)[1:-1]
            repaired[start:end] = True
    return values, repaired


def shimmer_header(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        rows = [f.readline().strip().split(",") for _ in range(4)]
    names = [f"{a.strip()}_{b.strip()}" for a, b in zip(rows[1], rows[2])]
    return names, rows[3]


def inventory(config=Config(), *, include_shimmer=True):
    for path in ([config.shimmer] if include_shimmer else []) + [config.sehat]:
        if not path.is_dir():
            raise FileNotFoundError(f"Dataset folder missing: {path}")
    for name in ["audit", "figures", "models", "cache"]:
        (config.out / name).mkdir(parents=True, exist_ok=True)
    metadata_paths = sorted(config.shimmer.rglob("*asting*imes.csv")) if include_shimmer else []
    label_rows = []
    for path in metadata_paths:
        df = pd.read_csv(path, dtype=str)
        for i, row in df.iterrows():
            rec = pd.to_datetime(row["RecordingTime"], format="%Y%m%d%H%M%S", errors="coerce")
            start = pd.to_datetime(row["FastingTime"], format="%Y%m%d%H%M%S", errors="coerce")
            target = (rec - start).total_seconds() / 3600 if pd.notna(rec) and pd.notna(start) else np.nan
            label_rows.append(dict(subject_id=path.parent.parent.name, record_key=str(row["RecordingTime"]),
                                   fasting_duration_hr=target, last_drink_time=str(start),
                                   label_provenance=f"{path.relative_to(config.root).as_posix()}:row{i + 2}"))
    labels = pd.DataFrame(label_rows, columns=["subject_id", "record_key", "fasting_duration_hr", "last_drink_time", "label_provenance"])
    if labels.duplicated(["subject_id", "record_key"]).any():
        raise ValueError("Duplicate Shimmer label keys: must resolve explicitly")
    labels.to_csv(config.out / "audit/shimmer_label_metadata.csv", index=False)
    lookup = {(r.subject_id, r.record_key): r._asdict() for r in labels.itertuples(index=False)}
    rows, schema = [], []
    sh_paths = [p for p in sorted(config.shimmer.rglob("*.csv")) if p.parent.name.lower() in ("fasting", "nonfasting") and p not in metadata_paths] if include_shimmer else []
    for path in sh_paths:
        names, units = shimmer_header(path)
        match = re.match(r"(\d{14})", path.name)
        key = match.group(1) if match else ""
        subject = path.parent.parent.name
        label = lookup.get((subject, key), {})
        target = label.get("fasting_duration_hr", np.nan)
        # No invented zero label for nonfasting; only an exact metadata match is usable.
        relative = path.relative_to(config.root).as_posix()
        rows.append(dict(device_source="Shimmer", path=str(path), relative_path=relative, file=path.name,
                         recording_id="Shimmer:" + relative + "@" + key,
                         subject_id=subject, session_id=path.stem, session_type=path.parent.name.lower(),
                         record_time=str(pd.to_datetime(key, format="%Y%m%d%H%M%S", errors="coerce")),
                         last_drink_time=label.get("last_drink_time", ""), fasting_duration_hr=target,
                         target_definition="reported_fasting_start", label_provenance=label.get("label_provenance", "unavailable"),
                         metadata_issues="", metadata_conflict=False, identity_resolved=True,
                         raw_subject_id=subject, raw_session_id=path.stem,
                         bytes=path.stat().st_size, raw_sha256="computed_during_extraction"))
        schema.append(dict(device_source="Shimmer", file=path.name, columns=json.dumps(names), units=json.dumps(units),
                           duplicate_column_names=len(names) - len(set(names)),
                           required_present=all(x in names for x in ["PPG_A13_CAL", "GSR_Skin_Conductance_CAL", "Timestamp_CAL"])))
    for path in sorted(config.sehat.glob("*.csv")):
        # Read all metadata: validate constancy, rather than assuming first row is representative.
        df = pd.read_csv(path)
        required = ["subject_id", "session_id", "last_drink_time", "record_time", "fasting_duration_hr", "elapsed_us", "elapsed_sec", "ppg_ir_raw", "gsr_conductance_us"]
        if not set(required).issubset(df.columns):
            raise ValueError(f"Missing SEHAT columns {path}: {set(required) - set(df.columns)}")
        issues = []
        for col in required[:5]:
            if df[col].nunique(dropna=False) != 1:
                issues.append(f"nonconstant_{col}")
        m = re.fullmatch(r"(\d{14})_(S\d+)_(S\d+_F\d+)_raw.csv", path.name)
        if not m:
            raise ValueError(f"Unrecognized filename: {path.name}")
        key, filename_subject, filename_session = m.groups()
        raw_subject, raw_session = str(df.subject_id.iloc[0]), str(df.session_id.iloc[0])
        if filename_subject != raw_subject:
            issues.append(f"subject_filename={filename_subject};internal={raw_subject}")
        if filename_session != raw_session:
            issues.append(f"session_filename={filename_session};internal={raw_session}")
        rec = pd.to_datetime(df.record_time.iloc[0], errors="coerce")
        last = pd.to_datetime(df.last_drink_time.iloc[0], errors="coerce")
        filetime = pd.to_datetime(key, format="%Y%m%d%H%M%S")
        if pd.isna(rec) or abs((rec - filetime).total_seconds()) > 1:
            issues.append("record_time_vs_filename_mismatch")
        target = pd.to_numeric(df.fasting_duration_hr.iloc[0], errors="coerce")
        computed = (rec - last).total_seconds() / 3600 if pd.notna(rec) and pd.notna(last) else np.nan
        # Capture logger sub-second rounding; difference over one second is suspicious.
        if not np.isfinite(computed) or not np.isfinite(target) or abs(target - computed) > 1 / 3600:
            issues.append("target_vs_last_drink_mismatch")
        correction = IDENTITY_CORRECTIONS.get(path.name, {})
        subject = correction.get("subject_id", filename_subject)
        session = correction.get("session_id", filename_session)
        resolved = filename_subject == raw_subject or bool(correction)
        relative = path.relative_to(config.root).as_posix()
        rows.append(dict(device_source="SEHAT", path=str(path), relative_path=relative, file=path.name,
                         recording_id="SEHAT:" + relative + "@" + str(rec), subject_id=subject,
                         session_id=session, session_type="acquisition_unspecified", record_time=str(rec),
                         last_drink_time=str(last), fasting_duration_hr=target, target_definition="self_reported_last_drink",
                         label_provenance="raw CSV fasting_duration_hr; checked against record_time-last_drink_time",
                         metadata_issues=" | ".join(issues), metadata_conflict=bool(issues), identity_resolved=resolved,
                         identity_correction=correction.get("reason", "filename used for unique session; internal metadata preserved"),
                         raw_subject_id=raw_subject, raw_session_id=raw_session, target_recomputed_hr=computed,
                         bytes=path.stat().st_size, raw_sha256=file_hash(path)))
        schema.append(dict(device_source="SEHAT", file=path.name, columns=json.dumps(list(df.columns)),
                           units="PPG=18-bit IR counts; GSR=uS; gyro=deg/s; elapsed_us=microseconds", duplicate_column_names=0,
                           required_present=True))
    manifest = pd.DataFrame(rows)
    if manifest.recording_id.duplicated().any():
        raise AssertionError("Recording identities must be unique")
    manifest["label_valid"] = np.isfinite(manifest.fasting_duration_hr) & manifest.fasting_duration_hr.ge(0)
    manifest.loc[manifest.metadata_issues.str.contains("nonconstant_|target_vs_|record_time_vs_", regex=True), "label_valid"] = False
    manifest["training_record_eligible"] = manifest.label_valid & manifest.identity_resolved
    manifest.to_csv(config.out / "dataset_manifest.csv", index=False)
    pd.DataFrame(schema).to_csv(config.out / "audit/column_schema.csv", index=False)
    manifest.loc[manifest.metadata_conflict].to_csv(config.out / "audit/metadata_conflicts.csv", index=False)
    sh_subjects = set(manifest.loc[manifest.device_source.eq("Shimmer"), "subject_id"])
    se_subjects = set(manifest.loc[manifest.device_source.eq("SEHAT"), "subject_id"])
    if sh_subjects & se_subjects:
        raise ValueError("Cross-domain subject IDs overlap: establish participant mapping before LOSO")
    # This dataset has S1-S11 vs S12-S16. Different IDs are assumed different participants.
    write_json(config.out / "config.json", {**asdict(config), "ppg_config": asdict(PPGConfig()),
                "features": FEATURES, "identity_corrections": IDENTITY_CORRECTIONS, "sources": SOURCES,
                "primary_metric": "recording-level pooled MAE; mean prediction of accepted windows",
                "weighting": "N/(domains * subjects_in_domain * recordings_of_subject * windows_of_recording)",
                "normalization": "none; global training-fold median imputation only; no personal calibration or log1p",
                "threshold_policy": "Engineering signal-quality rules fixed before model fitting; no test-score optimization.",
                "python": sys.version, "executable": sys.executable,
                "versions": {p: importlib.metadata.version(p) for p in ["numpy", "pandas", "scipy", "scikit-learn", "heartpy", "matplotlib", "joblib"]}})
    print(manifest.groupby("device_source").agg(files=("file", "size"), subjects=("subject_id", "nunique"),
          sessions=("session_id", "nunique"), labeled_records=("label_valid", "sum")).to_string(), flush=True)
    print(f"Shimmer CSV: {len(sh_paths)} raw + {len(metadata_paths)} label tables; SEHAT CSV: {sum(manifest.device_source.eq('SEHAT'))} raw", flush=True)
    print(manifest.loc[manifest.metadata_conflict, ["file", "metadata_issues", "identity_resolved"]].to_string(index=False), flush=True)
    return manifest


def load_sehat(path):
    raw = pd.read_csv(path)
    mapping = {"ppg_ir_raw": "ppg", "gsr_conductance_us": "gsr", "gyro_x_dps": "gyro_x", "gyro_y_dps": "gyro_y", "gyro_z_dps": "gyro_z"}
    frame = pd.DataFrame({alias: pd.to_numeric(raw.get(col, pd.Series(np.nan, index=raw.index)), errors="coerce") for col, alias in mapping.items()})
    frame["timestamp_ms"] = pd.to_numeric(raw.elapsed_us, errors="coerce") / 1000
    frame["elapsed_sec_reported"] = pd.to_numeric(raw.elapsed_sec, errors="coerce")
    frame["sample_index"] = pd.to_numeric(raw.sample_index, errors="coerce")
    frame["gsr_adc12_raw"] = pd.to_numeric(raw.gsr_adc12_raw, errors="coerce")
    frame["gyro_magnitude_reported"] = pd.to_numeric(raw.gyro_magnitude_dps, errors="coerce")
    return frame


def timing_audit(frame, config):
    ts = frame.timestamp_ms.to_numpy(float) / 1000
    dt = np.diff(ts)
    good_dt = dt[np.isfinite(dt) & (dt > 0)]
    median = float(np.median(good_dt)) if len(good_dt) else np.nan
    # Keep resets/duplicates visible. Never sort, deduplicate, or compress the axis.
    broken = (~np.isfinite(dt)) | (dt <= 0) | (np.abs(dt - 1 / config.fs) > 0.5 / config.fs)
    invalid_ts = ~np.isfinite(ts)
    boundaries = np.unique(np.r_[0, np.flatnonzero(broken) + 1, np.flatnonzero(invalid_ts), np.flatnonzero(invalid_ts) + 1, len(frame)])
    segments = [(a, b) for a, b in zip(boundaries[:-1], boundaries[1:]) if b > a and np.isfinite(ts[a:b]).all()]
    qc = dict(samples=len(frame), timestamp_nonfinite=int(invalid_ts.sum()), timestamp_duplicate=int((dt == 0).sum()),
              timestamp_backwards=int((dt < 0).sum()), timing_breaks=int(broken.sum()), continuous_runs=len(segments),
              fs_median_hz=1 / median if median > 0 else np.nan,
              fs_elapsed_hz=(len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 and ts[-1] > ts[0] else np.nan,
              elapsed_span_sec=float(ts[-1] - ts[0]), median_dt_sec=median,
              max_dt_sec=float(np.max(good_dt)) if len(good_dt) else np.nan)
    if "elapsed_sec_reported" in frame:
        qc["elapsed_timestamp_max_difference_sec"] = float(np.nanmax(np.abs(frame.elapsed_sec_reported - ts)))
        qc["sample_index_breaks"] = int((frame.sample_index.diff().iloc[1:] != 1).sum())
    if "system_timestamp_ms" in frame:
        qc["system_timestamp_duplicate_fraction"] = float(frame.system_timestamp_ms.diff().iloc[1:].eq(0).mean())
    return segments, qc


def preprocess_run(frame, device, config):
    """Preserve the recording time axis; repair/filter only within a continuous run."""
    frame = frame.copy()
    gsr = frame.gsr.to_numpy(float, copy=True)
    frame["gsr_nonfinite_raw"] = ~np.isfinite(gsr)
    frame["gsr_nonpositive_raw"] = np.isfinite(gsr) & (gsr <= 0)
    gsr[(~np.isfinite(gsr)) | (gsr <= 0)] = np.nan
    frame["gsr_repaired"], frame["gsr_interpolated"] = repair_short_gaps(gsr, config.fs, config.max_gap_sec)
    ppg = frame.ppg.to_numpy(float, copy=True)
    bad = ~np.isfinite(ppg)
    rail = np.zeros(len(ppg), bool)
    outlier = np.zeros(len(ppg), bool)
    if device == "SEHAT":
        rail = np.isfinite(ppg) & ((ppg <= 0) | (ppg >= 262143))
        # A conservative Hampel test suppresses isolated electrical/startup spikes.
        series = pd.Series(ppg)
        size = max(3, round(config.ppg_hampel_window_sec * config.fs) | 1)
        med = series.rolling(size, center=True, min_periods=3).median()
        residual = (series - med).abs()
        mad = residual.rolling(size, center=True, min_periods=3).median()
        threshold = np.maximum(config.ppg_hampel_mad * 1.4826 * mad, config.ppg_min_spike_dc_fraction * med.abs())
        outlier = (residual > threshold).fillna(False).to_numpy()
        bad |= rail | outlier
    ppg[bad] = np.nan
    frame["ppg_bad_raw"] = bad
    frame["ppg_rail_raw"] = rail
    frame["ppg_outlier_raw"] = outlier
    axes = [frame[c].to_numpy(float) for c in ["gyro_x", "gyro_y", "gyro_z"]]
    result = preprocess_ppg(ppg, *axes, fs=config.fs, config=PPGConfig(max_gap_sec=config.max_gap_sec))
    frame["ppg_clean"] = result.cleaned
    frame["ppg_interpolated"] = result.interpolated
    frame["ppg_high_motion"] = result.high_motion
    frame["motion_score"] = result.motion_score
    frame["gyro_magnitude"] = np.sqrt(sum(a ** 2 for a in axes))
    frame["severe_motion"] = frame.gyro_magnitude > config.severe_motion_dps
    return frame


def gsr_features(values, config):
    b, a = butter(config.gsr_filter_order, config.gsr_cutoff_hz, btype="low", fs=config.fs)
    clean = filtfilt(b, a, values)
    hist, _ = np.histogram(clean, bins=10)
    return dict(gsr_mean=float(np.mean(clean)), gsr_var=float(np.var(clean, ddof=0)),
                gsr_entropy=float(entropy(hist[hist > 0]))), clean


def process_file(row, config):
    path = Path(row["path"])
    frame = load_signals(path) if row["device_source"] == "Shimmer" else load_sehat(path)
    segments, qc = timing_audit(frame, config)
    qc.update({k: row.get(k, "") for k in ["device_source", "recording_id", "subject_id", "session_id", "file", "label_valid", "training_record_eligible", "metadata_issues"]})
    qc["raw_sha256"] = file_hash(path)
    qc["gsr_nan_pct_before"] = 100 * float((~np.isfinite(frame.gsr)).mean())
    qc["gsr_max_nonfinite_gap_samples"] = max((b - a for a, b in runs(~np.isfinite(frame.gsr))), default=0)
    qc["gsr_max_nonfinite_gap_sec"] = qc["gsr_max_nonfinite_gap_samples"] / qc["fs_median_hz"] if qc["fs_median_hz"] > 0 else np.nan
    qc["gsr_nonpositive_pct"] = 100 * float((np.isfinite(frame.gsr) & frame.gsr.le(0)).mean())
    qc["ppg_nonfinite_pct"] = 100 * float((~np.isfinite(frame.ppg)).mean())
    qc["gyro_missing_pct"] = 100 * float((~np.isfinite(frame[["gyro_x", "gyro_y", "gyro_z"]])).any(axis=1).mean())
    qc["gsr_raw_median_us"] = float(frame.gsr.median())
    qc["ppg_raw_median"] = float(frame.ppg.median())
    qc["ppg_raw_min"] = float(frame.ppg.min())
    qc["ppg_raw_max"] = float(frame.ppg.max())
    if row["device_source"] == "SEHAT":
        qc["signal_sha256"] = sha256(np.ascontiguousarray(frame[["ppg", "gsr"]].to_numpy(float)).tobytes()).hexdigest()
    size = int(round(config.fs * config.window_sec))
    step = int(round(size * (1 - config.overlap)))
    covered = np.zeros(len(frame), bool)
    candidate_covered = np.zeros(len(frame), bool)
    windows = []
    example = None
    repaired_total = outlier_total = ppg_rail_total = 0
    for run_id, (a, b) in enumerate(segments):
        # A single unsupported-rate file may have hundreds of thousands of
        # one-sample runs. Such runs cannot yield any complete feature window.
        if b - a < size:
            continue
        section = preprocess_run(frame.iloc[a:b], row["device_source"], config)
        repaired_total += int(section.gsr_interpolated.sum())
        outlier_total += int(section.ppg_outlier_raw.sum())
        ppg_rail_total += int(section.ppg_rail_raw.sum())
        for local in range(0, len(section) - size + 1, step):
            w = section.iloc[local:local + size]
            first = a + local
            candidate_covered[first:first + size] = True
            reasons = []
            gsr_missing = float(w.gsr_nonfinite_raw.mean())
            nonpositive = float(w.gsr_nonpositive_raw.mean())
            unresolved = float((~np.isfinite(w.gsr_repaired)).mean())
            motion = float(w.severe_motion.mean())
            adc_rail = float(((w.gsr_adc12_raw <= 0) | (w.gsr_adc12_raw >= 4095)).mean()) if "gsr_adc12_raw" in w else 0.0
            if gsr_missing > config.max_gsr_missing_fraction:
                reasons.append("gsr_missing_over_5pct")
            if unresolved > 0:
                reasons.append("gsr_unrepaired_gap")
            if nonpositive > config.max_gsr_missing_fraction:
                reasons.append("gsr_nonpositive_over_5pct")
            if adc_rail > 0.05:
                reasons.append("gsr_adc_rail_over_5pct")
            if motion > config.max_severe_motion_fraction:
                reasons.append("severe_motion_over_20pct")
            feats = dict.fromkeys(FEATURES, np.nan)
            feats["ppg_available"] = 0
            if unresolved == 0:
                gf, gc = gsr_features(w.gsr_repaired.to_numpy(float), config)
                feats.update(gf)
            else:
                gc = np.full(len(w), np.nan)
            ppg_bad = float(w.ppg_bad_raw.mean())
            pc = w.ppg_clean.to_numpy(float)
            ppg_status = "not_measured"
            rr_fraction = np.nan
            estimated = dict.fromkeys(PPG_FEATURES, np.nan)
            if ppg_bad <= config.max_ppg_bad_fraction and motion <= config.max_severe_motion_fraction and np.isfinite(pc).all():
                extracted = extract_ppg_features(pc, fs=config.fs, preprocessed=True)
                ppg_status = extracted["ppg_status"]
                rr_fraction = extracted["ppg_rr_rejected_fraction"]
                estimated = {k: extracted.get(k, np.nan) for k in PPG_FEATURES}
                if extracted["ppg_quality_ok"]:
                    feats.update(estimated)
                    feats["ppg_available"] = 1
            else:
                ppg_status = "raw_missing_outlier_or_motion"
            keep = not reasons
            if keep:
                covered[first:first + size] = True
            meta = {k: row.get(k, "") for k in ["device_source", "recording_id", "subject_id", "session_id", "raw_subject_id", "raw_session_id", "session_type", "record_time", "last_drink_time", "fasting_duration_hr", "target_definition", "label_provenance", "file", "training_record_eligible"]}
            meta.update(feats)
            meta.update(window_id=f"{run_id:04d}:{local:09d}", run_id=run_id, window_start_sample=first,
                        window_end_sample=first + size, window_samples=size, window_duration_sec=size / config.fs,
                        start_time_sec=float(w.timestamp_ms.iloc[0] - frame.timestamp_ms.iloc[0]) / 1000,
                        qc_pass=keep, rejection_reasons="|".join(reasons),
                        gsr_nan_pct_before=100 * gsr_missing, gsr_missing_fraction_after=unresolved,
                        gsr_interpolated_fraction=float(w.gsr_interpolated.mean()),
                        gsr_flat=bool(unresolved == 0 and np.ptp(w.gsr_repaired) < 1e-10),
                        gsr_nonpositive_fraction=nonpositive, gsr_adc_rail_fraction=adc_rail,
                        ppg_status=ppg_status, ppg_bad_fraction_before=ppg_bad,
                        ppg_interpolated_fraction=float(w.ppg_interpolated.mean()),
                        ppg_outlier_fraction=float(w.ppg_outlier_raw.mean()), ppg_rail_fraction=float(w.ppg_rail_raw.mean()),
                        ppg_rr_rejected_fraction=rr_fraction, ppg_high_motion_fraction=float(w.ppg_high_motion.mean()),
                        severe_motion_fraction=motion, gyro_missing_fraction=float(w.gyro_magnitude.isna().mean()),
                        ppg_dc_median=float(w.ppg.median()), ppg_raw_span=float(w.ppg.max() - w.ppg.min()))
            for key, value in estimated.items():
                meta["diagnostic_" + key] = value
            windows.append(meta)
            if example is None and keep:
                example = {"raw": w, "gsr_clean": gc, "ppg_clean": pc,
                           "file": row["file"], "device_source": row["device_source"],
                           "recording_id": row["recording_id"], "window_id": meta["window_id"]}
    qc.update(candidate_windows=len(windows), accepted_windows=sum(w["qc_pass"] for w in windows),
              ppg_available_windows=sum(w["qc_pass"] and w["ppg_available"] == 1 for w in windows),
              samples_in_full_candidates=int(candidate_covered.sum()), samples_in_accepted_windows=int(covered.sum()),
              samples_outside_full_windows=int((~candidate_covered).sum()), gsr_interpolated_samples=repaired_total,
              ppg_outlier_samples=outlier_total, ppg_rail_samples=ppg_rail_total)
    qc["rejected_windows"] = qc["candidate_windows"] - qc["accepted_windows"]
    qc["window_pass_pct"] = 100 * qc["accepted_windows"] / qc["candidate_windows"] if qc["candidate_windows"] else 0.0
    qc["sample_coverage_pass_pct"] = 100 * qc["samples_in_accepted_windows"] / len(frame) if len(frame) else 0
    excluded = []
    if not row["label_valid"]:
        excluded.append("no_valid_regression_label")
    if not row["identity_resolved"]:
        excluded.append("unresolved_subject_identity")
    if not qc["accepted_windows"]:
        excluded.append("no_accepted_full_windows")
    qc["exclusion_reason"] = "|".join(excluded)
    qc["sampling_rate_flag"] = ("median_rate_outside_1pct_nominal" if not np.isfinite(qc["fs_median_hz"]) or abs(qc["fs_median_hz"] - config.fs) > .01 * config.fs else "nominal_median_rate")
    qc["short_runs_not_filtered"] = sum(b - a < size for a, b in segments)
    return windows, qc, example


def extract_datasets(manifest, config=Config(), workers=3):
    start = time.monotonic()
    all_windows, qc_rows, examples = [], [], {}
    # Per-file cache contains a code/config signature AND source hash. First run computes everything.
    extraction_source = "\n".join(inspect.getsource(f) for f in [runs, repair_short_gaps, load_sehat, timing_audit, preprocess_run, gsr_features, process_file])
    code_hash = sha256((extraction_source + file_hash(config.root / "ppg_preprocessing.py") + json.dumps(asdict(config), sort_keys=True)).encode()).hexdigest()
    pending = []
    for row in manifest.to_dict("records"):
        key = sha256(row["recording_id"].encode()).hexdigest()[:24]
        cache = config.out / "cache" / f"{key}.joblib"
        metadata_hash = sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
        if cache.exists():
            stored = joblib.load(cache)
            if stored["signature"] == code_hash and stored.get("metadata_hash") == metadata_hash and stored["raw_hash"] == file_hash(row["path"]):
                result = stored["result"]
                all_windows.extend(result[0]); qc_rows.append(result[1])
                if result[2] is not None:
                    examples.setdefault(row["device_source"], result[2])
                continue
        pending.append((row, cache))
    print(f"Feature extraction: {len(pending)} raw files to process; {len(qc_rows)} verified caches", flush=True)
    def consume(result, row, cache):
        all_windows.extend(result[0]); qc_rows.append(result[1])
        if result[2] is not None:
            # Deterministic example selection independent of process completion order.
            device = row["device_source"]
            if device not in examples or row["file"] < examples[device]["file"]:
                examples[device] = result[2]
        joblib.dump(dict(signature=code_hash, metadata_hash=sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest(), raw_hash=result[1]["raw_sha256"], result=result), cache, compress=3)
        n = len(qc_rows)
        print(f"[{n}/{len(manifest)}] {row['device_source']} {row['file']}: {result[1]['accepted_windows']}/{result[1]['candidate_windows']} windows, {time.monotonic() - start:.0f}s", flush=True)
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_file, row, config): (row, cache) for row, cache in pending}
            for future in as_completed(futures):
                row, cache = futures[future]
                consume(future.result(), row, cache)
    else:
        for row, cache in pending:
            consume(process_file(row, config), row, cache)
    windows = pd.DataFrame(all_windows).sort_values(["device_source", "recording_id", "window_start_sample"]).reset_index(drop=True)
    qc = pd.DataFrame(qc_rows).sort_values(["device_source", "file"]).reset_index(drop=True)
    manifest["raw_sha256"] = manifest.recording_id.map(qc.set_index("recording_id").raw_sha256)
    manifest.to_csv(config.out / "dataset_manifest.csv", index=False)
    windows["training_eligible"] = windows.qc_pass & windows.training_record_eligible
    assert not windows.duplicated(["recording_id", "window_id"]).any()
    assert windows.window_samples.eq(round(config.fs * config.window_sec)).all()
    assert windows.loc[windows.ppg_available.eq(0), PPG_FEATURES].isna().all().all()
    windows.to_csv(config.out / "window_quality_control.csv", index=False)
    qc.to_csv(config.out / "quality_control_per_file.csv", index=False)
    for domain in ["Shimmer", "SEHAT"]:
        windows.loc[windows.device_source.eq(domain) & windows.training_eligible].to_csv(config.out / f"features_{domain.lower()}.csv", index=False)
    usable = windows.loc[windows.training_eligible].copy().reset_index(drop=True)
    usable.to_csv(config.out / "features_hybrid.csv", index=False)
    for grouping, filename in [(["device_source", "subject_id"], "quality_control_per_subject.csv"), (["device_source"], "quality_control_per_domain.csv")]:
        summary = qc.groupby(grouping).agg(files=("file", "size"), subjects=("subject_id", "nunique"), sessions=("session_id", "nunique"),
                    labeled_records=("label_valid", "sum"), samples=("samples", "sum"), candidate_windows=("candidate_windows", "sum"),
                    accepted_windows=("accepted_windows", "sum"), rejected_windows=("rejected_windows", "sum"),
                    ppg_available_windows=("ppg_available_windows", "sum"), samples_in_accepted_windows=("samples_in_accepted_windows", "sum"),
                    samples_outside_full_windows=("samples_outside_full_windows", "sum"), gsr_interpolated_samples=("gsr_interpolated_samples", "sum"))
        summary["window_pass_pct"] = 100 * summary.accepted_windows / summary.candidate_windows
        summary["sample_coverage_pass_pct"] = 100 * summary.samples_in_accepted_windows / summary.samples
        summary.to_csv(config.out / filename)
    rejected = windows.loc[~windows.qc_pass, ["device_source", "recording_id", "window_id", "rejection_reasons"]].copy()
    rejected.to_csv(config.out / "audit/rejected_windows.csv", index=False)
    qc.loc[qc.exclusion_reason.ne("")].to_csv(config.out / "audit/excluded_recordings.csv", index=False)
    joblib.dump(examples, config.out / "audit/signal_examples.joblib", compress=3)
    print(f"Extraction complete in {(time.monotonic() - start) / 60:.2f} minutes; {len(usable)} labeled QC-pass windows", flush=True)
    return windows, usable, qc, examples


def balanced_weights(train):
    """Equal domain -> subject -> recording mass, then equal window mass."""
    domain_subjects = train.groupby("device_source").subject_id.nunique()
    recordings = train.groupby(["device_source", "subject_id"]).recording_id.nunique()
    counts = train.groupby("recording_id").size()
    n, domains = len(train), train.device_source.nunique()
    weights = np.array([n / (domains * domain_subjects[r.device_source] * recordings.loc[(r.device_source, r.subject_id)] * counts[r.recording_id]) for r in train.itertuples()])
    check = train[["device_source", "subject_id", "recording_id"]].assign(weight=weights)
    assert np.allclose(check.groupby("device_source").weight.sum(), n / domains)
    for _, group in check.groupby("device_source"):
        assert np.allclose(group.groupby("subject_id").weight.sum(), group.weight.sum() / group.subject_id.nunique())
        for _, person in group.groupby("subject_id"):
            assert np.allclose(person.groupby("recording_id").weight.sum(), person.weight.sum() / person.recording_id.nunique())
    return weights


def make_pipeline(config):
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("model", ExtraTreesRegressor(n_estimators=config.n_estimators, max_depth=config.max_depth,
                                    min_samples_leaf=config.min_samples_leaf, random_state=config.random_state, n_jobs=-1)),
    ])


def fit_model(train, model_name, config):
    pipeline = make_pipeline(config)
    kwargs = {"model__sample_weight": balanced_weights(train)} if model_name == MODELS[2] else {}
    pipeline.fit(train[FEATURES], train.fasting_duration_hr, **kwargs)
    assert pipeline.named_steps["imputer"].transform(train[FEATURES].iloc[:1]).shape[1] == 9
    return pipeline


def metrics(data):
    return dict(n_recordings=len(data), MAE_hr=float(mean_absolute_error(data.y_true, data.y_pred)),
                RMSE_hr=float(np.sqrt(mean_squared_error(data.y_true, data.y_pred))),
                R2=float(r2_score(data.y_true, data.y_pred)) if len(data) >= 3 and np.var(data.y_true) > 1e-10 else np.nan,
                target_min_hr=float(data.y_true.min()), target_max_hr=float(data.y_true.max()))


def train_selection(data, model_name, held_out=None):
    if model_name == MODELS[0]:
        train = data.loc[data.device_source.eq("Shimmer")]
    elif model_name == MODELS[3]:
        train = data.loc[data.device_source.eq("SEHAT")]
    else:
        train = data
    if held_out is not None:
        train = train.loc[train.subject_id.ne(held_out)]
    return train.copy().reset_index(drop=True)


def evaluate(data, config=Config()):
    sehat = data.loc[data.device_source.eq("SEHAT")].copy()
    assert sehat.subject_id.nunique() >= 3
    assert data.groupby("recording_id").fasting_duration_hr.nunique().eq(1).all()
    predictions, folds, weight_audit, preprocess_audit = [], [], [], []
    for fold, subject in enumerate(sorted(sehat.subject_id.unique()), 1):
        test = sehat.loc[sehat.subject_id.eq(subject)].reset_index(drop=True)
        for model_name in MODELS:
            train = train_selection(data, model_name, subject)
            assert subject not in set(train.subject_id)
            assert set(train.recording_id).isdisjoint(test.recording_id)
            assert set(FEATURES).isdisjoint(["device_source", "subject_id", "recording_id", "window_id", "fasting_duration_hr", "record_time", "last_drink_time", "session_id"])
            pipeline = fit_model(train, model_name, config)
            pred = pipeline.predict(test[FEATURES])
            assert np.isfinite(pred).all()
            output = test[["subject_id", "session_id", "raw_session_id", "recording_id", "window_id", "file", "record_time", "last_drink_time", "ppg_available", "fasting_duration_hr"]].copy()
            output = output.rename(columns={"fasting_duration_hr": "y_true"})
            output["model"] = model_name
            output["fold"] = fold
            output["y_pred"] = pred
            predictions.append(output)
            joblib.dump(pipeline, config.out / "models" / f"fold_{subject}_{model_name}.joblib", compress=3)
            folds.append(dict(fold=fold, test_subject=subject, model=model_name, train_windows=len(train),
                              train_subjects="|".join(sorted(train.subject_id.unique())), train_recordings=train.recording_id.nunique(),
                              shimmer_train_windows=int(train.device_source.eq("Shimmer").sum()), sehat_train_windows=int(train.device_source.eq("SEHAT").sum()),
                              test_windows=len(test), test_recordings=test.recording_id.nunique(),
                              train_ppg_available=float(train.ppg_available.mean()), test_ppg_available=float(test.ppg_available.mean()),
                              train_target_min=float(train.fasting_duration_hr.min()), train_target_max=float(train.fasting_duration_hr.max()),
                              test_target_min=float(test.fasting_duration_hr.min()), test_target_max=float(test.fasting_duration_hr.max()),
                              window_MAE_hr=float(mean_absolute_error(test.fasting_duration_hr, pred))))
            preprocess_audit.extend(dict(fold=fold, test_subject=subject, model=model_name, feature=f, train_median=float(v),
                                         train_nonmissing=int(train[f].notna().sum())) for f, v in zip(FEATURES, pipeline.named_steps["imputer"].statistics_))
            if model_name == MODELS[2]:
                wa = train[["device_source", "subject_id", "recording_id"]].assign(weight=balanced_weights(train))
                wa = wa.groupby(["device_source", "subject_id", "recording_id"]).agg(windows=("weight", "size"), total_weight=("weight", "sum")).reset_index()
                wa["fold"] = fold
                wa["test_subject"] = subject
                weight_audit.append(wa)
        print(f"LOSO fold {fold}: {subject}, {test.recording_id.nunique()} test recordings, {len(test)} identical test windows for A/B/C/D", flush=True)
    oof = pd.concat(predictions, ignore_index=True)
    keys = ["subject_id", "recording_id", "window_id", "y_true"]
    reference = oof.loc[oof.model.eq(MODELS[0]), keys].reset_index(drop=True)
    for model_name in MODELS:
        pd.testing.assert_frame_equal(reference, oof.loc[oof.model.eq(model_name), keys].reset_index(drop=True))
    by_record = oof.groupby(["model", "fold", "subject_id", "session_id", "raw_session_id", "recording_id", "file"], as_index=False).agg(
        y_true=("y_true", "first"), y_pred=("y_pred", "mean"), windows=("window_id", "size"), ppg_available_fraction=("ppg_available", "mean"))
    by_record["residual_hr"] = by_record.y_pred - by_record.y_true
    by_record["absolute_error_hr"] = by_record.residual_hr.abs()
    per_subject = pd.DataFrame([dict(model=model_name, subject_id=subject, **metrics(group)) for (model_name, subject), group in by_record.groupby(["model", "subject_id"])])
    summary = pd.DataFrame([dict(model=model_name, **metrics(group),
                                macro_subject_MAE_hr=float(per_subject.loc[per_subject.model.eq(model_name), "MAE_hr"].mean()))
                            for model_name, group in by_record.groupby("model")])
    oof.to_csv(config.out / "oof_predictions_windows.csv", index=False)
    by_record.to_csv(config.out / "oof_predictions_recordings.csv", index=False)
    per_subject.to_csv(config.out / "evaluation_per_subject.csv", index=False)
    summary.to_csv(config.out / "evaluation_models.csv", index=False)
    pd.DataFrame(folds).to_csv(config.out / "audit/fold_manifest.csv", index=False)
    pd.DataFrame(preprocess_audit).to_csv(config.out / "audit/fold_imputation_statistics.csv", index=False)
    pd.concat(weight_audit, ignore_index=True).to_csv(config.out / "audit/fold_training_weights.csv", index=False)
    # Model choice is exploratory: these same LOSO folds choose the winner.
    best_name = str(summary.sort_values(["MAE_hr", "RMSE_hr", "model"]).iloc[0].model)
    train = train_selection(data, best_name)
    best = fit_model(train, best_name, config)
    joblib.dump(best, config.out / "models/best_model_pipeline.joblib", compress=3)
    np.testing.assert_allclose(best.predict(sehat[FEATURES].iloc[:3]), joblib.load(config.out / "models/best_model_pipeline.joblib").predict(sehat[FEATURES].iloc[:3]))
    write_json(config.out / "models/inference_contract.json", {
        "selected_model": best_name, "selection": "lowest pooled recording-level LOSO MAE (exploratory; no independent final test)",
        "training_recordings": train.recording_id.nunique(), "training_windows": len(train),
        "features_in_order": FEATURES, "units": ["uS", "uS^2", "nats", "beats/min", "ms", "ms", "percent", "count/30sec", "binary"],
        "imputation_medians": dict(zip(FEATURES, best.named_steps["imputer"].statistics_.tolist())),
        "ppg_unavailable": "All five PPG features NaN, ppg_available=0; replace NaNs with these frozen training medians.",
        "scaling": "none", "personal_statistics_required": False, "log1p": False,
        "output": "proxy duration hours, not a validated hydration measure", "raw_signal_preprocessing": "hybrid_retraining.py + config.json",
        "firmware_export": "not performed; feature parity with embedded peak detector must be established first"})
    print(summary.to_string(index=False), flush=True)
    print("Selected exploratory model:", best_name, flush=True)
    return oof, by_record, per_subject, summary, best_name


def plot_signals(examples, config=Config()):
    for device, example in examples.items():
        w = example["raw"]
        t = (w.timestamp_ms.to_numpy() - w.timestamp_ms.iloc[0]) / 1000
        raw = w.ppg.to_numpy(float)
        fig, axes = plt.subplots(5, 1, figsize=(12, 12), sharex=True)
        axes[0].plot(t, raw, lw=0.65, color="0.4")
        axes[0].set_ylabel("PPG mV" if device == "Shimmer" else "PPG IR counts")
        axes[0].set_title(f"{device}: {example['file']} — raw DC and filtered AC shown separately")
        axes[1].plot(t, raw - np.nanmedian(raw), lw=0.5, alpha=.5, label="Raw, DC removed for display")
        axes[1].plot(t, example["ppg_clean"], lw=1, label="Filtered PPG")
        axes[1].set_ylabel("PPG AC")
        low, high = np.nanquantile(raw - np.nanmedian(raw), [.01, .99])
        margin = max((high - low) * .15, 1e-6)
        axes[1].set_ylim(low - margin, high + margin)
        axes[1].set_title("AC zoom (1–99% raw range); startup extremes remain visible in the top panel", fontsize=9)
        axes[1].legend(loc="upper right")
        axes[2].plot(t, example["ppg_clean"], lw=.8, color="#007d8a")
        axes[2].set_ylabel("Filtered PPG AC")
        axes[2].set_title("Filtered pulse waveform on its own amplitude scale", fontsize=9)
        axes[3].plot(t, w.gsr, alpha=.6, lw=.7, label="Raw (gaps preserved)")
        axes[3].plot(t, example["gsr_clean"], lw=1, label="Short gaps repaired + 1 Hz low-pass")
        axes[3].set_ylabel("GSR (uS)")
        axes[3].legend(loc="upper right")
        axes[4].plot(t, w.gyro_magnitude, color="#8856a7", lw=.7)
        axes[4].set_ylabel("Gyro (deg/s)")
        axes[4].set_xlabel("Seconds within full 30 s window")
        for ax in axes:
            ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(config.out / f"figures/signals_{device.lower()}.png", dpi=160)
        plt.close(fig)


def plot_evaluation(data, records, per_subject, summary, config=Config()):
    colors = ["#4575b4", "#fdae61", "#1a9850", "#984ea3"]
    fig, axes = plt.subplots(2, 2, figsize=(11, 9), sharex=True, sharey=True)
    for ax, name, color in zip(axes.flat, MODELS, colors):
        g = records.loc[records.model.eq(name)]
        for subject, person in g.groupby("subject_id"):
            ax.scatter(person.y_true, person.y_pred, s=50, label=subject)
        high = max(records.y_true.max(), records.y_pred.max()) + .5
        ax.plot([0, high], [0, high], "--", color="0.5", lw=1)
        row = summary.loc[summary.model.eq(name)].iloc[0]
        ax.set_title(f"{name}: MAE={row.MAE_hr:.3f} h, R²={row.R2:.3f}")
        ax.set_xlabel("Actual duration (h)"); ax.set_ylabel("Mean OOF prediction (h)")
        ax.grid(alpha=.2)
    axes.flat[0].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(config.out / "figures/actual_vs_predicted.png", dpi=170); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    subjects = sorted(records.subject_id.unique())
    for k, (name, color) in enumerate(zip(MODELS, colors)):
        g = records.loc[records.model.eq(name)]
        x = np.array([subjects.index(s) for s in g.subject_id]) + (k - 1.5) * .15
        axes[0].scatter(x, g.residual_hr, color=color, label=name, s=30)
    axes[0].axhline(0, color="0.4", ls="--"); axes[0].set_xticks(range(len(subjects)), subjects)
    axes[0].set_ylabel("Prediction − actual (h), one point / recording")
    axes[0].legend(fontsize=7)
    pivot = per_subject.pivot(index="subject_id", columns="model", values="MAE_hr")[MODELS]
    pivot.plot.bar(ax=axes[1], color=colors, rot=0)
    axes[1].set_ylabel("Recording-level MAE (h)"); axes[1].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(config.out / "figures/errors_per_subject.png", dpi=170); plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    ordered = summary.set_index("model").loc[MODELS]
    for ax, metric in zip(axes, ["MAE_hr", "RMSE_hr", "R2"]):
        ax.bar(list("ABCD"), ordered[metric], color=colors)
        ax.axhline(0, color="0.5", lw=.6)
        ax.set_title(metric); ax.grid(axis="y", alpha=.2)
    fig.suptitle("Same SEHAT LOSO test recordings; A=Shimmer, B=hybrid, C=weighted hybrid, D=SEHAT")
    fig.tight_layout(); fig.savefig(config.out / "figures/model_comparison.png", dpi=170); plt.close(fig)
    # One median per recording reduces visual dominance by very long Shimmer files.
    record_features = data.groupby(["device_source", "recording_id"])[FEATURES].median().reset_index()
    record_features.to_csv(config.out / "feature_distributions_per_recording.csv", index=False)
    fig, axes = plt.subplots(3, 3, figsize=(12, 10))
    descriptive = []
    for ax, feature in zip(axes.flat, FEATURES):
        arrays = [record_features.loc[record_features.device_source.eq(d), feature].dropna().to_numpy() for d in ["Shimmer", "SEHAT"]]
        ax.boxplot(arrays, tick_labels=["Shimmer", "SEHAT"], showfliers=True)
        if feature in ("gsr_mean", "gsr_var"):
            ax.set_yscale("symlog", linthresh=.001)
        ax.set_title(feature + (" (display symlog)" if feature in ("gsr_mean", "gsr_var") else ""))
        ax.grid(axis="y", alpha=.2)
        for d, array in zip(["Shimmer", "SEHAT"], arrays):
            if len(array):
                descriptive.append(dict(device_source=d, feature=feature, n_recordings=len(array), min=float(np.min(array)),
                        q25=float(np.quantile(array, .25)), median=float(np.median(array)), q75=float(np.quantile(array, .75)), max=float(np.max(array))))
    fig.suptitle("Median of QC-pass labeled windows per recording; physical features fed to model without log")
    fig.tight_layout(); fig.savefig(config.out / "figures/feature_distributions.png", dpi=170); plt.close(fig)
    pd.DataFrame(descriptive).to_csv(config.out / "feature_distribution_statistics.csv", index=False)
    return record_features


def sensor_sensitivity(manifest, windows, config=Config()):
    """Target-independent diagnostics, not preprocessing selection on test scores."""
    from dataclasses import replace
    rows, gsr_rows = [], []
    for row in manifest.loc[manifest.device_source.eq("SEHAT")].to_dict("records"):
        frame = load_sehat(row["path"])
        segments, _ = timing_audit(frame, config)
        baseline = windows.loc[windows.recording_id.eq(row["recording_id"])].set_index("window_start_sample")
        for a, b in segments:
            section = frame.iloc[a:b]
            if len(section) < round(config.fs * config.window_sec):
                continue
            original = preprocess_run(section, "SEHAT", config)
            t = np.arange(len(section)) / config.fs
            # These are reconstructions of stored data, not the original MAX30102 FIFO stream.
            t50 = np.arange(0, t[-1] + 1e-8, 1 / 50)
            fifty = pd.DataFrame({col: np.interp(t50, t, section[col]) for col in ["ppg", "gsr", "gyro_x", "gyro_y", "gyro_z"]})
            fifty["timestamp_ms"] = t50 * 1000
            filtered50 = preprocess_run(fifty, "SEHAT", replace(config, fs=50.0))
            back = pd.DataFrame({col: np.interp(t, t50, fifty[col]) for col in ["ppg", "gsr", "gyro_x", "gyro_y", "gyro_z"]})
            back["timestamp_ms"] = t * 1000
            filtered_back = preprocess_run(back, "SEHAT", config)
            for local in range(0, len(section) - 1536 + 1, 768):
                if a + local not in baseline.index:
                    continue
                reference = baseline.loc[a + local]
                raw_gsr = original.gsr_repaired.iloc[local:local + 1536].to_numpy()
                if np.isfinite(raw_gsr).all():
                    b1, a1 = butter(2, 1, fs=config.fs)
                    b2, a2 = butter(2, 2, fs=config.fs)
                    c1, c2 = filtfilt(b1, a1, raw_gsr), filtfilt(b2, a2, raw_gsr)
                    gsr_rows.append(dict(recording_id=row["recording_id"], subject_id=row["subject_id"], window_id=reference.window_id,
                        raw_mean=float(np.mean(raw_gsr)), filtered1_mean=float(np.mean(c1)), filtered2_mean=float(np.mean(c2)),
                        raw_variance=float(np.var(raw_gsr)), filtered1_variance=float(np.var(c1)), filtered2_variance=float(np.var(c2))))
                starts = [local, int(round(local / config.fs * 50)), local]
                for method, fs, source, start in zip(["stored_51.2", "reconstructed_50", "roundtrip_51.2"], [51.2, 50., 51.2], [original, filtered50, filtered_back], starts):
                    w = source.iloc[start:start + round(30 * fs)]
                    if len(w) != round(30 * fs):
                        continue
                    feat = extract_ppg_features(w.ppg_clean.to_numpy(), fs=fs, preprocessed=True)
                    good = feat["ppg_quality_ok"] and w.ppg_bad_raw.mean() <= config.max_ppg_bad_fraction and w.severe_motion.mean() <= config.max_severe_motion_fraction
                    rows.append(dict(recording_id=row["recording_id"], subject_id=row["subject_id"], window_id=reference.window_id,
                                     method=method, available=bool(good), status=feat["ppg_status"],
                                     **{k: feat[k] for k in PPG_FEATURES}))
    sensitivity = pd.DataFrame(rows)
    sensitivity.to_csv(config.out / "audit/ppg_resampling_sensitivity.csv", index=False)
    comparisons = []
    base = sensitivity.loc[sensitivity.method.eq("stored_51.2")].set_index(["recording_id", "window_id"])
    for method, group in sensitivity.loc[~sensitivity.method.eq("stored_51.2")].groupby("method"):
        comp = group.set_index(["recording_id", "window_id"])
        paired = base.join(comp, lsuffix="_base", rsuffix="_other", how="inner")
        both = paired.loc[paired.available_base & paired.available_other]
        for f in PPG_FEATURES:
            dif = (both[f + "_other"] - both[f + "_base"]).abs().dropna()
            comparisons.append(dict(method=method, feature=f, paired_windows=len(paired), both_valid_windows=len(both),
                availability_disagreements=int((paired.available_base != paired.available_other).sum()),
                median_absolute_difference=float(dif.median()) if len(dif) else np.nan,
                max_absolute_difference=float(dif.max()) if len(dif) else np.nan))
    pd.DataFrame(comparisons).to_csv(config.out / "audit/ppg_resampling_summary.csv", index=False)
    gsr = pd.DataFrame(gsr_rows)
    gsr["variance_ratio_1hz_raw"] = gsr.filtered1_variance / gsr.raw_variance.replace(0, np.nan)
    gsr["variance_ratio_2hz_raw"] = gsr.filtered2_variance / gsr.raw_variance.replace(0, np.nan)
    gsr["absolute_mean_shift_1hz"] = (gsr.filtered1_mean - gsr.raw_mean).abs()
    gsr.to_csv(config.out / "audit/gsr_filter_sensitivity.csv", index=False)
    synthetic_resampling(config)
    return pd.DataFrame(comparisons), gsr


def synthetic_resampling(config=Config()):
    rng = np.random.default_rng(42)
    rows = []
    for rhythm in ["constant_RR", "variable_RR"]:
        intervals = np.full(130, .8) if rhythm == "constant_RR" else rng.uniform(.69, .91, 130)
        beat_times = np.cumsum(intervals)
        beat_times = beat_times[beat_times < 89]
        for phase in (0., 1 / 150, 2 / 150):
            t50 = np.arange(0, 90, 1 / 50) + phase
            raw50 = 100000 + 1500 * np.sin(2 * np.pi * .15 * t50)
            for beat in beat_times:
                raw50 += 2500 * np.exp(-.5 * ((t50 - beat) / .075) ** 2)
            t512 = np.arange(t50[0], t50[-1], 1 / 51.2)
            raw512 = np.interp(t512, t50, raw50)
            for name, fs, raw in [("known_native_50", 50., raw50), ("linear_50_to_51.2", 51.2, raw512)]:
                cleaned = preprocess_ppg(raw, np.zeros(len(raw)), np.zeros(len(raw)), np.zeros(len(raw)), fs=fs).cleaned
                for start_sec in (0, 15, 30, 45):
                    a, b = round(start_sec * fs), round((start_sec + 30) * fs)
                    features = extract_ppg_features(cleaned[a:b], fs=fs, preprocessed=True)
                    beats = beat_times[(beat_times >= phase + start_sec) & (beat_times < phase + start_sec + 30)]
                    rr = np.diff(beats) * 1000
                    entry = dict(method=name, rhythm=rhythm, sample_phase_sec=phase, start_sec=start_sec,
                                 available=features["ppg_quality_ok"], true_mean_hr=60000 / np.mean(rr),
                                 true_rmssd=np.sqrt(np.mean(np.diff(rr) ** 2)), true_sdnn=np.std(rr),
                                 true_pnn50=100 * np.mean(np.abs(np.diff(rr)) > 50), true_n_peaks=len(beats),
                                 **{k: features[k] for k in PPG_FEATURES})
                    for f in PPG_FEATURES:
                        entry["absolute_error_" + f] = abs(entry[f] - entry["true_" + f])
                    rows.append(entry)
    pd.DataFrame(rows).to_csv(config.out / "audit/ppg_synthetic_known_beats.csv", index=False)


def auxiliary_evaluation(data, records, per_subject, config=Config()):
    """Reference constant predictors and subject-level paired uncertainty."""
    sehat = data.loc[data.device_source.eq("SEHAT")]
    record_data = data.drop_duplicates("recording_id")
    constant_rows = []
    for subject in sorted(sehat.subject_id.unique()):
        test = record_data.loc[record_data.device_source.eq("SEHAT") & record_data.subject_id.eq(subject)]
        for domain, train in [("Shimmer", record_data.loc[record_data.device_source.eq("Shimmer")]),
                              ("SEHAT_train", record_data.loc[record_data.device_source.eq("SEHAT") & record_data.subject_id.ne(subject)])]:
            for agg in ["mean", "median"]:
                for r in test.itertuples():
                    constant_rows.append(dict(model=f"constant_{domain}_record_{agg}", subject_id=subject, recording_id=r.recording_id,
                                              y_true=r.fasting_duration_hr, y_pred=float(train.fasting_duration_hr.agg(agg))))
    constants = pd.DataFrame(constant_rows)
    constants.to_csv(config.out / "audit/constant_baseline_predictions.csv", index=False)
    pd.DataFrame([dict(model=n, **metrics(g)) for n, g in constants.groupby("model")]).to_csv(config.out / "audit/constant_baseline_metrics.csv", index=False)
    pivot = per_subject.pivot(index="subject_id", columns="model", values="MAE_hr")
    rng = np.random.default_rng(42)
    indexes = rng.integers(0, len(pivot), size=(10000, len(pivot)))
    rows = []
    for name in MODELS[1:]:
        delta = (pivot[name] - pivot[MODELS[0]]).to_numpy()
        boot = delta[indexes].mean(axis=1)
        rows.append(dict(model=name, contrast="model minus A; macro subject MAE, hours", subjects=len(pivot),
                         delta_macro_MAE_hr=float(delta.mean()), lower95=float(np.quantile(boot, .025)), upper95=float(np.quantile(boot, .975)),
                         subjects_improved=int((delta < 0).sum()), bootstrap_replicates=10000,
                         caution="exploratory five-subject bootstrap, not confirmatory; correlated sessions retained together"))
    uncertainty = pd.DataFrame(rows)
    uncertainty.to_csv(config.out / "audit/paired_subject_bootstrap.csv", index=False)
    # Influence diagnostic: exclude each test recording from aggregation only;
    # the OOF models are NOT retrained, and the primary evaluation is unchanged.
    influence = []
    for excluded in records.recording_id.unique():
        subset = records.loc[records.recording_id.ne(excluded)]
        for model_name, group in subset.groupby("model"):
            influence.append(dict(excluded_test_recording=excluded, model=model_name, **metrics(group),
                                  interpretation="fixed OOF predictions; aggregation influence only, no retraining"))
    pd.DataFrame(influence).to_csv(config.out / "audit/leave_one_test_recording_out_influence.csv", index=False)
    return uncertainty


def validate_results(manifest, windows, data, records, summary, config=Config()):
    assert len(manifest) == manifest.recording_id.nunique()
    assert windows.loc[windows.qc_pass, ["gsr_mean", "gsr_var", "gsr_entropy"]].notna().all().all()
    assert windows.window_duration_sec.eq(30).all()
    assert not data.duplicated(["recording_id", "window_id"]).any()
    assert data.loc[data.ppg_available.eq(0), PPG_FEATURES].isna().all().all()
    assert data.fasting_duration_hr.ge(0).all()
    assert np.isfinite(data.fasting_duration_hr).all()
    assert qc_signal_hashes_unique(config)
    assert set(summary.model) == set(MODELS)
    n = data.loc[data.device_source.eq("SEHAT"), "recording_id"].nunique()
    assert records.groupby("model").size().eq(n).all()
    assert records.groupby(["model", "recording_id"]).size().eq(1).all()
    folds = pd.read_csv(config.out / "audit/fold_manifest.csv")
    assert all(r.test_subject not in r.train_subjects.split("|") for r in folds.itertuples())
    bad_subject = manifest.loc[manifest.file.eq("20261107130818_S16_S16_F02_raw.csv")].iloc[0]
    assert bad_subject.subject_id == "S16" and bad_subject.raw_subject_id == "S15"
    f05 = manifest.loc[manifest.file.str.contains("S13_S13_F05")].iloc[0]
    assert f05.session_id == "S13_F05" and f05.raw_session_id == "S13_F04"
    assert f05.recording_id in set(data.recording_id)
    # Verify gap behavior with a meaningful adversarial example.
    x = np.r_[np.nan, 2., np.full(3, np.nan), 6., np.full(13, np.nan), 9., np.nan]
    repaired, mask = repair_short_gaps(x, 51.2, .25)
    assert np.isnan(repaired[0]) and np.isnan(repaired[-1])
    assert np.isfinite(repaired[2:5]).all() and np.isnan(repaired[6:19]).all() and mask.sum() == 3
    raw_check = pd.DataFrame(dict(ppg=np.r_[0., np.full(31, 100000.)], gsr=np.r_[np.nan, np.full(31, 2.)],
                                 gyro_x=np.zeros(32), gyro_y=np.zeros(32), gyro_z=np.zeros(32)))
    cleaned_check = preprocess_run(raw_check, "SEHAT", config)
    np.testing.assert_equal(cleaned_check.ppg.to_numpy(), raw_check.ppg.to_numpy())
    np.testing.assert_equal(cleaned_check.gsr.to_numpy(), raw_check.gsr.to_numpy())
    # Recompute every reported primary metric directly from saved predictions.
    saved = pd.read_csv(config.out / "oof_predictions_recordings.csv")
    for r in summary.itertuples():
        recomputed = metrics(saved.loc[saved.model.eq(r.model)])
        np.testing.assert_allclose([r.MAE_hr, r.RMSE_hr, r.R2], [recomputed["MAE_hr"], recomputed["RMSE_hr"], recomputed["R2"]])
    # Fresh-test perturbation cannot change training medians; saved objects use only nine inputs.
    for subject in folds.test_subject.unique():
        for model_name in MODELS:
            pipeline = joblib.load(config.out / "models" / f"fold_{subject}_{model_name}.joblib")
            train = train_selection(data, model_name, subject)
            check = SimpleImputer(strategy="median", keep_empty_features=True).fit(train[FEATURES])
            np.testing.assert_allclose(pipeline.named_steps["imputer"].statistics_, check.statistics_)
            assert pipeline.named_steps["model"].n_features_in_ == 9
    # Ensure raw data did not change across the experiment.
    file_qc = pd.read_csv(config.out / "quality_control_per_file.csv").set_index("recording_id")
    for r in manifest.itertuples():
        assert file_hash(r.path) == file_qc.loc[r.recording_id, "raw_sha256"], f"Raw modified: {r.file}"
    validation = dict(passed=True, raw_files_verified=len(manifest), model_folds_verified=len(folds),
                      same_test_recordings_per_model=n, feature_count=9, tests=[
                          "full windows only", "no train/test subject or recording leakage", "identical A/B/C/D test rows",
                          "frozen train-only imputation", "hierarchical weight mass", "gap boundaries and long gap retention",
                          "metadata override provenance", "F05 retained", "serialized model prediction roundtrip",
                          "metrics recomputed from CSV", "raw SHA256 unchanged"])
    write_json(config.out / "validation.json", validation)
    print("Validation passed:", validation, flush=True)
    return validation


def qc_signal_hashes_unique(config):
    qc = pd.read_csv(config.out / "quality_control_per_file.csv")
    return not qc.loc[qc.device_source.eq("SEHAT"), "signal_sha256"].duplicated().any()


def write_report(manifest, windows, data, qc, summary, per_subject, best_name, sensitivity, gsr_sensitivity, uncertainty, config=Config()):
    domain_qc = pd.read_csv(config.out / "quality_control_per_domain.csv")
    counts = data.groupby("device_source").agg(usable_recordings=("recording_id", "nunique"), usable_subjects=("subject_id", "nunique"), usable_windows=("window_id", "size")).reset_index()
    counts = domain_qc.merge(counts, on="device_source", how="left")
    counts.to_csv(config.out / "dataset_counts.csv", index=False)
    baseline = summary.loc[summary.model.eq(MODELS[0])].iloc[0]
    best = summary.loc[summary.model.eq(best_name)].iloc[0]
    improvement = baseline.MAE_hr - best.MAE_hr
    gains = {name: float(baseline.MAE_hr - summary.loc[summary.model.eq(name), "MAE_hr"].iloc[0]) for name in MODELS[1:3]}
    constants = pd.read_csv(config.out / "audit/constant_baseline_metrics.csv")
    constant_best = constants.sort_values("MAE_hr").iloc[0]
    gsr_record_med = data.groupby(["device_source", "recording_id"]).gsr_mean.median().groupby("device_source").median()
    min_shimmer = data.loc[data.device_source.eq("Shimmer"), "fasting_duration_hr"].min()
    se_targets = data.loc[data.device_source.eq("SEHAT")].drop_duplicates("recording_id").fasting_duration_hr
    gsr_stats = pd.read_csv(config.out / "feature_distribution_statistics.csv")
    report = ["# Eksperimen hybrid SEHAT — hasil aktual", "",
              "Eksperimen offline menggunakan ExtraTreesRegressor (35 trees, depth 8, min leaf 4, seed 42), tanpa tuning. Evaluasi Leave-One-SEHAT-Subject-Out: semua sesi subjek uji dikeluarkan dari training. Empat model memakai window uji yang identik. Prediksi window dirata-ratakan per rekaman; metrik utama memberi setiap rekaman bobot sama.", "",
              "## Data dan kualitas", "", counts.to_markdown(index=False) if importlib.util.find_spec("tabulate") else counts.to_string(index=False), "",
              "Jumlah CSV Shimmer mentah=124, tabel label fastingTimes=6 (total 130); SEHAT mentah=12. Angka tersebut diverifikasi pada manifest. QC dilakukan terhadap seluruh raw recording, termasuk Shimmer tanpa label; hanya label eksplisit yang valid masuk regresi.", "",
              "Persentase lolos dihitung dari kandidat window **penuh** di setiap continuous run. Sampel di tail/run pendek tidak diperlakukan sebagai window parsial; jumlahnya ada pada `samples_outside_full_windows`. Sample coverage menghitung gabungan indeks sampel window lolos, sehingga overlap tidak dihitung dua kali. Lolos kualitas sinyal tidak otomatis berarti memiliki label regresi.", "",
              "### Konflik metadata", "",
              "- `20261107130818_S16_S16_F02_raw.csv`: raw menyebut S15/S15_F02. Pengguna mengonfirmasi subjek sebenarnya **S16**; manifest memakai S16/S16_F02 dan mempertahankan raw_subject_id/raw_session_id serta alasan koreksi.",
              "- `20261112060931_S13_S13_F05_raw.csv`: raw menyebut session S13_F04. Rekaman **tetap dipakai** sebagai F05 dengan recording_id dari relative path dan timestamp; raw metadata tidak diubah.",
              "- Label Shimmer digabung exact pada (subject_id, RecordingTime), bukan timestamp lintas subjek atau nearest matching. Nonfasting tanpa label tidak diisi nol. Lihat `audit/excluded_recordings.csv` untuk seluruh pengecualian.", "",
              "## Preprocessing dan fitur", "",
              "Loader Shimmer mempertahankan header empat baris, PPG calibrated mV, GSR calibrated uS, serta device Timestamp_CAL. Timestamp sistem yang stuck bukan alasan otomatis menghapus file bila device timestamp valid. Loader SEHAT membaca IR counts, GSR uS, elapsed_us, dan gyro deg/s. Tidak ada penyamaan amplitudo PPG raw antarperangkat.", "",
              "Timestamp tidak diurutkan ulang atau dideduplikasi diam-diam: nilai nonfinite, nonpositive dt, dan penyimpangan dt >50% periode nominal memisahkan continuous run. FS median dan FS berdasarkan elapsed dicatat per file. Timestamp SEHAT adalah grid buatan firmware: fs nominal tepat bukan bukti clock MAX30102/FIFO atau waktu serial benar-benar bebas jitter.", "",
              "Beberapa file Shimmer memiliki sampling/timestamp tidak sesuai konfigurasi nominal; lihat `sampling_rate_flag`, `short_runs_not_filtered`, dan `samples_outside_full_windows`. Run yang lebih pendek dari 1536 sampel kontinu tidak difilter dan tidak menghasilkan window. Tidak mempercepat sinyal 0.2/10.24Hz seolah-olah 51.2Hz.", "",
              "GSR: NaN/Inf dicatat sebelum perbaikan; nilai <=0 ditandai invalid. Hanya gap internal <=0.25 s yang diinterpolasi, tanpa extrapolasi tepi atau melintasi putus timestamp. Window ditolak bila >5% raw missing, masih ada gap, >5% nonpositive, atau >5% ADC rail. Butterworth order 2 low-pass 1 Hz per window dipertahankan dari notebook lama; varians ddof=0, entropy histogram 10 bin log natural. Flat GSR positif ditandai, tidak otomatis ditolak karena belum ada bukti terpisah bahwa nilai konstan selalu artefak.", "",
              "PPG: high-pass .5 Hz order 4, gyro-adaptive low-pass 4/2.5 Hz, moving average .15 s; parameter utama helper lama dipertahankan. SEHAT menandai rail 0/262143 dan isolated spikes dengan Hampel .25 s, 8 MAD, minimal deviasi 2% baseline lokal; kemudian hanya gap <=.25 s diperbaiki. Tidak ada batas absolut kontak jari yang dipindahkan dari sensor lain. DC, span, flatline, outlier, rail dan RR rejection dilaporkan; kualitas kontak tidak dapat dipastikan tanpa ground truth.", "",
              "HeartPy memakai 40–180 bpm, quotient RR cleaning, high-precision 1000 Hz. Fitur PPG tersedia hanya saat lengkap dan RR rejected <=30%. PPG gagal: mean_hr/rmssd/sdnn/pnn50/n_peaks menjadi NaN dan ppg_available=0. Nilai diagnostik sebelum gating tetap tersimpan; n_peaks mengikuti total peaklist HeartPy, bukan jumlah RR yang lolos. pnn50 dalam %, rmssd/sdnn dalam ms. Gyro bukan predictor; >100 deg/s selama >20% window dianggap severe motion dan window ditolak. Threshold ini aturan engineering tetap sebelum fitting, bukan batas klinis atau hasil tuning skor test.", "",
              "Window 1536 sampel=30 s, hop768=15 s. Tidak ada partial window. PPG difilter per continuous run, GSR per window seperti referensi; definisi sembilan fitur sama, tetapi QC lebih ketat dan normalisasi berbeda dari notebook lama. A adalah Shimmer-only dengan pipeline baru yang konsisten, sehingga bukan reproduksi angka personal-zscore notebook lama.", "",
              "### Distribusi dan normalisasi", "", gsr_stats.loc[gsr_stats.feature.isin(FEATURES[:3])].to_string(index=False), "",
              "Tidak menggunakan personal z-score: subjek baru tidak membutuhkan histori. Tidak memakai log1p, karena transformasi nonlinear mengubah distribusi random thresholds ExtraTrees dan belum dievaluasi pada validasi terpisah. Statistik min/quartile tersedia pada CSV; grafik symlog hanya tampilan. GSR tetap dalam satuan fisik; konduktansi uS dari rangkaian berbeda belum berarti kalibrasinya setara. Median imputasi sembilan fitur hanya dari training fold; fitur yang seluruh training-nya missing memakai fallback0 dari SimpleImputer keep_empty_features=True. Flag ppg_available membedakan imputasi dan pengukuran. Tidak ada metadata, target, atau statistik personal test sebagai predictor.", "",
              f"Median lintas rekaman dari median gsr_mean: Shimmer={gsr_record_med.get('Shimmer', np.nan):.6f} uS, SEHAT={gsr_record_med.get('SEHAT', np.nan):.6f} uS. Sebanyak {int((se_targets < min_shimmer).sum())}/{len(se_targets)} label SEHAT berada di bawah label training Shimmer terkecil ({min_shimmer:.6f} jam). Model pohon Shimmer-only tidak dapat mengekstrapolasi prediksi di bawah rentang target training; perbaikan hybrid bisa mencerminkan kecocokan rentang target dan protokol, selain fitur sensor.", "",
              "## Hasil LOSO pada SEHAT", "", summary.to_string(index=False), "", per_subject.to_string(index=False), "",
              f"Model dengan MAE recording terkecil: **{best_name}**. MAE={best.MAE_hr:.6f} jam, RMSE={best.RMSE_hr:.6f} jam, R²={best.R2:.6f}. Selisih MAE terhadap A = {improvement:.6f} jam (positif berarti MAE berkurang).", "",
              f"Penambahan data SEHAT pada B mengubah MAE sebesar {-gains[MODELS[1]]:+.6f} jam terhadap A; C sebesar {-gains[MODELS[2]]:+.6f} jam (nilai negatif berarti lebih baik). Ini perbedaan aktual pada cohort ini, bukan bukti keunggulan umum hybrid atau penambahan informasi fisiologis yang kausal.", "",
              f"Baseline konstan terbaik menurut MAE: {constant_best.model}, MAE={constant_best.MAE_hr:.6f} jam. Model terpilih {'mengungguli' if best.MAE_hr < constant_best.MAE_hr else 'belum mengungguli'} baseline sederhana ini pada MAE; perbandingan ini penting sebelum menyimpulkan manfaat fitur fisiologis.", "",
              "B menyatukan semua window tanpa bobot. C menyeimbangkan total massa domain, lalu subjek dalam domain, rekaman dalam subjek, dan window dalam rekaman: w=N/(D*S_d*R_ds*n_dsr). Seluruh jumlah dihitung ulang dari training fold; imputasi median C tetap median training tanpa bobot agar preprocessing sama antararm. D hanya subjek SEHAT lain; datanya sangat kecil.", "",
              "R² per subjek hanya dihitung bila sedikitnya tiga rekaman dan variasi target memadai; fold dua rekaman diberi NaN. R² pooled tersedia tetapi sangat dipengaruhi rentang target sempit dan sedikit rekaman. Window beririsan bukan sampel independen.", "",
              "### Selisih per subjek dan ketidakpastian", "", uncertainty.to_string(index=False), "",
              "Bootstrap mengambil ulang lima subjek sebagai cluster, bukan window; interval tersebut deskriptif dan tidak membuktikan signifikansi atau generalisasi populasi. Pemilihan model terbaik memakai LOSO yang sama, sehingga estimasi terpilih bersifat eksploratif dan optimistis. Tidak ada klaim test final independen. Constant mean baselines training-only ada di `audit/constant_baseline_metrics.csv` untuk menilai manfaat dibanding prediksi durasi rata-rata sederhana.", "",
              "## Diagnostik sampling dan filter", "", sensitivity.to_string(index=False), "",
              "Data FIFO 50 Hz sebelum interpolasi tidak disimpan. Perbandingan stored51.2, reconstructed50, dan roundtrip51.2 mengukur sensitivitas pada sinyal yang sudah terinterpolasi; tidak bisa memulihkan ground truth atau membuktikan interpolasi firmware tidak merusak HRV. Pasangan fitur hanya dihitung ketika kedua window lolos kualitas; perubahan availability juga dilaporkan. Sinyal sintetis dengan beat time diketahui memberi kontrol tambahan (`audit/ppg_synthetic_known_beats.csv`), bukan validasi fisiologis manusia.", "",
              "n_peaks tetap jumlah kandidat HeartPy sesuai referensi, sehingga dapat berubah lebih besar daripada mean_hr sesudah RR cleaning. Perbedaan jumlah peak/HRV pada uji resampling harus diperiksa sebelum deployment; availability yang lolos bukan jaminan tiap peak benar. Sinyal sintetis mencakup RR konstan dan bervariasi serta tiga fase sampling.", "",
              f"GSR low-pass 1 Hz: median rasio variance filtered/raw={gsr_sensitivity.variance_ratio_1hz_raw.median():.6f}; median absolute mean shift={gsr_sensitivity.absolute_mean_shift_1hz.median():.6f} uS. Pembanding 2 Hz dicatat tanpa memilih cutoff dari skor regresi. Tidak ada jaminan komponen fisiologis tertentu dipertahankan tanpa referensi atau protokol validasi.", "",
              "## Batasan dan eksperimen berikutnya", "",
              "1. Target bukan pengukuran hidrasi langsung. Shimmer memakai durasi sejak awal puasa yang dilaporkan; SEHAT memakai waktu sejak terakhir minum. Protokol puasa bisa sekaligus melarang makanan/minuman, tetapi metadata ini tidak membuktikan last-drink time identik. Hybrid ini adalah transfer proxy label, bukan label klinis yang harmonis. Pertahankan provenance; kumpulkan label durasi minum terstandar dan referensi hidrasi jika tersedia pada studi berikutnya.",
              "2. Lima subjek dan 12 sesi SEHAT membatasi kesimpulan. S13 memiliki lebih banyak sesi dan satu durasi panjang; pooled metric dan macro-subject metric sama-sama dilaporkan. Waktu/sesi/protokol mungkin berhubungan dengan target dan kontak sensor. Tambahkan peserta baru serta sesi berulang pada rentang target yang seimbang dengan urutan pengukuran diacak.",
              "   Target adalah durasi saat awal rekaman yang dipertahankan konstan untuk seluruh window, mengikuti evaluasi satu target per recording. Durasi sesungguhnya bertambah selama pengukuran (sekitar .0833 jam pada sesi SEHAT lima menit, lebih besar pada rekaman Shimmer panjang). Angka desimal logger bukan presisi biologis. Sensitivitas pengaruh setiap sesi pada agregasi OOF tersedia, tanpa mengubah hasil utama atau melatih ulang model.",
              "3. ID S1–S11 Shimmer dan S12–S16 SEHAT diasumsikan peserta berbeda. Tidak ada pemetaan identitas eksternal untuk membuktikannya. Tidak ada sensor reference simultan untuk memisahkan domain shift dari variasi fisiologis/elektroda.",
              "4. QC menguji hanya data yang diterima; missingness/penolakan bisa tidak acak. Laporkan coverage bersama error, termasuk PPG yang diimputasi. Raw CSV utuh; pengecualian dapat ditinjau ulang tanpa kehilangan data.",
              "5. Deployment belum ekuivalen: Python HeartPy berbeda dari peak detector embedded; filtering full-run zero-phase memakai konteks masa depan dan threshold gyro per run, sedangkan firmware memakai window. Firmware lama menginterpolasi GSR panjang/tepi dan personal-normalizes; harus diselaraskan dengan kontrak baru melalui golden-window comparison sebelum ekspor model. Tidak ada model .h atau firmware yang diubah.",
              "6. Simpan FIFO asli 50 Hz dan timestamp sensor/clock aktual; ukur peak timing terhadap referensi denyut, evaluasi RR/HRV sebelum dan sesudah resampling. Kalibrasi GSR lintas perangkat dan periksa kestabilan kontak. Setelah protokol tetap, gunakan cohort prospektif baru atau nested subject validation untuk konfirmasi pemilihan strategi.", "",
              "## Artefak dan reproduksi", "",
              "Notebook `TRAIN_SEHAT_hybrid.ipynb` dijalankan berurutan melalui nbclient menggunakan Python proyek. `run_hybrid_notebook.py` membuat/menjalankan notebook; cache per file memerlukan hash raw, konfigurasi, dan kode ekstraksi yang sama. Hasil pertama dihitung dari raw. `validation.json` menyimpan pemeriksaan integritas. Manifest dan per-file QC menyimpan SHA256 raw; validasi akhir membaca ulang seluruh file untuk membuktikan tidak diubah.", "",
              "Model Python terpilih dan objek preprocessing berada di `models/best_model_pipeline.joblib`; `models/inference_contract.json` mencatat urutan, unit, median, dan kebijakan missing. Refit final memakai semua data yang sesuai strategi terpilih; metrik di atas tetap berasal dari model fold OOF, bukan refit final.", "",
              "Sumber teknis: " + "; ".join(f"[{k}]({v})" for k, v in SOURCES.items()), "",
              "Referensi lokal: `TRAIN_SEHAT_revisi copy.ipynb` (nama copy(1) tidak ditemukan), `ppg_preprocessing.py`, `MAX30102_PREPROCESSING_ESP32.md`, `GSR_PREPROCESSING_ESP32.md`, serta raw acquisition firmware (hanya dibaca)."]
    (config.out / "EXPERIMENT_REPORT.md").write_text("\n".join(report), encoding="utf-8")
    write_json(config.out / "experiment_summary.json", dict(best_model=best_name, improvement_MAE_vs_Shimmer_hr=float(improvement),
                metrics=summary.replace({np.nan: None}).to_dict("records"), data_counts=counts.to_dict("records"),
                per_subject_metrics=per_subject.replace({np.nan: None}).to_dict("records"),
                limitations=["proxy target definitions differ", "five SEHAT subjects; twelve recordings", "selection on same LOSO; exploratory",
                             "no physiological reference or native 50Hz stream", "embedded feature parity not established"],
                config_file="config.json", validation_file="validation.json"))
    print("Saved report:", config.out / "EXPERIMENT_REPORT.md", flush=True)
    return counts
