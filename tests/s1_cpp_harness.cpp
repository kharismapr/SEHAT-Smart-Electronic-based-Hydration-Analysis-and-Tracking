// Host-side contract check for the exact headers compiled into the ESP32 sketch.
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

#include "../SEHAT_GSR_PPG_ESP32_ML/s1_features.h"
typedef float float32;
#include "../SEHAT_GSR_PPG_ESP32_ML/et_hydration_model_S1.h"

void number(double value) {
  if (std::isfinite(value)) std::cout << value;
  else std::cout << "nan";
}

void result(const sehat_gsr::Features& g, const sehat_ppg::Features& p) {
  float x[sehat_s1::feature_count] = {};
  const bool ok = sehat_s1::makeModelInput(g, p, x);
  std::cout << g.window_samples << ',' << (g.valid ? 1 : 0) << ','
            << (p.ppg_available ? 1 : 0) << ',';
  number(g.gsr_mean); std::cout << ',';
  number(g.gsr_var); std::cout << ',';
  number(g.gsr_entropy); std::cout << ',';
  number(p.mean_hr); std::cout << ',';
  number(p.rmssd); std::cout << ',';
  number(p.sdnn); std::cout << ',';
  number(p.pnn50); std::cout << ',';
  number(p.n_peaks); std::cout << ',';
  std::cout << sehat_ppg::statusName(p.status) << ',' << (ok ? 1 : 0);
  for (float value : x) { std::cout << ','; number(ok ? value : NAN); }
  std::cout << ',';
  number(ok ? hydration_et_predict(x, sehat_s1::feature_count) : NAN);
  std::cout << '\n';
}

int main(int argc, char** argv) {
  std::cout << std::setprecision(17);
  if (argc > 1 && std::string(argv[1]) == "vectors") {
    float x[sehat_s1::feature_count];
    while (true) {
      for (float& value : x) if (!(std::cin >> value)) return 0;
      number(hydration_et_predict(x, sehat_s1::feature_count));
      std::cout << '\n';
    }
  }
  sehat_gsr::Processor gsr;
  sehat_ppg::Processor ppg;
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::istringstream row(line);
    std::string field[3];
    for (int i = 0; i < 3; ++i) {
      if (!std::getline(row, field[i], i < 2 ? ',' : '\n')) return 2;
    }
    const float g = std::strtof(field[0].c_str(), nullptr);
    const float p = std::strtof(field[1].c_str(), nullptr);
    const float gyro = std::strtof(field[2].c_str(), nullptr);
    sehat_gsr::Features gf;
    sehat_ppg::Features pf;
    const bool g_ready = gsr.addSample(g, gf);
    const bool p_ready = ppg.addSample(p, gyro, pf);
    if (g_ready != p_ready) return 3;
    if (g_ready) result(gf, pf);
  }
  if (argc > 1 && std::string(argv[1]) == "flush") {
    sehat_gsr::Features gf;
    sehat_ppg::Features pf;
    const bool g_ready = gsr.flush(gf);
    const bool p_ready = ppg.flush(pf);
    if (g_ready != p_ready) return 4;
    if (g_ready) result(gf, pf);
  }
  return 0;
}
