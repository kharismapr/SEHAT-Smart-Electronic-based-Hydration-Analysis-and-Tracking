"""Host-only comparisons; synthetic signals are not ESP32 sensor validation.

Run: .venv/Scripts/python tests/verify_s1_consistency.py
Requires the repository's Python dependencies and MinGW g++ on PATH.
"""

from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt
from scipy.stats import entropy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ppg_preprocessing import extract_ppg_features  # noqa: E402
from scripts.generate_s1_scaler import (  # noqa: E402
    PPG, check_model, prepare, scaler_and_training_data,
)


def compile_harness(output):
    subprocess.run(
        ["g++", "-std=c++17", "-O2", str(ROOT / "tests/s1_cpp_harness.cpp"),
         "-o", str(output)], check=True, cwd=ROOT,
    )


def syntax_check_firmware(directory):
    """Compile the .ino as C++ against API stubs; this is not an Arduino build."""
    stubs = Path(directory) / "arduino_stubs"
    stubs.mkdir()
    (stubs / "Arduino.h").write_text(
        "#pragma once\n#include <cstdint>\n#include <cmath>\n"
        "constexpr int ADC_11db=0; void delay(unsigned); unsigned long millis(); "
        "unsigned long micros(); int analogRead(int); void analogReadResolution(int); "
        "void analogSetPinAttenuation(int,int);\n"
        "struct SerialClass {void begin(int); int available(); int read(); "
        "void println(const char*); int printf(const char*,...);}; "
        "extern SerialClass Serial;\n", encoding="utf-8")
    (stubs / "Wire.h").write_text(
        "#pragma once\n#include <cstdint>\n"
        "struct WireClass {void begin(int,int); void setClock(int); "
        "void beginTransmission(uint8_t); void write(uint8_t); "
        "int endTransmission(bool=true); int requestFrom(uint8_t,uint8_t); "
        "int available(); int read();}; extern WireClass Wire;\n", encoding="utf-8")
    (stubs / "MAX30105.h").write_text(
        "#pragma once\n#include <cstdint>\n#include \"Wire.h\"\n"
        "constexpr int I2C_SPEED_STANDARD=0; struct MAX30105 { "
        "bool begin(WireClass&,int); void setup(int,int,int,int,int,int); "
        "void disableFIFORollover(); void clearFIFO(); uint16_t check(); "
        "bool available(); uint32_t getFIFOIR(); void nextSample();};\n", encoding="utf-8")
    sketch = ROOT / "SEHAT_GSR_PPG_ESP32_ML"
    subprocess.run(
        ["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-I", str(stubs),
         "-I", str(sketch), str(sketch / "SEHAT_GSR_PPG_ESP32_ML.ino")],
        check=True, cwd=ROOT,
    )
    print("Firmware .ino: host C++ syntax check passed (Arduino API stubs)")


def run_window(exe, gsr, ppg, gyro=None, flush=False):
    if gyro is None:
        gyro = np.full(len(gsr), np.nan)
    rows = "".join(
        f"{a:.9g},{b:.9g},{c:.9g}\n"
        for a, b, c in zip(gsr, ppg, gyro)
    )
    output = subprocess.run(
        [str(exe)] + (["flush"] if flush else []),
        input=rows, text=True, capture_output=True, check=True,
    ).stdout.strip().splitlines()
    parsed = []
    for line in output:
        fields = line.split(",")
        parsed.append({
            "samples": int(fields[0]), "gsr_valid": bool(int(fields[1])),
            "ppg_available": int(fields[2]),
            "raw": np.array([float(v) for v in fields[3:11]]),
            "status": fields[11], "input_valid": bool(int(fields[12])),
            "x": np.array([float(v) for v in fields[13:22]]),
            "prediction": float(fields[22]),
        })
    return parsed


def run_vectors(exe, vectors):
    text = "".join(" ".join(f"{v:.9g}" for v in row) + "\n" for row in vectors)
    output = subprocess.run(
        [str(exe), "vectors"], input=text, text=True,
        capture_output=True, check=True,
    ).stdout.strip().splitlines()
    return np.array([float(v) for v in output])


