export default function MapLegend() {
  return (
    <div className="absolute bottom-4 left-4 z-10 p-3 rounded" style={{ backgroundColor: 'rgba(15, 23, 42, 0.85)', border: '1px solid #334155' }}>
      <div className="text-xs text-slate-400 mb-2">
        Risk Level
      </div>
      
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <div className="w-[10px] h-[10px] rounded-full bg-[#22c55e]" />
          <span className="text-sm text-white">Low Risk &lt; 30%</span>
        </div>
        
        <div className="flex items-center gap-2">
          <div className="w-[10px] h-[10px] rounded-full bg-[#f59e0b]" />
          <span className="text-sm text-white">Medium Risk 30-60%</span>
        </div>
        
        <div className="flex items-center gap-2">
          <div className="w-[10px] h-[10px] rounded-full bg-[#ef4444]" />
          <span className="text-sm text-white">High Risk &gt; 60%</span>
        </div>
      </div>
    </div>
  );
}
