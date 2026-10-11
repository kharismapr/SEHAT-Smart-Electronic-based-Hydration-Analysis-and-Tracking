"""Offline, sample-preserving PPG preprocessing for the SEHAT Shimmer data.

Sabry et al. (2022), section 4.1.5 / Figure 5, doi:10.3390/s22051887.
The paper does not specify numerical filter settings. Defaults below are project
choices, not parameters reported by the authors. Motion controls filter strength;
it NEVER deletes samples or windows. Unrecoverable gaps remain explicitly missing.
"""
from dataclasses import dataclass
import warnings

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfiltfilt


@dataclass(frozen=True)
class PPGConfig:
    low_motion_cutoff_hz: float = 4.0
    high_motion_cutoff_hz: float = 2.5
    baseline_cutoff_hz: float = 0.5
    filter_order: int = 4
    motion_window_sec: float = 1.0
    smooth_window_sec: float = 0.15
    blend_window_sec: float = 0.25
    max_gap_sec: float = 0.25

    def validate(self, fs):
        if not np.isfinite(fs) or fs <= 0:
            raise ValueError('fs must be positive and finite')
        if not (0 <= self.baseline_cutoff_hz < self.high_motion_cutoff_hz
                <= self.low_motion_cutoff_hz < fs / 2):
            raise ValueError('Require 0 <= baseline < high-motion cutoff <= low-motion cutoff < Nyquist')
        if not isinstance(self.filter_order, (int, np.integer)) or self.filter_order < 1:
            raise ValueError('filter_order must be a positive integer')
        for name in ('motion_window_sec', 'smooth_window_sec', 'blend_window_sec', 'max_gap_sec'):
            value = getattr(self, name)
            if not np.isfinite(value) or value < 0 or (name == 'motion_window_sec' and value == 0):
                raise ValueError(f'Invalid {name}')


@dataclass
class PPGResult:
    cleaned: np.ndarray
    motion_score: np.ndarray
    high_motion: np.ndarray
    interpolated: np.ndarray
    missing: np.ndarray
    gyro_missing: np.ndarray
    motion_threshold: float


def _array(values, name):
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f'{name} must be one-dimensional')
    return array.copy()


def _runs(mask):
    boundaries = np.diff(np.r_[False, mask, False].astype(np.int8))
    return zip(np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1))


def _repair_short_gaps(values, max_samples):
    """Interpolate only interior bounded gaps, without changing the time axis."""
    values = values.copy()
    values[~np.isfinite(values)] = np.nan
    repaired = np.zeros(len(values), dtype=bool)
    for start, end in _runs(~np.isfinite(values)):
        if start > 0 and end < len(values) and end - start <= max_samples:
            values[start:end] = np.linspace(values[start - 1], values[end], end - start + 2)[1:-1]
            repaired[start:end] = True
    return values, repaired


def _odd_samples(seconds, fs):
    samples = max(1, int(round(seconds * fs)))
    return samples if samples % 2 else samples + 1


def _smooth(values, seconds, fs):
    if not len(values):
        return values.copy()
    return uniform_filter1d(values, size=_odd_samples(seconds, fs), mode='reflect')


def _filter(values, cutoff, fs, order, kind):
    if len(values) < 3:
        # Too short for a meaningful filter, but keep the observations.
        return values.copy()
    sos = butter(order, cutoff, btype=kind, fs=fs, output='sos')
    normal_pad = 3 * (2 * len(sos) + 1 - min((sos[:, 2] == 0).sum(), (sos[:, 5] == 0).sum()))
    return sosfiltfilt(sos, values, padlen=min(int(normal_pad), len(values) - 1))


