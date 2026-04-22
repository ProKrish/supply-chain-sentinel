import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  Legend,
  BarChart,
  Bar,
} from 'recharts';
import AppHeader from '../components/Layout/AppHeader';
import { getShipments, getGraph } from '../api/client';

const STATUS_COLORS = {
  in_transit: '#3b82f6',
  delayed: '#ef4444',
  delivered: '#22c55e',
};

const MODE_ICON = {
  sea: '\u{1F6A2}',
  air: '\u2708\uFE0F',
  rail: '\u{1F682}',
  road: '\u{1F69B}',
};

const clamp01 = (value) => Math.max(0, Math.min(1, Number(value) || 0));

const metricColorClass = (pct) => {
  if (pct < 30) return 'bg-[#22c55e]';
  if (pct <= 60) return 'bg-[#f59e0b]';
  return 'bg-[#ef4444]';
};

const riskTextClass = (score) => {
  const value = clamp01(score);
  if (value < 0.3) return 'text-[#22c55e]';
  if (value < 0.6) return 'text-[#f59e0b]';
  return 'text-[#ef4444]';
};

function generateRiskTrendData() {
  const now = new Date();
  const spikes = new Map([
    [6, 0.72],
    [13, 0.79],
    [20, 0.75],
  ]);

  let current = 0.35;
  return Array.from({ length: 24 }, (_, i) => {
    const hourDate = new Date(now.getTime() - (23 - i) * 60 * 60 * 1000);

    if (spikes.has(i)) {
      current = spikes.get(i);
    } else if (spikes.has(i - 1)) {
      current = clamp01(Math.max(0.34, current - 0.18));
    } else {
      const smoothDrift = (Math.sin(i / 3) * 0.02) + (Math.cos(i / 5) * 0.015);
      const directionalBias = i % 2 === 0 ? 0.008 : -0.006;
      current = clamp01(Math.max(0.3, Math.min(0.62, current + smoothDrift + directionalBias)));
    }

    return {
      time: hourDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      risk: Number(current.toFixed(3)),
    };
  });
}

