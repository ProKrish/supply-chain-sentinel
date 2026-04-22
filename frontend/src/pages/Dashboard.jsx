import React, { useState, useEffect, useCallback } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import ShipmentMap from '../components/Map/ShipmentMap';
import MapLegend from '../components/Map/MapLegend';
import AppHeader from '../components/Layout/AppHeader';
import AgentStreamPanel from '../components/Agent/AgentStreamPanel'
import RiskBreakdown from '../components/Risk/RiskBreakdown'
import {
  getShipments,
  getShipment as getShipmentDetail,
  getDisruptionHistory,
  getActiveDisruptions,
  injectDisruption,
  rerouteAgent
} from '../api/client';


const PORT_NODE_LIST = [
  "Shanghai", "Rotterdam", "Los Angeles", "Mumbai",
  "Felixstowe", "Singapore", "Hamburg", "Dubai",
  "New York", "Tokyo", "Long Beach", "Chennai",
  "Hong Kong", "Vancouver", "Busan", "Seattle",
  "Sydney", "Chicago", "Colombo", "Suez Canal Zone"
];

const DISRUPTION_TYPES = [
  "Typhoon", "Port Strike", "Customs Delay",
  "Equipment Failure", "Flooding", "Political Unrest",
  "Fog Closure", "Cyber Attack"
];

function clampRisk(value) {
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return 0;
  return Math.min(1, Math.max(0, numeric));
}

