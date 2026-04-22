import { useState, useCallback } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import { rerouteAgentStream } from '../../api/client'

const TOOL_ICONS = {
    get_shipment_details: '[INFO]',
    get_alternative_routes: '[PATH]',
    find_alternative_paths: '[PATH]',
    score_route: '[SCORE]',
    score_reroute_tradeoffs: '[SCORE]',
    commit_reroute: '[OK]',
}

const TOOL_LABELS = {
    get_shipment_details: 'Fetching shipment details',
    get_alternative_routes: 'Finding alternative routes',
    find_alternative_paths: 'Finding alternative paths',
    score_route: 'Scoring route',
    score_reroute_tradeoffs: 'Scoring tradeoffs',
    commit_reroute: 'Committing reroute decision',
}

function StreamEvent({ event }) {
    if (event.type === 'tool_call') return (
        <div className="flex items-center gap-2 py-1">
            <span>{TOOL_ICONS[event.tool] || '[TOOL]'}</span>
            <span className="text-slate-300 text-xs">
                {TOOL_LABELS[event.tool] || event.tool}...
            </span>
            <span className="ml-auto flex gap-0.5">
                {[0, 150, 300].map((d) => (
                    <span
                        key={d}
                        className="w-1 h-1 bg-cyan-400 rounded-full animate-bounce"
                        style={{ animationDelay: `${d}ms` }}
                    />
                ))}
            </span>
        </div>
    )

    if (event.type === 'tool_result') return (
        <div className="flex items-start gap-2 py-1 pl-6">
            <span className="text-green-400 text-xs mt-0.5">OK</span>
            <span className="text-slate-400 text-xs leading-relaxed line-clamp-2">
                {typeof event.result === 'object'
                    ? `${JSON.stringify(event.result).slice(0, 100)}...`
                    : String(event.result).slice(0, 100)}
            </span>
        </div>
    )

    return null
}

function DonePanel({ result, summary = '' }) {
    if (!result) return null

    const resolvedSummary =
        summary
        || result.final_recommendation
        || result.summary?.final_recommendation
        || ''

    const get = (label) => {
        const match = resolvedSummary.match(
            new RegExp(`\\*\\*${label}\\*\\*:\\s*([^\\n]+)`)
        )
        return match ? match[1].trim() : null
    }

    const decision = get('Decision')
    const path = get('Chosen Path')
    const riskDelta = get('Risk Delta')
    const timeImpact = get('Time Impact')
    const costImpact = get('Cost Impact')
    const rationale = get('Rationale')

    const toolCalls = Array.isArray(result.tool_calls)
        ? result.tool_calls
        : Array.isArray(result.summary?.tools_called)
            ? result.summary.tools_called
            : []

    const turns = result.turns ?? result.summary?.turns_taken ?? '?'

    return (
        <div className="mt-3 border-t border-[#334155] pt-3 space-y-3">
            {decision && (
                <div className="flex items-center gap-2">
                    <span className="text-slate-400 text-xs">Decision:</span>
                    <span
                        className={`text-xs px-2 py-0.5 rounded font-semibold ${decision.toLowerCase().includes('reroute')
                            ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                            : 'bg-green-500/20 text-green-400 border border-green-500/30'
                            }`}
                    >
                        {decision}
                    </span>
                </div>
            )}

            {path && (
                <div className="bg-[#0f172a] rounded px-3 py-2 border border-[#334155]">
                    <p className="text-slate-400 text-[10px] mb-1">Chosen Path</p>
                    <p className="text-[#06b6d4] font-mono text-xs">{path}</p>
                </div>
            )}

            <div className="grid grid-cols-3 gap-2">
                {[
                    { label: 'Risk Delta', value: riskDelta },
                    { label: 'Time', value: timeImpact },
                    { label: 'Cost', value: costImpact },
                ].map(({ label, value }) => value && (
                    <div key={label} className="bg-[#0f172a] rounded p-2 border border-[#334155] text-center">
                        <p className="text-slate-400 text-[10px]">{label}</p>
                        <p className="text-white text-xs font-semibold mt-0.5">{value}</p>
                    </div>
                ))}
            </div>

            {rationale && (
                <div>
                    <p className="text-slate-400 text-[10px] uppercase tracking-widest mb-1">Rationale</p>
                    <p className="text-slate-300 text-xs leading-relaxed">{rationale}</p>
                </div>
            )}

            {!decision && resolvedSummary && (
                <div className="bg-[#0f172a] rounded px-3 py-2 border border-[#334155]">
                    <p className="text-slate-300 text-xs leading-relaxed whitespace-pre-wrap">{resolvedSummary}</p>
                </div>
            )}

            <div className="flex gap-3 pt-1 border-t border-[#334155]">
                <span className="text-slate-500 text-[10px]">{turns} turns</span>
                <span className="text-slate-500 text-[10px]">{toolCalls.length} tools</span>
                <span className="text-slate-500 text-[10px] truncate">{toolCalls.join(' -> ')}</span>
            </div>
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

export default function AgentStreamPanel({ shipmentId }) {
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
                    // Ignore malformed chunks and continue streaming.
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

    return (
        <div className="mt-4">
            <button
                onClick={runStream}
                disabled={loading}
                className="w-full py-3 px-6 rounded-lg font-semibold text-sm tracking-wide transition-all duration-200"
                style={{
                    backgroundColor: loading ? '#0e7490' : '#06b6d4',
                    color: '#0f172a',
                    cursor: loading ? 'wait' : 'pointer',
                }}
            >
                {loading ? 'Agent Running...' : result ? 'Re-analyze with AI' : 'Analyze with AI'}
            </button>

            {(loading || events.length > 0 || result || error) && (
                <div className="mt-3 bg-[#0f172a] border border-[#334155] rounded-lg overflow-hidden">
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-[#334155] bg-[#1e293b]">
                        <span className={`w-2 h-2 rounded-full ${loading ? 'bg-cyan-400 animate-pulse' : 'bg-green-400'}`} />
                        <p className="text-white text-xs font-semibold">
                            {loading ? 'Agent Reasoning...' : 'AI Recommendation'}
                        </p>
                    </div>

                    {events.length > 0 && (
                        <div className="px-3 py-2 max-h-48 overflow-y-auto space-y-0.5">
                            {events.map((e, i) => <StreamEvent key={i} event={e} />)}
                        </div>
                    )}

                    {error && (
                        <p className="px-3 py-2 text-red-400 text-xs">Error: {error}</p>
                    )}

                    {result && (
                        <div className="px-3 pb-3">
                            <DonePanel result={result} summary={lastText} />
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
