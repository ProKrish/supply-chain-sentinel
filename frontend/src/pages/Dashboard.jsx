import React, { useState, useEffect, useCallback } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import ShipmentMap from '../components/Map/ShipmentMap';
import MapLegend from '../components/Map/MapLegend';
import AppHeader from '../components/Layout/AppHeader';
import { 
  getShipments, 
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

function timeAgoText(dateString) {
  if (!dateString) return '';
  const seconds = Math.floor((new Date() - new Date(dateString)) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} mins ago`;
  return `${Math.floor(seconds / 3600)} hrs ago`;
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

export default function Dashboard() {
  const { user } = useAuth0();
  const roles = user?.["https://supply-chain-sentinel/roles"] || [];
  const isManager = roles.includes("logistics_manager");

  const [selectedShipment, setSelectedShipment] = useState(null);
  const [agentResult, setAgentResult] = useState(null);
  const [agentLoading, setAgentLoading] = useState(false);
  
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
      
      if (selectedShipment) {
        const updated = shipments.find(s => s.shipment_id === selectedShipment.shipment_id);
        if (updated) setSelectedShipment(updated);
      }
    } catch(e) {
      console.error("Failed loading shipments", e);
    }
  }, [selectedShipment]);

  const loadDisruptions = useCallback(async () => {
    try {
      const hist = await getDisruptionHistory();
      setDisruptionHistory(hist?.slice(0, 10) || []);
      const active = await getActiveDisruptions();
      setActiveDisruptions(active || []);
      setStats(prev => ({ ...prev, active: (active || []).length }));
    } catch(e) {
      console.error("Failed loading disruptions", e);
    }
  }, []);

  useEffect(() => {
    loadShipments();
    loadDisruptions();
    const interval = setInterval(() => {
        loadShipments();
        loadDisruptions();
    }, 15000);
    return () => clearInterval(interval);
  }, [loadShipments, loadDisruptions]);

  const handleInjectDisruption = async () => {
    try {
      await injectDisruption({
        node_id: modalNode,
        severity: parseFloat(modalSeverity),
        disruption_type: modalType
      });
      setShowDisruptionModal(false);
      loadDisruptions();
    } catch(e) {
      console.error("Inject failed", e);
      alert("Failed to inject disruption: " + e.message);
    }
  };

  const handleAgentAnalysis = async () => {
    if (!selectedShipment) return;
    setAgentLoading(true);
    setAgentResult(null);
    try {
      const res = await rerouteAgent(selectedShipment.shipment_id);
      setAgentResult(res?.final_recommendation || res?.agent_reasoning?.[0] || JSON.stringify(res));
    } catch(e) {
      setAgentResult(`Error: ${e.message}`);
    } finally {
      setAgentLoading(false);
    }
  };

  return (
    <div className="h-screen w-full bg-[#0f172a] flex flex-col font-sans overflow-hidden">
      <AppHeader />
      
      <div className="flex flex-row pt-16 h-full w-full">
        {/* LEFT COLUMN: Map Area */}
        <div className="w-[65%] h-full relative border-r border-[#334155]">
          <ShipmentMap 
            onShipmentClick={(s) => {
              setSelectedShipment(s);
              setAgentResult(null);
            }}
            selectedShipmentId={selectedShipment?.shipment_id}
          />
          <MapLegend />
        </div>

        {/* RIGHT COLUMN: Info Panel */}
        <div className="w-[35%] h-full bg-[#0f172a] p-4 overflow-y-auto relative z-10 shadow-[-10px_0_20px_-5px_rgba(0,0,0,0.3)]">
          
          {/* SECTION 1: STATS GRID */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-400 text-xs mb-1">Active Shipments</p>
              <p className="text-[#06b6d4] text-xl font-bold">{stats.total}</p>
            </div>
            <div className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-400 text-xs mb-1">High Risk</p>
              <p className="text-[#ef4444] text-xl font-bold">{stats.highRisk}</p>
            </div>
            <div className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-400 text-xs mb-1">Disruptions</p>
              <p className="text-[#f59e0b] text-xl font-bold">{stats.active}</p>
            </div>
            <div className="bg-[#1e293b] rounded-lg p-3 hover:bg-[#263548] transition duration-200">
              <p className="text-slate-400 text-xs mb-1">Avg Network Risk</p>
              <p className={`text-xl font-bold ${getAvgRiskColorClass(stats.avgRisk)}`}>
                {(stats.avgRisk * 100).toFixed(1)}%
              </p>
            </div>
          </div>

          {/* SECTION 2: DISRUPTION FEED */}
          <div className="mb-6">
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-white text-sm font-semibold">Live Disruption Feed</h3>
              <button onClick={loadDisruptions} className="text-slate-400 hover:text-white transition-colors">
                <svg xmlns="http://www.w3.org/-2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
            </div>
            
            <div className="space-y-2 mb-3">
              {disruptionHistory.length === 0 && (
                <p className="text-slate-500 text-xs italic">No active disruptions recorded.</p>
              )}
              {disruptionHistory.map((d, idx) => (
                <div key={idx} className={`bg-[#1e293b] rounded p-2 flex items-center justify-between border-l-4 border-transparent ${getHoverBorderColor(d.severity || 0)} cursor-pointer transition-all duration-200`}>
                  <div className="flex items-center gap-3">
                    <div className={`w-[10px] h-[10px] rounded-full ${getSeverityColor(d.severity || 0)}`} />
                    <div className="flex flex-col">
                      <span className="text-white text-sm font-medium">{d.disruption_type || "Unknown"}</span>
                      <span className="text-slate-400 text-xs">{d.affected_node || "Unknown Node"}</span>
                    </div>
                  </div>
                  <span className="text-xs text-slate-400">{timeAgoText(d.timestamp || d.created_at)}</span>
                </div>
              ))}
            </div>

            {isManager && (
              <button 
                onClick={() => setShowDisruptionModal(true)}
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
                <p className="text-slate-400 text-sm text-center">Click a shipment on the map <br/>to view details and run AI analysis</p>
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
                  <span className="text-slate-400 text-lg">&rarr;</span>
                  <span className="text-white text-sm">{selectedShipment.destination}</span>
                </div>

                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-slate-400 text-xs">Cargo Type</p>
                    <p className="text-white text-sm">{selectedShipment.cargo_type || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-xs">Priority Tier</p>
                    <p className="text-white text-sm">Tier {selectedShipment.priority_tier || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-xs">Carrier</p>
                    <p className="text-white text-sm">{selectedShipment.carrier || 'N/A'}</p>
                  </div>
                  <div>
                    <p className="text-slate-400 text-xs">SLA Deadline</p>
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
                        ⚠️ SLA breach risk: {Math.max(0, days)} days remaining
                      </div>
                    )
                  }
                  return null
                })()}

                <div className="mb-4 text-center">
                  <p className="text-3xl font-bold" style={{ color: getRiskColorHex(selectedShipment.risk_score) }}>
                    {(selectedShipment.risk_score * 100).toFixed(1)}%
                  </p>
                  <p className="text-slate-400 text-xs uppercase tracking-widest mt-1 mb-2">Risk Score</p>
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
                  <p className="text-slate-400 text-sm mb-1">
                    Priority Level: Tier {selectedShipment.priority_tier || 'N/A'}
                  </p>
                  <div className="w-full bg-[#0f172a] h-1.5 rounded-full overflow-hidden border border-[#334155]">
                    <div className="h-full rounded-full bg-[#06b6d4]"
                      style={{ width: `${((4 - (selectedShipment.priority_tier || 4)) / 3) * 100}%` }} />
                  </div>
                </div>

                {isManager && (
                  <button 
                    onClick={handleAgentAnalysis}
                    disabled={agentLoading}
                    className={`w-full py-2.5 rounded font-medium transition-all ${
                      agentLoading 
                        ? 'bg-slate-700 text-slate-400 cursor-not-allowed' 
                        : 'bg-[#06b6d4] hover:bg-[#06b6d4] hover:brightness-110 text-white shadow-lg shadow-cyan-500/20'
                    }`}
                  >
                    {agentLoading ? (
                      <span className="flex items-center justify-center gap-2">
                        <div className="w-4 h-4 border-2 border-slate-400 border-t-white rounded-full animate-spin" />
                        Agent analyzing...
                      </span>
                    ) : (
                      "Analyze with AI"
                    )}
                  </button>
                )}

                {agentResult && (
                  <div className="mt-4 bg-[#0f172a] border border-[#334155] rounded-lg overflow-hidden text-sm">
                    
                    {/* Header */}
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-[#334155] bg-[#1e293b]">
                      <span className="bg-green-500 rounded-full w-4 h-4 flex items-center justify-center text-[10px]">✓</span>
                      <p className="text-white font-semibold">AI Recommendation</p>
                    </div>

                    {(() => {
                      try {
                        const parsed = typeof agentResult === 'string' ? JSON.parse(agentResult) : agentResult
                        const summary = parsed.summary || ''

                        // Parse fields from summary string
                        const get = (label) => {
                          const match = summary.match(new RegExp(`\\*\\*${label}\\*\\*:\\s*([^\\n]+)`))
                          return match ? match[1].trim() : null
                        }

                        const decision   = get('Decision')
                        const path       = get('Chosen Path')
                        const riskDelta  = get('Risk Delta')
                        const timeImpact = get('Time Impact')
                        const costImpact = get('Cost Impact')
                        const rationale  = get('Rationale')

                        return (
                          <div className="p-3 space-y-3">

                            {/* Decision badge */}
                            {decision && (
                              <div className="flex items-center gap-2">
                                <span className="text-slate-400 text-xs">Decision:</span>
                                <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                                  decision.toLowerCase().includes('reroute') 
                                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                                    : 'bg-green-500/20 text-green-400 border border-green-500/30'
                                }`}>
                                  {decision}
                                </span>
                              </div>
                            )}

                            {/* Chosen path */}
                            {path && (
                              <div className="bg-[#1e293b] rounded px-3 py-2 border border-[#334155]">
                                <p className="text-slate-400 text-xs mb-1">Chosen Path</p>
                                <p className="text-[#06b6d4] font-mono text-xs">{path}</p>
                              </div>
                            )}

                            {/* Stat chips */}
                            <div className="grid grid-cols-3 gap-2">
                              {[
                                { label: 'Risk \u0394',  value: riskDelta  },
                                { label: 'Time',    value: timeImpact },
                                { label: 'Cost',    value: costImpact },
                              ].map(({ label, value }) => value && (
                                <div key={label} className="bg-[#1e293b] rounded p-2 border border-[#334155] text-center">
                                  <p className="text-slate-400 text-[10px]">{label}</p>
                                  <p className="text-white text-xs font-semibold mt-0.5">{value}</p>
                                </div>
                              ))}
                            </div>

                            {/* Rationale */}
                            {rationale && (
                              <div>
                                <p className="text-slate-400 text-[10px] uppercase tracking-widest mb-1">Rationale</p>
                                <p className="text-slate-300 text-xs leading-relaxed">{rationale}</p>
                              </div>
                            )}

                            {/* Footer */}
                            <div className="flex items-center gap-3 pt-1 border-t border-[#334155]">
                              <span className="text-slate-500 text-[10px]">
                                {parsed.turns_taken} turns
                              </span>
                              <span className="text-slate-500 text-[10px]">
                                {parsed.tool_calls?.length || 0} tools called
                              </span>
                              <span className="text-slate-500 text-[10px]">
                                {parsed.tool_calls?.join(' \u2192 ')}
                              </span>
                            </div>

                          </div>
                        )
                      } catch (e) {
                        // fallback \u2014 raw text if JSON parse fails
                        return (
                          <p className="p-3 text-slate-300 text-xs whitespace-pre-wrap leading-relaxed">
                            {agentResult}
                          </p>
                        )
                      }
                    })()}
                  </div>
                )}

              </div>
            )}
          </div>
        </div>
      </div>

      {/* DISRUPTION MODAL */}
      {showDisruptionModal && (
        <div className="fixed inset-0 z-[1000] bg-black/70 flex items-center justify-center">
          <div className="bg-[#1e293b] rounded-xl p-6 w-96 shadow-2xl border border-[#334155]">
            <h2 className="text-white text-lg font-bold mb-4">Inject Disruption</h2>
            
            <div className="mb-4">
              <label className="block text-slate-400 text-xs mb-1">Affected Node</label>
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
              <label className="block text-slate-400 text-xs mb-1">
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
              <label className="block text-slate-400 text-xs mb-1">Disruption Type</label>
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