# Data and Model Contract

## S1 model input

The deployed S1 ExtraTrees model receives nine values in this exact order:

1. `gsr_mean`
2. `gsr_var`
3. `gsr_entropy`
4. `mean_hr`
5. `rmssd`
6. `sdnn`
7. `pnn50`
8. `n_peaks`
9. `ppg_available`

The first eight values use the S1 training mean and pandas sample standard deviation (`ddof=1`). `ppg_available` is a raw availability flag and is not normalized.

When PPG features are invalid, the five PPG feature values are zeroed after normalization and `ppg_available` is `0`. Invalid, missing, or constant GSR prevents prediction.

## Sampling and windows

- Shared nominal sample rate: `51.2 Hz`
- Window length: `1536` samples (`30 seconds`)
- Window hop: `768` samples (`15 seconds`)
- Overlap: `50%`
- GSR units: microsiemens (`uS`)
- Heart-rate and HRV units follow the existing preprocessing implementation.

## Prediction target

The model output is `fasting_duration_hr`: an estimated number of hours since fasting began. It is not a hydration percentage, a direct measurement of fluid level, or a clinical diagnosis.

The dashboard may derive a presentation status from a documented threshold, but that status is not the model target.

## Provenance

Every generated scaler or model header should record:

- model name and version
- source dataset path and SHA-256
- feature order
- preprocessing version
- generation command
- generation date

Generated headers are deployment artifacts, not hand-maintained model logic.

## API direction

Production measurements should carry the ESP32 prediction and enough metadata to identify the model and preprocessing version. The API persists the result without silently replacing it with a different heuristic. Any demo inference must be explicitly marked as simulated.
