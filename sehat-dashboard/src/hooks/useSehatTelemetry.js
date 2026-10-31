import React, { useState, useEffect, useCallback, useRef } from 'react';
import { HistoryService } from '../services/historyService';
import { estimateHoursSinceHydration, classifyHydration } from '../utils/calculations';

/**
 * Custom Hook: useSehatTelemetry
 * 
 * Clinical Hardware & Session Control:
 * - 'c': Calibrate Grove GSR open-circuit baseline
 * - 's': Start 30-second continuous acquisition
 * - 'f': Flush partial window buffer and calculate features
 * - 'r': Reset recording state
 */
export const CLINICAL_WINDOW_SEC = 30;

export function useSehatTelemetry() {
  // Live biosignal telemetry feeds (ephemeral display only, updates gauges)
  const [rawSensors, setRawSensors] = useState({
    bpm: 72,
    spo2: null,
    spo2Valid: false,
    gsr: 9.5,
    temperature: 36.5,
    humidity: 55,
    rmssd: 32,
    predictedHours: null,
    isLive: false
  });

  // State of measurement session
  const [measurementPhase, setMeasurementPhase] = useState('idle'); // 'idle' | 'sampling' | 'inferring'
  const [measurementProgress, setMeasurementProgress] = useState(0);
  const [secondsRemaining, setSecondsRemaining] = useState(CLINICAL_WINDOW_SEC);

  // Persistent historical records (only finalized 30s results)
  const [history, setHistory] = useState(() => HistoryService.seedSampleDataIfEmpty());

  // Latest committed measurement result
  const [latestResult, setLatestResult] = useState(() => {
    const initial = HistoryService.getAll();
    return initial.length > 0 ? initial[0] : null;
  });

  const latestSensorsRef = useRef(rawSensors);
  useEffect(() => {
    latestSensorsRef.current = rawSensors;
  }, [rawSensors]);

  // 1. Initial Synchronize of History from SQLite Database
  useEffect(() => {
    let isMounted = true;
    const syncHistory = async () => {
      try {
        const remoteRecords = await HistoryService.fetchAllRemote();
        if (isMounted && remoteRecords && remoteRecords.length > 0) {
          setHistory(remoteRecords);
          setLatestResult(remoteRecords[0]);
        }
      } catch (err) {
        console.debug('History sync error:', err);
      }
    };
    syncHistory();
  }, []);

  // 2. High-Frequency Live Telemetry Poller (Every 250ms - Updates UI cards only, zero DB writes)
  useEffect(() => {
    let isMounted = true;

    const pollLiveSensors = async () => {
      try {
        const live = await HistoryService.fetchLiveTelemetry();
        if (isMounted && live) {
          setRawSensors({
            bpm: Number(live.bpm) || 72,
            spo2: live.spo2Valid && Number.isFinite(Number(live.spo2)) ? Number(live.spo2) : null,
            spo2Valid: live.spo2Valid === true,
            gsr: Number(live.gsr) || 9.5,
            temperature: Number(live.temperature) || 36.5,
            humidity: Number(live.humidity) || 55,
            rmssd: Number(live.rmssd) || 32,
            predictedHours: live.predictedHours != null ? Number(live.predictedHours) : null,
            isLive: live.isLive
          });
        }
      } catch {
        // Ignore network jitter
      }
    };

    const interval = setInterval(pollLiveSensors, 250);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // =========================================================================
  // 4 Direct Hardware Command Actions ('c', 's', 'f', 'r')
  // =========================================================================

  // 1. Calibrate ('c')
  const handleCalibrate = useCallback(async () => {
    await HistoryService.sendDeviceCommand('c');
  }, []);

  // 2. Start ('s') -> Launches 30s Countdown
  const handleStart = useCallback(async () => {
    await HistoryService.sendDeviceCommand('s');
    setMeasurementPhase('sampling');
    setMeasurementProgress(0);
    setSecondsRemaining(CLINICAL_WINDOW_SEC);
  }, []);

  // 3. Flush ('f') -> Immediately forces window calculation
  const handleFlush = useCallback(async () => {
    await HistoryService.sendDeviceCommand('f');
    setMeasurementPhase('inferring');
  }, []);

  // 4. Reset ('r') -> Clears recording
  const handleReset = useCallback(async () => {
    await HistoryService.sendDeviceCommand('r');
    setMeasurementPhase('idle');
    setMeasurementProgress(0);
    setSecondsRemaining(CLINICAL_WINDOW_SEC);
  }, []);

  // Handle live sampling countdown (30s)
  useEffect(() => {
    if (measurementPhase !== 'sampling') return;

    const intervalTime = 100; // update progress every 100ms
    const totalTicks = (CLINICAL_WINDOW_SEC * 1000) / intervalTime;
    let currentTick = 0;

    const timer = setInterval(() => {
      currentTick += 1;
      const progress = Math.min(100, Math.round((currentTick / totalTicks) * 100));
      const remaining = Math.max(0, Math.ceil((totalTicks - currentTick) * (intervalTime / 1000)));

      setMeasurementProgress(progress);
      setSecondsRemaining(remaining);

      // When 30 seconds complete, transition to finalize & save
      if (currentTick >= totalTicks) {
        clearInterval(timer);
        setMeasurementPhase('inferring');
      }
    }, intervalTime);

    return () => clearInterval(timer);
  }, [measurementPhase]);

  // Handle Finalizing Result & Committing Single Record to SQLite
  useEffect(() => {
    if (measurementPhase !== 'inferring') return;

    // Send flush command 'f' to ESP32 to finalize window
    HistoryService.sendDeviceCommand('f');

    const finalizeTimer = setTimeout(async () => {
      const captured = latestSensorsRef.current;
      
      // Check if the ML model on ESP32 provided an inferred hours estimate
      const modelHours = captured.predictedHours;
      const finalHours = (modelHours != null && !isNaN(modelHours))
        ? modelHours
        : estimateHoursSinceHydration(captured);

      const finalStatus = classifyHydration(finalHours);

      const newRecord = {
        id: `meas_${Date.now()}`,
        timestamp: Date.now(),
        bpm: captured.bpm,
        spo2: captured.spo2Valid ? captured.spo2 : null,
        spo2Valid: captured.spo2Valid,
        gsr: captured.gsr,
        temperature: captured.temperature,
        humidity: captured.humidity,
        hoursSinceHydration: finalHours,
        predictedHoursSinceHydration: finalHours,
        statusKey: finalStatus.key,
        notes: `30s Clinical Session (RMSSD: ${captured.rmssd || 32}ms)`
      };

      // Commit ONLY THIS SINGLE RESULT to SQLite Database & History Table
      const updated = HistoryService.save(newRecord);
      setHistory(updated);
      setLatestResult(newRecord);
      setMeasurementPhase('idle');
    }, 1200);

    return () => clearTimeout(finalizeTimer);
  }, [measurementPhase]);

  // Clear history
  const clearHistory = useCallback(() => {
    const cleared = HistoryService.clear();
    setHistory(cleared);
    setLatestResult(null);
  }, []);

  const isMeasuring = measurementPhase === 'sampling' || measurementPhase === 'inferring';
  const isInferring = measurementPhase === 'inferring';

  return {
    rawSensors,
    latestResult,
    history,
    measurementPhase,
    isMeasuring,
    isInferring,
    measurementProgress,
    secondsRemaining,
    startMeasurement: handleStart,
    handleStart,
    handleCalibrate,
    handleFlush,
    handleReset,
    clearHistory
  };
}