def preprocess_ppg(ppg, gyro_x=None, gyro_y=None, gyro_z=None, fs=51.2, config=None):
    """Baseline removal -> gyro-adaptive low-pass -> reflected moving average.

    Motion = rolling mean absolute increments of gyro magnitude. The threshold
    is the mean of that score over the recording. This is an explicit resolution
    of the paper's ambiguous signed cumulative-change equation. Both low-pass
    branches use zero-phase SOS filtering and blend over 0.25 s by default.
    Filtering is offline/noncausal; each finite run is independent of long gaps.
    """
    config = config or PPGConfig()
    config.validate(fs)
    raw = _array(ppg, 'ppg')
    length = len(raw)
    max_gap = int(np.floor(config.max_gap_sec * fs))
    repaired_ppg, repaired = _repair_short_gaps(raw, max_gap)
    gyro = []
    gyro_missing = np.zeros(length, dtype=bool)
    for name, values in zip(('gyro_x', 'gyro_y', 'gyro_z'), (gyro_x, gyro_y, gyro_z)):
        axis = np.full(length, np.nan) if values is None else _array(values, name)
        if len(axis) != length:
            raise ValueError(f'{name} and ppg must have identical lengths')
        gyro_missing |= ~np.isfinite(axis)
        gyro.append(_repair_short_gaps(axis, max_gap)[0])

    magnitude = np.sqrt(sum(axis ** 2 for axis in gyro))
    score = np.full(length, np.nan)
    for start, end in _runs(np.isfinite(magnitude)):
        increments = np.abs(np.diff(magnitude[start:end], prepend=magnitude[start]))
        score[start:end] = _smooth(increments, config.motion_window_sec, fs)
    finite_score = np.isfinite(score)
    threshold = float(np.mean(score[finite_score])) if finite_score.any() else np.nan
    high_motion = finite_score & (score > threshold)
    blend = _smooth(high_motion.astype(float), config.blend_window_sec, fs)
    # A missing gyroscope does not imply high motion; use the low-motion branch
    # and expose the unavailable motion evidence through gyro_missing.
    blend[~finite_score] = 0.0
    cleaned = np.full(length, np.nan)
    for start, end in _runs(np.isfinite(repaired_ppg)):
        section = repaired_ppg[start:end]
        if config.baseline_cutoff_hz > 0:
            section = _filter(section, config.baseline_cutoff_hz, fs, config.filter_order, 'highpass')
        low = _filter(section, config.low_motion_cutoff_hz, fs, config.filter_order, 'lowpass')
        high = _filter(section, config.high_motion_cutoff_hz, fs, config.filter_order, 'lowpass')
        adaptive = (1 - blend[start:end]) * low + blend[start:end] * high
        cleaned[start:end] = _smooth(adaptive, config.smooth_window_sec, fs)
    return PPGResult(cleaned, score, high_motion, repaired, ~np.isfinite(cleaned), gyro_missing, threshold)


def adaptive_ppg_filter(ppg, gyro_x=None, gyro_y=None, gyro_z=None, fs=51.2, config=None):
    """Convenience wrapper returning just the cleaned waveform."""
    return preprocess_ppg(ppg, gyro_x, gyro_y, gyro_z, fs=fs, config=config).cleaned


def load_signals(path):
    """Read calibrated Shimmer columns by position; keep every source row.

    Shimmer exports can have duplicate GSR names and different column orders.
    The device timestamp is preferred to the often-stuck system timestamp.
    Missing gyro columns are represented by NaN instead of discarding the PPG.
    """
    with open(path, encoding='utf-8-sig') as stream:
        stream.readline()
        signals = stream.readline().strip().split(',')
        calibrated = stream.readline().strip().split(',')
    names = [f'{signal.strip()}_{cal.strip()}' for signal, cal in zip(signals, calibrated)]
    wanted = {'ppg': 'PPG_A13_CAL', 'gsr': 'GSR_Skin_Conductance_CAL',
              'temp': 'Temperature_BMP280_CAL', 'pressure': 'Pressure_BMP280_CAL',
              'gyro_x': 'Gyro_X_CAL', 'gyro_y': 'Gyro_Y_CAL', 'gyro_z': 'Gyro_Z_CAL',
              'timestamp_ms': 'Timestamp_CAL',
              'system_timestamp_ms': 'System_Timestamp_Plot_Zeroed_CAL'}
    if wanted['ppg'] not in names:
        raise ValueError(f'No calibrated PPG column in {path}')
    positions = sorted((names.index(name), alias) for alias, name in wanted.items() if name in names)
    frame = pd.read_csv(path, skiprows=4, header=None,
                        usecols=[position for position, _ in positions], low_memory=False,
                        skip_blank_lines=False)
    frame.columns = [alias for _, alias in positions]
    for alias in wanted:
        frame[alias] = pd.to_numeric(frame[alias], errors='coerce') if alias in frame else np.nan
    if frame['timestamp_ms'].isna().all():
        frame['timestamp_ms'] = frame['system_timestamp_ms']
    return frame


