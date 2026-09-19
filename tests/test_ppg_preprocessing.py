"""Behavioral regression tests for sample-preserving PPG reprocessing.

Run from the project root with:
    .venv/Scripts/python -m unittest discover -s tests -v
"""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ppg_preprocessing import (
    PPGConfig,
    create_windows,
    extract_ppg_features,
    extract_preprocessed_features,
    load_signals,
    prepare_recording,
    preprocess_ppg,
)


FS = 51.2


def pulse(seconds=30, fs=FS):
    time = np.arange(round(seconds * fs)) / fs
    # Slight modulation avoids the zero-SDSD special case in beat fitting.
    phase = 2 * np.pi * 1.2 * time + 0.025 * np.sin(2 * np.pi * 0.2 * time)
    return time, np.sin(phase)


def recording(seconds=30):
    time, signal = pulse(seconds)
    return pd.DataFrame({
        'ppg': 1500 + signal,
        'gyro_x': np.zeros(len(time)),
        'gyro_y': np.zeros(len(time)),
        'gyro_z': np.zeros(len(time)),
        'timestamp_ms': time * 1000,
    })


class SignalRetentionTests(unittest.TestCase):
    def test_motion_adapts_filter_without_deleting_samples(self):
        time, signal = pulse()
        moving = (time > 10) & (time < 20)
        gyro = np.zeros(len(time))
        gyro[moving] = 100 * np.sin(2 * np.pi * 5 * time[moving])
        raw = signal + 0.5 * np.sin(2 * np.pi * 12 * time)
        original = raw.copy()
        result = preprocess_ppg(raw, gyro, np.zeros(len(time)), np.zeros(len(time)))

        np.testing.assert_array_equal(raw, original)
        for name in ('cleaned', 'motion_score', 'high_motion', 'interpolated',
                     'missing', 'gyro_missing'):
            self.assertEqual(getattr(result, name).shape, raw.shape)
        self.assertTrue(np.isfinite(result.cleaned).all())
        self.assertFalse(result.missing.any())
        self.assertGreater(result.high_motion[moving].mean(), 0.8)
        self.assertLess(result.high_motion[time < 8].mean(), 0.05)
        self.assertTrue(np.isfinite(result.cleaned[result.high_motion]).all())
        self.assertGreater(np.std(result.cleaned[result.high_motion]), 0.2)

    def test_short_bounded_gaps_repaired_long_and_edge_gaps_remain(self):
        _, raw = pulse(20)
        raw[:2] = np.nan
        raw[-2:] = np.inf
        raw[100:105] = np.nan
        raw[300:330] = np.nan
        original = raw.copy()
        result = preprocess_ppg(raw)

        expected_repaired = np.zeros(len(raw), dtype=bool)
        expected_repaired[100:105] = True
        np.testing.assert_array_equal(result.interpolated, expected_repaired)
        expected_missing = ~np.isfinite(raw) & ~expected_repaired
        np.testing.assert_array_equal(result.missing, expected_missing)
        np.testing.assert_array_equal(np.isnan(result.cleaned), expected_missing)
        np.testing.assert_array_equal(raw, original)

    def test_long_missing_gap_isolates_filtering_on_either_side(self):
        _, raw = pulse(20)
        raw[400:450] = np.nan
        first = preprocess_ppg(raw).cleaned
        changed = raw.copy()
        changed[450:] = changed[450:] * 50 + 1000
        second = preprocess_ppg(changed).cleaned
        np.testing.assert_allclose(first[:400], second[:400], atol=0, rtol=0)
        self.assertTrue(np.isnan(second[400:450]).all())

    def test_empty_tiny_all_missing_and_flat_signals_keep_their_length(self):
        samples = ([], [2], [2, 3], [np.nan], np.full(500, np.nan), np.full(500, 7.0))
        for values in samples:
            with self.subTest(length=len(values)):
                result = preprocess_ppg(values)
                self.assertEqual(len(result.cleaned), len(values))
                self.assertEqual(len(result.missing), len(values))
                if np.isfinite(values).all():
                    self.assertTrue(np.isfinite(result.cleaned).all())
                else:
                    self.assertTrue(result.missing.all())

    def test_constant_signal_has_no_smoothing_edge_dip_without_highpass(self):
        raw = np.full(500, 7.0)
        result = preprocess_ppg(raw, config=PPGConfig(baseline_cutoff_hz=0))
        np.testing.assert_allclose(result.cleaned, raw, atol=1e-10, rtol=0)

    def test_absent_gyro_keeps_ppg_and_marks_motion_unavailable(self):
        _, raw = pulse()
        unavailable = preprocess_ppg(raw)
        stationary = preprocess_ppg(raw, np.zeros(len(raw)), np.zeros(len(raw)), np.zeros(len(raw)))
        self.assertTrue(unavailable.gyro_missing.all())
        self.assertTrue(np.isnan(unavailable.motion_score).all())
        self.assertTrue(np.isnan(unavailable.motion_threshold))
        self.assertFalse(unavailable.high_motion.any())
        np.testing.assert_allclose(unavailable.cleaned, stationary.cleaned)

    def test_invalid_sampling_and_filter_parameters_fail_explicitly(self):
        for fs in (0, -1, np.nan, np.inf, 5):
            with self.subTest(fs=fs), self.assertRaises(ValueError):
                preprocess_ppg([1, 2, 3], fs=fs)
        invalid = {
            'low_motion_cutoff_hz': (FS / 2, np.nan),
            'high_motion_cutoff_hz': (0, 5),
            'baseline_cutoff_hz': (-1, 3),
            'filter_order': (0, 1.5),
            'motion_window_sec': (0, -1),
            'smooth_window_sec': (-1, np.nan),
            'blend_window_sec': (-1, np.inf),
            'max_gap_sec': (-1, np.nan),
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(parameter=name, value=value), self.assertRaises(ValueError):
                    preprocess_ppg([1, 2, 3], config=replace(PPGConfig(), **{name: value}))

    def test_multidimensional_or_misaligned_channels_fail_explicitly(self):
        with self.assertRaises(ValueError):
            preprocess_ppg([[1, 2], [3, 4]])
        with self.assertRaises(ValueError):
            preprocess_ppg([1, 2, 3], gyro_x=[1, 2])
        with self.assertRaises(ValueError):
            preprocess_ppg([1, 2], gyro_x=[[1, 2]])


class RecordingAndWindowTests(unittest.TestCase):
    def test_prepare_preserves_raw_values_index_metadata_and_row_count(self):
        raw = recording(10)
        raw.index = pd.Index(np.arange(len(raw)) * 3 + 8, name='source_row')
        raw.attrs['subject'] = 'synthetic'
        raw.loc[raw.index[100], 'ppg'] = np.nan
        snapshot = raw.copy(deep=True)
        prepared = prepare_recording(raw)
        pd.testing.assert_frame_equal(raw, snapshot)
        pd.testing.assert_frame_equal(prepared[list(raw.columns)], raw)
        self.assertEqual(prepared.attrs['subject'], 'synthetic')
        self.assertEqual(len(prepared), len(raw))
        self.assertTrue(prepared['ppg_interpolated'].iloc[100])

    def test_timestamp_gap_splits_filtering_and_flags_feature_window(self):
        raw = recording(20)
        split = len(raw) // 2
        raw.loc[split:, 'timestamp_ms'] += 3000
        raw.loc[split:, 'ppg'] += 5000
        prepared = prepare_recording(raw)
        expected_left = preprocess_ppg(raw['ppg'].iloc[:split].to_numpy()).cleaned
        expected_right = preprocess_ppg(raw['ppg'].iloc[split:].to_numpy()).cleaned
        np.testing.assert_allclose(prepared['ppg_clean'].iloc[:split], expected_left)
        np.testing.assert_allclose(prepared['ppg_clean'].iloc[split:], expected_right)
        self.assertEqual(int(prepared['ppg_timing_gap'].sum()), 1)
        self.assertTrue(prepared['ppg_timing_gap'].iloc[split])
        self.assertTrue(np.isfinite(prepared['ppg_clean']).all())
        features = extract_preprocessed_features(prepared)
        self.assertEqual(features['ppg_status'], 'timing_gap')
        self.assertFalse(features['ppg_feature_valid'])
        self.assertTrue(np.isnan(features['bpm']))
        self.assertEqual(features['window_samples'], len(raw))
        self.assertEqual(features['ppg_timing_gap_count'], 1)
        after_gap = extract_preprocessed_features(prepared.iloc[split:])
        self.assertNotEqual(after_gap['ppg_status'], 'timing_gap')
        self.assertEqual(after_gap['ppg_timing_gap_count'], 0)

    def test_duplicate_and_missing_timestamps_flag_without_dropping_rows(self):
        raw = recording(10)
        raw.loc[100, 'timestamp_ms'] = raw.loc[99, 'timestamp_ms']
        raw.loc[200, 'timestamp_ms'] = np.nan
        prepared = prepare_recording(raw)
        self.assertEqual(len(prepared), len(raw))
        self.assertTrue(prepared['ppg_timing_gap'].iloc[[100, 101, 200, 201]].all())
        self.assertTrue(np.isfinite(prepared['ppg_clean']).all())

    def test_windows_cover_every_source_row_and_keep_partial_tail(self):
        cases = ((0, []), (3, [3]), (10, [10]), (11, [10, 6]),
                 (15, [10, 10]), (16, [10, 10, 6]), (21, [10, 10, 10, 6]))
        for length, expected_lengths in cases:
            with self.subTest(length=length):
                frame = pd.DataFrame({'ppg': np.arange(length)})
                windows = create_windows(frame, fs=10, window_sec=1, overlap=0.5)
                self.assertEqual([len(window) for window in windows], expected_lengths)
                covered = {index for window in windows for index in window.index}
                self.assertEqual(covered, set(range(length)))

    def test_window_coverage_with_no_overlap_and_heavy_overlap(self):
        for overlap in (0, 0.1, 0.5, 0.9, 0.999):
            with self.subTest(overlap=overlap):
                frame = pd.DataFrame({'ppg': np.arange(37)})
                windows = create_windows(frame, fs=10, window_sec=1, overlap=overlap)
                self.assertEqual({i for w in windows for i in w.index}, set(frame.index))
                self.assertTrue(all(0 < len(window) <= 10 for window in windows))

    def test_invalid_window_parameters_raise(self):
        frame = pd.DataFrame({'ppg': [1, 2]})
        for args in ({'fs': 0}, {'window_sec': 0}, {'overlap': -0.1},
                     {'overlap': 1}, {'overlap': np.nan}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                create_windows(frame, **args)

    def test_csv_duplicate_sensor_names_missing_values_and_blank_rows_preserved(self):
        # The duplicate GSR signal has RAW and CAL columns, and PPG is not first.
        content = (
            'Shimmer export\n'
            'Timestamp,GSR_Skin_Conductance,GSR_Skin_Conductance,PPG_A13,Gyro_X,Gyro_Y,Gyro_Z,System_Timestamp_Plot_Zeroed\n'
            'CAL,RAW,CAL,CAL,CAL,CAL,CAL,CAL\n'
            'ms,raw,uS,mV,deg/s,deg/s,deg/s,ms\n'
            '0,900,1.5,100,0,0,0,0\n'
            '19.53125,901,1.6,,1,2,3,0\n'
            '\n'
            '58.59375,902,1.7,102,2,3,4,0\n'
        )
        with tempfile.TemporaryDirectory(prefix='sehat-ppg-test-') as directory:
            path = Path(directory) / 'signals.csv'
            path.write_text(content, encoding='utf-8')
            loaded = load_signals(path)
        self.assertEqual(len(loaded), 4)
        np.testing.assert_allclose(loaded['ppg'], [100, np.nan, np.nan, 102], equal_nan=True)
        np.testing.assert_allclose(loaded['gsr'], [1.5, 1.6, np.nan, 1.7], equal_nan=True)
        np.testing.assert_allclose(loaded['timestamp_ms'], [0, 19.53125, np.nan, 58.59375], equal_nan=True)
        self.assertTrue(loaded['temp'].isna().all())


class FeatureExtractionTests(unittest.TestCase):
    def test_known_pulse_is_denoised_and_heart_rate_retained(self):
        time, clean = pulse(60)
        noise = 0.65 * np.sin(2 * np.pi * 12 * time)
        drift = 0.6 * np.sin(2 * np.pi * 0.12 * time)
        contaminated = clean + noise + drift
        result = preprocess_ppg(contaminated)
        interior = slice(round(5 * FS), -round(5 * FS))
        error_before = np.mean((contaminated[interior] - clean[interior]) ** 2)
        error_after = np.mean((result.cleaned[interior] - clean[interior]) ** 2)
        self.assertLess(error_after, error_before * 0.1)
        features = extract_ppg_features(result.cleaned, preprocessed=True)
        self.assertTrue(features['ppg_feature_valid'], features)
        self.assertAlmostEqual(features['bpm'], 72, delta=1)
        self.assertAlmostEqual(features['ibi'], 60000 / 72, delta=15)
        self.assertEqual(features['mean_hr'], features['bpm'])
        self.assertTrue(np.isfinite(features['rmssd']))

    def test_empty_short_flat_and_missing_have_explanatory_status(self):
        values_and_status = (
            ([], 'too_short'),
            ([1, 2], 'too_short'),
            (np.full(round(FS * 10), 2.0), 'flat_signal'),
            (np.full(round(FS * 10), np.nan), 'missing_ppg'),
        )
        for values, status in values_and_status:
            with self.subTest(status=status):
                features = extract_ppg_features(values, preprocessed=True)
                self.assertEqual(features['ppg_status'], status)
                self.assertFalse(features['ppg_feature_valid'])
                self.assertFalse(features['ppg_quality_ok'])
                self.assertTrue(np.isnan(features['bpm']))

    @staticmethod
    def mock_heartpy_result(bpm=72, rr_mask=(0, 0, 0, 0)):
        working = {'peaklist': [5, 50, 92, 138, 181], 'RR_masklist': list(rr_mask),
                   'RR_list': [800, 200, 840, 820]}
        measures = {'bpm': bpm, 'ibi': 60000 / bpm, 'rmssd': 17.25,
                    'sdnn': 20, 'pnn50': 0.25, 'breathingrate': 0.2}
        return working, measures

    def test_heartpy_units_aliases_and_rr_statistics_are_preserved(self):
        _, values = pulse(10)
        original = values.copy()
        # The wrapper must retain HeartPy's masked-RR statistic rather than
        # recomputing differences across intervals removed by beat rejection.
        result = self.mock_heartpy_result(rr_mask=(0, 1, 0, 0))
        with patch('heartpy.process', return_value=result) as process:
            features = extract_ppg_features(values, preprocessed=True)
        self.assertEqual(features['bpm'], 72)
        self.assertEqual(features['mean_hr'], 72)
        self.assertEqual(features['pnn50'], 25)
        self.assertEqual(features['breathingrate'], 0.2)
        self.assertEqual(features['breathing_rate_bpm'], 12)
        self.assertEqual(features['rmssd'], 17.25)
        self.assertEqual(features['n_peaks'], 5)
        self.assertEqual(features['ppg_rr_rejected_fraction'], 0.25)
        self.assertTrue(features['ppg_feature_valid'])
        self.assertTrue(features['ppg_quality_ok'])
        self.assertFalse(process.call_args.kwargs['reject_segmentwise'])
        self.assertTrue(process.call_args.kwargs['clean_rr'])
        self.assertEqual(process.call_args.kwargs['sample_rate'], FS)
        np.testing.assert_array_equal(values, original)

    def test_out_of_range_estimate_is_visible_but_flagged(self):
        _, values = pulse(10)
        for bpm in (39, 181):
            with self.subTest(bpm=bpm), patch('heartpy.process', return_value=self.mock_heartpy_result(bpm)):
                features = extract_ppg_features(values, preprocessed=True)
                self.assertEqual(features['bpm'], bpm)
                self.assertEqual(features['ppg_status'], 'review_bpm_range')
                self.assertFalse(features['ppg_feature_valid'])
                self.assertFalse(features['ppg_quality_ok'])

    def test_high_rr_rejection_keeps_metrics_but_requires_review(self):
        _, values = pulse(10)
        with patch('heartpy.process', return_value=self.mock_heartpy_result(rr_mask=(0, 1, 1, 0))):
            features = extract_ppg_features(values, preprocessed=True)
        self.assertEqual(features['bpm'], 72)
        self.assertEqual(features['ppg_status'], 'review_rr_rejections')
        self.assertTrue(features['ppg_feature_valid'])
        self.assertFalse(features['ppg_quality_ok'])

    def test_incomplete_rr_metrics_remain_missing_without_imputation(self):
        _, values = pulse(10)
        working, measures = self.mock_heartpy_result()
        measures['rmssd'] = np.nan
        with patch('heartpy.process', return_value=(working, measures)):
            features = extract_ppg_features(values, preprocessed=True)
        self.assertEqual(features['bpm'], 72)
        self.assertTrue(np.isnan(features['rmssd']))
        self.assertFalse(features['ppg_feature_valid'])
        self.assertEqual(features['ppg_status'], 'insufficient_valid_beats')

    def test_heartpy_failure_retains_window_diagnostics(self):
        prepared = prepare_recording(recording(10))
        with patch('heartpy.process', side_effect=ValueError('no reliable peaks')):
            features = extract_preprocessed_features(prepared)
        self.assertEqual(features['ppg_status'], 'heartpy_failed')
        self.assertIn('no reliable peaks', features['ppg_error'])
        self.assertEqual(features['window_samples'], len(prepared))
        self.assertFalse(features['ppg_feature_valid'])
        self.assertEqual(features['ppg_missing_fraction'], 0)


if __name__ == '__main__':
    unittest.main()
