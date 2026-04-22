import React, { useEffect, useMemo, useState } from "react";

const FACTORS = [
  {
    key: "congestion_contribution",
    icon: "\uD83D\uDEA2",
    label: "Port Congestion",
  },
  {
    key: "weather_contribution",
    icon: "\uD83C\uDF2A\uFE0F",
    label: "Weather Risk",
  },
  {
    key: "geopolitical_contribution",
    icon: "\uD83C\uDF0D",
    label: "Geopolitical",
  },
  {
    key: "carrier_reliability_contribution",
    icon: "\uD83D\uDE9B",
    label: "Carrier Reliability",
  },
  {
    key: "time_pressure_contribution",
    icon: "\u23F0",
    label: "Time Pressure",
  },
];

const getZeroValues = () =>
  FACTORS.reduce((accumulator, factor) => {
    accumulator[factor.key] = 0;
    return accumulator;
  }, {});

const clampScore = (value) => {
  const numericValue = Number(value);

  if (Number.isNaN(numericValue)) {
    return 0;
  }

  return Math.min(1, Math.max(0, numericValue));
};

const getRiskTextColor = (value) => {
  if (value < 0.3) return "text-[#22c55e]";
  if (value < 0.6) return "text-[#f59e0b]";
  return "text-[#ef4444]";
};

const getRiskBarColor = (value) => {
  if (value < 0.3) return "bg-[#22c55e]";
  if (value < 0.6) return "bg-[#f59e0b]";
  return "bg-[#ef4444]";
};

const formatPercent = (value) => `${Math.round(clampScore(value) * 100)}%`;

function RiskBreakdown({ shipment, riskBreakdown, loading }) {
  const [animatedValues, setAnimatedValues] = useState(getZeroValues);
  const hasBreakdownData = Boolean(riskBreakdown);

  const normalizedBreakdown = useMemo(() => {
    const source = riskBreakdown ?? {};

    const factorValues = FACTORS.reduce((accumulator, factor) => {
      accumulator[factor.key] = clampScore(source[factor.key]);
      return accumulator;
    }, {});

    return {
      ...factorValues,
      total_risk_score: clampScore(source.total_risk_score),
      summary_text:
        typeof source.summary_text === "string" && source.summary_text.trim().length > 0
          ? source.summary_text
          : "No risk summary is available for this shipment.",
    };
  }, [riskBreakdown]);

  useEffect(() => {
    if (!shipment || loading || !hasBreakdownData) {
      setAnimatedValues(getZeroValues());
      return;
    }

    setAnimatedValues(getZeroValues());

    const timeoutId = setTimeout(() => {
      setAnimatedValues(
        FACTORS.reduce((accumulator, factor) => {
          accumulator[factor.key] = normalizedBreakdown[factor.key];
          return accumulator;
        }, {})
      );
    }, 40);

    return () => clearTimeout(timeoutId);
  }, [hasBreakdownData, loading, normalizedBreakdown, shipment]);

  if (!shipment) {
    return (
      <div className="w-full rounded-xl bg-[#1e293b] p-4">
        <div className="flex min-h-[160px] items-center justify-center text-sm text-slate-500">
          Select a shipment to see risk breakdown
        </div>
      </div>
    );
  }

  const totalRiskScore = normalizedBreakdown.total_risk_score;

  const dominantFactor = FACTORS.reduce((maxFactor, currentFactor) => {
    if (!maxFactor) return currentFactor;

    return normalizedBreakdown[currentFactor.key] > normalizedBreakdown[maxFactor.key]
      ? currentFactor
      : maxFactor;
  }, null);

  return (
    <div className="w-full rounded-xl bg-[#1e293b] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-white">Risk Breakdown</h3>
        <div className="rounded-lg bg-slate-900/40 px-3 py-1">
          <span
            className={`text-2xl font-bold leading-none ${
              loading ? "text-slate-400" : getRiskTextColor(totalRiskScore)
            }`}
          >
            {loading ? "--" : formatPercent(totalRiskScore)}
          </span>
        </div>
      </div>

      {loading ? (
        <div className="mb-4 h-4 w-3/4 animate-pulse rounded bg-slate-700" />
      ) : (
        <p className="mb-4 text-sm italic text-slate-300">{normalizedBreakdown.summary_text}</p>
      )}

      {loading ? (
        <div className="space-y-3">
          {FACTORS.map((factor) => (
            <div key={factor.key} className="flex items-center gap-3">
              <div className="h-4 w-36 animate-pulse rounded bg-slate-700" />
              <div className="flex flex-1 items-center gap-3">
                <div className="h-2 w-full animate-pulse rounded-full bg-slate-700" />
                <div className="h-3 w-10 animate-pulse rounded bg-slate-700" />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="space-y-3">
            {FACTORS.map((factor) => {
              const value = normalizedBreakdown[factor.key];
              const animatedValue = animatedValues[factor.key] ?? 0;

              return (
                <div key={factor.key} className="flex items-center gap-3">
                  <div className="flex w-44 shrink-0 items-center gap-2 text-sm text-slate-400">
                    <span>{factor.icon}</span>
                    <span>{factor.label}</span>
                  </div>

                  <div className="flex flex-1 items-center gap-3">
                    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-700">
                      <div
                        className={`h-2 rounded-full ${getRiskBarColor(value)}`}
                        style={{
                          width: `${Math.round(animatedValue * 100)}%`,
                          transition: "width 0.6s ease-in-out",
                        }}
                      />
                    </div>
                    <span className="w-10 text-right text-xs text-slate-300">{formatPercent(value)}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {hasBreakdownData && dominantFactor && (
            <p className="mt-4 text-sm font-medium text-[#f59e0b]">
              {"\u26A0\uFE0F"} Primary Risk Driver: {dominantFactor.label}
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default RiskBreakdown;
