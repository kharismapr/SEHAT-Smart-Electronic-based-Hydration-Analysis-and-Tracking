# SEHAT Unified ESP32 Firmware

This directory houses the unified **on-device firmware** that executes the complete SEHAT biosignal pipeline directly on an ESP32:
1. **Multisensor Acquisition**: Reads MAX30102 (PPG & SpO2), GY-9250 (IMU Gyroscope), and Grove GSR (Galvanic Skin Response).
2. **On-Device Preprocessing & DSP**: Butterworth bandpass/lowpass filtering, motion artifact compensation, and statistical/HRV feature extraction.
3. **On-Device TinyML Inference**: Evaluates the pre-compiled Random Forest model (`rf_hydration_model.h`) to predict hydration state ($y_{\text{hat}}$).
4. **Wi-Fi Ingestion**: Transmits telemetry and classification packets over HTTP POST directly to the SEHAT backend database.

---

## 1. Pinout Wiring

### I2C Bus Configuration (Shared by MAX30102, GY-9250)
| Sensor | VCC | GND | SDA | SCL |
| :--- | :--- | :--- | :--- | :--- |
| **MAX30102** | 3.3V | GND | `D4` on XIAO (GPIO 21 on DevKit) | `D5` on XIAO (GPIO 22 on DevKit) |
| **GY-9250 / MPU-9250** | 3.3V | GND | `D4` on XIAO (GPIO 21 on DevKit) | `D5` on XIAO (GPIO 22 on DevKit) |

### Analog Sensor (Grove GSR)
| Sensor Pin | ESP32 Pin |
| :--- | :--- |
| **Grove GSR SIG** | `A0` on XIAO (GPIO 2 on C3; GPIO 1 on S3; GPIO 34 on DevKit) |
| **Grove GSR VCC** | `3.3V` |
| **Grove GSR GND** | `GND` |

---

## 2. Required Arduino IDE Libraries

Install these via **Tools > Manage Libraries...** in the Arduino IDE:
1. `SparkFun MAX3010x Pulse and Proximity Sensor Library` (by SparkFun, includes `spo2_algorithm.h`)
2. `ArduinoJson` (v6 or v7, by Benoit Blanchon)

## SpO2 Data
The MAX30102 red and IR FIFO channels feed the SparkFun/Maxim SpO2 algorithm.
The firmware sends `spo2` (percent, or JSON `null`) and `spo2Valid` (boolean)
with each measurement. A valid value requires a full 100-sample window and a
successful algorithm result. The serial bridge forwards the same fields to
`/api/telemetry/live`; `/api/measurements` stores them in SQLite. Old records
have `spo2: null` and `spo2Valid: 0`.

Use a reference pulse oximeter to evaluate accuracy before interpreting these
readings clinically.

---

## 3. Configuration & Flashing

1. Open `SEHAT_ESP32_Unified.ino` in Arduino IDE.
2. Update your Wi-Fi credentials and the IP address of the machine running the SEHAT backend server:
   ```cpp
   const char* WIFI_SSID = "YOUR_WIFI_SSID";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   const char* SERVER_URL = "http://192.168.1.100:5000/api/measurements";
   ```
3. Select your ESP32 board and COM port, then click **Upload**.
4. Open the **Serial Monitor at 115200 baud**.

---

## 4. Running the Entire SEHAT System

### Step 1: Start the Backend Server
```powershell
cd D:\SEHAT-Smart-Electronic-based-Hydration-Analysis-and-Tracking\server
npm start
```
The server will start listening on `http://localhost:5000`.

### Step 2: Start the Web Dashboard
```powershell
cd D:\SEHAT-Smart-Electronic-based-Hydration-Analysis-and-Tracking\sehat-dashboard
npm run dev
```
Open `http://localhost:5173` in your browser.

### Step 3: Power on the ESP32 Wearable
As soon as the ESP32 connects to Wi-Fi and gathers a 30-second window:
- It runs the Random Forest model on-chip.
- It sends the telemetry packet via HTTP POST to the backend.
- The dashboard automatically displays the incoming biometric data in real-time.