def prepare_recording(frame, fs=51.2, config=None):
    """Filter once before overlapping windows, splitting at timestamp breaks."""
    config = config or PPGConfig()
    config.validate(fs)
    result = frame.copy()
    length = len(result)
    gaps = np.zeros(length, dtype=bool)
    if 'timestamp_ms' in frame and length > 1:
        ts = frame['timestamp_ms'].to_numpy(dtype=float)
        differences = np.diff(ts)
        gaps[1:] = (~np.isfinite(differences) | (differences <= 0)
                    | (np.abs(differences - 1000.0 / fs) > 0.5 * 1000.0 / fs))
    columns = {'ppg_clean': np.full(length, np.nan), 'ppg_motion_score': np.full(length, np.nan),
               'ppg_motion_threshold': np.full(length, np.nan),
               'ppg_high_motion': np.zeros(length, dtype=bool),
               'ppg_interpolated': np.zeros(length, dtype=bool),
               'ppg_missing': np.ones(length, dtype=bool),
               'ppg_gyro_missing': np.ones(length, dtype=bool)}
    thresholds = []
    boundaries = np.unique(np.r_[0, np.flatnonzero(gaps), length])
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        section = frame.iloc[start:end]
        axes = [section[name].to_numpy() if name in section else None
                for name in ('gyro_x', 'gyro_y', 'gyro_z')]
        filtered = preprocess_ppg(section['ppg'].to_numpy(), *axes, fs=fs, config=config)
        for name, attr in [('ppg_clean', 'cleaned'), ('ppg_motion_score', 'motion_score'),
                           ('ppg_high_motion', 'high_motion'), ('ppg_interpolated', 'interpolated'),
                           ('ppg_missing', 'missing'), ('ppg_gyro_missing', 'gyro_missing')]:
            columns[name][start:end] = getattr(filtered, attr)
        thresholds.append(filtered.motion_threshold)
        columns['ppg_motion_threshold'][start:end] = filtered.motion_threshold
    for name, values in columns.items():
        result[name] = values
    result['ppg_timing_gap'] = gaps
    result.attrs.update(frame.attrs)
    result.attrs.update(sample_rate=fs, motion_thresholds=thresholds)
    return result


def create_windows(frame, fs=51.2, window_sec=30, overlap=0.5):
    """Keep all windows including a final partial window for uncovered samples."""
    if not np.isfinite(fs) or fs <= 0 or not np.isfinite(window_sec) or window_sec <= 0:
        raise ValueError('fs and window_sec must be positive and finite')
    if not np.isfinite(overlap) or not 0 <= overlap < 1:
        raise ValueError('overlap must be in [0, 1)')
    size = max(1, int(round(window_sec * fs)))
    step = max(1, int(round(size * (1 - overlap))))
    starts = list(range(0, max(0, len(frame) - size + 1), step))
    if len(frame) and (not starts or starts[-1] + size < len(frame)):
        starts.append(starts[-1] + step if starts else 0)
    return [frame.iloc[start:min(start + size, len(frame))] for start in starts]


def _empty_features(status, error=''):
    features = dict.fromkeys(('ibi', 'bpm', 'mean_hr', 'breathingrate', 'breathing_rate_bpm',
                             'rmssd', 'sdnn', 'pnn50'), np.nan)
    features.update(n_peaks=0, ppg_status=status, ppg_error=error,
                    ppg_rr_rejected_fraction=np.nan, ppg_feature_valid=False,
                    ppg_quality_ok=False)
    return features


def extract_ppg_features(ppg_segment, gyro_x=None, gyro_y=None, gyro_z=None,
                         fs=51.2, preprocessed=False, config=None):
    """HeartPy metrics without motion-triggered window rejection.

    Invalid beats/RR intervals may still be excluded by HeartPy. No waveform is
    overwritten and no failed feature is replaced with an invented measurement.
    pnn50 is percent (legacy notebook units); breathingrate is Hz.
    """
    config = config or PPGConfig()
    config.validate(fs)
    values = _array(ppg_segment, 'ppg_segment')
    if not preprocessed:
        values = preprocess_ppg(values, gyro_x, gyro_y, gyro_z, fs, config).cleaned
    if len(values) < int(np.ceil(5 * fs)):
        return _empty_features('too_short')
    if not np.isfinite(values).all():
        return _empty_features('missing_ppg')
    spread = float(np.ptp(values))
    if spread <= max(1e-8, np.max(np.abs(values)) * 1e-10):
        return _empty_features('flat_signal')
    # A positive affine scaling is needed for HeartPy's moving-average peak
    # threshold on a zero-centred waveform. It does not alter peak timing.
    scaled = (values - np.min(values)) / spread * 1000.0
    import heartpy as hp
    from heartpy.exceptions import BadSignalWarning
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', RuntimeWarning)
            working, measures = hp.process(
                scaled, sample_rate=fs, bpmmin=40, bpmmax=180,
                clean_rr=True, clean_rr_method='quotient-filter',
                reject_segmentwise=False, high_precision=True,
                high_precision_fs=1000.0, interp_clipping=False,
                working_data={}, measures={})
    except (BadSignalWarning, ValueError, IndexError, ZeroDivisionError, FloatingPointError) as exc:
        return _empty_features('heartpy_failed', f'{type(exc).__name__}: {str(exc).strip()}')
    output = _empty_features('ok')
    for key in ('ibi', 'bpm', 'breathingrate', 'rmssd', 'sdnn', 'pnn50'):
        value = measures.get(key, np.nan)
        output[key] = float(value) if np.isfinite(value) else np.nan
    output['mean_hr'] = output['bpm']
    output['pnn50'] *= 100.0
    output['breathing_rate_bpm'] = output['breathingrate'] * 60.0
    output['n_peaks'] = len(working.get('peaklist', []))
    rr_mask = np.asarray(working.get('RR_masklist', []), dtype=bool)
    output['ppg_rr_rejected_fraction'] = float(rr_mask.mean()) if len(rr_mask) else np.nan
    complete = all(np.isfinite(output[k]) for k in ('bpm', 'ibi', 'rmssd', 'sdnn', 'pnn50'))
    in_range = np.isfinite(output['bpm']) and 40 <= output['bpm'] <= 180
    output['ppg_feature_valid'] = bool(complete and in_range)
    if not complete:
        output['ppg_status'] = 'insufficient_valid_beats'
    elif not in_range:
        # HeartPy's bpmmin/bpmmax constrain its initial fit, not necessarily the
        # rate after RR cleaning. Keep estimates visible but explicitly flagged.
        output['ppg_status'] = 'review_bpm_range'
    elif output['ppg_rr_rejected_fraction'] > 0.3:
        output['ppg_status'] = 'review_rr_rejections'
    output['ppg_quality_ok'] = bool(output['ppg_feature_valid']
                                    and output['ppg_rr_rejected_fraction'] <= 0.3)
    if caught:
        output['ppg_error'] = '; '.join(dict.fromkeys(str(w.message) for w in caught))
    return output


