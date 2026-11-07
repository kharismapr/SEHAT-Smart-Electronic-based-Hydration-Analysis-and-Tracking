#!/usr/bin/env python3
"""Capture SEHAT raw PPG/GSR/MPU9250 samples from ESP32 Serial."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
except ImportError as exc:
    raise SystemExit("pyserial belum terpasang. Jalankan: pip install pyserial") from exc

BAUD_RATE = 115200
DATA_COLUMNS = [
    "subject_id",
    "session_id",
    "last_drink_time",
    "record_time",
    "fasting_duration_hr",
    "sample_index",
    "elapsed_us",
    "elapsed_sec",
    "ppg_ir_raw",
    "gsr_adc12_raw",
    "gsr_adc10_scaled",
    "gsr_conductance_us",
    "gyro_x_dps",
    "gyro_y_dps",
    "gyro_z_dps",
    "gyro_magnitude_dps",
]


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    if not cleaned:
        raise ValueError("ID tidak boleh kosong.")
    return cleaned


def parse_local_datetime(value: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Format waktu harus YYYY-MM-DD HH:MM, contoh 2026-11-06 09:00.") from exc


def read_line(ser: serial.Serial) -> str:
    try:
        return ser.readline().decode("utf-8", errors="replace").strip()
    except serial.SerialException as exc:
        raise RuntimeError(f"Koneksi serial terputus: {exc}") from exc


def wait_for_calibration(ser: serial.Serial, timeout_sec: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        line = read_line(ser)
        if not line:
            continue
        print(line)
        if line.startswith("INFO,GSR_CALIBRATION_DONE"):
            return
        if line.startswith("ERROR,"):
            raise RuntimeError(line)
    raise TimeoutError("Tidak menerima konfirmasi kalibrasi GSR dari ESP32.")


def parse_data_line(line: str) -> list[str] | None:
    if not line.startswith("DATA,"):
        return None
    parts = line.split(",")
    if len(parts) != 11:
        print(f"Peringatan: format DATA tidak sesuai, dilewati: {line}", file=sys.stderr)
        return None
    return parts[1:]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merekam raw PPG, GSR, dan gyroscope dari firmware SEHAT."
    )
    parser.add_argument("port", help="Serial port ESP32, contoh COM5 atau /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=BAUD_RATE)
    args = parser.parse_args()

    try:
        subject_id = safe_name(input("Subject ID (contoh S12): "))
        session_id = safe_name(input("Session ID (contoh S12_F01): "))
        last_drink_dt = parse_local_datetime(
            input("Last drink time (YYYY-MM-DD HH:MM): ")
        )
        duration_min = float(input("Durasi perekaman dalam menit [5]: ").strip() or "5")
        if duration_min <= 0:
            raise ValueError("Durasi perekaman harus lebih dari 0 menit.")
    except ValueError as exc:
        print(f"Input tidak valid: {exc}", file=sys.stderr)
        return 2

    output_dir = Path("sehat_raw_data")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nMembuka {args.port} pada {args.baud} baud...")
    try:
        with serial.Serial(args.port, args.baud, timeout=1) as ser:
            # Opening an ESP32 serial port commonly resets the board.
            time.sleep(2.5)
            ser.reset_input_buffer()

            print("\nTAHAP 1 - Kalibrasi GSR")
            print("Pastikan elektroda/kontak GSR tidak menyentuh kulit.")
            input("Tekan Enter untuk menjalankan kalibrasi GSR...")
            ser.write(b"c\n")
            wait_for_calibration(ser)

            print("\nTAHAP 2 - Pemasangan sensor")
            print("Pasang kembali elektroda GSR dan letakkan jari pada MAX30102.")
            print("Subjek duduk dengan posisi yang konsisten dan minim gerakan.")
            input("Tekan Enter untuk memulai perekaman...")
            ser.reset_input_buffer()
            ser.write(b"s\n")

            record_time: datetime | None = None
            fasting_duration_hr: float | None = None
            csv_file = None
            writer = None
            output_path: Path | None = None
            saved = 0
            duration_us = int(duration_min * 60 * 1_000_000)
            last_elapsed_us = -1
            start_wall = time.monotonic()

            print("Menunggu sampel pertama...")
            try:
                while True:
                    line = read_line(ser)
                    if not line:
                        # Guard against a sensor/firmware hang after start.
                        if record_time is None and time.monotonic() - start_wall > 20:
                            raise TimeoutError("Tidak ada sampel DATA selama 20 detik.")
                        if record_time is not None and time.monotonic() - start_wall > duration_min * 60 + 30:
                            raise TimeoutError("Perekaman melewati batas waktu tanpa menerima sampel yang cukup.")
                        continue

                    if line.startswith("INFO,") or line.startswith("ERROR,"):
                        print(line)
                        if line.startswith("ERROR,"):
                            raise RuntimeError(line)
                        continue

                    values = parse_data_line(line)
                    if values is None:
                        continue

                    sample_index = int(values[0])
                    elapsed_us = int(values[1])
                    if elapsed_us >= duration_us:
                        ser.write(b"f\n")
                        break

                    if record_time is None:
                        record_time = datetime.now()
                        if last_drink_dt > record_time:
                            raise ValueError("Last drink time berada setelah record time. Periksa input.")
                        fasting_duration_hr = (record_time - last_drink_dt).total_seconds() / 3600.0
                        stamp = record_time.strftime("%Y%m%d%H%M%S")
                        output_path = output_dir / (
                            f"{stamp}_{subject_id}_{session_id}_raw.csv"
                        )
                        csv_file = output_path.open("w", newline="", encoding="utf-8-sig")
                        writer = csv.DictWriter(csv_file, fieldnames=DATA_COLUMNS)
                        writer.writeheader()
                        print(f"\nPerekaman dimulai: {record_time:%Y-%m-%d %H:%M:%S}")
                        print(f"Fasting duration tercatat: {fasting_duration_hr:.4f} jam")
                        print(f"File output: {output_path}")

                    assert writer is not None
                    row = {
                        "subject_id": subject_id,
                        "session_id": session_id,
                        "last_drink_time": last_drink_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "record_time": record_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "fasting_duration_hr": f"{fasting_duration_hr:.6f}",
                        "sample_index": sample_index,
                        "elapsed_us": elapsed_us,
                        "elapsed_sec": f"{elapsed_us / 1_000_000:.6f}",
                        "ppg_ir_raw": values[2],
                        "gsr_adc12_raw": values[3],
                        "gsr_adc10_scaled": values[4],
                        "gsr_conductance_us": values[5],
                        "gyro_x_dps": values[6],
                        "gyro_y_dps": values[7],
                        "gyro_z_dps": values[8],
                        "gyro_magnitude_dps": values[9],
                    }
                    writer.writerow(row)
                    saved += 1
                    last_elapsed_us = elapsed_us

                    if saved % 256 == 0:
                        csv_file.flush()
                        print(f"Terekam {saved} sampel ({elapsed_us / 1_000_000:.1f} detik)")

            except KeyboardInterrupt:
                print("\nPerekaman dihentikan oleh operator.")
                ser.write(b"f\n")
            finally:
                # Stop acquisition even if a parsing or file error occurred.
                try:
                    ser.write(b"f\n")
                except serial.SerialException:
                    pass
                if csv_file is not None:
                    csv_file.flush()
                    csv_file.close()

            # Read final ESP32 status if available.
            final_deadline = time.monotonic() + 2
            while time.monotonic() < final_deadline:
                line = read_line(ser)
                if line:
                    print(line)
                    if line.startswith("INFO,RECORDING_STOPPED"):
                        break

            if saved == 0 or output_path is None:
                print("Tidak ada data yang tersimpan.", file=sys.stderr)
                return 1

            print("\nPerekaman selesai.")
            print(f"Jumlah sampel tersimpan : {saved}")
            print("Time base data           : nominal 51.2 Hz (elapsed_us dari indeks sampel)")
            print(f"Durasi data              : {last_elapsed_us / 1_000_000:.2f} detik")
            print(f"CSV                      : {output_path.resolve()}")
            return 0

    except (serial.SerialException, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"Gagal merekam: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