function MetricBar({ value }) {
  const pct = Math.round(clamp01(value) * 100);

  return (
    <div className="flex items-center gap-3 min-w-[140px]">
      <div className="w-full h-2 bg-[#0f172a] rounded-full overflow-hidden border border-[#334155]">
        <div className={`h-full ${metricColorClass(pct)}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-300 w-10 text-right">{pct}%</span>
    </div>
  );
}

export default function Analytics() {
  const navigate = useNavigate();

  const [shipments, setShipments] = useState([]);
  const [edges, setEdges] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const trendData = useMemo(() => generateRiskTrendData(), []);

  useEffect(() => {
    let mounted = true;

    async function loadAnalyticsData() {
      setIsLoading(true);
      setError('');

      try {
        const [shipmentsRes, graphRes] = await Promise.all([
          getShipments({ limit: 500 }),
          getGraph(),
        ]);

        if (!mounted) return;

        const normalizedShipments = Array.isArray(shipmentsRes)
          ? shipmentsRes
          : Array.isArray(shipmentsRes?.shipments)
            ? shipmentsRes.shipments
            : [];

        const normalizedEdges = Array.isArray(graphRes?.edges) ? graphRes.edges : [];

        setShipments(normalizedShipments);
        setEdges(normalizedEdges);
      } catch (fetchError) {
        if (!mounted) return;
        setError(fetchError?.message || 'Failed to load analytics data.');
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    loadAnalyticsData();
    return () => {
      mounted = false;
    };
  }, []);

  const tradeLaneRows = useMemo(() => {
    return edges
      .map((edge) => {
        const congestion = clamp01(edge.congestion_index);
        const weather = clamp01(edge.weather_risk);
        const geopolitical = clamp01(edge.geopolitical_score);
        const overall = edge.edge_risk_score != null
          ? clamp01(edge.edge_risk_score)
          : clamp01((0.4 * congestion) + (0.35 * weather) + (0.25 * geopolitical));

        return {
          lane: `${edge.from} \u2192 ${edge.to}`,
          mode: String(edge.mode || 'road').toLowerCase(),
          congestion,
          weather,
          geopolitical,
          overall,
        };
      })
      .sort((a, b) => b.overall - a.overall)
      .slice(0, 8);
  }, [edges]);

  const shipmentStatusData = useMemo(() => {
    const counts = { in_transit: 0, delayed: 0, delivered: 0 };

    shipments.forEach((shipment) => {
      if (counts[shipment.status] != null) {
        counts[shipment.status] += 1;
      }
    });

    return [
      { name: 'in_transit', value: counts.in_transit },
      { name: 'delayed', value: counts.delayed },
      { name: 'delivered', value: counts.delivered },
    ];
  }, [shipments]);

  const topRiskShipments = useMemo(() => {
    return [...shipments]
      .sort((a, b) => clamp01(b.risk_score) - clamp01(a.risk_score))
      .slice(0, 5);
  }, [shipments]);

  const carrierReliabilityData = useMemo(() => {
    const grouped = new Map();

    shipments.forEach((shipment) => {
      const carrier = shipment.carrier_id || 'Unknown';
      if (!grouped.has(carrier)) {
        grouped.set(carrier, { carrier, count: 0, riskTotal: 0 });
      }

      const current = grouped.get(carrier);
      current.count += 1;
      current.riskTotal += clamp01(shipment.risk_score);
    });

    return [...grouped.values()]
      .map((entry) => {
        const avgRisk = entry.count > 0 ? entry.riskTotal / entry.count : 0;
        return {
          carrier: entry.carrier,
          reliability: clamp01(1 - avgRisk),
          shipmentCount: entry.count,
        };
      })
      .sort((a, b) => {
        if (b.shipmentCount !== a.shipmentCount) {
          return b.shipmentCount - a.shipmentCount;
        }
        return b.reliability - a.reliability;
      })
      .slice(0, 8);
  }, [shipments]);

  const pieTotal = useMemo(
    () => shipmentStatusData.reduce((sum, item) => sum + item.value, 0),
    [shipmentStatusData],
  );

  const renderPieLabel = ({ value, percent }) => {
    if (!value) return '';
    return `${value} (${(percent * 100).toFixed(0)}%)`;
  };

  return (
    <div role="main" className="min-h-screen bg-[#0f172a] text-white">
      <AppHeader />

      <div className="pt-20 px-6 pb-6">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-white">Analytics</h1>
          <p className="text-slate-300 mt-1">Network Risk Intelligence</p>
        </div>

        {error && (
          <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-300 text-sm">
            {error}
          </div>
        )}

        <section aria-label="Risk trend chart over last 24 hours" className="w-full bg-[#1e293b] rounded-xl p-4 mb-6 border border-[#334155]">
          <h2 className="text-lg font-semibold mb-4">Network Risk Score \u2014 Last 24 Hours</h2>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trendData}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <YAxis
                domain={[0, 1]}
                stroke="#94a3b8"
                tick={{ fill: '#94a3b8', fontSize: 12 }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value) => [Number(value).toFixed(2), 'Risk Score']}
              />
              <Line
                type="monotone"
                dataKey="risk"
                stroke="#06b6d4"
                strokeWidth={3}
                dot={false}
                activeDot={{ r: 5, fill: '#06b6d4' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </section>

        <section aria-label="Trade lane risk table" className="w-full bg-[#1e293b] rounded-xl p-4 mb-6 border border-[#334155]">
          <h2 className="text-lg font-semibold mb-4">Trade Lane Risk Breakdown</h2>
          {isLoading ? (
            <p className="text-slate-300 text-sm">Loading...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-sm">
                <thead>
                  <tr className="text-left text-slate-300 border-b border-[#334155]">
                    <th className="py-2 pr-2">Lane</th>
                    <th className="py-2 px-2">Mode</th>
                    <th className="py-2 px-2">Congestion</th>
                    <th className="py-2 px-2">Weather Risk</th>
                    <th className="py-2 px-2">Geopolitical</th>
                    <th className="py-2 pl-2 text-right">Overall Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {tradeLaneRows.map((row) => (
                    <tr
                      key={`${row.lane}-${row.mode}`}
                      tabIndex={0}
                      role="button"
                      onClick={() => navigate('/dashboard')}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.currentTarget.click();
                        }
                      }}
                      className="border-b border-[#334155]/60 cursor-pointer focus:outline focus:outline-2 focus:outline-cyan-400"
                    >
                      <td className="py-3 pr-2 text-slate-100 whitespace-nowrap">{row.lane}</td>
                      <td className="py-3 px-2 text-lg" title={row.mode}>
                        {MODE_ICON[row.mode] || '\u{1F69B}'}
                      </td>
                      <td className="py-3 px-2"><MetricBar value={row.congestion} /></td>
                      <td className="py-3 px-2"><MetricBar value={row.weather} /></td>
                      <td className="py-3 px-2"><MetricBar value={row.geopolitical} /></td>
                      <td className={`py-3 pl-2 text-right font-semibold ${riskTextClass(row.overall)}`}>
                        {(row.overall * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                  {tradeLaneRows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-4 text-slate-300 text-center">No lane data available.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="grid grid-cols-1 xl:grid-cols-5 gap-6 mb-6">
          <div aria-label="Shipment status distribution chart" className="xl:col-span-3 bg-[#1e293b] rounded-xl p-4 border border-[#334155]">
            <h2 className="text-lg font-semibold mb-4">Shipment Status Breakdown</h2>
            {isLoading ? (
              <p className="text-slate-300 text-sm">Loading...</p>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie
                      data={shipmentStatusData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="45%"
                      outerRadius={90}
                      labelLine={false}
                      label={renderPieLabel}
                    >
                      {shipmentStatusData.map((entry) => (
                        <Cell key={entry.name} fill={STATUS_COLORS[entry.name]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }}
                      formatter={(value, name) => {
                        const pct = pieTotal ? ((Number(value) / pieTotal) * 100).toFixed(1) : '0.0';
                        return [`${value} (${pct}%)`, name];
                      }}
                    />
                    <Legend verticalAlign="bottom" wrapperStyle={{ color: '#cbd5e1', paddingTop: '8px' }} />
                  </PieChart>
                </ResponsiveContainer>
              </>
            )}
          </div>

          <div className="xl:col-span-2 bg-[#1e293b] rounded-xl p-4 border border-[#334155]">
            <h2 className="text-lg font-semibold mb-4">Top 5 High Risk Shipments</h2>
            {isLoading ? (
              <p className="text-slate-300 text-sm">Loading...</p>
            ) : (
              <div className="space-y-3">
                {topRiskShipments.map((shipment) => {
                  const risk = clamp01(shipment.risk_score);
                  const tier = Math.min(3, Math.max(1, Number(shipment.priority_tier) || 3));

                  return (
                    <button
                      key={shipment.shipment_id}
                      type="button"
                      onClick={() => navigate('/dashboard')}
                      className="w-full text-left bg-[#0f172a] border border-[#334155] rounded-lg p-3 hover:border-[#06b6d4] transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-[#06b6d4] font-mono text-sm font-semibold">{shipment.shipment_id}</span>
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-700 text-slate-200">
                          P{tier}
                        </span>
                      </div>
                      <p className="text-slate-300 text-sm mt-1">
                        {shipment.origin} \u2192 {shipment.destination}
                      </p>
                      <p className={`text-2xl font-bold mt-2 ${riskTextClass(risk)}`}>
                        {(risk * 100).toFixed(1)}%
                      </p>
                    </button>
                  );
                })}
                {topRiskShipments.length === 0 && (
                  <p className="text-slate-300 text-sm">No shipment data available.</p>
                )}
              </div>
            )}
          </div>
        </section>

        <section aria-label="Carrier reliability comparison chart" className="w-full bg-[#1e293b] rounded-xl p-4 border border-[#334155]">
          <h2 className="text-lg font-semibold mb-4">Carrier Reliability Scores</h2>
          {isLoading ? (
            <p className="text-slate-300 text-sm">Loading...</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={carrierReliabilityData}
                layout="vertical"
                margin={{ top: 10, right: 24, left: 8, bottom: 10 }}
              >
                <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  domain={[0, 1]}
                  stroke="#94a3b8"
                  tick={{ fill: '#94a3b8', fontSize: 12 }}
                />
                <YAxis
                  type="category"
                  dataKey="carrier"
                  width={120}
                  stroke="#94a3b8"
                  tick={{ fill: '#cbd5e1', fontSize: 12 }}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px' }}
                  formatter={(value, _name, props) => [
                    `${Number(value).toFixed(2)} (n=${props?.payload?.shipmentCount || 0})`,
                    'Reliability',
                  ]}
                />
                <Bar dataKey="reliability" radius={[0, 6, 6, 0]}>
                  {carrierReliabilityData.map((entry) => {
                    let fill = '#ef4444';
                    if (entry.reliability > 0.8) fill = '#22c55e';
                    else if (entry.reliability >= 0.6) fill = '#f59e0b';

                    return <Cell key={entry.carrier} fill={fill} />;
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>
      </div>
    </div>
  );
}
