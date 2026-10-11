# SEHAT Biometric Telemetry & Database Server

A lightweight, zero-configuration local backend and SQLite database for the **SEHAT** (*Smart Electronic-based Hydration Analysis and Tracking*) system.

---

## 1. Database Schema (`measurements` in `sehat.db`)

The database explicitly separates raw physiological sensor feeds from the inferred target variable:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `TEXT PRIMARY KEY` | Unique measurement ID |
| `timestamp` | `INTEGER NOT NULL` | Epoch millisecond timestamp |
| `created_at` | `TEXT NOT NULL` | Human-readable ISO 8601 UTC timestamp |
| `bpm` | `REAL NOT NULL` | **Raw Sensor**: Heart rate from PPG (MAX30102) |
| `gsr` | `REAL NOT NULL` | **Raw Sensor**: Galvanic skin conductance in $\mu\text{S}$ |
| `temperature` | `REAL NOT NULL` | **Raw Sensor**: Body / skin temperature in °C |
| `humidity` | `REAL NOT NULL` | **Raw Sensor**: Ambient relative humidity in % |
| `predicted_hours_since_hydration` | `REAL NOT NULL` | **Model Output**: Predicted hours dry ($y_{hat}$), NOT raw counted time |
| `status_key` | `TEXT NOT NULL` | `WELL_HYDRATED` ($\le 10\text{h}$) or `AT_RISK` ($> 10\text{h}$) |
| `notes` | `TEXT` | Optional clinical / test annotations |

---

## 2. Running the Server

From the `server` directory:

```bash
# Start server
npm start

# Or with live auto-reload
npm run dev
```

The server listens on `http://localhost:5000` (or your local IP for external ESP32 access).

---

## 3. REST API Endpoints

### `GET /api/health`
Checks server status and database connectivity.

### `GET /api/measurements`
Retrieves measurement history sorted newest first.
* **Query parameters**: `limit` (default: 200)

### `GET /api/measurements/latest`
Retrieves the most recent measurement.

### `POST /api/measurements`
Records a new measurement. Can be submitted by the React dashboard or directly from an ESP32/microcontroller.

**Payload Example (Direct sensor input from ESP32)**:
```json
{
  "bpm": 76.5,
  "gsr": 8.2,
  "temperature": 36.6,
  "humidity": 52.0
}
```
*(If `predicted_hours_since_hydration` is omitted, the server automatically computes the regression inference).*

### `DELETE /api/measurements`
Clears all measurement history.

### `DELETE /api/measurements/:id`
Deletes a specific measurement by ID.

---

## 4. ESP32 Arduino Integration Example

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "http://192.168.1.100:5000/api/measurements";

void sendMeasurement(float bpm, float gsr, float temp, float humidity) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<200> doc;
    doc["bpm"] = bpm;
    doc["gsr"] = gsr;
    doc["temperature"] = temp;
    doc["humidity"] = humidity;

    String jsonString;
    serializeJson(doc, jsonString);

    int httpResponseCode = http.POST(jsonString);
    http.end();
  }
}
```
