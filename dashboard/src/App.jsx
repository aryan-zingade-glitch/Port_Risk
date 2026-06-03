import { useState } from 'react';
import WorldRiskMap from './components/WorldRiskMap';
import PortDrilldown from './components/PortDrilldown';
import RouteSimulator from './components/RouteSimulator';

const NAV = [
  { id: 'map',   label: 'World Risk Map',  icon: '🗺' },
  { id: 'route', label: 'Route Simulator', icon: '🚢' },
];

export default function App() {
  const [panel,        setPanel]        = useState('map');
  const [selectedPort, setSelectedPort] = useState(null);

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white overflow-hidden">
      {/* Top nav */}
      <header className="flex items-center justify-between px-5 py-3 bg-gray-900 border-b border-gray-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center text-sm">⚓</div>
            <span className="font-bold text-white tracking-tight">PortRisk</span>
          </div>
          <span className="text-gray-600 text-xs hidden sm:block">Global Port Delay Intelligence</span>
        </div>

        <nav className="flex gap-1">
          {NAV.map(n => (
            <button
              key={n.id}
              onClick={() => { setPanel(n.id); if (n.id !== 'map') setSelectedPort(null); }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                panel === n.id
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <span>{n.icon}</span>
              <span className="hidden sm:inline">{n.label}</span>
            </button>
          ))}
        </nav>

        <div className="text-gray-600 text-xs hidden md:block">
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
