import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { HistoryService } from '../services/historyService';
import { estimateHoursSinceHydration, classifyHydration } from '../utils/calculations';

/**
 * Custom Hook: useSehatTelemetry
 * 
 * On-demand Measurement Protocol:
 * 1. Idle state: User adjusts/attaches sensors.
 * 2. "Start Measurement" triggered:
 *    - Runs a countdown/sampling session (e.g. 5-second stabilization).
 *    - Samples and calculates the regression output from live signals.
 *    - Saves the final valid measurement to the offline database (LocalStorage).
 */
export const MEASUREMENT_DURATION_SEC = 5;

export function useSehatTelemetry() {
  // Live / preview sensor telemetry readings
  const [rawSensors, setRawSensors] = useState({
    bpm: 72,
    gsr: 9.5,
    temperature: 36.5,
    humidity: 55
  });

  // State of measurement session
  const [isMeasuring, setIsMeasuring] = useState(false);
  const [measurementProgress, setMeasurementProgress] = useState(0); // 0 to 100%
  const [secondsRemaining, setSecondsRemaining] = useState(MEASUREMENT_DURATION_SEC);

  // Latest saved measurement result (null if fresh session)
  const [latestResult, setLatestResult] = useState(null);

  // Inferred outputs derived from current live sensor signals
  const liveInference = useMemo(() => {
    const hours = estimateHoursSinceHydration(rawSensors);
    const status = classifyHydration(hours);
    return {
      hoursSinceHydration: hours,
      status: status
    };
  }, [rawSensors]);

  // Persistent historical records
  const [history, setHistory] = useState([]);

  // Load history on initial mount
  useEffect(() => {
    const records = HistoryService.seedSampleDataIfEmpty();
    setHistory(records);
    if (records.length > 0) {
      setLatestResult(records[0]);
    }
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
    if (isMeasuring) return;
    setIsMeasuring(true);
    setMeasurementProgress(0);
    setSecondsRemaining(MEASUREMENT_DURATION_SEC);
  }, [isMeasuring]);

  // Handle measurement sampling countdown timer
  useEffect(() => {
    if (!isMeasuring) return;

    const intervalTime = 100; // update progress every 100ms
    const totalTicks = (MEASUREMENT_DURATION_SEC * 1000) / intervalTime;
    let currentTick = 0;

    const timer = setInterval(() => {
      currentTick += 1;
      const progress = Math.min(100, Math.round((currentTick / totalTicks) * 100));
      const remaining = Math.max(0, Math.ceil((totalTicks - currentTick) * (intervalTime / 1000)));

      setMeasurementProgress(progress);
      setSecondsRemaining(remaining);

      // Subtle dynamic noise during sampling to simulate sensor settling
      setRawSensors(prev => ({
        bpm: Math.min(140, Math.max(50, prev.bpm + (Math.floor(Math.random() * 3) - 1))),
        gsr: +(Math.min(20, Math.max(1, prev.gsr + (Math.random() * 0.2 - 0.1)))).toFixed(2),
        temperature: +(prev.temperature + (Math.random() * 0.04 - 0.02)).toFixed(1),
        humidity: prev.humidity
      }));

      // When measurement session completes
      if (currentTick >= totalTicks) {
        clearInterval(timer);
        setIsMeasuring(false);

        // Compute final regression output from captured signals
        const finalHours = estimateHoursSinceHydration(rawSensors);
        const finalStatus = classifyHydration(finalHours);

        const newRecord = {
          id: `meas_${Date.now()}`,
          timestamp: Date.now(),
          bpm: rawSensors.bpm,
          gsr: rawSensors.gsr,
          temperature: rawSensors.temperature,
          humidity: rawSensors.humidity,
          hoursSinceHydration: finalHours,
          statusKey: finalStatus.key
        };

        // Commit to offline storage
        const updated = HistoryService.save(newRecord);
        setHistory(updated);
        setLatestResult(newRecord);
      }
    }, intervalTime);

    return () => clearInterval(timer);
  }, [isMeasuring, rawSensors]);

  // Clear history
  const clearHistory = useCallback(() => {
    const cleared = HistoryService.clear();
    setHistory(cleared);
    setLatestResult(null);
  }, []);

  return {
    rawSensors,
    liveInference,
    latestResult,
    history,
    isMeasuring,
    measurementProgress,
    secondsRemaining,
    startMeasurement,
    updateFeature,
    clearHistory
  };
}