def gsr_reference(raw):
    signal = pd.Series(raw).replace([np.inf, -np.inf], np.nan)
    if not signal.notna().any():
        return np.full(3, np.nan)
    clean = signal.interpolate(limit_direction="both").to_numpy()
    if len(clean) > 9:
        b, a = butter(2, 1.0 / (0.5 * 51.2), btype="low")
        clean = filtfilt(b, a, clean)
    hist, _ = np.histogram(clean, bins=10, density=True)
    return np.array([np.mean(clean), np.var(clean), entropy(hist[hist > 0])])


def main():
    df = prepare()
    means, stds, x_train = scaler_and_training_data(df)
    model = check_model(x_train, df.fasting_duration_hr)
    with tempfile.TemporaryDirectory() as directory:
        exe = Path(directory) / "s1_cpp_harness.exe"
        compile_harness(exe)
        syntax_check_firmware(directory)

        # Every S1 training feature row, with the notebook's normalized columns.
        vectors = x_train.to_numpy(dtype=np.float32)
        cpp_prediction = run_vectors(exe, vectors)
        py_prediction = model.predict(pd.DataFrame(vectors, columns=x_train.columns))
        delta = np.abs(cpp_prediction - py_prediction)
        print(f"Model: {len(vectors)} S1 dataset vectors; "
              f"max |C++ - sklearn| = {delta.max():.9f} h")
        if delta.max() > 2e-5:
            raise AssertionError("Exported model disagrees with retrained sklearn model")
        threshold = model.estimators_[0].tree_.threshold[0]
        boundary = np.tile(vectors[0], (2, 1))
        root_feature = model.estimators_[0].tree_.feature[0]
        boundary[:, root_feature] = [threshold - 0.002, threshold + 0.002]
        boundary_delta = np.abs(
            run_vectors(exe, boundary)
            - model.predict(pd.DataFrame(boundary, columns=x_train.columns))
        )
        print(f"Model root boundary: max |C++ - sklearn| = {boundary_delta.max():.9f} h")
        if boundary_delta.max() > 2e-5:
            raise AssertionError("Tree threshold boundary disagrees")

        # Synthetic waveform with mild beat-to-beat modulation; no recording is
        # bundled in this repository, so this checks numerical implementation.
        t = np.arange(1536) / 51.2
        phase = 2 * np.pi * 1.2 * t + 0.09 * np.sin(2 * np.pi * 0.12 * t)
        synthetic_gsr = (0.7 + 0.03 * np.sin(2 * np.pi * 0.08 * t)
                         + 0.004 * np.sin(2 * np.pi * 3 * t))
        synthetic_ppg = 100000 + 2000 * np.sin(phase) + 100 * np.sin(2 * phase)
        extended_t = np.arange(2304) / 51.2
        extended_gsr = (0.7 + 0.03 * np.sin(2 * np.pi * 0.08 * extended_t)
                        + 0.004 * np.sin(2 * np.pi * 3 * extended_t))
        extended_phase = (2 * np.pi * 1.2 * extended_t
                          + 0.09 * np.sin(2 * np.pi * 0.12 * extended_t))
        extended_ppg = 100000 + 2000 * np.sin(extended_phase)
        overlap = run_window(exe, extended_gsr, extended_ppg)
        if len(overlap) != 2 or any(row["samples"] != 1536 for row in overlap):
            raise AssertionError("1536-sample window / 768-sample hop failed")
        overlap_errors = [
            np.max(np.abs(row["raw"][:3] - gsr_reference(extended_gsr[start:start + 1536])))
            for row, start in zip(overlap, (0, 768))
        ]
        print(f"Overlap: two 30-s windows, 15-s hop; "
              f"max GSR |diff|={max(overlap_errors):.9g}")
        if max(overlap_errors) > 2e-4:
            raise AssertionError("Overlapping GSR windows differ from Python")
        cases = {
            "valid": (synthetic_gsr, synthetic_ppg, False),
            "missing_ppg": (synthetic_gsr, np.full(1536, np.nan), False),
            "flat_ppg": (synthetic_gsr, np.full(1536, 100000.0), False),
            "gsr_gap": (synthetic_gsr.copy(), synthetic_ppg, False),
            "ppg_nan_gap": (synthetic_gsr, synthetic_ppg.copy(), False),
            "flat_gsr": (np.full(1536, 0.7), synthetic_ppg, False),
            "missing_gsr": (np.full(1536, np.nan), synthetic_ppg, False),
            "short": (synthetic_gsr[:100], synthetic_ppg[:100], True),
        }
        cases["gsr_gap"][0][100:104] = np.nan
        cases["ppg_nan_gap"][1][100:104] = np.nan
        for name, (gsr, ppg, flush) in cases.items():
            outputs = run_window(exe, gsr, ppg, flush=flush)
            if len(outputs) != 1:
                raise AssertionError(f"{name}: expected one window, got {len(outputs)}")
            result = outputs[0]
            try:
                reference = gsr_reference(gsr)
            except ValueError:
                # NumPy's histogram cannot make ten finite bins when filtfilt
                # leaves a constant signal with only roundoff-scale spread.
                if name != "flat_gsr":
                    raise
                reference = np.full(3, np.nan)
                print("flat_gsr: Python histogram undefined at roundoff-scale spread")
            gsr_difference = np.abs(result["raw"][:3] - reference)
            print(f"{name}: GSR |diff|={np.array2string(gsr_difference, precision=8)}, "
                  f"PPG={result['status']}/{result['ppg_available']}, "
                  f"input_valid={result['input_valid']}")
            if np.isfinite(reference).all() and np.max(gsr_difference) > 2e-4:
                raise AssertionError(f"{name}: GSR extractor differs from Python")
            if name in ("missing_gsr", "flat_gsr") and result["input_valid"]:
                raise AssertionError(f"{name}: invalid GSR produced a prediction")
            if name in ("missing_ppg", "flat_ppg", "short"):
                if result["ppg_available"] or not result["input_valid"]:
                    raise AssertionError(f"{name}: invalid PPG handling failed")
                if not np.array_equal(result["x"][3:], np.zeros(6)):
                    raise AssertionError(f"{name}: invalid PPG is not zero in normalized space")
            if result["input_valid"]:
                expected_x = np.zeros(9)
                expected_x[:3] = (result["raw"][:3] - means[:3]) / stds[:3]
                if result["ppg_available"]:
                    expected_x[3:8] = (result["raw"][3:] - means[3:]) / stds[3:]
                    expected_x[8] = 1
                vector_difference = np.max(np.abs(result["x"] - expected_x))
                if vector_difference > 1e-6:
                    raise AssertionError(f"{name}: normalized feature vector differs")
                py_model_prediction = model.predict(pd.DataFrame(
                    result["x"].astype(np.float32)[None, :], columns=x_train.columns
                ))[0]
                prediction_difference = abs(result["prediction"] - py_model_prediction)
                print(f"  normalized x={np.array2string(result['x'], precision=5)}; "
                      f"|C++ - sklearn|={prediction_difference:.9f} h")
                if prediction_difference > 2e-5:
                    raise AssertionError(f"{name}: model prediction differs")
            if name == "valid":
                python_ppg = extract_ppg_features(ppg, fs=51.2)
                py_raw = np.array([python_ppg[k] for k in PPG])
                ppg_difference = np.abs(result["raw"][3:] - py_raw)
                print(f"  HeartPy vs embedded PPG |diff|={np.array2string(ppg_difference, precision=6)}")
                print(f"  HeartPy status={python_ppg['ppg_status']}; "
                      f"embedded status={result['status']}")
                py_x = np.zeros(9, dtype=np.float32)
                py_x[:3] = (reference - means[:3]) / stds[:3]
                if python_ppg["ppg_feature_valid"]:
                    py_x[3:8] = (py_raw - means[3:]) / stds[3:]
                    py_x[8] = 1
                python_pipeline_prediction = model.predict(pd.DataFrame(
                    py_x[None, :], columns=x_train.columns
                ))[0]
                print(f"  |Python pipeline - embedded pipeline prediction|="
                      f"{abs(python_pipeline_prediction - result['prediction']):.9f} h")


if __name__ == "__main__":
    main()
