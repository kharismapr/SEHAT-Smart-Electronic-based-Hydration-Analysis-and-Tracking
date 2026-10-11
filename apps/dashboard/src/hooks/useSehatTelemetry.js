import React, { useState, useEffect, useCallback, useRef } from 'react';
import { HistoryService } from '../services/historyService';
import { estimateHoursSinceHydration, classifyHydration } from '../utils/calculations';

/**
 * Custom Hook: useSehatTelemetry
 * 
 * Multi-stage Measurement Protocol:
 * 1. Idle: Displays latest saved specimen or ready state.
 * 2. Sampling (5s): Live PPG, GSR, Temp, Humidity streams appear immediately on screen.
 *    Prediction target is in placeholder state ('--').
 * 3. ML Inference (800ms): Sensor features are locked; ML pipeline processes the features.
 * 4. Completed: Prediction output (hours since hydration & classification) is revealed.
 */
export const SAMPLING_DURATION_SEC = 5;

export function useSehatTelemetry() {
  // Live biosignal telemetry feeds
  const [rawSensors, setRawSensors] = useState({
    bpm: 72,
    gsr: 9.5,
    temperature: 36.5,
    humidity: 55
  });

  // State of measurement session: 'idle' | 'sampling' | 'inferring'
  const [measurementPhase, setMeasurementPhase] = useState('idle');
  const [measurementProgress, setMeasurementProgress] = useState(0); // 0 to 100%
  const [secondsRemaining, setSecondsRemaining] = useState(SAMPLING_DURATION_SEC);

  // Persistent historical records
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

  // Fetch from backend SQLite database on mount
  useEffect(() => {
    HistoryService.fetchAllRemote().then(remoteRecords => {
      if (remoteRecords && remoteRecords.length > 0) {
        setHistory(remoteRecords);
        setLatestResult(remoteRecords[0]);
      }
    });
  }, []);

  // Update a single sensor feature manually (testing sliders)
  const updateFeature = useCallback((field, value) => {
    setRawSensors(prev => ({
      ...prev,
      [field]: value
    }));
  }, []);

  // Start an On-Demand Measurement session
  const startMeasurement = useCallback(() => {
    if (measurementPhase !== 'idle') return;
    setMeasurementPhase('sampling');
    setMeasurementProgress(0);
    setSecondsRemaining(SAMPLING_DURATION_SEC);
  }, [measurementPhase]);

  // Handle live sampling countdown
  useEffect(() => {
    if (measurementPhase !== 'sampling') return;

    const intervalTime = 100; // update progress & live sensors every 100ms
    const totalTicks = (SAMPLING_DURATION_SEC * 1000) / intervalTime;
    let currentTick = 0;

    const timer = setInterval(() => {
      currentTick += 1;
      const progress = Math.min(100, Math.round((currentTick / totalTicks) * 100));
      const remaining = Math.max(0, Math.ceil((totalTicks - currentTick) * (intervalTime / 1000)));

      setMeasurementProgress(progress);
      setSecondsRemaining(remaining);

      // Live real-time fluctuations as sensors acquire signals
      setRawSensors(prev => ({
        bpm: Math.min(130, Math.max(55, prev.bpm + (Math.floor(Math.random() * 3) - 1))),
        gsr: +(Math.min(18, Math.max(2, prev.gsr + (Math.random() * 0.2 - 0.1)))).toFixed(2),
        temperature: +(prev.temperature + (Math.random() * 0.04 - 0.02)).toFixed(1),
        humidity: prev.humidity
      }));

      // When sampling ends, transition to ML Inference phase
      if (currentTick >= totalTicks) {
        clearInterval(timer);
        setMeasurementPhase('inferring');
      }
    }, intervalTime);

    return () => clearInterval(timer);
  }, [measurementPhase]);

  // Handle ML Inference processing delay
  useEffect(() => {
    if (measurementPhase !== 'inferring') return;

    // Simulate ML feature pipeline & model execution
    const inferenceTimer = setTimeout(() => {
      const captured = latestSensorsRef.current;
      const finalHours = estimateHoursSinceHydration(captured);
      const finalStatus = classifyHydration(finalHours);

      const newRecord = {
        id: `meas_${Date.now()}`,
        timestamp: Date.now(),
        bpm: captured.bpm,
        gsr: captured.gsr,
        temperature: captured.temperature,
        humidity: captured.humidity,
        hoursSinceHydration: finalHours,
        statusKey: finalStatus.key
      };

      // Commit to SQLite DB and local storage
      const updated = HistoryService.save(newRecord);
      setHistory(updated);
      setLatestResult(newRecord);
      setMeasurementPhase('idle');
    }, 700);

    return () => clearTimeout(inferenceTimer);
  }, [measurementPhase]);

  // Clear history
  const clearHistory = useCallback(() => {
    const cleared = HistoryService.clear();
    setHistory(cleared);
    setLatestResult(null);
  }, []);

  const isMeasuring = measurementPhase !== 'idle';
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
    startMeasurement,
    updateFeature,
    clearHistory
  };
}
