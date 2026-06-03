import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({ baseURL: BASE, timeout: 10000 });

export const getPorts       = ()            => api.get('/ports').then(r => r.data);
export const getPort        = (code)        => api.get(`/ports/${code}`).then(r => r.data);
export const getRiskScores  = (year, month) => api.get(`/risk-scores/${year}/${month}`).then(r => r.data);
export const getRoute       = (o, d)        => api.get(`/route/${o}/${d}`).then(r => r.data);
