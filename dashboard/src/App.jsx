import { useState } from 'react';
import { Anchor, MapTrifold, Path } from '@phosphor-icons/react';
import WorldRiskMap from './components/WorldRiskMap';
import PortDrilldown from './components/PortDrilldown';
import RouteSimulator from './components/RouteSimulator';

const NAV = [
  { id: 'map',   label: 'World Risk Map',  Icon: MapTrifold },
  { id: 'route', label: 'Route Simulator', Icon: Path },
];

export default function App() {
  const [panel,        setPanel]        = useState('map');
  const [selectedPort, setSelectedPort] = useState(null);

  return (
    <div className="flex flex-col h-dvh bg-abyss text-ink overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-5 h-[56px] bg-hull border-b hairline shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-signal-deep/25 border border-signal/30 flex items-center justify-center shrink-0">
            <Anchor size={17} weight="bold" className="text-signal" />
          </div>
          <div className="leading-tight min-w-0">
            <div className="font-semibold tracking-tight text-[15px]">NautIQ</div>
            <div className="text-ink-dim text-[11px] truncate hidden sm:block">Global port delay intelligence</div>
          </div>
        </div>

        <nav className="flex gap-1 bg-abyss/60 border hairline rounded-lg p-1" aria-label="Views">
          {NAV.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => { setPanel(id); if (id !== 'map') setSelectedPort(null); }}
              aria-current={panel === id ? 'page' : undefined}
              className={`pressable flex items-center gap-2 px-3 py-1.5 rounded-md text-[13px] font-medium ${
                panel === id
                  ? 'bg-hull-3 text-ink'
                  : 'text-ink-mute hover:text-ink hover:bg-hull-2'
              }`}
            >
              <Icon size={15} weight={panel === id ? 'fill' : 'regular'}
                    className={panel === id ? 'text-signal' : ''} />
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
        </nav>

        <div className="text-ink-dim text-[11px] font-mono hidden md:block">
          XGBoost · 60 ports · 2020–2024
        </div>
      </header>

      {/* Main content */}
      <main className="flex flex-1 overflow-hidden">
        {panel === 'map' && (
          <>
            <WorldRiskMap onPortSelect={setSelectedPort} />
            {selectedPort && (
              <PortDrilldown
                portCode={selectedPort}
                onClose={() => setSelectedPort(null)}
              />
            )}
          </>
        )}
        {panel === 'route' && <RouteSimulator />}
      </main>
    </div>
  );
}
