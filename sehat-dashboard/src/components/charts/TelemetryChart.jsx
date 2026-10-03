import React from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid
} from 'recharts';
import { formatTimeOnly } from '../../utils/calculations';

/**
 * Custom Tooltip for strict 4-color palette
 */
const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-white border border-[#83c4e2] p-3 rounded-xl shadow-md text-xs space-y-1.5">
        <p className="font-bold text-[#054867] border-b border-[#83c4e2]/30 pb-1">
          {label}
        </p>
        {payload.map((entry, index) => (
          <div key={`item-${index}`} className="flex items-center justify-between gap-4">
            <span style={{ color: entry.color }} className="font-semibold">
              {entry.name}:
            </span>
            <span className="font-mono text-[#054867] font-bold">
              {entry.value} {entry.unit}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

/**
 * TelemetryChart Component
 * Palette: #054867, #1081b7, #83c4e2, white
 */
export const TelemetryChart = ({ history = [] }) => {
  const chartData = [...history]
    .reverse()
    .slice(-20)
    .map(item => ({
      time: formatTimeOnly(item.timestamp),
      bpm: item.bpm,
      gsr: item.gsr,
      temperature: item.temperature,
      humidity: item.humidity,
      hours: item.hoursSinceHydration,
    }));

  if (chartData.length === 0) {
    return (
      <div className="bg-white border border-[#83c4e2]/40 rounded-2xl p-8 text-center text-[#054867]/50 text-sm shadow-xs">
        No telemetry records available to plot.
      </div>
    );
  }

  return (
    <div className="bg-white border border-[#83c4e2]/50 rounded-2xl p-6 shadow-xs space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#83c4e2]/30 pb-4">
        <div>
          <h3 className="text-base font-extrabold text-[#054867] tracking-tight">
            Physiological & Environmental Telemetry Trends
          </h3>
          <p className="text-xs text-[#1081b7] font-medium">
            Multi-sensor continuous observation over recent measurement intervals
          </p>
        </div>
        <span className="text-xs font-mono text-[#054867] bg-[#f0f7fb] border border-[#83c4e2] px-2.5 py-1 rounded-md font-semibold">
          {chartData.length} records
        </span>
      </div>

      <div className="h-72 w-full pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8f2f7" vertical={false} />
            <XAxis
              dataKey="time"
              stroke="#1081b7"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#83c4e2' }}
            />
            <YAxis
              stroke="#1081b7"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#83c4e2' }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ paddingTop: '10px', fontSize: '12px', color: '#054867' }}
              iconType="circle"
            />

            {/* PPG Line - Deep Ocean Navy */}
            <Line
              type="monotone"
              dataKey="bpm"
              name="PPG (BPM)"
              unit="BPM"
              stroke="#054867"
              strokeWidth={2.4}
              dot={{ r: 2.5, fill: '#054867' }}
              activeDot={{ r: 4 }}
            />

            {/* GSR Line - Vibrant Azure */}
            <Line
              type="monotone"
              dataKey="gsr"
              name="GSR (μS)"
              unit="μS"
              stroke="#1081b7"
              strokeWidth={2.4}
              dot={{ r: 2.5, fill: '#1081b7' }}
              activeDot={{ r: 4 }}
            />

            {/* Temperature Line - Soft Sky Blue */}
            <Line
              type="monotone"
              dataKey="temperature"
              name="Temp (°C)"
              unit="°C"
              stroke="#83c4e2"
              strokeWidth={2.4}
              dot={{ r: 2.5, fill: '#83c4e2' }}
              activeDot={{ r: 4 }}
            />

            {/* Predicted Hours Since Hydration - Dashed Deep Navy */}
            <Line
              type="monotone"
              dataKey="hours"
              name="Pred. Interval Dry (h)"
              unit="hrs"
              stroke="#054867"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={{ r: 3, fill: '#1081b7' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
