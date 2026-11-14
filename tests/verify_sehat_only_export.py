"""Compile and compare the new header with its SEHAT-only sklearn pipeline.

Checks raw features, existing makeModelInput, unavailable PPG, float32 split
boundaries, invalid arguments, and the firmware with the SEHAT-only model.
Host compilation uses Arduino stubs; this is not an ESP32 hardware build.
"""
from pathlib import Path
import json
from hashlib import sha256
import subprocess
import sys
import tempfile

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_et_sehat_only import read_legacy_scaler  # noqa: E402
from verify_s1_consistency import syntax_check_firmware  # noqa: E402

OUT = ROOT / "sehat_only_results"


HARNESS = r'''
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include "s1_features.h"
typedef float float32;
#include "et_sehat_only.h"
#include "et_sehat_only.h"

int main(int argc, char** argv) {
  std::cout << std::setprecision(17);
  const std::string mode = argc > 1 ? argv[1] : "legacy";
  if (mode == "invalid") {
    float x[9] = {};
    if (!std::isnan(hydration_et_predict(nullptr, 9))) return 1;
    if (!std::isnan(hydration_et_predict(x, 8))) return 2;
    if (!std::isnan(hydration_et_predict(x, 10))) return 3;
    x[8] = NAN;
    if (!std::isnan(hydration_et_predict(x, 9))) return 4;
    x[8] = 0.5f;
    if (!std::isnan(hydration_et_predict(x, 9))) return 5;
    x[8] = 1.0f;
    x[0] = INFINITY;
    if (!std::isnan(hydration_et_predict(x, 9))) return 6;
    return 0;
  }
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::istringstream row(line);
    double values[9];
    for (double& value : values) {
      std::string token;
      if (!(row >> token)) return 7;
      value = std::strtod(token.c_str(), nullptr);
    }
    float x[9];
    for (int i = 0; i < 9; ++i) x[i] = static_cast<float>(values[i]);
    if (mode == "features") {
      sehat_gsr::Features g;
      g.gsr_mean = values[0]; g.gsr_var = values[1]; g.gsr_entropy = values[2];
      g.valid = true; g.window_samples = 1536;
      sehat_ppg::Features p;
      p.mean_hr = values[3]; p.rmssd = values[4]; p.sdnn = values[5];
      p.pnn50 = values[6];
      p.n_peaks = std::isfinite(values[7]) ? static_cast<uint16_t>(values[7]) : 0;
      p.window_samples = 1536;
      p.ppg_available = values[8] == 1.0;
      p.ppg_feature_valid = p.ppg_available;
      if (!sehat_s1::makeModelInput(g, p, x)) return 8;
    }
    const float result = mode == "raw" ? sehat_only::predictRaw(x, 9)
                                        : hydration_et_predict(x, 9);
    std::cout << result << '\n';
  }
}
'''


def run(exe, mode, vectors):
    text = "".join(" ".join(format(float(v), ".17g") for v in row) + "\n" for row in vectors)
    result = subprocess.run([str(exe), mode], input=text, text=True,
                            capture_output=True, check=True, cwd=ROOT)
    return np.array([float(v) for v in result.stdout.splitlines()])


def legacy_vectors(raw, means, stds):
    values = np.empty_like(raw, dtype=np.float32)
    values[:, :8] = (raw[:, :8] - means) / stds
    values[:, 8] = raw[:, 8]
    values[raw[:, 8] == 0, 3:8] = 0.0
    return values


def decode_legacy(values, means, stds):
    raw = np.empty(values.shape, dtype=np.float32)
    raw[:, :8] = values[:, :8].astype(np.float64) * stds + means
    raw[:, 8] = values[:, 8]
    raw[values[:, 8] == 0, 3:8] = np.nan
    return raw


