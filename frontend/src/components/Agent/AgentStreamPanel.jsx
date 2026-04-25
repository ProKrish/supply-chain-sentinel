import { useState, useCallback } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import { rerouteAgentStream } from '../../api/client'

const TOOL_META = {
    get_shipment_details: { icon: '📦', color: '#06b6d4', label: 'Fetching shipment details' },
    get_alternative_routes: { icon: '🗺️', color: '#8b5cf6', label: 'Finding alternative routes' },
    find_alternative_paths: { icon: '🗺️', color: '#8b5cf6', label: 'Finding alternative paths' },
    score_route: { icon: '📊', color: '#f59e0b', label: 'Scoring route' },
    score_reroute_tradeoffs: { icon: '⚖️', color: '#f59e0b', label: 'Scoring tradeoffs' },
    commit_reroute: { icon: '✅', color: '#22c55e', label: 'Committing reroute decision' },
}

/* ---------- visual result renderers ---------- */

function ShipmentCard({ data }) {
    if (!data) return null
    const d = typeof data === 'string' ? tryParse(data) : data
    if (!d) return null
    const risk = Number(d.risk_score)
    const riskPct = isNaN(risk) ? 0 : Math.round(risk * 100)
    const riskColor = risk > 0.6 ? '#ef4444' : risk > 0.3 ? '#f59e0b' : '#22c55e'
    return (
        <div className="bg-[#0f172a] rounded-lg p-3 border border-[#334155] space-y-2 animate-fade-in">
            <div className="flex items-center gap-2">
                <span className="text-cyan-400 font-mono text-xs font-bold">{d.shipment_id}</span>
                <span className={`ml-auto text-[10px] uppercase tracking-wider px-2 py-0.5 rounded font-semibold`}
                    style={{ backgroundColor: riskColor + '22', color: riskColor, border: `1px solid ${riskColor}44` }}>
                    {d.status?.replace('_', ' ') || 'unknown'}
                </span>
            </div>
            <div className="flex items-center justify-center gap-3 bg-[#1e293b] rounded-md py-2 px-3">
                <div className="text-center">
                    <p className="text-[10px] text-slate-500 uppercase">Origin</p>
                    <p className="text-white text-sm font-medium">{d.origin || '—'}</p>
                </div>
                <div className="flex flex-col items-center gap-0.5">
                    <div className="flex items-center gap-1">
                        <div className="w-2 h-2 rounded-full bg-cyan-400" />
                        <div className="w-12 h-0.5 bg-gradient-to-r from-cyan-400 to-amber-400 rounded" />
                        <div className="w-2 h-2 rounded-full bg-amber-400" />
                    </div>
                    <span className="text-[9px] text-slate-500">{d.cargo_type || 'cargo'}</span>
                </div>
                <div className="text-center">
                    <p className="text-[10px] text-slate-500 uppercase">Dest</p>
                    <p className="text-white text-sm font-medium">{d.destination || '—'}</p>
                </div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
                <MiniStat label="Risk" value={`${riskPct}%`} color={riskColor} />
                <MiniStat label="Priority" value={`Tier ${d.priority_tier || '?'}`} color="#06b6d4" />
                <MiniStat label="Carrier" value={d.carrier_id || d.carrier || '—'} color="#94a3b8" />
            </div>
        </div>
    )
}

