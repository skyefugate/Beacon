interface HeaderProps {
  probeId: string
  isOnline: boolean
}

export default function Header({ probeId, isOnline }: HeaderProps) {
  return (
    <header className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${isOnline ? 'bg-emerald-400' : 'bg-red-400'}`} />
          <span className="text-lg font-semibold text-slate-100 tracking-tight">Beacon</span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <span className="text-sm text-slate-400 font-mono">{probeId}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
          isOnline
            ? 'bg-emerald-400/10 text-emerald-400'
            : 'bg-red-400/10 text-red-400'
        }`}>
          {isOnline ? 'Online' : 'Offline'}
        </span>
      </div>
    </header>
  )
}