def main():
    contract = json.loads((OUT / "models/inference_contract.json").read_text(encoding="utf-8"))
    model = joblib.load(OUT / "models/et_sehat_only_pipeline.joblib")
    for file, expected_hash in [
        (ROOT / contract["header"], contract["header_sha256"]),
        (OUT / "models/et_sehat_only_pipeline.joblib", contract["model_sha256"]),
        (OUT / "features_sehat.csv", contract["training_features_sha256"]),
        (ROOT / "SEHAT_GSR_PPG_ESP32_ML/s1_scaler.h", contract["legacy_scaler_sha256"]),
    ]:
        assert sha256(file.read_bytes()).hexdigest() == expected_hash, f"Artifact hash mismatch: {file}"
    columns = contract["features_in_order"]
    data = pd.read_csv(OUT / "features_sehat.csv")
    raw = data[columns].to_numpy(float)
    means, stds = read_legacy_scaler()
    np.testing.assert_array_equal(means, contract["legacy_mean"])
    np.testing.assert_array_equal(stds, contract["legacy_std"])
    medians = model.named_steps["imputer"].statistics_
    imputed = model.named_steps["imputer"].transform(data[columns])
    rng = np.random.default_rng(42)
    random = rng.uniform(np.min(imputed, axis=0), np.max(imputed, axis=0), size=(1000, 9))
    random[:, 8] = rng.integers(0, 2, size=len(random))
    random[random[:, 8] == 0, 3:8] = np.nan
    boundaries = []
    for estimator in model.named_steps["model"].estimators_:
        for index, threshold in zip(estimator.tree_.feature, estimator.tree_.threshold):
            if index < 0:
                continue
            rounded = np.float32(threshold)
            for value in [np.nextafter(rounded, np.float32(-np.inf)), rounded,
                          np.nextafter(rounded, np.float32(np.inf))]:
                row = medians.copy()
                row[index] = value
                boundaries.append(row)
    missing = np.tile(medians, (10, 1))
    for i in range(9):
        missing[i, i] = np.nan
    missing[-1, :] = np.nan
    raw_vectors = np.vstack([raw, random, boundaries, missing]).astype(np.float32)

    def predict(vectors):
        return model.predict(pd.DataFrame(vectors, columns=columns)).astype(np.float32).astype(float)

    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        source = directory / "verify.cpp"
        source.write_text(HARNESS, encoding="utf-8")
        exe = directory / "verify.exe"
        subprocess.run(["g++", "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-I", str(ROOT / "SEHAT_GSR_PPG_ESP32_ML"), str(source), "-o", str(exe)], check=True)
        subprocess.run([str(exe), "invalid"], check=True)
        raw_cpp = run(exe, "raw", raw_vectors)
        raw_expected = predict(raw_vectors)
        np.testing.assert_allclose(raw_cpp, raw_expected, atol=1e-6, rtol=0)
        raw_error = float(np.max(np.abs(raw_cpp - raw_expected)))

        # This traverses the actual unchanged makeModelInput function in C++.
        legacy = legacy_vectors(raw, means, stds)
        expected = predict(decode_legacy(legacy, means, stds))
        full_cpp = run(exe, "features", raw)
        np.testing.assert_allclose(full_cpp, expected, atol=1e-6, rtol=0)
        integration_error = float(np.max(np.abs(full_cpp - expected)))

        # Explicitly distinguish valid normalized zeros from unavailable PPG.
        valid_zero = np.zeros((1, 9), dtype=np.float32)
        valid_zero[:, 8] = 1
        unavailable = legacy.copy()
        unavailable[:, 8] = 0
        unavailable[:, 3:8] = np.nan  # Placeholders must be ignored at flag zero.
        wrapper_vectors = np.vstack([legacy, valid_zero, unavailable,
                                     legacy_vectors(random, means, stds)])
        wrapper_cpp = run(exe, "legacy", wrapper_vectors)
        wrapper_expected = predict(decode_legacy(wrapper_vectors, means, stds))
        np.testing.assert_allclose(wrapper_cpp, wrapper_expected, atol=1e-6, rtol=0)
        wrapper_error = float(np.max(np.abs(wrapper_cpp - wrapper_expected)))
        roundtrip_error = float(np.max(np.abs(expected - predict(raw.astype(np.float32)))))
        syntax_directory = directory / "new_model"
        syntax_directory.mkdir()
        syntax = "passed; SEHAT-only sketch"
        existing_errors = []
        try:
            syntax_check_firmware(syntax_directory, model_header="et_sehat_only.h")
        except subprocess.CalledProcessError as new_error:
            # Detect existing sketch failures separately from new model regressions.
            baseline_directory = directory / "old_model"
            baseline_directory.mkdir()
            try:
                syntax_check_firmware(baseline_directory)
            except subprocess.CalledProcessError as baseline_error:
                def error_messages(result):
                    return [line.split("error: ", 1)[1] for line in result.stderr.splitlines() if "error: " in line]
                existing_errors = error_messages(baseline_error)
                assert existing_errors and error_messages(new_error) == existing_errors, new_error.stderr
                syntax = "blocked: identical existing syntax errors with old and new model headers"
            else:
                raise new_error

    validation = dict(
        header_numerical_checks_passed=True, compiler="g++ C++11 -O2 -Wall -Wextra -Werror -pedantic",
        raw_vectors=len(raw_vectors), split_boundary_vectors=len(boundaries),
        training_windows_through_actual_makeModelInput=len(raw), wrapper_vectors=len(wrapper_vectors),
        raw_max_abs_error_hr=raw_error, wrapper_max_abs_error_hr=wrapper_error,
        makeModelInput_max_abs_error_hr=integration_error,
        legacy_scaler_roundtrip_max_prediction_change_hr=roundtrip_error,
        null_length_availability_nonfinite_checks=True,
        sketch_syntax_with_new_include=syntax,
        existing_sketch_errors=existing_errors,
        esp32_hardware_build=False,
    )
    (OUT / "export_validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
