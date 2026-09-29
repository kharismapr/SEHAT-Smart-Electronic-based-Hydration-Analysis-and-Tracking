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
 * Custom Tooltip for light clean aesthetic
 */
const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-white/95 border border-slate-200 p-3 rounded-xl shadow-lg text-xs space-y-1.5 backdrop-blur-md">
        <p className="font-bold text-slate-700 border-b border-slate-100 pb-1">
          {label}
        </p>
        {payload.map((entry, index) => (
          <div key={`item-${index}`} className="flex items-center justify-between gap-4">
            <span style={{ color: entry.color }} className="font-semibold">
              {entry.name}:
            </span>
            <span className="font-mono text-slate-900 font-bold">
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
 * TelemetryChart Component (Light Mode)
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
      <div className="bg-white border border-slate-200 rounded-2xl p-8 text-center text-slate-400 text-sm shadow-sm">
        No telemetry records available to plot.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
        <div>
          <h3 className="text-base font-extrabold text-slate-900 tracking-tight">
            Physiological & Environmental Telemetry Trends
          </h3>
          <p className="text-xs text-slate-500 font-medium">
            Multi-sensor continuous observation over recent measurement intervals
          </p>
        </div>
        <span className="text-xs font-mono text-slate-600 bg-slate-100 px-2.5 py-1 rounded-md font-semibold">
          {chartData.length} data points
        </span>
      </div>

      <div className="h-72 w-full pt-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis
              dataKey="time"
              stroke="#94a3b8"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#e2e8f0' }}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#e2e8f0' }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }}
              iconType="circle"
            />

            {/* PPG Line */}
            <Line
              type="monotone"
              dataKey="bpm"
              name="PPG (BPM)"
              unit="BPM"
              stroke="#e11d48"
              strokeWidth={2.5}
              dot={{ r: 3, fill: '#e11d48' }}
              activeDot={{ r: 5 }}
            />

            {/* GSR Line */}
            <Line
              type="monotone"
              dataKey="gsr"
              name="GSR (μS)"
              unit="μS"
              stroke="#0891b2"
              strokeWidth={2.5}
              dot={{ r: 3, fill: '#0891b2' }}
              activeDot={{ r: 5 }}
            />

            {/* Temperature Line */}
            <Line
              type="monotone"
              dataKey="temperature"
              name="Temp (°C)"
              unit="°C"
              stroke="#d97706"
              strokeWidth={2.5}
              dot={{ r: 3, fill: '#d97706' }}
              activeDot={{ r: 5 }}
            />

            {/* Hours Since Hydration */}
            <Line
              type="monotone"
              dataKey="hours"
              name="Hours Dry (h)"
              unit="hrs"
              stroke="#059669"
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={{ r: 3, fill: '#059669' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