def extract_preprocessed_features(window_df, fs=51.2):
    """Return metrics and audit flags; a quality flag never removes the row."""
    # A gap on the very first sample is outside this window's RR intervals.
    has_gap = ('ppg_timing_gap' in window_df
               and window_df['ppg_timing_gap'].iloc[1:].any())
    features = (_empty_features('timing_gap') if has_gap else
                extract_ppg_features(window_df['ppg_clean'].to_numpy(), fs=fs, preprocessed=True))
    for column, key in [('ppg_high_motion', 'ppg_high_motion_fraction'),
                         ('ppg_interpolated', 'ppg_interpolated_fraction'),
                         ('ppg_missing', 'ppg_missing_fraction'),
                         ('ppg_gyro_missing', 'ppg_gyro_missing_fraction')]:
        features[key] = float(window_df[column].mean()) if len(window_df) else np.nan
    features['ppg_timing_gap_count'] = int(window_df['ppg_timing_gap'].iloc[1:].sum())
    features['window_samples'] = len(window_df)
    features['window_duration_sec'] = len(window_df) / fs
    features['ppg_mean_motion_score'] = float(window_df['ppg_motion_score'].mean()) if len(window_df) else np.nan
    return features


def plot_ppg_comparison(frame, fs=51.2, start_sec=0, duration_sec=30):
    """Comparable AC waveform amplitudes plus gyro activity, on the same time axis."""
    import matplotlib.pyplot as plt
    if 'ppg_clean' not in frame:
        frame = prepare_recording(frame, fs=fs)
    start = max(0, int(round(start_sec * fs)))
    end = min(len(frame), start + int(round(duration_sec * fs)))
    section = frame.iloc[start:end]
    time = np.arange(start, end) / fs
    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True)
    raw = section['ppg'].to_numpy()
    if np.isfinite(raw).any():
        raw = raw - np.nanmedian(raw)
    axes[0].plot(time, raw, color='0.5', linewidth=0.7, label='Raw PPG (median removed for display)')
    axes[0].plot(time, section['ppg_clean'], color='#007d8a', linewidth=1, label='Cleaned PPG')
    axes[0].set_ylabel('PPG (mV, AC)')
    axes[0].legend(loc='upper right')
    axes[1].plot(time, section['ppg_clean'], color='#007d8a', linewidth=1)
    axes[1].set_ylabel('Cleaned PPG (mV)')
    axes[1].set_title('Filtered waveform; motion periods shaded, all samples retained')
    axes[2].plot(time, section['ppg_motion_score'], color='#8054a1', linewidth=0.8)
    axes[2].set_ylabel('Gyro motion score')
    axes[2].set_xlabel('Sample time (s, nominal rate)')
    for axis in axes:
        for first, last in _runs(section['ppg_high_motion'].to_numpy(dtype=bool)):
            axis.axvspan(time[first], time[last - 1] + 1 / fs, color='#e5a238', alpha=0.17, linewidth=0)
        axis.grid(alpha=0.15)
    fig.tight_layout()
    return fig
