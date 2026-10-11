# MAX30102 PPG preprocessing with GY-9250 on ESP32

Open [`MAX30102_Preprocessing_ESP32.ino`](MAX30102_Preprocessing_ESP32/MAX30102_Preprocessing_ESP32.ino)
in Arduino IDE. Keep
[`ppg_preprocessing_esp32.h`](MAX30102_Preprocessing_ESP32/ppg_preprocessing_esp32.h)
in the same sketch folder. Install **SparkFun MAX3010x Pulse and Proximity Sensor Library**
through Library Manager; the header is named `MAX30105.h` and [SparkFun states
that it also supports MAX30102](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library).
For an ESP32 DevKit, the sketch defaults to SDA = GPIO21 and SCL = GPIO22.
Connect **both** MAX30102 and GY-9250 SDA to GPIO21, both SCL to GPIO22,
and all grounds together. Connect each module's VCC/VIN to the supply stated
for **that particular breakout board**; GY-9250 boards can differ in their
onboard power circuitry. The MPU-9250 chip and ESP32 I2C pins use 3.3 V
logic, so ensure SDA/SCL are pulled up to 3.3 V. If the GY-9250 `NCS` pin
is exposed without a board pull-up, hold it high for I2C. `AD0` low selects
address 0x68, high selects 0x69; the sketch
checks both. Change `kSdaPin`/`kSclPin` for another ESP32 board. The sketch
uses only the gyro; it does not need the GY-9250 accelerometer or magnetometer.
Use Serial Monitor at **115200 baud**. First results appear after about 30 s;
subsequent 30 s windows have 50% overlap. Send `f` to emit the partial tail or
`r` to restart a recording.

## Relation to the training pipeline

The notebook `TRAIN_SEHAT_FINAL.ipynb` delegates PPG preprocessing to
`ppg_preprocessing.py` with these settings:

| Stage | ESP32 sketch |
| --- | --- |
| Sampling | MAX30102 FIFO at 50 Hz, linear interpolation to 51.2 Hz |
| Window | 1536 samples (30 s), 768-sample hop (50% overlap) |
| Missing data | Interpolate only interior PPG gaps up to 12 samples; other gaps invalidate features |
| Baseline | Butterworth high-pass order 4 at 0.5 Hz, forward/backward |
| Motion-dependent low-pass | Butterworth order 4, 4 Hz for low motion and 2.5 Hz for high motion, forward/backward |
| Motion score | Reflected 1 s mean of absolute changes in gyro magnitude; high if above the window's mean score |
| Transition | 13-sample reflected smoothing of the high-motion flag |
| Final smoothing | 9-sample reflected moving average |
| Output | `mean_hr`, `rmssd`, `sdnn`, `pnn50`, `n_peaks`, `ppg_available` and quality fields |

The paper `[3] referensi utama.pdf` §4.1.5/Figure 5 describes gyro-adaptive
filtering, smoothing and HeartPy feature extraction. It does not provide
filter cutoffs or orders. Those numbers come from this project's Python
pipeline. When gyro readings are unavailable, the Python code selects the
low-motion 4 Hz branch; the sketch does the same and reports
`gyro_missing=1.000`.

The `.ino` now initializes the MPU-9250 on GY-9250 using `Wire`, checks its
`WHO_AM_I` value (0x71), and reads the three gyro axes in degrees/second.
It configures ±500 dps, the range listed for the paper's Shimmer gyro, with
100 Hz MPU output. At each 50 Hz MAX30102 FIFO sample it reads the latest
gyro sample, then interpolates each gyro axis with IR to 51.2 Hz. The two
sensors do not share a hardware clock, so this is approximate alignment.
If MPU initialization or an individual I2C read fails, the sketch keeps PPG
samples and reports gyro missing data; sustained missing gyro selects the
4 Hz branch. Register addresses, device ID, and sensitivity follow the
[TDK MPU-9250 register map](https://invensense.tdk.com/wp-content/uploads/2015/02/RM-MPU-9250A-00-v1.6.pdf)
and [product specification](https://invensense.tdk.com/wp-content/uploads/2015/02/PS-MPU-9250A-01-v1.1.pdf).

The sketch uses windowed forward/backward filtering. Python filters the whole
continuous recording before splitting windows, so window-edge samples can
differ. The C++ filter coefficients and reflected smoothing match the Python
no-gyro branch within normal float rounding on a complete synthetic window.
The sketch detects peaks and calculates RR features with a **small embedded
algorithm**. It cannot run HeartPy's peak fitting, high-precision resampling
and quotient RR cleaner exactly, so HRV results can differ from training.
`pnn50` is a percentage, and `rmssd`/`sdnn` are milliseconds. A failed window
keeps `ppg_available=0` and missing metrics as NaN; it does not invent a
heartbeat. For model inference, apply the same per-subject training z-score
to valid PPG features and the notebook's zero-fill rule for unavailable PPG.

The notebook's sensor is calibrated Shimmer PPG in mV; MAX30102 produces IR
ADC counts. Beat timing can still be extracted, but model performance on
MAX30102 data has not been established. Check against a trusted reference
before treating estimates as physiological measurements.
