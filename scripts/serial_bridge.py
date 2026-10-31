"""
========================================================================================
SEHAT: USB Serial-to-Dashboard Telemetry Bridge
========================================================================================

Architecture:
1. Live Sensor Stream (Every 250ms) -> POST /api/telemetry/live (Live UI gauges, zero DB writes)
2. Finalized 30s ML Prediction Window -> POST /api/measurements (Saves clean ML result to SQLite)
3. Bidirectional Device Commands    -> GET /api/device/command (Sends 'c' / 's' / 'f' to ESP32)

Usage:
  python scripts/serial_bridge.py [COM_PORT]
"""

import sys
import re
import time
import serial
import serial.tools.list_ports
import requests

BAUD_RATE = 115200
API_BASE_URL = 'http://localhost:5000/api'


def find_default_com_port():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return None
    for p in ports:
        desc = (p.description or '').lower()
        if any(keyword in desc for keyword in ['cp210', 'ch340', 'uart', 'usb serial', 'esp32']):
            return p.device
    return ports[0].device


def main():
    target_port = sys.argv[1] if len(sys.argv) > 1 else find_default_com_port()

    if not target_port:
        print("[Error] No active COM ports detected. Please plug in your ESP32 via USB.")
        sys.exit(1)

    print("\n=======================================================")
    print("  SEHAT: USB Serial -> Live Dashboard Telemetry Bridge")
    print(f"  Target Port : {target_port} @ {BAUD_RATE} baud")
    print(f"  Backend API : {API_BASE_URL}")
    print("=======================================================\n")

    while True:
        try:
            print(f"[Connecting] Opening serial connection to {target_port}...")
            ser = serial.Serial(target_port, BAUD_RATE, timeout=0.05)
            print(f"[Connected] Active link established with ESP32 on {target_port}.\n")

            latest_gsr = 9.5
            latest_bpm = 72.0
            latest_spo2 = None
            spo2_valid = False
            latest_rmssd = 32.0
            latest_hours = None

            last_live_post = 0
            last_cmd_poll = 0

            while True:
                # 1. Read incoming Serial lines from ESP32
                raw_bytes = ser.readline()
                if raw_bytes:
                    line = raw_bytes.decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"[ESP32] {line}")

                        # A. Extract Live Instant GSR Conductance
                        # Matches: GSR_us=8.45, GSR: 8.45 uS, GSR=8.45, Mean=8.45 uS, konduktansi=8.45 uS
                        gsr_match = re.search(r'(?:GSR_us|GSR_mean|GSR|konduktansi|Mean)\s*[:=]\s*([\d.]+)', line, re.IGNORECASE)
                        if gsr_match:
                            try:
                                val = float(gsr_match.group(1))
                                if val > 0:
                                    latest_gsr = val
                            except ValueError:
                                pass

                        # B. Extract PPG / HRV Features
                        # Matches: BPM=75.0, BPM: 75, HR=75, HR: 75, mean_hr=75, Heart Rate: 75
                        hr_match = re.search(r'(?:mean_hr|Heart\s*Rate|BPM|HR)\s*[:=]\s*([\d.]+)', line, re.IGNORECASE)
                        if hr_match:
                            try:
                                hr = float(hr_match.group(1))
                                if 35 <= hr <= 220:
                                    latest_bpm = hr
                            except ValueError:
                                pass

                        rmssd_match = re.search(r'rmssd\s*[:=]\s*([\d.]+)', line, re.IGNORECASE)
                        if rmssd_match:
                            try:
                                latest_rmssd = float(rmssd_match.group(1))
                            except ValueError:
                                pass

                        # C. Extract SpO2 (Blood Oxygen Saturation)
                        spo2_match = re.search(r'SpO2\s*[:=]\s*(null|[\d.]+)(?:\s*%)?(?:\s*\|\s*valid=([01]))?', line, re.IGNORECASE)
                        if spo2_match:
                            try:
                                val_str = spo2_match.group(1).lower()
                                flag = spo2_match.group(2)
                                if flag is not None:
                                    spo2_valid = (flag == '1')
                                    latest_spo2 = float(val_str) if spo2_valid and val_str != 'null' else None
                                else:
                                    val = float(val_str)
                                    if 50 <= val <= 100:
                                        latest_spo2 = val
                                        spo2_valid = True
                            except ValueError:
                                pass

                        # D. Extract ExtraTrees S1 Model Inferred Hours & Commit to SQLite
                        if 'fasting-duration estimate' in line:
                            hours_match = re.search(r'fasting-duration estimate\s*=\s*([\d.]+)', line)
                            if hours_match:
                                try:
                                    latest_hours = float(hours_match.group(1))
                                except ValueError:
                                    pass

                            payload = {
                                'bpm': round(latest_bpm, 1),
                                'spo2': latest_spo2,
                                'spo2Valid': spo2_valid,
                                'gsr': round(latest_gsr, 2),
                                'predictedHoursSinceHydration': round(latest_hours, 2) if latest_hours is not None else 4.0,
                                'notes': f'ESP32 ExtraTrees S1 (RMSSD: {latest_rmssd:.1f}ms)'
                            }
                            try:
                                res = requests.post(f"{API_BASE_URL}/measurements", json=payload, timeout=1.5)
                                if res.status_code in (200, 201):
                                    print(f"\n  ⭐ [ML Result Recorded] Hours={payload['predictedHoursSinceHydration']}h | BPM={payload['bpm']} | GSR={payload['gsr']} uS\n")
                            except requests.exceptions.RequestException as e:
                                print(f"  [History Sync Error] {e}")

                now = time.time()

                # 2. Fast 250ms Live Stream to /api/telemetry/live (Live UI display only, no DB writes)
                if now - last_live_post >= 0.25:
                    last_live_post = now
                    live_payload = {
                        'bpm': round(latest_bpm, 1),
                        'spo2': latest_spo2,
                        'spo2Valid': spo2_valid,
                        'gsr': round(latest_gsr, 2),
                        'rmssd': round(latest_rmssd, 1),
                        'predictedHours': round(latest_hours, 2) if latest_hours is not None else None
                    }
                    try:
                        requests.post(f"{API_BASE_URL}/telemetry/live", json=live_payload, timeout=0.3)
                    except requests.exceptions.RequestException:
                        pass

                # 3. Check for Dashboard Commands ('c', 's', 'f', 'r')
                if now - last_cmd_poll >= 0.3:
                    last_cmd_poll = now
                    try:
                        cmd_res = requests.get(f"{API_BASE_URL}/device/command", timeout=0.3)
                        if cmd_res.status_code == 200:
                            cmd_data = cmd_res.json()
                            cmd = cmd_data.get('command')
                            if cmd:
                                print(f"\n[Dashboard Command Received] Sending '{cmd}' to ESP32...")
                                ser.write(f"{cmd}\n".encode('utf-8'))
                                ser.flush()
                        elif cmd_res.status_code == 404 and not getattr(main, '_warned_server_404', False):
                            print("\n[Warning] Backend server is running an older instance without /api/device/command. Please restart 'node server.js'.")
                            main._warned_server_404 = True
                    except requests.exceptions.RequestException:
                        pass

        except serial.SerialException as err:
            print(f"[Serial Disconnected] {err}")
            print("[Retrying] Reconnecting in 3 seconds...\n")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n[Bridge Stopped by User]")
            break


if __name__ == '__main__':
    main()
