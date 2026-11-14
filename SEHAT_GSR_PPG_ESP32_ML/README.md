# SEHAT S1 ESP32 firmware

Open `SEHAT_GSR_PPG_ESP32_ML.ino` in Arduino IDE with an ESP32 board and the
SparkFun MAX3010x library installed. The sketch uses GPIO21/22 for I2C and
GPIO34 for Grove GSR analog input, as in the earlier combined sketch. An
MPU-9250/GY-9250 on the I2C bus is optional; without it the PPG filter uses
its low-motion branch.

At 115200 baud, remove the GSR electrodes and send `c` to calibrate the Grove
ADC. Attach the electrodes and finger afterward, then send `s` to start a
fresh recording. No inference starts without calibration and `s`. Send `f`
to finish a recording and discard its uncovered partial window; `r` resets the
recording while retaining the current GSR calibration. Send `s` to begin again. Recalibrate
after changing the GSR potentiometer, electrodes or wiring.

The MAX30102 supplies 50-Hz IR data; it is linearly interpolated to a nominal
51.2-Hz shared time index. GSR ADC readings are scheduled at 51.2 Hz. The two
processors receive paired samples, create 1536-sample (30-second) windows,
and advance by 768 samples (15 seconds). Inference uses complete windows only.
Missed GSR ADC instants are stored as missing data. Inference skips windows with
more than 5% missing GSR, a gap longer than 12 samples, an edge gap, or more
than 20% samples above 100 deg/s gyroscope magnitude. PPG is marked unavailable
if its feature-quality check fails or more than 5% of its samples were repaired.
Prolonged sample loss or FIFO overflow resets the recording.

The SEHAT-only ExtraTrees input is, in order:

`gsr_mean, gsr_var, gsr_entropy, mean_hr, rmssd, sdnn, pnn50, n_peaks, ppg_available`

The existing `s1_features.h` applies the legacy S1 z-score. The
`et_sehat_only.h` wrapper reverses it before inference, applies the frozen
SEHAT training medians to unavailable PPG features, and runs the model in raw
units. The ninth value is the raw 0/1 availability flag. Valid GSR still permits
a prediction when PPG is unavailable. The output is **estimated fasting duration
in hours**, not a hydration percentage or a clinical diagnosis.

The current model export and inference contract are in `sehat_only_results`.
Regenerate the export with `python scripts/export_et_sehat_only.py` from the
repository root. The legacy scaler remains part of the wrapper input contract.

Host model export checks: `.venv/Scripts/python tests/verify_sehat_only_export.py`.
S1 preprocessing reference checks: `.venv/Scripts/python tests/verify_s1_consistency.py`.
Python preprocessing unit tests: `.venv/Scripts/python -m unittest discover -s tests -v`.
The export check compiles the model header, compares predictions with the
scikit-learn pipeline, and syntax-checks the `.ino` using Arduino API stubs.
A syntax check with stubs is not an ESP32 build.

The C++ PPG peak detector is an embedded approximation of HeartPy, so HRV
numbers can differ from the training pipeline even for the same waveform.
The firmware also filters PPG per window and does not yet reproduce the Python
pipeline's full-run filtering or Hampel outlier detection. Its GSR extractor
rejects constant readings that Python can retain.
The training data used calibrated Shimmer signals; the Grove GSR and MAX30102
have different acquisition characteristics. Compare simultaneous real sensor
recordings against a reference, check acquisition timing and RAM use on the
actual board, and validate prediction error before treating device outputs as
reliable estimates. This repository does not include raw training recordings.
