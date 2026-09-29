# PPG reprocessing

Both training notebooks now use `ppg_preprocessing.py`. Run the notebooks from
this folder, or reproduce the reprocessing without running model training:

```powershell
.\.venv\Scripts\python.exe scripts/reprocess_ppg.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For a new environment, install `requirements-ppg.txt` with the Python interpreter
used by the notebook. The local `.venv` contains HeartPy. The notebook also has a
`%pip install` cell. Restart its kernel and run from the beginning so old function
definitions and old feature values are not reused.

## Method and reference

The local `[3] referensi utama.pdf` is Sabry et al., *Towards On-Device Dehydration
Monitoring Using Machine Learning from Wearable Device's Data*, Sensors 2022,
22, 1887, [DOI](https://doi.org/10.3390/s22051887). Section 4.1.5 on page 8 calls
for motion-adaptive low-pass filtering, smoothing and HeartPy. Figure 5 on page 9
calls the filtering Butterworth **bandpass**. We reconcile these descriptions
with fixed baseline removal followed by a gyroscope-adaptive low-pass filter.

The paper does **not** report cutoff frequencies, order, motion-window length,
transition duration or smoothing-window length. These are configurable project
defaults, not a claim of exact numerical reproduction:

| Setting | Default |
| --- | --- |
| Nominal sampling rate | 51.2 Hz, from this dataset's EDA |
| Baseline-removal high-pass | 0.5 Hz; set `baseline_cutoff_hz=0` for low-pass only |
| Low-motion / high-motion low-pass | 4 Hz / 2.5 Hz |
| Butterworth order | 4 per filter; forward/backward zero-phase application |
| Gyroscope motion window | 1 second |
| Transition between filter branches | 0.25-second reflected moving average |
| Final smoothing | 0.15-second reflected moving average |
| Maximum interpolated PPG gap | 0.25 second, bounded by observed samples |
| Feature window / overlap | 30 seconds / 50%, plus an uncovered partial tail |

Change settings explicitly when comparing alternatives, for example:

```python
from ppg_preprocessing import PPGConfig, load_signals, prepare_recording

config = PPGConfig(low_motion_cutoff_hz=4.0, high_motion_cutoff_hz=2.5)
cleaned = prepare_recording(load_signals(recording_path), fs=51.2, config=config)
```

Figure 5 uses four-minute feature chunks. This project keeps its existing
30-second training windows; that difference is intentional. Breathing rate and
HRV from short windows require particular care when interpreting results.

Processing steps:

1. Read calibrated PPG and three gyroscope axes by CSV column position, keeping
   every row and its timestamp. The calibrated device timestamp takes priority
   over the system timestamp. Preserve the original waveform separately.
2. Identify timestamp discontinuities using the expected sample interval. Filter
   the stretches on either side independently. Do not concatenate time across a
   break. A missing/duplicate/backward timestamp or an interval more than 50%
   away from the nominal interval is flagged.
3. Interpolate only short, interior missing PPG/gyro gaps. Long and edge PPG gaps
   remain missing and split the filter into independent finite stretches.
4. Calculate gyroscope magnitude and the rolling mean of its **absolute** sample
   changes. Above-mean motion selects the stronger low-pass branch. The threshold
   is computed per continuous recording stretch, before feature windowing.
   The paper's signed cumulative-change equation would telescope; absolute
   increments are our explicit interpretation of its motion description.
5. Apply baseline removal, both low-pass branches, smooth blending and final
   smoothing. Reflected boundaries avoid the artificial endpoint amplitude
   collapse caused by zero-padded moving averages. Missing gyro uses the 4 Hz
   branch and is flagged.
6. Run HeartPy on each window after a positive affine rescaling for its peak
   detector. Use sub-sample peak refinement and RR cleaning, with
   `reject_segmentwise=False`. Motion alone never triggers a feature rejection.
   Invalid individual beats may still be excluded from physiological measures.

The filter is offline and uses future samples. It is not a causal ESP32
implementation. Low-pass filtering cannot recover a pulse erased by contact
loss or separate all motion energy that overlaps the pulse frequency band.
Neither smooth appearance nor successful feature extraction proves accuracy.

## Retention and feature interpretation

Raw samples, cleaned samples and timestamps have the same length. Each source
sample is covered by an output window, including the tail. No motion threshold
deletes a row. Unusable windows remain in the table with a reason such as
`missing_ppg`, `timing_gap`, `flat_signal`, `too_short` or `heartpy_failed`.

`ppg_feature_valid` means the core HeartPy metrics are finite and final BPM is
within the configured analysis range of 40–180. It is an **availability
indicator**, not proof that their physiological values are true.
`review_rr_rejections` preserves computed features but flags windows where more
than 30% of RR intervals were rejected. Motion, missing-data, interpolation and
gyro availability fractions provide additional evidence for review.
`review_bpm_range` flags a final BPM outside 40–180, retaining the estimate for
inspection. `ppg_quality_ok` additionally requires at most 30% RR rejection;
it is a screening flag, not validation against ground truth.

The reference paper also carries the previous feature value forward on failure.
This implementation leaves unavailable measurements as NaN and flags them;
it does not present carried values as newly measured physiology. Existing model
cells retain their explicit missing-feature treatment. Model inputs remain the
previous numeric feature list so status strings and diagnostics are not
accidentally passed to the model.

| Feature | Unit / meaning |
| --- | --- |
| `ibi`, `rmssd`, `sdnn` | milliseconds |
| `bpm`, `mean_hr` | beats/minute; identical values |
| `breathingrate` | Hz, as returned by HeartPy |
| `breathing_rate_bpm` | breaths/minute (`breathingrate * 60`) |
| `pnn50` | percent (HeartPy's fraction multiplied by 100) |
| `n_peaks` | detected peaks, including subsequently rejected beats |

HeartPy preserves an RR rejection mask for successive-interval calculations;
we use its metrics rather than recomputing RMSSD from a compressed interval list.
See its [processing API](https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/heartpy.heartpy.html)
and [breathing-rate explanation](https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/algorithmfunctioning.html).

## Outputs and comparison

The command-line run uses the 112 recording names and labels already present in
`dataset_final_features.csv`. It reads the corresponding raw recordings again.
Other raw files outside that original table are listed in the audit, not silently
added with guessed labels. Nonfasting records retain their missing fasting-time
regression target. The notebooks use their own EDA-selected recording list.

- `dataset_final_features_reprocessed.csv`: all reprocessed windows and flags.
- `artifacts/ppg/cleaned/<subject>/<session>/<recording>.npz`: original PPG, cleaned
  PPG, original timestamps, motion score and sample masks. These large generated
  archives are ignored by Git but remain available locally.
- `artifacts/ppg/summary.json`: per-recording sample/window retention, errors,
  missing data, quality status and comparison against the old feature table.
- `artifacts/ppg/ppg_comparison.png`: raw/cleaned waveform and motion illustration.

`--limit-files 2` performs a small run and writes `features_preview.csv` and
`summary_preview.json` in the output directory. `--output-dir` selects a separate
artifact folder. The original feature CSV and the existing model header remain
available for comparison; preprocessing does not retrain or export the model.

Before/after availability is matched on filename and window ID. The former
loader deleted missing sensor rows, so matching IDs need not imply exactly
matching sample boundaries. The audit explicitly reports new tail windows and
unmatched IDs. Availability comparisons do not establish denoising accuracy;
that would require paired clean physiological ground truth.
