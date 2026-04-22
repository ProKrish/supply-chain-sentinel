// frontend/src/api/client.js
import axios from 'axios';

const client = axios.create({
    baseURL: import.meta.env.VITE_API_URL,
});

// Auth0 token injected per-request — call getToken before each request
let _getToken = null;
export const setTokenGetter = (fn) => { _getToken = fn; };

client.interceptors.request.use(async (config) => {
    if (_getToken) {
        try {
            const token = await _getToken({
                authorizationParams: {
                    audience: import.meta.env.VITE_AUTH0_AUDIENCE,
                },
            });
            if (token) config.headers.Authorization = `Bearer ${token}`;
        } catch (_) {
            // unauthenticated — let request go without header
        }
    }
    return config;
});

export const getShipments = (params) => client.get('/shipments', { params }).then(r => r.data);
export const getShipment = (id) => client.get(`/shipments/${id}`).then(r => r.data);
export const getGraph = () => client.get('/graph').then(r => r.data);
export const getDisruptionHistory = () => client.get('/disruptions/history').then(r => r.data);
export const getActiveDisruptions = () => client.get('/disruptions/active').then(r => r.data);
export const injectDisruption = (data) => client.post('/disruptions/inject', data).then(r => r.data);
export const autoDisruption = () => client.post('/disruptions/auto').then(r => r.data);
export const rerouteAgent = (id) => client.post('/agent/reroute', { shipment_id: id }).then(r => r.data);

export const rerouteAgentStream = async (shipmentId, getToken) => {
  const token = await getToken({
    authorizationParams: { audience: import.meta.env.VITE_AUTH0_AUDIENCE }
  })

  const response = await fetch(
    `${import.meta.env.VITE_API_URL}/agent/reroute/stream`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ shipment_id: shipmentId })
    }
  )

  if (!response.ok) throw new Error(`Stream failed: ${response.status}`)
  return response.body.getReader()
}

export default client;