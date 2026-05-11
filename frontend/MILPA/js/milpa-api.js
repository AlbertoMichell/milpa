// milpa-api.js — Módulo de API para datos dinámicos (cultivos, sensores, recomendaciones)
// Todas las llamadas pasan por /api/ai/* → proxy del frontend → backend IA (puerto 8000)

const MILPA_API = {

  // ───────── HELPERS ─────────

  _getToken() {
    return localStorage.getItem('milpaToken');
  },

  _getUserId() {
    try {
      const user = JSON.parse(localStorage.getItem('milpaUser'));
      return user ? user.userId : null;
    } catch { return null; }
  },

  _fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      if (!file) {
        resolve(null);
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('No se pudo leer la imagen seleccionada'));
      reader.readAsDataURL(file);
    });
  },

  async _fetch(path, options = {}) {
    const token = this._getToken();
    const headers = { ...(options.headers || {}) };
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
    if (!isFormData && !headers['Content-Type'] && !headers['content-type']) {
      headers['Content-Type'] = 'application/json';
    }
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
      localStorage.removeItem('milpaToken');
      localStorage.removeItem('milpaUser');
      window.location.href = 'login.html';
      throw new Error('Sesión expirada');
    }
    if (res.status === 204) return null;
    if (!res.ok) {
      const contentType = res.headers.get('content-type') || '';
      const err = contentType.includes('application/json')
        ? await res.json().catch(() => ({ error: res.statusText }))
        : { error: await res.text().catch(() => res.statusText) };
      throw new Error(err.error || err.detail || 'Error del servidor');
    }
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return res.json();
    }
    return res.text();
  },

  // ───────── CULTIVOS ─────────

  async getCrops() {
    const uid = this._getUserId();
    if (!uid) throw new Error('No autenticado');
    return this._fetch(`/api/ai/crops/${uid}`);
  },

  async createCrop(data) {
    const uid = this._getUserId();
    return this._fetch('/api/ai/crops', {
      method: 'POST',
      body: JSON.stringify({ user_id: Number(uid), ...data })
    });
  },

  async updateCrop(cropId, data) {
    return this._fetch(`/api/ai/crops/${cropId}`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    });
  },

  async uploadCropImage(cropId, file) {
    const imageData = await this._fileToDataUrl(file);
    if (!imageData) throw new Error('Selecciona una imagen para continuar');
    return this._fetch(`/api/crops/${cropId}/image`, {
      method: 'POST',
      body: JSON.stringify({ fileName: file.name, imageData })
    });
  },

  async deleteCrop(cropId) {
    return this._fetch(`/api/ai/crops/${cropId}`, { method: 'DELETE' });
  },

  // ───────── PARCELA (telemetría agregada del predio) ─────────
  // El predio físico tiene una sola realidad de sensores; estos endpoints
  // agregan las lecturas de todos los cultivos del usuario y, cuando aplica,
  // las fusionan con edaphology_global_readings.

  /** Última lectura agregada de la parcela (todos los cultivos + edafología global). */
  async getParcelLatest() {
    const uid = this._getUserId();
    if (!uid) throw new Error('No autenticado');
    return this._fetch(`/api/ai/parcel/latest/${uid}`);
  },

  /**
   * Serie histórica diaria de la parcela. Acepta:
   *   - since: 'YYYY-MM-DD' (fecha de siembra del cultivo a usar como ventana)
   *   - days:  ventana en días si no se da `since` (default backend = 120)
   *   - limit: tope de filas (default backend = 240)
   */
  async getParcelReadings({ since = null, days = null, limit = null } = {}) {
    const uid = this._getUserId();
    if (!uid) throw new Error('No autenticado');
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (days != null) params.set('days', String(days));
    if (limit != null) params.set('limit', String(limit));
    const qs = params.toString();
    return this._fetch(`/api/ai/parcel/readings/${uid}${qs ? '?' + qs : ''}`);
  },

  /**
   * Salud agronómica de la parcela y por cultivo. Cruza:
   *   - lectura parcela actual
   *   - perfil agronómico (crop_profiles) de cada cultivo
   *   - retraso fenológico desde planted_at
   */
  async getParcelHealth() {
    const uid = this._getUserId();
    if (!uid) throw new Error('No autenticado');
    return this._fetch(`/api/ai/parcel/health/${uid}`);
  },

  /** Umbrales de parcela (JSON desde guía MILPA · documento paralelo para RAG). */
  async getParcelMonitoringGuidelines() {
    return this._fetch('/api/ai/parcel/monitoring-guidelines');
  },

  /** Plan RAG de actividades para un cultivo (con citas reales a documentos). */
  async generateRagCalendarPlan(userCropId) {
    return this._fetch(`/api/ai/calendar/rag-plan/${userCropId}`, { method: 'POST' });
  },

  /**
   * Catálogo dinámico de cultivos que reconoce el sistema (lee crop_profiles).
   * Reemplaza a las antiguas listas cerradas (`['maiz', 'frijol', 'calabaza', ...]`).
   * Cualquier cultivo nuevo registrado en `crop_profiles` aparece automáticamente.
   */
  async getKnownCrops() {
    return this._fetch('/api/known-crops');
  },

  // ───────── SENSORES ─────────

  async getSensorReadings(cropId, limit = 50) {
    return this._fetch(`/api/ai/sensors/${cropId}?limit=${limit}`);
  },

  async getLatestSensor(cropId) {
    return this._fetch(`/api/ai/sensors/${cropId}/latest`);
  },

  async postSensorReading(data) {
    return this._fetch('/api/ai/sensors', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  // ───────── NUTRIENTES DEL SUELO (N/P/K) ─────────

  async getSoilNutrients(cropId, limit = 12) {
    return this._fetch(`/api/ai/soil-nutrients/${cropId}?limit=${limit}`);
  },

  async getLatestSoilNutrients(cropId) {
    return this._fetch(`/api/ai/soil-nutrients/${cropId}/latest`);
  },

  async postSoilNutrients(data) {
    return this._fetch('/api/ai/soil-nutrients', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  // ───────── EDAFOLOGIA GLOBAL ─────────

  async getGlobalEdaphologyLatest() {
    return this._fetch('/api/ai/edaphology/global/latest');
  },

  async postGlobalEdaphology(data) {
    return this._fetch('/api/ai/edaphology/global', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  async getCropProfile(cropName) {
    return this._fetch(`/api/ai/edaphology/crop-profile/${encodeURIComponent(cropName)}`);
  },

  // ───────── RECOMENDACIONES ─────────

  async getRecommendations(filters = {}) {
    const uid = this._getUserId();
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.crop) params.set('crop', filters.crop);
    if (filters.action_type) params.set('action_type', filters.action_type);
    const qs = params.toString();
    return this._fetch(`/api/ai/recommendations/user/${uid}${qs ? '?' + qs : ''}`);
  },

  async getRecommendationActionTypes() {
    return this._fetch('/api/recommendations/action-types');
  },

  async getRecommendationsForCrop(cropId) {
    return this._fetch(`/api/ai/recommendations/${cropId}`);
  },

  async generateRecommendation(userCropId) {
    return this._fetch('/api/ai/recommendations/generate', {
      method: 'POST',
      body: JSON.stringify({ user_crop_id: userCropId })
    });
  },

  async autoGenerateRecommendations(context = 'general') {
    return this._fetch('/api/recommendations/auto-generate', {
      method: 'POST',
      body: JSON.stringify({ context })
    });
  },

  async updateRecommendationStatus(recId, status) {
    return this._fetch(`/api/ai/recommendations/${recId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status })
    });
  },

  // ───────── RIEGO (irrigation_events) ─────────

  async getIrrigationEvents(cropId, limit = 30) {
    return this._fetch(`/api/ai/irrigation-events/${cropId}?limit=${limit}`);
  },

  async getIrrigationEfficiency(cropId) {
    return this._fetch(`/api/ai/irrigation-events/${cropId}/efficiency`);
  },

  async postIrrigationEvent(data) {
    return this._fetch('/api/ai/irrigation-events', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  // ───────── RAG QUERY DIRECTA ─────────

  async queryRAG(queryText, k = 8) {
    return this._fetch('/api/ai/query', {
      method: 'POST',
      body: JSON.stringify({ query: queryText, k, mode: 'hybrid' })
    });
  },

  // ───────── PERFIL / CUENTA / AJUSTES ─────────

  async getProfile() {
    return this._fetch('/api/profile');
  },

  async updateProfile(data) {
    return this._fetch('/api/profile', {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  },

  async updateAccount(data) {
    return this._fetch('/api/account', {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  },

  async deleteAccount() {
    return this._fetch('/api/account', {
      method: 'DELETE'
    });
  },

  async uploadProfileAvatar(file) {
    const imageData = await this._fileToDataUrl(file);
    if (!imageData) throw new Error('Selecciona una imagen para continuar');
    return this._fetch('/api/profile/avatar', {
      method: 'POST',
      body: JSON.stringify({ fileName: file.name, imageData })
    });
  },

  async getSettings() {
    return this._fetch('/api/settings');
  },

  async updateSettings(data) {
    return this._fetch('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  },

  // ───────── CALENDARIO ─────────

  async getCalendarEvents() {
    return this._fetch('/api/calendar/events');
  },

  async getCalendarEventTypes() {
    return this._fetch('/api/calendar/event-types');
  },

  async createCalendarEvent(data) {
    return this._fetch('/api/calendar/events', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  async updateCalendarEvent(eventId, data) {
    return this._fetch(`/api/calendar/events/${eventId}`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    });
  },

  async deleteCalendarEvent(eventId) {
    return this._fetch(`/api/calendar/events/${eventId}`, {
      method: 'DELETE'
    });
  },

  async generateCalendarPlan(params = {}) {
    return this._fetch('/api/calendar/plans/generate', {
      method: 'POST',
      body: JSON.stringify({
        include_past: Boolean(params.include_past),
        force: Boolean(params.force),
      })
    });
  },

  // ───────── DATASETS POR USUARIO ─────────

  async getDatasetUsers() {
    return this._fetch('/api/datasets/users');
  },

  async importDataset(payload) {
    return this._fetch('/api/datasets/import', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  },

  async bootstrapDataset(payload = {}) {
    return this._fetch('/api/datasets/bootstrap', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  },

  // ───────── BIBLIOTECA ─────────

  async getLibrary(params = {}) {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        qs.set(key, String(value));
      }
    }
    return this._fetch(`/api/library${qs.toString() ? '?' + qs.toString() : ''}`);
  },

  async getLibraryFacets() {
    return this._fetch('/api/library/facets');
  },

  async getLibraryDetail(docId) {
    return this._fetch(`/api/library/${encodeURIComponent(docId)}`);
  },

  async getLibraryCategories() {
    return this._fetch('/api/library/categories');
  },

  // ───────── FAQs (preguntas frecuentes dinámicas) ─────────

  async getFaqs(params = {}) {
    const qs = new URLSearchParams();
    if (params.category) qs.set('category', params.category);
    if (params.crop) qs.set('crop', params.crop);
    return this._fetch(`/api/faqs${qs.toString() ? '?' + qs.toString() : ''}`);
  },

  // ───────── NOTIFICACIONES (por usuario) ─────────

  async getNotifications(params = {}) {
    const qs = new URLSearchParams();
    if (params.limit) qs.set('limit', params.limit);
    if (params.unread) qs.set('unread', '1');
    return this._fetch(`/api/notifications${qs.toString() ? '?' + qs.toString() : ''}`);
  },

  async createNotification(data) {
    return this._fetch('/api/notifications', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  async markNotificationRead(id) {
    return this._fetch(`/api/notifications/${id}/read`, { method: 'PATCH' });
  },

  async deleteNotification(id) {
    return this._fetch(`/api/notifications/${id}`, { method: 'DELETE' });
  }
};