function computeTimePressureContribution(slaDeadline) {
  if (!slaDeadline) return 0;
  const raw = typeof slaDeadline === 'string'
    ? slaDeadline.replace('+00:00Z', 'Z').replace('+00:00', 'Z')
    : slaDeadline;
  const deadline = new Date(raw);
  if (Number.isNaN(deadline.getTime())) return 0;

  const daysRemaining = Math.ceil((deadline.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (daysRemaining <= 0) return 1;
  if (daysRemaining <= 1) return 0.95;
  if (daysRemaining <= 2) return 0.85;
  if (daysRemaining <= 3) return 0.75;
  if (daysRemaining <= 5) return 0.55;
  if (daysRemaining <= 7) return 0.4;
  return 0.2;
}

function transformRiskBreakdown(detail, fallbackShipment) {
  const rawBreakdown = detail?.risk_breakdown || {};
  const detailShipment = detail?.shipment || {};
  const shipment = { ...fallbackShipment, ...detailShipment };

  if (
    rawBreakdown.congestion_contribution != null
    || rawBreakdown.weather_contribution != null
    || rawBreakdown.geopolitical_contribution != null
    || rawBreakdown.carrier_reliability_contribution != null
    || rawBreakdown.time_pressure_contribution != null
  ) {
    return {
      congestion_contribution: clampRisk(rawBreakdown.congestion_contribution),
      weather_contribution: clampRisk(rawBreakdown.weather_contribution),
      geopolitical_contribution: clampRisk(rawBreakdown.geopolitical_contribution),
      carrier_reliability_contribution: clampRisk(rawBreakdown.carrier_reliability_contribution),
      time_pressure_contribution: clampRisk(rawBreakdown.time_pressure_contribution),
      total_risk_score: clampRisk(rawBreakdown.total_risk_score ?? shipment.risk_score),
      summary_text: rawBreakdown.summary_text || '',
    };
  }

  const adjacentEdges = Array.isArray(rawBreakdown.adjacent_edges) ? rawBreakdown.adjacent_edges : [];
  const hasEdgeSignals = adjacentEdges.length > 0;
  const edgeCount = adjacentEdges.length || 1;

  const totals = adjacentEdges.reduce(
    (accumulator, edge) => {
      accumulator.congestion += clampRisk(edge.congestion_index);
      accumulator.weather += clampRisk(edge.weather_risk);
      accumulator.geopolitical += clampRisk(edge.geopolitical_score);
      accumulator.edgeRisk += clampRisk(edge.edge_risk_score);
      return accumulator;
    },
    { congestion: 0, weather: 0, geopolitical: 0, edgeRisk: 0 }
  );

  const activeDisruptions = Array.isArray(rawBreakdown.active_disruptions)
    ? rawBreakdown.active_disruptions
    : [];
  const maxDisruptionSeverity = activeDisruptions.reduce(
    (max, disruption) => Math.max(max, clampRisk(disruption?.severity)),
    0
  );

  let congestionContribution = totals.congestion / edgeCount;
  let weatherContribution = totals.weather / edgeCount;
  let geopoliticalContribution = totals.geopolitical / edgeCount;
  const carrierReliability = detail?.carrier?.reliability_score;
  let carrierContribution = carrierReliability == null ? 0 : clampRisk(1 - carrierReliability);
  let timePressureContribution = computeTimePressureContribution(shipment?.sla_deadline);
  const avgEdgeRisk = totals.edgeRisk / edgeCount;
  const totalRiskScore = clampRisk(shipment?.risk_score ?? avgEdgeRisk);

  if (!hasEdgeSignals) {
    const baseline = totalRiskScore;
    congestionContribution = clampRisk(baseline * 0.4);
    weatherContribution = clampRisk(baseline * 0.3);
    geopoliticalContribution = clampRisk(Math.max(baseline * 0.25, maxDisruptionSeverity));
    carrierContribution = clampRisk(Math.max(carrierContribution, baseline * 0.2));
    timePressureContribution = clampRisk(Math.max(timePressureContribution, baseline * 0.25));
  }

  const factors = [
    { label: 'Port congestion', value: congestionContribution },
    { label: 'Weather risk', value: weatherContribution },
    { label: 'Geopolitical pressure', value: geopoliticalContribution },
    { label: 'Carrier reliability', value: carrierContribution },
    { label: 'Time pressure', value: timePressureContribution },
  ];
  const primaryFactor = factors.reduce((max, current) => (current.value > max.value ? current : max), factors[0]);
  const nodeText = shipment?.current_node ? ` around ${shipment.current_node}` : '';
  const summaryText = activeDisruptions.length > 0
    ? `${activeDisruptions.length} active disruption(s)${nodeText}. Primary pressure: ${primaryFactor.label}.`
    : hasEdgeSignals
      ? `Primary pressure: ${primaryFactor.label}.`
      : `Primary pressure: ${primaryFactor.label} (estimated from shipment risk score).`;

  return {
    congestion_contribution: congestionContribution,
    weather_contribution: weatherContribution,
    geopolitical_contribution: geopoliticalContribution,
    carrier_reliability_contribution: carrierContribution,
    time_pressure_contribution: timePressureContribution,
    total_risk_score: totalRiskScore,
    summary_text: summaryText,
  };
}

function normalizeDisruptionEvent(event) {
  return {
    ...event,
    event_id: event?.event_id || event?.id || `${event?.disruption_type || 'event'}-${event?.timestamp || Date.now()}`,
    affected_node: event?.affected_node || event?.node_id || 'Unknown Node',
    disruption_type: event?.disruption_type || 'Unknown',
    severity: clampRisk(event?.severity),
    timestamp: event?.timestamp || event?.created_at || event?.detected_at || null,
  };
}

function getSeverityColor(severity) {
  if (severity > 0.7) return 'bg-[#ef4444]'; // red
  if (severity > 0.4) return 'bg-[#f59e0b]'; // amber
  return 'bg-[#22c55e]'; // green
}

function getHoverBorderColor(severity) {
  if (severity > 0.7) return 'hover:border-[#ef4444]'; // red
  if (severity > 0.4) return 'hover:border-[#f59e0b]'; // amber
  return 'hover:border-[#22c55e]'; // green
}

function getRiskColorHex(score) {
  if (score < 0.3) return '#22c55e';
  if (score < 0.6) return '#f59e0b';
  return '#ef4444';
}

function getAvgRiskColorClass(score) {
  if (score < 0.3) return 'text-[#22c55e]';
  if (score < 0.6) return 'text-[#f59e0b]';
  return 'text-[#ef4444]';
}

function hasShipmentChanged(prev, next) {
  if (!prev || !next) return prev !== next;
  return (
    prev.status !== next.status ||
    prev.risk_score !== next.risk_score ||
    prev.current_node !== next.current_node ||
    prev.estimated_arrival !== next.estimated_arrival
  );
}

export default function Dashboard() {
  const getTimeAgo = (timestamp) => {
    if (!timestamp) return 'recently'
    const cleaned = typeof timestamp === 'string'
      ? timestamp.replace('+00:00Z', 'Z').replace('+00:00', 'Z')
      : timestamp
    const date = new Date(cleaned)
    if (isNaN(date.getTime())) return 'recently'
    const diff = Date.now() - date.getTime()
    const hrs = Math.floor(diff / 3600000)
    const mins = Math.floor(diff / 60000)
    if (hrs > 24) return `${Math.floor(hrs / 24)}d ago`
    if (hrs > 0) return `${hrs}hrs ago`
    if (mins > 0) return `${mins}mins ago`
    return 'just now'
  }
  const { user } = useAuth0()
  const roles = user?.['https://supply-chain-sentinel/roles'] || []
  const isManager = roles.includes('logistics_manager')

  const [selectedShipment, setSelectedShipment] = useState(null);
  const [riskBreakdown, setRiskBreakdown] = useState(null)
  const [riskLoading, setRiskLoading] = useState(false)

  const [showDisruptionModal, setShowDisruptionModal] = useState(false);
  const [modalNode, setModalNode] = useState('Singapore');
  const [modalSeverity, setModalSeverity] = useState(0.7);
  const [modalType, setModalType] = useState('Typhoon');

  const [activeDisruptions, setActiveDisruptions] = useState([]);
  const [disruptionHistory, setDisruptionHistory] = useState([]);
  const [allShipments, setAllShipments] = useState([]);

  const [stats, setStats] = useState({ total: 0, highRisk: 0, active: 0, avgRisk: 0 });

  const loadShipments = useCallback(async () => {
    try {
      const res = await getShipments({ limit: 500 });
      const shipments = res?.shipments || res || [];
      setAllShipments(shipments);

      let total = 0, highRisk = 0, sumRisk = 0;
      shipments.forEach(s => {
        if (s.status === 'in_transit') total++;
        if (s.risk_score > 0.6) highRisk++;
        sumRisk += (s.risk_score || 0);
      });
      const avgRisk = shipments.length > 0 ? sumRisk / shipments.length : 0;

      setStats(prev => ({ ...prev, total, highRisk, avgRisk }));

      setSelectedShipment((previous) => {
        if (!previous) return previous;
        const updated = shipments.find((s) => s.shipment_id === previous.shipment_id);
        if (!updated) return null;
        return hasShipmentChanged(previous, updated) ? updated : previous;
      });
    } catch (e) {
      console.error("Failed loading shipments", e);
    }
  }, []);

  const loadDisruptions = useCallback(async () => {
    try {
      const hist = await getDisruptionHistory();
      const activeRes = await getActiveDisruptions();
      const histArray = (Array.isArray(hist) ? hist : hist?.disruptions || hist?.history || hist?.events || [])
        .map(normalizeDisruptionEvent);
      const activeArray = (Array.isArray(activeRes)
        ? activeRes
        : activeRes?.disruptions || [])
        .map(normalizeDisruptionEvent);

      // Keep latest active disruptions visible even when DB history insert fails.
      const dedupedById = new Map();
      [...activeArray, ...histArray].forEach((event) => {
        if (!dedupedById.has(event.event_id)) {
          dedupedById.set(event.event_id, event);
        }
      });

      setDisruptionHistory(Array.from(dedupedById.values()).slice(0, 10));
      setActiveDisruptions(activeArray);
      setStats(prev => ({ ...prev, active: activeArray.length }));
    } catch (e) {
      console.error("Failed loading disruptions", e);
    }
  }, []);

  useEffect(() => {
    loadShipments();
    loadDisruptions();
    const interval = setInterval(() => {
      loadShipments();
      loadDisruptions();
    }, 60000);
    return () => clearInterval(interval);
  }, [loadShipments, loadDisruptions]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setShowDisruptionModal(false);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleInjectDisruption = async () => {
    try {
      await injectDisruption({
        node_id: modalNode,
        severity: parseFloat(modalSeverity),
        disruption_type: modalType
      });
      setShowDisruptionModal(false);
      loadDisruptions();
    } catch (e) {
      const apiDetail = e?.response?.data?.detail;
      const reason = typeof apiDetail === 'string' ? apiDetail : e?.message;
      console.error("Inject failed", apiDetail || e);
      alert("Failed to inject disruption: " + reason);
    }
  };

  const handleShipmentClick = async (shipment) => {
    if (!shipment) {
      setSelectedShipment(null)
      setRiskBreakdown(null)
      setRiskLoading(false)
      return
    }
    const shipmentId = shipment.shipment_id || shipment.id
    if (!shipmentId) {
      setSelectedShipment(shipment)
      setRiskBreakdown(null)
      setRiskLoading(false)
      return
    }
    setSelectedShipment(shipment)
    setRiskLoading(true)
    setRiskBreakdown(null)
    try {
      const detail = await getShipmentDetail(shipmentId)
      setSelectedShipment(() => ({
        ...(shipment || {}),
        ...(detail?.shipment || {}),
        ...(detail?.carrier?.carrier_name ? { carrier: detail.carrier.carrier_name } : {}),
      }))
      setRiskBreakdown(transformRiskBreakdown(detail, shipment))
    } catch (e) {
      console.error('Risk breakdown failed:', e)
    } finally {
      setRiskLoading(false)
    }
  }

  const handleDisruptionFeedClick = async (disruption) => {
    const affectedNode = disruption?.affected_node || disruption?.node_id;
    if (!affectedNode) return;

    const impactedShipment = [...(allShipments || [])]
      .filter((shipment) =>
        shipment?.current_node === affectedNode
        || shipment?.origin === affectedNode
        || shipment?.destination === affectedNode
      )
      .sort((a, b) => (b?.risk_score || 0) - (a?.risk_score || 0))[0];

    if (impactedShipment) {
      await handleShipmentClick(impactedShipment);
      return;
    }

    if (isManager) {
      const disruptionSeverity = Number(disruption?.severity);
      setModalNode(affectedNode);
      setModalType(disruption?.disruption_type || modalType);
      if (!Number.isNaN(disruptionSeverity)) {
        setModalSeverity(Math.min(1, Math.max(0.1, disruptionSeverity)));
      }
      setShowDisruptionModal(true);
    }
  }



  return (
    <div className="h-screen w-full bg-[#0f172a] flex flex-col font-sans overflow-hidden">
      <AppHeader />

      <div role="main" className="flex flex-row pt-16 h-full w-full">
        {/* LEFT COLUMN: Map Area */}
        <div aria-label="Shipment map" className="w-[65%] h-full relative border-r border-[#334155]">
          <ShipmentMap
            onShipmentClick={handleShipmentClick}
            selectedShipmentId={selectedShipment?.shipment_id}
          />
          <MapLegend />
        </div>

        {/* RIGHT COLUMN: Info Panel */}
        <div aria-label="Control panel" className="w-[35%] h-full bg-[#0f172a] p-4 overflow-y-auto relative z-10 shadow-[-10px_0_20px_-5px_rgba(0,0,0,0.3)]">

          {/* SECTION 1: STATS GRID */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div aria-label={`${stats.total} active shipments`} className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-300 text-xs mb-1">Active Shipments</p>
              <p className="text-[#06b6d4] text-xl font-bold">{stats.total}</p>
            </div>
            <div aria-label={`${stats.highRisk} high risk shipments`} className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-300 text-xs mb-1">High Risk</p>
              <p className="text-[#ef4444] text-xl font-bold">{stats.highRisk}</p>
            </div>
            <div aria-label={`${stats.active} active disruptions`} className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-300 text-xs mb-1">Disruptions</p>
              <p className="text-[#f59e0b] text-xl font-bold">{stats.active}</p>
            </div>
            <div aria-label={`${(stats.avgRisk * 100).toFixed(1)} percent average network risk`} className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-300 text-xs mb-1">Avg Network Risk</p>
              <p className={`text-xl font-bold ${getAvgRiskColorClass(stats.avgRisk)}`}>
                {(stats.avgRisk * 100).toFixed(1)}%
              </p>
            </div>
          </div>

          {/* SECTION 2: DISRUPTION FEED */}
          <div className="mb-6">
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-white text-sm font-semibold">Live Disruption Feed</h3>
              <button onClick={loadDisruptions} className="text-slate-300 hover:text-white transition-colors">
                <svg xmlns="http://www.w3.org/-2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>

            <div className="space-y-2 mb-3">
              {(disruptionHistory || []).length === 0 && (
                <p className="text-slate-300 text-xs italic">No active disruptions recorded.</p>
              )}
              {(disruptionHistory || []).map((d, idx) => (
                <div
                  key={idx}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleDisruptionFeedClick(d)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      handleDisruptionFeedClick(d);
                    }
                  }}
                  className={`bg-[#1e293b] rounded p-2 flex items-center justify-between border-l-4 border-transparent ${getHoverBorderColor(d.severity || 0)} cursor-pointer transition-all duration-200 focus:outline focus:outline-2 focus:outline-cyan-400`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-[10px] h-[10px] rounded-full ${getSeverityColor(d.severity || 0)}`} />
                    <div className="flex flex-col">
                      <span className="text-white text-sm font-medium">{d.disruption_type || "Unknown"}</span>
                      <span className="text-slate-300 text-xs">{d.affected_node || "Unknown Node"}</span>
                    </div>
                  </div>
                  <span className="text-xs text-slate-300">{getTimeAgo(d.timestamp || d.created_at || d.detected_at || d.resolved_at)}</span>
                </div>
              ))}
            </div>

            {isManager && (
              <button
                onClick={() => setShowDisruptionModal(true)}
                aria-label="Open disruption injection modal"
                className="w-full py-2 border border-[#06b6d4] text-[#06b6d4] hover:bg-[#06b6d4] hover:text-white hover:brightness-110 rounded text-sm transition-all font-medium"
              >
                Inject Disruption
              </button>
            )}
          </div>

          {/* SECTION 3: SHIPMENT DETAIL PANEL */}
          <div>
            <h3 className="text-white text-sm font-semibold mb-3 border-b border-[#334155] pb-2">Shipment Detail</h3>

            {!selectedShipment && (
              <div className="flex flex-col items-center justify-center py-10 opacity-60">
                <svg className="w-16 h-16 text-slate-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/-2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path>
                </svg>
                <p className="text-slate-300 text-sm text-center">Click a shipment on the map <br />to view details and run AI analysis</p>
              </div>
            )}

            {selectedShipment && (
              <div className="flex flex-col bg-[#1e293b] rounded-lg p-4 animate-slide-in">
                <div className="flex justify-between items-center mb-4">
                  <span className="text-[#06b6d4] font-mono font-bold text-lg">
                    {selectedShipment.id || selectedShipment.shipment_id}
                  </span>
                  <span className={`text-xs px-2 py-1 rounded text-white font-medium uppercase tracking-wide
                    ${selectedShipment.status === 'in_transit' ? 'bg-blue-500/80' :
                      selectedShipment.status === 'delayed' ? 'bg-red-500/80' : 'bg-green-500/80'}`}>
                    {selectedShipment.status}
                  </span>
                </div>

                <div className="flex items-center justify-center gap-3 mb-4 bg-[#0f172a] rounded py-2 border border-[#334155]">
                  <span className="text-white text-sm">{selectedShipment.origin}</span>
                  <span className="text-slate-300 text-lg">&rarr;</span>
                  <span className="text-white text-sm">{selectedShipment.destination}</span>
                </div>

                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-slate-300 text-xs">Cargo Type</p>
                    <p className="text-white text-sm">{selectedShipment.cargo_type || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-slate-300 text-xs">Priority Tier</p>
                    <p className="text-white text-sm">Tier {selectedShipment.priority_tier || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-slate-300 text-xs">Carrier</p>
                    <p className="text-white text-sm">{selectedShipment.carrier || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-slate-300 text-xs">SLA Deadline</p>
                    {(() => {
                      const raw = selectedShipment.sla_deadline?.replace('+00:00Z', 'Z').replace('+00:00', 'Z')
                      const date = new Date(raw)
                      const days = Math.ceil((date - new Date()) / (1000 * 60 * 60 * 24))
                      const valid = !isNaN(date.getTime())
                      return (
                        <p className="text-sm font-medium" style={{ color: valid && days < 3 ? '#ef4444' : '#ffffff' }}>
                          {valid ? date.toLocaleDateString() : 'N/A'}
                        </p>
                      )
                    })()}
                  </div>
                </div>

                {/* SLA Warning */}
                {(() => {
                  const raw = selectedShipment.sla_deadline?.replace('+00:00Z', 'Z').replace('+00:00', 'Z')
                  const date = new Date(raw)
                  const days = Math.ceil((date - new Date()) / (1000 * 60 * 60 * 24))
                  if (!isNaN(date.getTime()) && days < 3 && selectedShipment.status !== 'delivered') {
                    return (
                      <div className="bg-red-500/20 text-red-400 p-2 rounded text-sm mb-4 border border-red-500/30 font-medium">
                        {'\u26A0\uFE0F'} SLA breach risk: {Math.max(0, days)} days remaining
                      </div>
                    )
                  }
                  return null
                })()}

                <div className="mb-4 text-center">
                  <p className="text-3xl font-bold" style={{ color: getRiskColorHex(selectedShipment.risk_score) }}>
                    {(selectedShipment.risk_score * 100).toFixed(1)}%
                  </p>
                  <p className="text-slate-300 text-xs uppercase tracking-widest mt-1 mb-2">Risk Score</p>
                  <div className="w-full bg-[#0f172a] h-2 rounded-full overflow-hidden border border-[#334155]">
                    <div className="h-full rounded-full"
                      style={{
                        width: `${selectedShipment.risk_score * 100}%`,
                        backgroundColor: getRiskColorHex(selectedShipment.risk_score)
                      }} />
                  </div>
                </div>

                {/* Priority Tier bar replaces missing carrier_reliability */}
                <div className="mb-6">
                  <p className="text-slate-300 text-sm mb-1">
                    Priority Level: Tier {selectedShipment.priority_tier || 'N/A'}
                  </p>
                  <div className="w-full bg-[#0f172a] h-1.5 rounded-full overflow-hidden border border-[#334155]">
                    <div className="h-full rounded-full bg-[#06b6d4]"
                      style={{ width: `${((4 - (selectedShipment.priority_tier || 4)) / 3) * 100}%` }} />
                  </div>
                </div>

                {isManager && (
                  <AgentStreamPanel
                    shipmentId={selectedShipment.id || selectedShipment.shipment_id}
                    analyzeButtonAriaLabel="Run AI rerouting analysis for this shipment"
                  />
                )}

                <RiskBreakdown
                  shipment={selectedShipment}
                  riskBreakdown={riskBreakdown}
                  loading={riskLoading}
                />

              </div>
            )}
          </div>
        </div>
      </div>

      {/* DISRUPTION MODAL */}
      {showDisruptionModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Inject disruption event"
          className="fixed inset-0 z-[1000] bg-black/70 flex items-center justify-center"
        >
          <div className="bg-[#1e293b] rounded-xl p-6 w-96 shadow-2xl border border-[#334155]">
            <h2 className="text-white text-lg font-bold mb-4">Inject Disruption</h2>

            <div className="mb-4">
              <label className="block text-slate-300 text-xs mb-1">Affected Node</label>
              <select
                value={modalNode}
                onChange={(e) => setModalNode(e.target.value)}
                className="w-full bg-[#0f172a] border border-[#334155] rounded text-white text-sm p-2 outline-none focus:border-[#06b6d4] transition-colors"
              >
                {PORT_NODE_LIST.map(node => (
                  <option key={node} value={node}>{node}</option>
                ))}
              </select>
            </div>

            <div className="mb-4">
              <label className="block text-slate-300 text-xs mb-1">
                Severity: {parseFloat(modalSeverity).toFixed(1)}
              </label>
              <input
                type="range"
                min="0.1" max="1.0" step="0.1"
                value={modalSeverity}
                onChange={(e) => setModalSeverity(e.target.value)}
                className="w-full accent-[#06b6d4]"
              />
            </div>

            <div className="mb-6">
              <label className="block text-slate-300 text-xs mb-1">Disruption Type</label>
              <select
                value={modalType}
                onChange={(e) => setModalType(e.target.value)}
                className="w-full bg-[#0f172a] border border-[#334155] rounded text-white text-sm p-2 outline-none focus:border-[#06b6d4] transition-colors"
              >
                {DISRUPTION_TYPES.map(type => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowDisruptionModal(false)}
                className="px-4 py-2 rounded text-slate-300 border border-[#334155] hover:bg-slate-700 hover:text-white text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleInjectDisruption}
                className="px-4 py-2 rounded bg-[#06b6d4] text-white hover:brightness-110 text-sm transition-all"
              >
                Inject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