function RouteCards({ data }) {
    const routes = Array.isArray(data) ? data : tryParse(data)
    if (!Array.isArray(routes) || routes.length === 0) return <FallbackResult data={data} />
    return (
        <div className="space-y-2 animate-fade-in">
            {routes.map((r, i) => {
                const nodes = r.nodes || r.path || []
                const score = r.risk_score ?? r.total_risk ?? null
                const scorePct = score != null ? Math.round(Number(score) * 100) : null
                const scoreColor = score > 0.6 ? '#ef4444' : score > 0.3 ? '#f59e0b' : '#22c55e'
                return (
                    <div key={i} className="bg-[#0f172a] rounded-lg p-3 border border-[#334155]">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-purple-400 text-xs font-bold">{r.route_id || `Route ${i + 1}`}</span>
                            {scorePct != null && (
                                <span className="text-[10px] px-2 py-0.5 rounded font-semibold"
                                    style={{ backgroundColor: scoreColor + '22', color: scoreColor }}>
                                    Risk {scorePct}%
                                </span>
                            )}
                        </div>
                        {nodes.length > 0 && (
                            <div className="flex items-center gap-1 flex-wrap py-1">
                                {nodes.map((n, j) => (
                                    <div key={j} className="flex items-center gap-1">
                                        <span className="bg-[#1e293b] text-slate-300 text-[10px] px-2 py-0.5 rounded-full border border-[#334155]">
                                            {n}
                                        </span>
                                        {j < nodes.length - 1 && <span className="text-slate-600 text-xs">→</span>}
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="flex gap-3 mt-2 text-[10px] text-slate-500">
                            {r.estimated_days != null && <span>⏱ {r.estimated_days}d</span>}
                            {r.total_edges != null && <span>🔗 {r.total_edges} edges</span>}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

function ScoreCard({ data }) {
    const d = typeof data === 'string' ? tryParse(data) : data
    if (!d) return <FallbackResult data={data} />
    const nodes = d.route_nodes || d.nodes || d.path || []
    const items = [
        { label: 'Time', value: d.time_score, icon: '⏱' },
        { label: 'Cost', value: d.cost_score, icon: '💰' },
        { label: 'Risk', value: d.risk_score, icon: '⚠️' },
    ].filter(i => i.value != null)
    return (
        <div className="bg-[#0f172a] rounded-lg p-3 border border-[#334155] animate-fade-in">
            {nodes.length > 0 && (
                <p className="text-slate-400 text-[10px] mb-2">
                    Route: {nodes.join(' → ')}
                </p>
            )}
            <div className="grid grid-cols-3 gap-2">
                {items.map(({ label, value, icon }) => {
                    const pct = Math.round(Number(value) * 100)
                    const color = pct > 60 ? '#ef4444' : pct > 30 ? '#f59e0b' : '#22c55e'
                    return (
                        <div key={label} className="text-center bg-[#1e293b] rounded-md p-2">
                            <span className="text-sm">{icon}</span>
                            <p className="text-lg font-bold mt-0.5" style={{ color }}>{pct}%</p>
                            <p className="text-[9px] text-slate-500 uppercase">{label}</p>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function CommitCard({ data }) {
    const d = typeof data === 'string' ? tryParse(data) : data
    if (!d) return <FallbackResult data={data} />
    const success = d.success === true || d.success === 'true'
    return (
        <div className={`rounded-lg p-3 border animate-fade-in ${success ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
            <div className="flex items-center gap-2 mb-1">
                <span className="text-lg">{success ? '✅' : '❌'}</span>
                <span className={`text-sm font-semibold ${success ? 'text-green-400' : 'text-red-400'}`}>
                    {success ? 'Reroute Committed' : 'Reroute Failed'}
                </span>
            </div>
            {d.new_route && (
                <p className="text-slate-300 text-xs mt-1">
                    New route: <span className="text-cyan-400 font-mono">{Array.isArray(d.new_route) ? d.new_route.join(' → ') : d.new_route}</span>
                </p>
            )}
            {d.rationale && <p className="text-slate-400 text-xs mt-1 italic">{d.rationale}</p>}
        </div>
    )
}

function MiniStat({ label, value, color }) {
    return (
        <div className="bg-[#1e293b] rounded-md px-2 py-1.5">
            <p className="text-[9px] text-slate-500 uppercase">{label}</p>
            <p className="text-xs font-bold truncate" style={{ color }}>{value}</p>
        </div>
    )
}

function FallbackResult({ data }) {
    const text = typeof data === 'object' ? JSON.stringify(data) : String(data || '')
    if (!text || text === 'undefined') return null
    return (
        <p className="text-slate-400 text-xs leading-relaxed line-clamp-2 pl-6 py-1">
            {text.slice(0, 120)}{text.length > 120 ? '…' : ''}
        </p>
    )
}

function tryParse(s) {
    if (typeof s !== 'string') return s
    try { return JSON.parse(s) } catch { return null }
}

const RESULT_RENDERERS = {
    get_shipment_details: (d) => <ShipmentCard data={d} />,
    get_alternative_routes: (d) => <RouteCards data={d} />,
    find_alternative_paths: (d) => <RouteCards data={d} />,
    score_route: (d) => <ScoreCard data={d} />,
    score_reroute_tradeoffs: (d) => <ScoreCard data={d} />,
    commit_reroute: (d) => <CommitCard data={d} />,
}

/* ---------- stream event row ---------- */

function StreamEvent({ event, prevTool }) {
    const meta = TOOL_META[event.tool] || TOOL_META[prevTool] || { icon: '🔧', color: '#94a3b8', label: event.tool || 'Processing' }

    if (event.type === 'tool_call') return (
        <div className="flex items-center gap-2.5 py-2">
            <span className="text-base shrink-0">{meta.icon}</span>
            <span className="text-sm font-medium" style={{ color: meta.color }}>{meta.label}…</span>
            <span className="ml-auto flex gap-1">
                {[0, 150, 300].map((d) => (
                    <span key={d} className="w-1.5 h-1.5 rounded-full animate-bounce"
                        style={{ backgroundColor: meta.color, animationDelay: `${d}ms` }} />
                ))}
            </span>
        </div>
    )

    if (event.type === 'tool_result') {
        const renderer = RESULT_RENDERERS[prevTool]
        if (renderer) return <div className="py-1 pl-2">{renderer(event.result)}</div>
        return <FallbackResult data={event.result} />
    }

    return null
}

/* ---------- text parser ---------- */

function parseAISummary(text) {
    if (!text) return {}
    const clean = text.replace(/\*\*/g, '')

    // Extract shipment info
    const shipIdM = clean.match(/(?:shipment|SHP)[_ ]?(SHP[_\d]+|\d+)/i)
    const shipmentId = shipIdM ? shipIdM[1] : (clean.match(/SHP_\d+/)?.[0] || null)
    const originM = clean.match(/originat(?:ing|es?) (?:from|in) ([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)/i)
    const origin = originM ? originM[1] : null
    const destM = clean.match(/destination[:\s]+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)/i)
    const destination = destM ? destM[1] : null
    const riskM = clean.match(/risk[:\s]*(?:score)?[:\s]*(?:of\s+)?(\d*\.?\d+)/i)
    const riskScore = riskM ? parseFloat(riskM[1]) : null

    // Extract routes
    const routeMatches = [...clean.matchAll(/\d+\.\s*\[([^\]]+)\]/g)]
    const routes = routeMatches.map((m, i) => ({
        id: i + 1,
        nodes: m[1].split(',').map(n => n.replace(/"/g, '').trim()).filter(Boolean)
    }))

    // Extract new route / status from commit section
    const newRouteM = clean.match(/New Route[:\s]*\[([^\]]+)\]/i)
    const newRoute = newRouteM ? newRouteM[1].split(',').map(n => n.replace(/"/g, '').trim()).filter(Boolean) : null
    const newRiskM = clean.match(/New Risk[:\s]*(?:Score)?[:\s]*(\d*\.?\d+)/i)
    const newRisk = newRiskM ? parseFloat(newRiskM[1]) : null
    const statusM = clean.match(/Status[:\s]*([\w_]+)/i)
    const status = statusM ? statusM[1] : null
    const isRerouted = /reroute|commit|chosen|selected/i.test(clean)

    // Split into paragraphs for analysis sections
    const paragraphs = clean.split(/\n\n+/).map(p => p.trim()).filter(p => p.length > 20)
    // Find analysis paragraph (the longest one that talks about scoring/routes)
    const analysisPara = paragraphs.find(p => /scor|route|alternative|risk|tool|composite/i.test(p) && p.length > 60) || ''
    // Find rationale paragraph
    const rationalePara = paragraphs.find(p => /given|therefore|decision|mandatory|chosen|commit/i.test(p) && p.length > 40) || ''

    return { shipmentId, origin, destination, riskScore, routes, newRoute, newRisk, status, isRerouted, analysisPara, rationalePara }
}

/* ---------- animated section wrapper ---------- */
function AnimSection({ delay = 0, children, className = '' }) {
    return (
        <div className={`done-section ${className}`}
            style={{ animationDelay: `${delay}ms` }}>
            {children}
        </div>
    )
}

/* ---------- done panel ---------- */

function DonePanel({ result, summary = '' }) {
    if (!result) return null

    const resolvedSummary = summary || result.final_recommendation || result.summary?.final_recommendation || ''
    const parsed = parseAISummary(resolvedSummary)
    const toolCalls = Array.isArray(result.tool_calls) ? result.tool_calls
        : Array.isArray(result.summary?.tools_called) ? result.summary.tools_called : []
    const turns = result.turns ?? result.summary?.turns_taken ?? '?'

    const riskColor = (v) => !v && v !== 0 ? '#94a3b8' : v > 0.6 ? '#ef4444' : v > 0.3 ? '#f59e0b' : '#22c55e'
    const riskPct = (v) => v != null ? Math.round((v > 1 ? v : v * 100)) : null

    return (
        <div className="mt-3 pt-3 border-t border-[#334155] space-y-3">

            {/* ── Success Banner ── */}
            <AnimSection delay={0}>
                <div className="relative overflow-hidden rounded-xl p-4"
                    style={{ background: parsed.isRerouted
                        ? 'linear-gradient(135deg, rgba(34,197,94,0.12), rgba(6,182,212,0.08))'
                        : 'linear-gradient(135deg, rgba(6,182,212,0.12), rgba(139,92,246,0.08))',
                        border: `1px solid ${parsed.isRerouted ? 'rgba(34,197,94,0.25)' : 'rgba(6,182,212,0.25)'}` }}>
                    <div className="done-glow" style={{ background: parsed.isRerouted ? '#22c55e' : '#06b6d4' }} />
                    <div className="flex items-center gap-3 relative z-10">
                        <div className="w-10 h-10 rounded-full flex items-center justify-center text-lg"
                            style={{ background: parsed.isRerouted ? 'rgba(34,197,94,0.2)' : 'rgba(6,182,212,0.2)' }}>
                            {parsed.isRerouted ? '✅' : '🔍'}
                        </div>
                        <div>
                            <p className="text-white text-sm font-bold">
                                {parsed.isRerouted ? 'Reroute Committed' : 'Analysis Complete'}
                            </p>
                            <p className="text-slate-400 text-[11px]">
                                {parsed.shipmentId && <>Shipment <span className="text-cyan-400 font-mono">{parsed.shipmentId}</span></>}
                                {parsed.origin && parsed.destination && <> · {parsed.origin} → {parsed.destination}</>}
                            </p>
                        </div>
                    </div>
                </div>
            </AnimSection>

            {/* ── Risk Comparison ── */}
            {parsed.riskScore != null && (
                <AnimSection delay={150}>
                    <div className="grid grid-cols-2 gap-2">
                        <div className="bg-[#0f172a] rounded-xl p-3 border border-[#334155] text-center">
                            <p className="text-slate-500 text-[9px] uppercase tracking-wider mb-1">Before</p>
                            <div className="relative w-16 h-16 mx-auto">
                                <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
                                    <circle cx="40" cy="40" r="32" fill="none" stroke="#1e293b" strokeWidth="6"/>
                                    <circle cx="40" cy="40" r="32" fill="none"
                                        stroke={riskColor(parsed.riskScore)} strokeWidth="6" strokeLinecap="round"
                                        strokeDasharray={`${(parsed.riskScore > 1 ? parsed.riskScore / 100 : parsed.riskScore) * 201} 201`}
                                        className="done-gauge" />
                                </svg>
                                <span className="absolute inset-0 flex items-center justify-center text-sm font-bold"
                                    style={{ color: riskColor(parsed.riskScore) }}>
                                    {riskPct(parsed.riskScore)}%
                                </span>
                            </div>
                            <p className="text-red-400 text-[10px] font-medium mt-1">High Risk</p>
                        </div>
                        <div className="bg-[#0f172a] rounded-xl p-3 border border-[#334155] text-center">
                            <p className="text-slate-500 text-[9px] uppercase tracking-wider mb-1">After</p>
                            <div className="relative w-16 h-16 mx-auto">
                                <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
                                    <circle cx="40" cy="40" r="32" fill="none" stroke="#1e293b" strokeWidth="6"/>
                                    <circle cx="40" cy="40" r="32" fill="none"
                                        stroke={riskColor(parsed.newRisk ?? 0)} strokeWidth="6" strokeLinecap="round"
                                        strokeDasharray={`${(parsed.newRisk ?? 0) * 201} 201`}
                                        className="done-gauge" style={{ animationDelay: '400ms' }} />
                                </svg>
                                <span className="absolute inset-0 flex items-center justify-center text-sm font-bold"
                                    style={{ color: riskColor(parsed.newRisk ?? 0) }}>
                                    {riskPct(parsed.newRisk ?? 0)}%
                                </span>
                            </div>
                            <p className="text-green-400 text-[10px] font-medium mt-1">Optimized</p>
                        </div>
                    </div>
                </AnimSection>
            )}

            {/* ── Routes Considered ── */}
            {parsed.routes.length > 0 && (
                <AnimSection delay={300}>
                    <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2 flex items-center gap-1.5">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" strokeWidth="2"><path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg>
                        Routes Evaluated
                    </p>
                    <div className="space-y-2">
                        {parsed.routes.map((r, i) => (
                            <div key={i} className="bg-[#0f172a] rounded-lg p-2.5 border border-[#334155] route-card"
                                style={{ animationDelay: `${350 + i * 100}ms` }}>
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-purple-400 text-[10px] font-bold shrink-0">#{r.id}</span>
                                    {r.nodes.map((n, j) => (
                                        <div key={j} className="flex items-center gap-1">
                                            <span className="bg-[#1e293b] text-slate-300 text-[10px] px-2 py-0.5 rounded-full border border-[#334155]">{n}</span>
                                            {j < r.nodes.length - 1 && <span className="text-purple-500/50 text-[10px]">→</span>}
                                        </div>
                                    ))}
                                    {parsed.newRoute && JSON.stringify(r.nodes) === JSON.stringify(parsed.newRoute) && (
                                        <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded bg-green-500/15 text-green-400 border border-green-500/25 font-semibold">CHOSEN</span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </AnimSection>
            )}

            {/* ── New Route Result ── */}
            {parsed.newRoute && (
                <AnimSection delay={500}>
                    <div className="bg-gradient-to-r from-[#0f172a] to-[#0c1322] rounded-xl p-3 border border-cyan-500/20">
                        <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-2 flex items-center gap-1.5">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>
                            Committed Route
                        </p>
                        <div className="flex items-center gap-1.5 flex-wrap">
                            {parsed.newRoute.map((n, j) => (
                                <div key={j} className="flex items-center gap-1.5">
                                    <span className="bg-cyan-500/10 text-cyan-300 text-xs px-2.5 py-1 rounded-lg border border-cyan-500/20 font-medium">{n}</span>
                                    {j < parsed.newRoute.length - 1 && (
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                                    )}
                                </div>
                            ))}
                        </div>
                        {parsed.status && (
                            <div className="mt-2 flex items-center gap-2">
                                <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                                <span className="text-amber-400 text-[10px] font-semibold uppercase tracking-wider">{parsed.status.replace(/_/g, ' ')}</span>
                            </div>
                        )}
                    </div>
                </AnimSection>
            )}

            {/* ── Analysis Summary ── */}
            {parsed.rationalePara && (
                <AnimSection delay={650}>
                    <div className="bg-[#0f172a] rounded-xl p-3 border border-[#334155]">
                        <p className="text-slate-500 text-[10px] uppercase tracking-widest mb-1.5 flex items-center gap-1.5">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                            Rationale
                        </p>
                        <p className="text-slate-300 text-xs leading-relaxed">{parsed.rationalePara}</p>
                    </div>
                </AnimSection>
            )}

            {/* ── Agent Stats Footer ── */}
            <AnimSection delay={800}>
                <div className="flex items-center gap-3 pt-2 border-t border-[#334155]/50">
                    <div className="flex items-center gap-1.5 text-slate-500 text-[10px]">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
                        {turns} turns
                    </div>
                    <div className="flex items-center gap-1.5 text-slate-500 text-[10px]">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>
                        {toolCalls.length} tools
                    </div>
                    <div className="flex items-center gap-1 text-slate-600 text-[10px] truncate ml-auto">
                        {toolCalls.map((t, i) => (
                            <span key={i} className="flex items-center gap-1">
                                <span className="bg-[#1e293b] px-1.5 py-0.5 rounded text-[9px]">{t.replace(/^(get_|find_|commit_|score_)/, '')}</span>
                                {i < toolCalls.length - 1 && <span className="text-slate-700">›</span>}
                            </span>
                        ))}
                    </div>
                </div>
            </AnimSection>
        </div>
    )
}

function normalizeDoneEvent(event) {
    const summary = event?.summary || {}
    return {
        turns: event?.turns ?? summary?.turns_taken ?? null,
        tool_calls: event?.tool_calls ?? summary?.tools_called ?? [],
        final_recommendation: event?.final_recommendation ?? summary?.final_recommendation ?? '',
        summary,
    }
}

export default function AgentStreamPanel({ shipmentId, analyzeButtonAriaLabel }) {
    const { getAccessTokenSilently } = useAuth0()
    const [events, setEvents] = useState([])
    const [result, setResult] = useState(null)
    const [lastText, setLastText] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const runStream = useCallback(async () => {
        setEvents([])
        setResult(null)
        setLastText('')
        setError(null)
        setLoading(true)

        try {
            const reader = await rerouteAgentStream(shipmentId, getAccessTokenSilently)
            const decoder = new TextDecoder()
            let buffer = ''

            const processLine = (rawLine) => {
                const line = rawLine.trim()
                if (!line.startsWith('data:')) return

                try {
                    const event = JSON.parse(line.slice(5).trim())
                    if (event.type === 'done') {
                        const normalized = normalizeDoneEvent(event)
                        setResult(normalized)
                        if (normalized.final_recommendation) {
                            setLastText((prev) => prev || normalized.final_recommendation)
                        }
                        return
                    }

                    if (event.type === 'text' && event.content) {
                        setLastText((prev) => prev + event.content)
                        return
                    }

                    if (event.type === 'error') {
                        setError(event.content || 'Streaming error')
                    }

                    setEvents((prev) => [...prev, event])
                } catch {
                    // Ignore malformed chunks
                }
            }

            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop() || ''

                for (const line of lines) {
                    processLine(line)
                }
            }

            const flushed = buffer + decoder.decode()
            if (flushed.trim()) {
                flushed.split('\n').forEach(processLine)
            }
        } catch (err) {
            setError(err?.message || 'Failed to read stream')
        } finally {
            setLoading(false)
        }
    }, [shipmentId, getAccessTokenSilently])

    // Track last tool_call name so tool_result knows which renderer to use
    let lastToolName = null

    return (
        <div className="mt-4">
            <button
                onClick={runStream}
                disabled={loading}
                aria-label={analyzeButtonAriaLabel}
                className="w-full py-3 px-6 rounded-lg font-semibold text-sm tracking-wide transition-all duration-200 flex items-center justify-center gap-2"
                style={{
                    background: loading
                        ? 'linear-gradient(135deg, #0e7490, #0891b2)'
                        : 'linear-gradient(135deg, #06b6d4, #0891b2)',
                    color: '#0f172a',
                    cursor: loading ? 'wait' : 'pointer',
                    boxShadow: loading ? 'none' : '0 0 20px rgba(6,182,212,0.3)',
                }}
            >
                {loading ? (
                    <>
                        <span className="w-4 h-4 border-2 border-[#0f172a] border-t-transparent rounded-full animate-spin" />
                        Agent Running…
                    </>
                ) : result ? '🔄 Re-analyze with AI' : '🤖 Analyze with AI'}
            </button>

            {(loading || events.length > 0 || result || error) && (
                <div className="mt-3 bg-[#0f172a] border border-[#334155] rounded-xl overflow-hidden shadow-lg">
                    <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[#334155] bg-gradient-to-r from-[#1e293b] to-[#0f172a]">
                        <span className={`w-2.5 h-2.5 rounded-full ${loading ? 'bg-cyan-400 animate-pulse' : 'bg-green-400'}`} />
                        <p className="text-white text-xs font-semibold">
                            {loading ? '🧠 Agent Reasoning…' : '✨ AI Recommendation'}
                        </p>
                    </div>

                    {events.length > 0 && (
                        <div className="px-4 py-2 max-h-[400px] overflow-y-auto space-y-1 scrollbar-thin">
                            {events.map((e, i) => {
                                if (e.type === 'tool_call') lastToolName = e.tool
                                const prevTool = e.type === 'tool_result' ? lastToolName : e.tool
                                return <StreamEvent key={i} event={e} prevTool={prevTool} />
                            })}
                        </div>
                    )}

                    {error && (
                        <p className="px-4 py-2 text-red-400 text-xs">⚠️ Error: {error}</p>
                    )}

                    {result && (
                        <div className="px-4 pb-4">
                            <DonePanel result={result} summary={lastText} />
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
