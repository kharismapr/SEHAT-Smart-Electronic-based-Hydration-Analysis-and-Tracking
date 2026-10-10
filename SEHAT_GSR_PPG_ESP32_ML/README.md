# SEHAT S1 ESP32 firmware

Open `SEHAT_GSR_PPG_ESP32_ML.ino` in Arduino IDE with an ESP32 board and the
SparkFun MAX3010x library installed. The sketch uses GPIO21/22 for I2C and
GPIO34 for Grove GSR analog input, as in the earlier combined sketch. An
MPU-9250/GY-9250 on the I2C bus is optional; without it the PPG filter uses
its low-motion branch.

At 115200 baud, remove the GSR electrodes and send `c` to calibrate the Grove
ADC. Attach the electrodes and finger afterward, then send `s` to start a
fresh recording. No inference starts without calibration and `s`. Send `f`
to finish a recording and emit its uncovered partial window; `r` resets the
recording while retaining the current GSR calibration. Send `s` to begin again. Recalibrate
after changing the GSR potentiometer, electrodes or wiring.

The MAX30102 supplies 50-Hz IR data; it is linearly interpolated to a nominal
51.2-Hz shared time index. GSR ADC readings are scheduled at 51.2 Hz. The two
processors receive paired samples, create 1536-sample (30-second) windows,
and advance by 768 samples (15 seconds). Missed GSR ADC instants are stored as
missing data, so the GSR extractor can apply the training interpolation rule.
Prolonged sample loss or FIFO overflow resets the recording.

The S1 ExtraTrees input is, in order:

`gsr_mean, gsr_var, gsr_entropy, mean_hr, rmssd, sdnn, pnn50, n_peaks, ppg_available`

The first eight values use the personal S1 pandas z-score (`ddof=1`) from
`s1_scaler.h`. The last flag is 0 or 1. If PPG is invalid, all five PPG
numbers are zero **after** normalization. Valid GSR still permits a prediction
in that case. Invalid, missing, or constant GSR suppresses prediction.
The output is **estimated fasting duration in hours** for S1, not a hydration
percentage or a clinical diagnosis.

Regenerate the scaler with `python scripts/generate_s1_scaler.py` from the
repository root. That script reconstructs the revised notebook's S1 sample,
checks all 35 root splits against `et_hydration_model_S1.h`, and records the
training CSV SHA-256 in the generated header. Retraining the deployed model is
not part of the firmware build.

Host consistency checks: `.venv/Scripts/python tests/verify_s1_consistency.py`.
Python preprocessing unit tests: `.venv/Scripts/python -m unittest discover -s tests -v`.
The consistency check compiles the actual C++ preprocessing and model headers,
syntax-checks the `.ino` using Arduino API stubs, compares 2,487 training
vectors against a deterministic scikit-learn retrain, and compares synthetic
signal windows with Python. A syntax check with stubs is not an ESP32 build.

The C++ PPG peak detector is an embedded approximation of HeartPy, so HRV
numbers can differ from the training pipeline even for the same waveform.
The training data used calibrated Shimmer signals; the Grove GSR and MAX30102
have different acquisition characteristics. Compare simultaneous real sensor
recordings against a reference, check acquisition timing and RAM use on the
actual board, and validate prediction error before treating device outputs as
reliable estimates. This repository does not include raw training recordings.
