document.addEventListener('DOMContentLoaded', async () => {
  const cropSelect = document.getElementById('sensorCropSelect');
  const lastUpdate = document.getElementById('sensorLastUpdate');
  const alertsList = document.getElementById('sensorAlertsList');
  const alertsBadge = document.getElementById('alertsCountBadge');
  const refreshButtons = [document.getElementById('refreshSensorDataBtn'), document.getElementById('refreshSensorDataBtnMap')].filter(Boolean);
  const seedDatasetButton = document.getElementById('seedDatasetBtn');
  const monitoringDataStatus = document.getElementById('monitoringDataStatus');

  const ctx = document.getElementById('realtimeChart').getContext('2d');
  const realtimeChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Humedad suelo (%)',
          data: [],
          borderColor: '#2E7D32',
          backgroundColor: 'rgba(46, 125, 50, 0.1)',
          borderWidth: 2,
          tension: 0.35,
          yAxisID: 'y',
        },
        {
          label: 'Temperatura (°C)',
          data: [],
          borderColor: '#dc3545',
          backgroundColor: 'rgba(220, 53, 69, 0.1)',
          borderWidth: 2,
          tension: 0.35,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      scales: {
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          title: { display: true, text: 'Humedad (%)' },
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: true, text: 'Temperatura (°C)' },
        },
      },
    },
  });

  /** Paralelo del JSON guía MILPA (models/parcel_micrometeorology_reference.json) + texto en biblioteca RAG */
  const DEFAULT_PARCEL_GUIDE = {
    version: '2026.04',
    air_temp_c: {
      optimal_min: 16, optimal_max: 30, cold_stress_below: 12, severe_cold_below: 5,
      heat_stress_above: 32, severe_hot_above: 38,
    },
    soil_moisture_pct: { optimal_min: 38, optimal_max: 72, low_below: 32, saturation_above: 82 },
    air_humidity_pct: { optimal_min: 45, optimal_max: 85, very_dry_below: 35, very_wet_above: 92 },
    relative_light_pct: { optimal_min: 35, optimal_max: 92, low_below: 25, stress_glare_above: 98 },
    wind_kmh: { calm_max: 18, stress_above: 32, high_above: 45 },
  };

  const state = {
    crops: [],
    settings: null,
    parcelGuidelines: null,
    /** Vacío = vista parcela (promedio de cultivos + lectura regional). */
    activeCropId: '',
    globalReading: null,
    recommendations: [],
    /** Perfil agronómico del cultivo activo (lee crop_profiles); null en vista parcela. */
    activeCropProfile: null,
    /** Caché por crop_name -> perfil (evita N requests). */
    profileCache: {},
  };

  /** Umbrales para alertas (barra derecha): crop_profiles > settings usuario > defaults guía parcela MILPA */
  function effectiveThresholds() {
    const s = state.settings || {};
    const pg = state.parcelGuidelines || DEFAULT_PARCEL_GUIDE;
    const gc = pg.air_temp_c || DEFAULT_PARCEL_GUIDE.air_temp_c;
    const gso = pg.soil_moisture_pct || DEFAULT_PARCEL_GUIDE.soil_moisture_pct;
    const gh = pg.air_humidity_pct || DEFAULT_PARCEL_GUIDE.air_humidity_pct;
    const p = state.activeCropProfile;
    if (p) {
      return {
        soilMin: Number(p.optimal_soil_moisture_min ?? s.min_soil_moisture ?? gso.optimal_min),
        soilMax: Number(p.optimal_soil_moisture_max ?? gso.optimal_max),
        tempMin: Number(p.optimal_temp_min ?? gc.optimal_min),
        tempMax: Number(p.optimal_temp_max ?? s.max_temperature ?? gc.optimal_max),
        humMin:  Number(p.optimal_air_humidity_min ?? s.min_air_humidity ?? gh.optimal_min),
        humMax:  Number(p.optimal_air_humidity_max ?? gh.optimal_max),
        guide: pg,
        source:  'crop_profile',
        label:   p.crop_name,
      };
    }
    return {
      soilMin: Number(s.min_soil_moisture ?? gso.optimal_min),
      soilMax: Number(gso.optimal_max ?? 72),
      tempMin: Number(gc.optimal_min),
      tempMax: Number(s.max_temperature ?? gc.optimal_max),
      humMin:  Number(s.min_air_humidity ?? gh.optimal_min),
      humMax:  Number(gh.optimal_max ?? 85),
      guide: pg,
      source:  'settings',
      label:   'parcela',
    };
  }

  /** Etiquetas de tarjetas: referencia MILPA parcela ± preferencias / perfil cultivado (sin bandas ficticias 10‑30). */
  function classifyTempStatus(v, t, g) {
    const gc = (g.air_temp_c || DEFAULT_PARCEL_GUIDE.air_temp_c);
    if (v == null || Number.isNaN(Number(v))) return { text: 'sin lectura', level: 'status-danger' };
    const x = Number(v);
    if (x < gc.severe_cold_below) return { text: 'estrés por frío severo', level: 'status-danger' };
    if (x < gc.cold_stress_below) return { text: 'frío significativo', level: 'status-warning' };
    if (x < t.tempMin) return { text: 'bajo rango esperado', level: 'status-warning' };
    if (x > gc.severe_hot_above) return { text: 'calor extremo', level: 'status-danger' };
    if (x > gc.heat_stress_above) return { text: 'calor elevado', level: 'status-warning' };
    if (x > t.tempMax) return { text: 'calor alto', level: 'status-warning' };
    return { text: 'en rango estable', level: 'status-normal' };
  }

  function classifySoilStatus(v, t, g) {
    const go = g.soil_moisture_pct || DEFAULT_PARCEL_GUIDE.soil_moisture_pct;
    if (v == null || Number.isNaN(Number(v))) return { text: 'sin lectura', level: 'status-danger' };
    const x = Number(v);
    if (x < go.low_below) return { text: 'muy seco', level: 'status-danger' };
    if (x < t.soilMin) return { text: 'seco vs objetivo', level: 'status-warning' };
    if (x > go.saturation_above) return { text: 'saturación', level: 'status-danger' };
    if (x > t.soilMax) return { text: 'húmedo alto', level: 'status-warning' };
    return { text: 'en rango', level: 'status-normal' };
  }

  function classifyHumidityStatus(v, t, g) {
    const gh = g.air_humidity_pct || DEFAULT_PARCEL_GUIDE.air_humidity_pct;
    if (v == null || Number.isNaN(Number(v))) return { text: 'sin lectura', level: 'status-danger' };
    const x = Number(v);
    if (x < gh.very_dry_below) return { text: 'aire muy seco', level: 'status-danger' };
    if (x < t.humMin) return { text: 'bajo rango objetivo', level: 'status-warning' };
    if (x > gh.very_wet_above) return { text: 'aire muy húmedo', level: 'status-danger' };
    if (x > t.humMax) return { text: 'húmedo alto', level: 'status-warning' };
    return { text: 'en rango', level: 'status-normal' };
  }

  function classifyLightStatus(v, g) {
    const gl = g.relative_light_pct || DEFAULT_PARCEL_GUIDE.relative_light_pct;
    if (v == null || Number.isNaN(Number(v))) return { text: 'sin lectura', level: 'status-danger' };
    const x = Number(v);
    if (x < gl.low_below) return { text: 'luz muy baja', level: 'status-danger' };
    if (x < gl.optimal_min) return { text: 'luz media', level: 'status-warning' };
    if (x > gl.stress_glare_above) return { text: 'radiación extrema', level: 'status-danger' };
    if (x > gl.optimal_max) return { text: 'mucha luz', level: 'status-warning' };
    return { text: 'aportación adecuada', level: 'status-normal' };
  }

  function classifyWindStatus(v, g) {
    const gw = g.wind_kmh || DEFAULT_PARCEL_GUIDE.wind_kmh;
    if (v == null || Number.isNaN(Number(v))) return { text: 'sin lectura', level: 'status-danger' };
    const x = Number(v);
    if (x >= gw.high_above) return { text: 'viento muy fuerte', level: 'status-danger' };
    if (x >= gw.stress_above) return { text: 'viento fuerte', level: 'status-warning' };
    if (x <= gw.calm_max) return { text: 'brisa / calmo', level: 'status-normal' };
    return { text: 'viento moderado', level: 'status-warning' };
  }

  function classifyPrecipStatus(v) {
    if (v == null || Number.isNaN(Number(v))) return { text: 'sin datos', level: 'status-warning' };
    const x = Number(v);
    if (x <= 0) return { text: 'sin lluvia', level: 'status-normal' };
    if (x < 5) return { text: 'llovizna', level: 'status-warning' };
    return { text: 'lluvia activa', level: 'status-danger' };
  }

  async function getCropProfileCached(cropName) {
    const key = String(cropName || '').toLowerCase();
    if (!key) return null;
    if (state.profileCache[key] !== undefined) return state.profileCache[key];
    try {
      const profile = await MILPA_API.getCropProfile(key);
      state.profileCache[key] = profile || null;
    } catch (_e) {
      state.profileCache[key] = null;
    }
    return state.profileCache[key];
  }

  function avgField(arr, field) {
    const vals = arr.map(x => x?.[field]).filter(v => v != null && !Number.isNaN(Number(v)));
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + Number(b), 0) / vals.length;
  }

  function averageSensorRows(rows) {
    const ok = (rows || []).filter(Boolean);
    if (!ok.length) return null;
    const created = ok.map(r => r.created_at).filter(Boolean).sort().reverse()[0];
    return {
      soil_moisture: avgField(ok, 'soil_moisture'),
      air_temp: avgField(ok, 'air_temp'),
      air_humidity: avgField(ok, 'air_humidity'),
      light: avgField(ok, 'light'),
      precipitation: avgField(ok, 'precipitation'),
      wind_speed: avgField(ok, 'wind_speed'),
      created_at: created,
    };
  }

  function mergeSensorHistories(rows) {
    const byDay = new Map();
    for (const r of rows || []) {
      if (!r?.created_at) continue;
      const key = new Date(r.created_at).toISOString().slice(0, 10);
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key).push(r);
    }
    const merged = [];
    for (const [day, group] of byDay) {
      merged.push({
        created_at: `${day}T12:00:00.000Z`,
        soil_moisture: avgField(group, 'soil_moisture'),
        air_temp: avgField(group, 'air_temp'),
        air_humidity: avgField(group, 'air_humidity'),
        light: avgField(group, 'light'),
      });
    }
    merged.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    return merged;
  }

  function getCurrentUserId() {
    try {
      const user = JSON.parse(localStorage.getItem('milpaUser'));
      return Number(user?.userId || 0);
    } catch {
      return 0;
    }
  }

  function showMonitoringStatus(message, type = 'info') {
    if (!monitoringDataStatus) return;
    monitoringDataStatus.className = `alert alert-${type}`;
    monitoringDataStatus.textContent = message;
    monitoringDataStatus.classList.remove('d-none');
  }

  function hideMonitoringStatus() {
    if (!monitoringDataStatus) return;
    monitoringDataStatus.classList.add('d-none');
  }

  function setMetric(valueId, statusId, indicatorId, value, unit, statusText, level, decimals = 0) {
    const valueEl = document.getElementById(valueId);
    const statusEl = document.getElementById(statusId);
    const indicatorEl = document.getElementById(indicatorId);
    if (valueEl) {
      valueEl.textContent = value == null ? 'N/D' : `${Number(value).toFixed(decimals)}${unit}`;
    }
    if (statusEl) statusEl.textContent = statusText;
    if (indicatorEl) {
      indicatorEl.classList.remove('status-normal', 'status-warning', 'status-danger');
      indicatorEl.classList.add(level);
    }
  }

  function renderMetrics(sensor) {
    const t = effectiveThresholds();
    const g = t.guide || DEFAULT_PARCEL_GUIDE;

    const soilStatus = classifySoilStatus(sensor?.soil_moisture, t, g);
    const tempStatus = classifyTempStatus(sensor?.air_temp, t, g);
    const lightStatus = classifyLightStatus(sensor?.light, g);
    const humidityStatus = classifyHumidityStatus(sensor?.air_humidity, t, g);
    const windStatus = classifyWindStatus(sensor?.wind_speed, g);
    const precipStatus = classifyPrecipStatus(sensor?.precipitation);

    setMetric('soilMoistureValue', 'soilMoistureStatus', 'soilMoistureIndicator', sensor?.soil_moisture, '%', soilStatus.text, soilStatus.level);
    setMetric('airTempValue', 'airTempStatus', 'airTempIndicator', sensor?.air_temp, '°C', tempStatus.text, tempStatus.level);
    setMetric('lightValue', 'lightStatus', 'lightIndicator', sensor?.light, '%', lightStatus.text, lightStatus.level);
    setMetric('airHumidityValue', 'airHumidityStatus', 'airHumidityIndicator', sensor?.air_humidity, '%', humidityStatus.text, humidityStatus.level);
    setMetric('windValue', 'windStatus', 'windIndicator', sensor?.wind_speed, ' km/h', windStatus.text, windStatus.level, 0);
    setMetric('precipValue', 'precipStatus', 'precipIndicator', sensor?.precipitation, ' mm', precipStatus.text, precipStatus.level, 1);

    const basisEl = document.getElementById('monitoringBasisLine');
    if (basisEl) {
      basisEl.style.display = 'block';
      const ver = g.version || DEFAULT_PARCEL_GUIDE.version;
      basisEl.innerHTML = t.source === 'crop_profile'
        ? `Criterios de tarjetas: <strong>perfil agronómico</strong> (${t.label}) cuando aplica, completados con guía <strong>parcela MILPA</strong> v${ver} (mismo criterio citado en biblioteca RAG).`
        : `Criterios de tarjetas: preferencias de usuario (configuración) + guía <strong>parcela MILPA</strong> v${ver} (documento en biblioteca; no son bandas fijas arbitrarias en código).`;
    }

    if (lastUpdate) {
      lastUpdate.textContent = sensor?.created_at
        ? new Date(sensor.created_at).toLocaleString('es-MX')
        : 'Sin datos disponibles';
    }
  }

  function renderChart(history) {
    const ordered = [...history].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    realtimeChart.data.labels = ordered.map(reading => new Date(reading.created_at).toLocaleDateString('es-MX', { day: '2-digit', month: '2-digit', year: '2-digit' }));
    realtimeChart.data.datasets[0].data = ordered.map(reading => reading.soil_moisture ?? null);
    realtimeChart.data.datasets[1].data = ordered.map(reading => reading.air_temp ?? null);
    realtimeChart.update();
  }

  function filterReadingsSincePlanting(rows, plantedAt) {
    if (!plantedAt || !Array.isArray(rows)) return rows || [];
    const p = new Date(plantedAt).getTime();
    if (Number.isNaN(p)) return rows;
    return rows.filter(r => {
      if (!r?.created_at) return false;
      return new Date(r.created_at).getTime() >= p;
    });
  }

  function weekKeyFromDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    const normalized = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const weekday = (normalized.getDay() + 6) % 7;
    normalized.setDate(normalized.getDate() - weekday);
    return normalized.toISOString().slice(0, 10);
  }

  function buildWeeklySeries(history, maxPoints = 24) {
    const orderedDesc = [...(history || [])].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const seenWeeks = new Set();
    const weekly = [];

    for (const reading of orderedDesc) {
      const weekKey = weekKeyFromDate(reading.created_at);
      if (!weekKey || seenWeeks.has(weekKey)) {
        continue;
      }
      seenWeeks.add(weekKey);
      weekly.push(reading);
      if (weekly.length >= maxPoints) {
        break;
      }
    }

    return weekly;
  }

  function renderAlerts(sensor, opts = {}) {
    if (!alertsList || !alertsBadge) return;
    const alerts = [];
    const t = effectiveThresholds();
    const scope = opts.parcel ? 'La parcela (promedio)' : `El cultivo (${t.label})`;
    const basisTag = t.source === 'crop_profile'
      ? ` <span class="badge bg-light text-dark border ms-1" title="Umbral del crop_profiles del cultivo seleccionado">crop_profile</span>`
      : ` <span class="badge bg-light text-dark border ms-1" title="Umbral global del usuario (settings)">settings</span>`;

    if (sensor?.soil_moisture != null && sensor.soil_moisture < t.soilMin) {
      alerts.push({ type: 'danger', icon: 'fa-tint', title: 'Humedad del suelo baja' + basisTag, text: `${scope} reporta ${Number(sensor.soil_moisture).toFixed(0)}% (mínimo ${t.soilMin}%). Considera riego o acolchado.` });
    } else if (sensor?.soil_moisture != null && sensor.soil_moisture > t.soilMax) {
      alerts.push({ type: 'warning', icon: 'fa-tint', title: 'Humedad del suelo alta' + basisTag, text: `${scope} reporta ${Number(sensor.soil_moisture).toFixed(0)}% (máx. ${t.soilMax}%). Verifica drenaje.` });
    }
    if (sensor?.air_temp != null && sensor.air_temp > t.tempMax) {
      alerts.push({ type: 'warning', icon: 'fa-temperature-high', title: 'Temperatura alta' + basisTag, text: `${scope} llegó a ${Number(sensor.air_temp).toFixed(0)}°C (máx. ${t.tempMax}°C).` });
    } else if (sensor?.air_temp != null && sensor.air_temp < t.tempMin) {
      alerts.push({ type: 'warning', icon: 'fa-temperature-low', title: 'Temperatura baja' + basisTag, text: `${scope} cayó a ${Number(sensor.air_temp).toFixed(0)}°C (mín. ${t.tempMin}°C).` });
    }
    if (sensor?.air_humidity != null && sensor.air_humidity < t.humMin) {
      alerts.push({ type: 'warning', icon: 'fa-cloud', title: 'Humedad del aire baja' + basisTag, text: `${scope}: humedad relativa en ${Number(sensor.air_humidity).toFixed(0)}% (mín. ${t.humMin}%).` });
    }
    // Calor regional: dispara solo si supera el techo del cultivo activo
    // (en vista parcela usa el techo de settings). Antes era 35° fijo.
    if (state.globalReading?.air_temp != null && Number(state.globalReading.air_temp) >= t.tempMax) {
      alerts.push({ type: 'danger', icon: 'fa-sun', title: 'Calor regional' + basisTag, text: `Edafología global reporta ${Number(state.globalReading.air_temp).toFixed(0)}°C (techo agronómico ${t.tempMax}°C).` });
    }

    alertsBadge.textContent = `${alerts.length} nuevas`;

    if (!alerts.length) {
      const explain = t.source === 'crop_profile'
        ? `Telemetría dentro del rango óptimo de <strong>${t.label}</strong> (crop_profiles).`
        : 'Telemetría dentro de los umbrales del usuario (settings).';
      alertsList.innerHTML = `<div class="alert alert-success mb-0"><div class="d-flex align-items-center"><i class="fas fa-check-circle me-3 fs-4"></i><div><strong>Sin alertas críticas</strong><p class="mb-0 small">${explain}</p></div></div></div>`;
      return;
    }

    alertsList.innerHTML = alerts.map(alert => `
      <div class="alert alert-${alert.type} mb-2">
        <div class="d-flex align-items-center">
          <i class="fas ${alert.icon} me-3 fs-4"></i>
          <div>
            <strong>${alert.title}</strong>
            <p class="mb-0 small">${alert.text}</p>
          </div>
        </div>
      </div>
    `).join('');
  }

  function renderSensorMarkers() {
    const layer = document.getElementById('sensorMarkersLayer');
    if (!layer) return;
    layer.innerHTML = '';
    const fallback = [
      [0.25, 0.30], [0.60, 0.45], [0.40, 0.70], [0.75, 0.35],
    ];
    state.crops.forEach((crop, idx) => {
      const x = Number(crop.sensor_x_pct);
      const y = Number(crop.sensor_y_pct);
      const fx = Number.isFinite(x) ? x : fallback[idx % fallback.length][0];
      const fy = Number.isFinite(y) ? y : fallback[idx % fallback.length][1];
      const m = document.createElement('div');
      m.className = 'sensor-marker';
      m.style.top = `${(fy * 100).toFixed(1)}%`;
      m.style.left = `${(fx * 100).toFixed(1)}%`;
      m.dataset.cropId = String(crop.id);
      m.title = crop.display_name || crop.crop_name;
      m.addEventListener('click', async () => {
        state.activeCropId = crop.id;
        if (cropSelect) cropSelect.value = String(state.activeCropId);
        await refreshActiveCrop();
      });
      layer.appendChild(m);
    });
  }

  async function loadCropOptions() {
    state.crops = await MILPA_API.getCrops();
    renderSensorMarkers();
    if (!cropSelect) return;
    if (!state.crops.length) {
      cropSelect.innerHTML = '<option value="">No hay cultivos registrados</option>';
      cropSelect.disabled = true;
      seedDatasetButton?.classList.remove('d-none');
      showMonitoringStatus('Este usuario no tiene cultivos ni telemetria. Carga un dataset demo o importa uno desde Configuracion.', 'warning');
      return;
    }

    hideMonitoringStatus();
    seedDatasetButton?.classList.add('d-none');
    cropSelect.disabled = false;
    cropSelect.innerHTML =
      `<option value="">Parcela — promedio de cultivos</option>` +
      state.crops.map(crop => `<option value="${crop.id}">${crop.display_name || crop.crop_name}</option>`).join('');
    if (state.activeCropId === undefined || state.activeCropId === null) {
      state.activeCropId = '';
    }
    cropSelect.value = state.activeCropId === '' ? '' : String(state.activeCropId);
  }

  function earliestPlantedAt(crops) {
    const dates = (crops || [])
      .map(c => (c?.planted_at ? String(c.planted_at).slice(0, 10) : null))
      .filter(Boolean)
      .sort();
    return dates[0] || null;
  }

  /**
   * Vista parcela: telemetría compartida del predio (todos los cultivos del usuario
   * + edafología global). El backend agrega y promedia por día.
   * El histórico arranca en la siembra MÁS ANTIGUA: si hay maíz desde enero y tomate
   * desde febrero, la parcela muestra desde enero — porque la realidad de la parcela
   * existió desde entonces.
   */
  async function refreshParcelView() {
    const crops = state.crops;
    if (!crops.length) {
      renderMetrics(null);
      renderChart([]);
      renderAlerts(null);
      return;
    }

    // Vista parcela: no hay un único `crop_profile`; usamos settings global.
    state.activeCropProfile = null;

    const since = earliestPlantedAt(crops);

    const [latest, history, globalReading] = await Promise.all([
      MILPA_API.getParcelLatest().catch(() => null),
      MILPA_API.getParcelReadings({ since, limit: 240 }).catch(() => null),
      MILPA_API.getGlobalEdaphologyLatest().catch(() => null),
    ]);
    state.globalReading = globalReading;

    const sensor = latest && (latest.soil_moisture != null || latest.air_temp != null)
      ? {
          soil_moisture: latest.soil_moisture,
          air_temp: latest.air_temp,
          air_humidity: latest.air_humidity,
          light: latest.light,
          precipitation: latest.precipitation,
          wind_speed: latest.wind_speed,
          created_at: latest.created_at,
        }
      : null;

    const rows = Array.isArray(history?.rows) ? history.rows : [];
    const merged = rows.map(r => ({
      created_at: r.created_at,
      soil_moisture: r.soil_moisture,
      air_temp: r.air_temp,
      air_humidity: r.air_humidity,
      light: r.light,
    }));

    // No mezclamos recomendaciones aquí: tienen su propia pantalla
    // (recomendaciones.html). Antes se duplicaban en este panel.
    state.recommendations = [];

    renderMetrics(sensor);
    renderChart(buildWeeklySeries(merged, 24));
    renderAlerts(sensor, { parcel: true });
  }

  /**
   * Vista por cultivo: misma telemetría de la parcela, pero filtrada
   * desde la fecha de siembra (planted_at) del cultivo seleccionado.
   * Si la parcela tiene datos de enero a marzo y el cultivo se sembró en febrero,
   * el histórico va de febrero a marzo.
   */
  async function refreshActiveCrop() {
    const gid = state.activeCropId;
    const parcelMode = gid === '' || gid === null || gid === undefined;

    if (parcelMode) {
      await refreshParcelView();
      return;
    }

    const cropId = Number(gid);
    if (!Number.isFinite(cropId)) {
      await refreshParcelView();
      return;
    }

    const cropRow = state.crops.find(c => Number(c.id) === cropId);
    const since = cropRow?.planted_at ? String(cropRow.planted_at).slice(0, 10) : null;

    // Carga el crop_profile del cultivo activo en paralelo a la telemetría.
    // Esto reemplaza al uso de settings globales para clasificar lecturas:
    // ahora cada cultivo se evalúa con su propio rango óptimo.
    const [latest, history, globalReading, profile] = await Promise.all([
      MILPA_API.getParcelLatest().catch(() => null),
      MILPA_API.getParcelReadings({ since, limit: 240 }).catch(() => null),
      MILPA_API.getGlobalEdaphologyLatest().catch(() => null),
      cropRow?.crop_name ? getCropProfileCached(cropRow.crop_name) : Promise.resolve(null),
    ]);
    state.activeCropProfile = profile || null;

    const sensor = latest && (latest.soil_moisture != null || latest.air_temp != null)
      ? {
          soil_moisture: latest.soil_moisture,
          air_temp: latest.air_temp,
          air_humidity: latest.air_humidity,
          light: latest.light,
          precipitation: latest.precipitation,
          wind_speed: latest.wind_speed,
          created_at: latest.created_at,
        }
      : null;

    const rows = Array.isArray(history?.rows) ? history.rows : [];
    const cropHistory = rows.map(r => ({
      created_at: r.created_at,
      soil_moisture: r.soil_moisture,
      air_temp: r.air_temp,
      air_humidity: r.air_humidity,
      light: r.light,
    }));

    state.recommendations = [];
    state.globalReading = globalReading;
    renderMetrics(sensor);
    renderChart(buildWeeklySeries(cropHistory, 24));
    renderAlerts(sensor, { parcel: false });

    if (!rows.length && since) {
      showMonitoringStatus(
        `Aún no hay lecturas de parcela posteriores a la fecha de siembra (${since}). ` +
        'El histórico aparecerá conforme se carguen lecturas más recientes.',
        'info'
      );
    } else {
      hideMonitoringStatus();
    }
  }

  async function autoGenerateRecommendations(context = 'monitoring') {
    try {
      await MILPA_API.autoGenerateRecommendations(context);
    } catch (error) {
      console.warn('No se pudo ejecutar autogeneración de recomendaciones:', error.message);
    }
  }

  cropSelect?.addEventListener('change', async event => {
    const v = event.target.value;
    state.activeCropId = v === '' ? '' : Number(v);
    await refreshActiveCrop();
  });

  for (const button of refreshButtons) {
    button.addEventListener('click', async () => {
      await refreshActiveCrop();
    });
  }

  seedDatasetButton?.addEventListener('click', async () => {
    const userId = getCurrentUserId();
    if (!userId) {
      window.alert('No hay sesion activa para generar datos.');
      return;
    }

    seedDatasetButton.disabled = true;
    seedDatasetButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Cargando...';

    try {
      await MILPA_API.bootstrapDataset({
        target_user_id: userId,
        clear_existing: true,
        weeks: 24,
        interval_days: 7,
      });
      await loadCropOptions();
      state.activeCropId = '';
      if (cropSelect) cropSelect.value = '';
      await refreshActiveCrop();
      showMonitoringStatus('Dataset demo cargado. Vista parcela por defecto.', 'success');
    } catch (error) {
      console.error('No se pudo cargar dataset demo:', error);
      showMonitoringStatus(error.message || 'No se pudo cargar datos demo para monitoreo.', 'danger');
    } finally {
      seedDatasetButton.disabled = false;
      seedDatasetButton.innerHTML = '<i class="fas fa-database me-2"></i>Cargar datos demo';
    }
  });

  // Los marcadores .sensor-marker ahora son creados dinámicamente por renderSensorMarkers()
  // (ver loadCropOptions). El binding del click se hace al construirlos.

  try {
    state.settings = await MILPA_API.getSettings();
  } catch (error) {
    console.warn('No se pudieron cargar umbrales de monitoreo, se usarán valores por defecto.', error);
    state.settings = null;
  }

  try {
    state.parcelGuidelines = await MILPA_API.getParcelMonitoringGuidelines();
  } catch (_) {
    state.parcelGuidelines = DEFAULT_PARCEL_GUIDE;
  }

  await loadCropOptions();
  await autoGenerateRecommendations('monitoring');
  await refreshActiveCrop();
  setInterval(async () => {
    await autoGenerateRecommendations('monitoring');
    await refreshActiveCrop();
  }, 30000);
});