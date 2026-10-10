/**
 * SEHAT USB Serial Bridge (Node.js)
 * 
 * Reads live sensor telemetry and preprocessed window features from ESP32 Serial output
 * (from SEHAT_GSR_PPG_ESP32.ino) and forwards them to the SEHAT backend server (http://localhost:5000/api/measurements).
 * 
 * Usage:
 *   node serial_bridge.js <COM_PORT> (e.g. node serial_bridge.js COM3)
 */

import { createInterface } from 'node:readline';
import { SerialPort } from 'serialport';
import { ReadlineParser } from '@serialport/parser-readline';

const COM_PORT = process.argv[2] || 'COM3';
const BAUD_RATE = 115200;
const SERVER_URL = 'http://localhost:5000/api/measurements';

console.log(`[SEHAT Bridge] Opening ${COM_PORT} at ${BAUD_RATE} baud...`);

let port;
try {
  port = new SerialPort({ path: COM_PORT, baudRate: BAUD_RATE });
} catch (err) {
  console.error(`[Error] Could not open ${COM_PORT}:`, err.message);
  process.exit(1);
}

const parser = port.pipe(new ReadlineParser({ delimiter: '\n' }));

let latestGSR = 9.5;
let latestBPM = 72.0;

parser.on('data', async (line) => {
  const text = line.trim();
  console.log(`[ESP32] ${text}`);

  // 1. Match live stream: ADC10=..., GSR_us=...
  const gsrMatch = text.match(/GSR_us=([\d.]+)/);
  if (gsrMatch) {
    latestGSR = parseFloat(gsrMatch[1]);
  }

  // 2. Match PPG window features: mean_hr=..., rmssd=...
  const ppgMatch = text.match(/mean_hr=([\d.]+)/);
  if (ppgMatch) {
    const hr = parseFloat(ppgMatch[1]);
    if (!isNaN(hr) && hr > 30 && hr < 220) {
      latestBPM = hr;
    }
  }

  // 3. Forward complete window feature updates or periodic vitals
  if (text.includes('gsr_mean=') || text.includes('mean_hr=')) {
    try {
      const payload = {
        bpm: latestBPM,
        gsr: latestGSR,
        temperature: 36.5,
        humidity: 55.0,
        notes: 'ESP32 Serial Bridge'
      };

      const res = await fetch(SERVER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        console.log(`[Bridge -> Dashboard] Forwarded telemetry: BPM=${latestBPM}, GSR=${latestGSR} uS`);
      }
    } catch (err) {
      console.warn(`[Bridge Error] Could not forward to server:`, err.message);
    }
  }
});

port.on('open', () => {
  console.log(`[SEHAT Bridge] Connected to ESP32 on ${COM_PORT}! Listening for telemetry...`);
});

port.on('error', (err) => {
  console.error('[SerialPort Error]', err.message);
});
