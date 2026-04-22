import 'leaflet/dist/leaflet.css';
import { MapContainer, TileLayer, CircleMarker, Polyline, Tooltip } from 'react-leaflet';
import { getShipments, getGraph } from "../../api/client";
import { useState, useEffect, useRef } from 'react';

const PORT_COORDS = {
  "Shanghai": [31.2304, 121.4737],
  "Rotterdam": [51.9225, 4.4792],
  "Los Angeles": [33.7290, -118.2620],
  "Mumbai": [19.0760, 72.8777],
  "Felixstowe": [51.9639, 1.3518],
  "Singapore": [1.3521, 103.8198],
  "Hamburg": [53.5753, 9.8689],
  "Dubai": [25.2048, 55.2708],
  "New York": [40.6501, -74.0094],
  "Tokyo": [35.6762, 139.6503],
  "Long Beach": [33.7701, -118.1937],
  "Chennai": [13.0827, 80.2707],
  "Hong Kong": [22.3193, 114.1694],
  "Vancouver": [49.2827, -123.1207],
  "Busan": [35.1796, 129.0756],
  "Seattle": [47.6062, -122.3321],
  "Sydney": [-33.8688, 151.2093],
  "Chicago": [41.8781, -87.6298],
  "Colombo": [6.9271, 79.8612],
  "Suez Canal Zone": [30.5852, 32.2650]
};

function getRiskColor(score) {
  if (score < 0.3) return '#22c55e'; // green
  if (score < 0.6) return '#f59e0b'; // amber
  return '#ef4444'; // red
}

export default function ShipmentMap({ onShipmentClick, selectedShipmentId }) {
  const [shipments, setShipments] = useState([]);
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(true);
  const [secondsAgo, setSecondsAgo] = useState(0);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [shipmentsRes, graphRes] = await Promise.all([
        getShipments({ limit: 500 }),
        getGraph()
      ]);
      setShipments(shipmentsRes?.shipments || shipmentsRes || []);
      setGraphData(graphRes || { nodes: [], edges: [] });
      setLastUpdated(new Date());
      setSecondsAgo(0);
    } catch (error) {
      console.error("Failed to fetch map data:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!lastUpdated) return;
    const interval = setInterval(() => {
      setSecondsAgo(Math.floor((new Date() - lastUpdated) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [lastUpdated]);

  return (
    <div className="relative w-full h-full bg-[#0f172a]">
      <MapContainer
        center={[20, 0]}
        zoom={2}
        style={{ height: '100%', width: '100%', backgroundColor: '#0f172a' }}
        zoomControl={true}
        zoomControlPosition="bottomright"
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution="&copy; CartoDB"
        />

        {graphData.edges?.map((edge, index) => {
          const fromCoord = PORT_COORDS[edge.from_node];
          const toCoord = PORT_COORDS[edge.to_node];

          if (!fromCoord || !toCoord) return null;

          return (
            <Polyline
              key={`edge-${index}`}
              positions={[fromCoord, toCoord]}
              color={getRiskColor(edge.edge_risk_score || 0)}
              weight={1.5}
              opacity={0.4}
            />
          );
        })}

        {shipments?.map((shipment) => {
          const position = PORT_COORDS[shipment.current_node];
          if (!position) return null;

          const isSelected = selectedShipmentId === shipment.shipment_id;

          return (
            <CircleMarker
              key={shipment.shipment_id}
              center={position}
              radius={isSelected ? 10 : 6}
              fillColor={getRiskColor(shipment.risk_score)}
              color={isSelected ? '#ffffff' : getRiskColor(shipment.risk_score)}
              weight={isSelected ? 2 : 1}
              fillOpacity={0.85}
              eventHandlers={{
                click: () => onShipmentClick && onShipmentClick(shipment)
              }}
            >
              <Tooltip>
                <div className="text-xs">
                  <p className="font-semibold border-b border-gray-200 pb-1 mb-1">{shipment.shipment_id}</p>
                  <p>{shipment.origin} &rarr; {shipment.destination}</p>
                  <p className="mt-1 font-medium">Risk: {(shipment.risk_score * 100).toFixed(1)}%</p>
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* Timestamp Overlay */}
      {lastUpdated && (
        <div className="absolute top-2 right-2 z-[400] bg-slate-900/80 px-3 py-1.5 rounded border border-slate-700 shadow-sm pointer-events-none">
          <span className="text-xs text-slate-300">
            Last updated {secondsAgo} seconds ago
          </span>
        </div>
      )}
    </div>
  );
}
