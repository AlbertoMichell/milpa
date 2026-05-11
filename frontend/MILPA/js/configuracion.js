document.addEventListener('DOMContentLoaded', () => {
  const state = {
    profile: null,
    settings: null,
    crops: [],
    datasetUsers: [],
  };

  const elements = {
    settingsStatus: document.getElementById('settingsStatus'),
    profileForm: document.getElementById('profileForm'),
    accountForm: document.getElementById('accountForm'),
    notificationsForm: document.getElementById('notificationsForm'),
    alertsForm: document.getElementById('alertsForm'),
    privacyForm: document.getElementById('privacyForm'),
    profileResetBtn: document.getElementById('profileResetBtn'),
    profileAvatarPreview: document.getElementById('profileAvatarPreview'),
    avatarInput: document.getElementById('avatarInput'),
    plantForm: document.getElementById('plantForm'),
    plantImage: document.getElementById('plantImage'),
    plantImagePreview: document.getElementById('plantImagePreview'),
    registeredPlantsList: document.getElementById('registeredPlantsList'),
    refreshPlantsBtn: document.getElementById('refreshPlantsBtn'),
    resetPlantFormBtn: document.getElementById('resetPlantFormBtn'),
    sensorTableBody: document.getElementById('sensorTableBody'),
    refreshSensorTableBtn: document.getElementById('refreshSensorTableBtn'),
    confirmDelete: document.getElementById('confirmDelete'),
    deleteAccountBtn: document.getElementById('deleteAccountBtn'),
    exportJsonBtn: document.getElementById('exportJsonBtn'),
    exportPdfBtn: document.getElementById('exportPdfBtn'),
    datasetUserSelect: document.getElementById('datasetUserSelect'),
    datasetWeeks: document.getElementById('datasetWeeks'),
    datasetIntervalDays: document.getElementById('datasetIntervalDays'),
    datasetClearExisting: document.getElementById('datasetClearExisting'),
    datasetFileInput: document.getElementById('datasetFileInput'),
    datasetJsonInput: document.getElementById('datasetJsonInput'),
    datasetLoadTemplateBtn: document.getElementById('datasetLoadTemplateBtn'),
    datasetBootstrapBtn: document.getElementById('datasetBootstrapBtn'),
    datasetImportBtn: document.getElementById('datasetImportBtn'),
    // Carga rápida sintética
    syntheticUserSelect: document.getElementById('syntheticUserSelect'),
    syntheticWeeks: document.getElementById('syntheticWeeks'),
    syntheticIntervalDays: document.getElementById('syntheticIntervalDays'),
    syntheticClearExisting: document.getElementById('syntheticClearExisting'),
    datasetSyntheticBtn: document.getElementById('datasetSyntheticBtn'),
    syntheticResult: document.getElementById('syntheticResult'),
  };

  function getCurrentUserId() {
    try {
      const user = JSON.parse(localStorage.getItem('milpaUser'));
      return Number(user?.userId || 0);
    } catch {
      return 0;
    }
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showStatus(message, type = 'success') {
    if (!elements.settingsStatus) return;
    elements.settingsStatus.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">${escapeHtml(message)}<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button></div>`;
  }

  function buildDatasetTemplate(weeks = 24, intervalDays = 7) {
    const rows = [];
    const cropNames = ['maiz', 'frijol', 'chile'];
    const now = new Date();

    for (let week = 0; week < weeks; week += 1) {
      const ts = new Date(now.getTime() - (weeks - 1 - week) * intervalDays * 24 * 60 * 60 * 1000);
      ts.setHours(12, 0, 0, 0);
      const createdAt = ts.toISOString().slice(0, 19).replace('T', ' ');

      cropNames.forEach((cropName, index) => {
        const seed = week + index * 2;
        rows.push({
          crop_name: cropName,
          soil_moisture: 42 + (seed % 10) * 2.2,
          air_temp: 19 + (seed % 9) * 1.4,
          air_humidity: 45 + (seed % 8) * 3.1,
          light: 60 + (seed % 7) * 3.7,
          precipitation: seed % 4 === 0 ? 7.5 : 0,
          wind_speed: 5.8 + (seed % 6) * 0.9,
          created_at: createdAt,
        });
      });
    }

    return {
      metadata: {
        format_version: '1.0',
        description: 'Dataset semanal de monitoreo por usuario',
        interval_days: intervalDays,
        weeks,
      },
      crops: [
        { crop_name: 'maiz', display_name: 'Maiz de prueba', variety: 'Criollo', status: 'activo', growth_stage: 'desarrollo', progress: 55 },
        { crop_name: 'frijol', display_name: 'Frijol de prueba', variety: 'Negro', status: 'activo', growth_stage: 'establecimiento', progress: 40 },
        { crop_name: 'chile', display_name: 'Chile de prueba', variety: 'Serrano', status: 'activo', growth_stage: 'floracion', progress: 62 },
      ],
      sensor_readings: rows,
      global_readings: rows.filter((_, idx) => idx % 3 === 0).map(item => ({
        location_name: 'general',
        soil_temp: 22,
        air_temp: item.air_temp,
        air_humidity: item.air_humidity,
        soil_moisture: item.soil_moisture,
        precipitation: item.precipitation,
        wind_speed: item.wind_speed,
        ph: 6.4,
        conductivity: 1.1,
        notes: 'Carga desde panel de configuracion',
        created_at: item.created_at,
      })),
    };
  }

  function renderDatasetUsers() {
    if (!elements.datasetUserSelect) return;
    if (!state.datasetUsers.length) {
      elements.datasetUserSelect.innerHTML = '<option value="">Sin usuarios disponibles</option>';
      elements.datasetUserSelect.disabled = true;
      if (elements.syntheticUserSelect) {
        elements.syntheticUserSelect.innerHTML = '<option value="">Sin usuarios disponibles</option>';
        elements.syntheticUserSelect.disabled = true;
      }
      return;
    }

    const currentUserId = getCurrentUserId();

    const buildOptions = () => state.datasetUsers.map(user => {
      const metrics = `${user.crop_count || 0} cultivos · ${user.sensor_readings_count || 0} lecturas`;
      return `<option value="${user.id}">${escapeHtml(user.username)} (${metrics})</option>`;
    }).join('');

    elements.datasetUserSelect.disabled = false;
    elements.datasetUserSelect.innerHTML = buildOptions();
    if (elements.syntheticUserSelect) {
      elements.syntheticUserSelect.disabled = false;
      elements.syntheticUserSelect.innerHTML = buildOptions();
    }

    const selected = state.datasetUsers.find(user => Number(user.id) === currentUserId) || state.datasetUsers[0];
    elements.datasetUserSelect.value = String(selected.id);
    if (elements.syntheticUserSelect) elements.syntheticUserSelect.value = String(selected.id);
  }

  async function reloadDatasetUsers() {
    state.datasetUsers = await MILPA_API.getDatasetUsers();
    renderDatasetUsers();
  }

  function resetPlantForm() {
    elements.plantForm?.reset();
    const cropId = document.getElementById('plantCropId');
    if (cropId) cropId.value = '';
    if (elements.plantImagePreview) {
      elements.plantImagePreview.src = 'elementos/default.jpg';
    }
    const progress = document.getElementById('plantProgress');
    if (progress) progress.value = 0;
    const status = document.getElementById('plantStatus');
    if (status) status.value = 'activo';
    const stage = document.getElementById('plantGrowthStage');
    if (stage) stage.value = 'siembra';
  }

  function previewImage(file, imageElement, fallback = 'elementos/default.jpg') {
    if (!file || !imageElement) {
      if (imageElement) imageElement.src = fallback;
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      imageElement.src = String(reader.result || fallback);
    };
    reader.readAsDataURL(file);
  }

  function fillProfile(profile) {
    state.profile = profile;
    document.getElementById('firstName').value = profile.first_name || '';
    document.getElementById('lastName').value = profile.last_name || '';
    document.getElementById('bio').value = profile.bio || '';
    document.getElementById('location').value = profile.location || '';
    document.getElementById('experience').value = profile.experience || '5-15 años';
    document.getElementById('email').value = profile.email || '';
    document.getElementById('phone').value = profile.phone || '';
    document.getElementById('language').value = profile.language || 'Español';
    if (elements.profileAvatarPreview) {
      elements.profileAvatarPreview.src = profile.avatar_path || 'elementos/Campesinos.jpg';
    }
  }

  function fillSettings(settings) {
    state.settings = settings;
    document.getElementById('emailAlerts').checked = Boolean(settings.email_alerts);
    document.getElementById('dailySummary').checked = Boolean(settings.daily_summary);
    document.getElementById('weeklyReport').checked = Boolean(settings.weekly_report);
    document.getElementById('pushAlerts').checked = Boolean(settings.push_alerts);
    document.getElementById('pushRecommendations').checked = Boolean(settings.push_recommendations);
    document.getElementById('pushReminders').checked = Boolean(settings.push_reminders);

    const frequency = settings.notification_frequency || 'inmediata';
    document.getElementById('frequencyImmediate').checked = frequency === 'inmediata';
    document.getElementById('frequencyDaily').checked = frequency === 'resumen_diario';
    document.getElementById('frequencyCustom').checked = frequency === 'personalizado';

    document.getElementById('minSoilMoisture').value = settings.min_soil_moisture ?? 40;
    document.getElementById('maxTemperature').value = settings.max_temperature ?? 35;
    document.getElementById('minAirHumidity').value = settings.min_air_humidity ?? 50;
    document.getElementById('pestThreshold').value = settings.pest_threshold ?? 3;

    document.getElementById('alertWater').checked = Boolean(settings.alert_water);
    document.getElementById('alertTemp').checked = Boolean(settings.alert_temp);
    document.getElementById('alertPests').checked = Boolean(settings.alert_pests);
    document.getElementById('alertGrowth').checked = Boolean(settings.alert_growth);
    document.getElementById('alertWeather').checked = Boolean(settings.alert_weather);

    document.getElementById('dataCollection').checked = Boolean(settings.data_collection);
    document.getElementById('researchParticipation').checked = Boolean(settings.research_participation);
    document.getElementById('locationSharing').checked = Boolean(settings.location_sharing);
  }

  function collectSettingsFormData() {
    let notificationFrequency = 'inmediata';
    if (document.getElementById('frequencyDaily').checked) {
      notificationFrequency = 'resumen_diario';
    } else if (document.getElementById('frequencyCustom').checked) {
      notificationFrequency = 'personalizado';
    }

    return {
      email_alerts: document.getElementById('emailAlerts').checked,
      daily_summary: document.getElementById('dailySummary').checked,
      weekly_report: document.getElementById('weeklyReport').checked,
      push_alerts: document.getElementById('pushAlerts').checked,
      push_recommendations: document.getElementById('pushRecommendations').checked,
      push_reminders: document.getElementById('pushReminders').checked,
      notification_frequency: notificationFrequency,
      min_soil_moisture: Number(document.getElementById('minSoilMoisture').value),
      max_temperature: Number(document.getElementById('maxTemperature').value),
      min_air_humidity: Number(document.getElementById('minAirHumidity').value),
      pest_threshold: Number(document.getElementById('pestThreshold').value),
      alert_water: document.getElementById('alertWater').checked,
      alert_temp: document.getElementById('alertTemp').checked,
      alert_pests: document.getElementById('alertPests').checked,
      alert_growth: document.getElementById('alertGrowth').checked,
      alert_weather: document.getElementById('alertWeather').checked,
      data_collection: document.getElementById('dataCollection').checked,
      research_participation: document.getElementById('researchParticipation').checked,
      location_sharing: document.getElementById('locationSharing').checked,
    };
  }

  function fillPlantForm(crop) {
    document.getElementById('plantCropId').value = crop.id;
    document.getElementById('plantCropName').value = crop.crop_name || '';
    document.getElementById('plantDisplayName').value = crop.display_name || '';
    document.getElementById('plantVariety').value = crop.variety || '';
    document.getElementById('plantStatus').value = crop.status || 'activo';
    document.getElementById('plantPlantedAt').value = crop.planted_at || '';
    document.getElementById('plantExpectedHarvestAt').value = crop.expected_harvest_at || '';
    document.getElementById('plantGrowthStage').value = crop.growth_stage || 'siembra';
    document.getElementById('plantProgress').value = crop.progress ?? 0;
    document.getElementById('plantNotes').value = crop.notes || '';
    if (elements.plantImagePreview) {
      elements.plantImagePreview.src = crop.image_path || `elementos/${crop.crop_name}.jpg`;
      elements.plantImagePreview.onerror = () => {
        elements.plantImagePreview.src = 'elementos/default.jpg';
      };
    }
  }

  function renderPlants() {
    if (!elements.registeredPlantsList) return;
    if (!state.crops.length) {
      elements.registeredPlantsList.innerHTML = '<p class="text-muted mb-0">Aún no hay plantas registradas. Usa el formulario para cargar la primera.</p>';
      return;
    }

    elements.registeredPlantsList.innerHTML = state.crops.map(crop => {
      const imagePath = crop.image_path || `elementos/${crop.crop_name}.jpg`;
      const name = escapeHtml(crop.display_name || crop.crop_name || 'Cultivo');
      const meta = [crop.growth_stage, crop.variety].filter(Boolean).map(escapeHtml).join(' · ');
      return `<div class="card border-0 shadow-sm">
        <div class="card-body d-flex gap-3 align-items-center">
          <img src="${imagePath}" alt="${escapeHtml(crop.crop_name)}" class="rounded" style="width:68px;height:68px;object-fit:cover;" onerror="this.src='elementos/default.jpg'">
          <div class="flex-grow-1">
            <h6 class="mb-1">${name}</h6>
            <p class="small text-muted mb-1">${meta || 'Sin metadatos extra'}</p>
            <p class="small text-muted mb-0">Progreso ${Number(crop.progress || 0)}%</p>
          </div>
          <div class="d-flex flex-column gap-2">
            <button type="button" class="btn btn-sm btn-outline-secondary" data-action="edit" data-crop-id="${crop.id}">Editar</button>
            <button type="button" class="btn btn-sm btn-outline-danger" data-action="delete" data-crop-id="${crop.id}">Eliminar</button>
          </div>
        </div>
      </div>`;
    }).join('');
  }

  function classifySensorStatus(sensor) {
    if (!sensor) return ['bg-secondary', 'Sin lecturas'];
    const ageMs = Date.now() - new Date(sensor.created_at).getTime();
    if (Number.isNaN(ageMs)) return ['bg-secondary', 'Sin fecha'];
    if (ageMs < 6 * 60 * 60 * 1000) return ['bg-success', 'Activo'];
    if (ageMs < 24 * 60 * 60 * 1000) return ['bg-warning text-dark', 'Reciente'];
    return ['bg-danger', 'Sin actualizar'];
  }

  async function renderSensorTable() {
    if (!elements.sensorTableBody) return;
    if (!state.crops.length) {
      elements.sensorTableBody.innerHTML = '<tr><td colspan="5" class="text-muted text-center py-4">No hay cultivos registrados para mostrar sensores.</td></tr>';
      return;
    }

    elements.sensorTableBody.innerHTML = '<tr><td colspan="5" class="text-muted text-center py-4">Actualizando sensores...</td></tr>';

    const sensorRows = await Promise.all(state.crops.map(async (crop, index) => {
      try {
        const sensor = await MILPA_API.getLatestSensor(crop.id);
        const [badgeClass, badgeText] = classifySensorStatus(sensor);
        const readingText = sensor
          ? `Suelo ${sensor.soil_moisture != null ? Number(sensor.soil_moisture).toFixed(0) + '%' : 'N/D'} · Aire ${sensor.air_temp != null ? Number(sensor.air_temp).toFixed(0) + 'C' : 'N/D'}`
          : 'Sin telemetría';
        return `<tr>
          <td>${escapeHtml(crop.display_name || crop.crop_name)}</td>
          <td>Sector ${index + 1}</td>
          <td><span class="badge ${badgeClass}">${badgeText}</span></td>
          <td>${escapeHtml(readingText)}</td>
          <td><a class="btn btn-sm btn-outline-secondary" href="tiempo-real.html">Monitorear</a></td>
        </tr>`;
      } catch (error) {
        return `<tr>
          <td>${escapeHtml(crop.display_name || crop.crop_name)}</td>
          <td>Sector ${index + 1}</td>
          <td><span class="badge bg-danger">Error</span></td>
          <td>No se pudo leer la última telemetría</td>
          <td><a class="btn btn-sm btn-outline-secondary" href="tiempo-real.html">Monitorear</a></td>
        </tr>`;
      }
    }));

    elements.sensorTableBody.innerHTML = sensorRows.join('');
  }

  async function reloadCrops() {
    state.crops = await MILPA_API.getCrops();
    renderPlants();
    await renderSensorTable();
  }

  async function loadInitialState() {
    try {
      const [profile, settings, crops] = await Promise.all([
        MILPA_API.getProfile(),
        MILPA_API.getSettings(),
        MILPA_API.getCrops(),
      ]);
      await reloadDatasetUsers();
      fillProfile(profile);
      fillSettings(settings);
      state.crops = crops;
      renderPlants();
      await renderSensorTable();
    } catch (error) {
      console.error('Error cargando configuración:', error);
      showStatus(error.message || 'No se pudo cargar la configuración.', 'danger');
    }
  }

  elements.profileForm?.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await MILPA_API.updateProfile({
        first_name: document.getElementById('firstName').value.trim(),
        last_name: document.getElementById('lastName').value.trim(),
        bio: document.getElementById('bio').value.trim(),
        location: document.getElementById('location').value.trim(),
        experience: document.getElementById('experience').value,
      });
      if (elements.avatarInput?.files?.[0]) {
        const avatar = await MILPA_API.uploadProfileAvatar(elements.avatarInput.files[0]);
        if (avatar?.avatar_path && elements.profileAvatarPreview) {
          elements.profileAvatarPreview.src = avatar.avatar_path;
        }
        elements.avatarInput.value = '';
      }
      state.profile = await MILPA_API.getProfile();
      fillProfile(state.profile);
      showStatus('Perfil actualizado correctamente.');
    } catch (error) {
      showStatus(error.message || 'No se pudo actualizar el perfil.', 'danger');
    }
  });

  elements.accountForm?.addEventListener('submit', async event => {
    event.preventDefault();
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    if (newPassword && newPassword !== confirmPassword) {
      showStatus('La confirmación de contraseña no coincide.', 'warning');
      return;
    }

    try {
      await MILPA_API.updateAccount({
        email: document.getElementById('email').value.trim(),
        phone: document.getElementById('phone').value.trim(),
        language: document.getElementById('language').value,
        currentPassword: document.getElementById('currentPassword').value,
        newPassword,
      });
      document.getElementById('currentPassword').value = '';
      document.getElementById('newPassword').value = '';
      document.getElementById('confirmPassword').value = '';
      state.profile = await MILPA_API.getProfile();
      fillProfile(state.profile);
      showStatus('Cuenta actualizada correctamente.');
    } catch (error) {
      showStatus(error.message || 'No se pudo actualizar la cuenta.', 'danger');
    }
  });

  const saveSettings = async (successMessage) => {
    try {
      state.settings = await MILPA_API.updateSettings(collectSettingsFormData());
      fillSettings(state.settings);
      showStatus(successMessage);
    } catch (error) {
      showStatus(error.message || 'No se pudieron guardar los ajustes.', 'danger');
    }
  };

  elements.notificationsForm?.addEventListener('submit', async event => {
    event.preventDefault();
    await saveSettings('Preferencias de notificación guardadas.');
  });

  elements.alertsForm?.addEventListener('submit', async event => {
    event.preventDefault();
    await saveSettings('Umbrales de alerta guardados.');
  });

  elements.privacyForm?.addEventListener('submit', async event => {
    event.preventDefault();
    await saveSettings('Ajustes de privacidad guardados.');
  });

  elements.plantForm?.addEventListener('submit', async event => {
    event.preventDefault();
    const cropId = document.getElementById('plantCropId').value;
    const payload = {
      crop_name: document.getElementById('plantCropName').value.trim().toLowerCase(),
      display_name: document.getElementById('plantDisplayName').value.trim(),
      variety: document.getElementById('plantVariety').value.trim(),
      status: document.getElementById('plantStatus').value,
      planted_at: document.getElementById('plantPlantedAt').value || null,
      expected_harvest_at: document.getElementById('plantExpectedHarvestAt').value || null,
      growth_stage: document.getElementById('plantGrowthStage').value,
      progress: Number(document.getElementById('plantProgress').value || 0),
      notes: document.getElementById('plantNotes').value.trim(),
    };

    if (!payload.crop_name) {
      showStatus('Indica el nombre del cultivo antes de guardar.', 'warning');
      return;
    }

    try {
      const crop = cropId
        ? await MILPA_API.updateCrop(Number(cropId), payload)
        : await MILPA_API.createCrop(payload);

      if (elements.plantImage?.files?.[0]) {
        const upload = await MILPA_API.uploadCropImage(crop.id, elements.plantImage.files[0]);
        crop.image_path = upload.image_path;
      }

      showStatus('Planta guardada y conectada al sistema. Ya puede aparecer en Inicio.');
      resetPlantForm();
      await reloadCrops();
    } catch (error) {
      showStatus(error.message || 'No se pudo guardar la planta.', 'danger');
    }
  });

  elements.registeredPlantsList?.addEventListener('click', async event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const cropId = Number(button.dataset.cropId);
    const crop = state.crops.find(item => item.id === cropId);
    if (!crop) return;

    if (button.dataset.action === 'edit') {
      fillPlantForm(crop);
      showStatus('Planta cargada en el formulario para edición.', 'info');
      return;
    }

    if (button.dataset.action === 'delete') {
      if (!window.confirm(`¿Eliminar ${crop.display_name || crop.crop_name}?`)) {
        return;
      }
      try {
        await MILPA_API.deleteCrop(cropId);
        await reloadCrops();
        resetPlantForm();
        showStatus('Planta eliminada correctamente.');
      } catch (error) {
        showStatus(error.message || 'No se pudo eliminar la planta.', 'danger');
      }
    }
  });

  elements.profileResetBtn?.addEventListener('click', () => {
    if (state.profile) fillProfile(state.profile);
    if (elements.avatarInput) elements.avatarInput.value = '';
  });

  elements.resetPlantFormBtn?.addEventListener('click', () => {
    resetPlantForm();
  });

  elements.refreshPlantsBtn?.addEventListener('click', async () => {
    await reloadCrops();
    showStatus('Listado de plantas actualizado.', 'info');
  });

  elements.refreshSensorTableBtn?.addEventListener('click', async () => {
    await renderSensorTable();
    showStatus('Telemetría actualizada.', 'info');
  });

  elements.avatarInput?.addEventListener('change', event => {
    previewImage(event.target.files?.[0], elements.profileAvatarPreview, state.profile?.avatar_path || 'elementos/Campesinos.jpg');
  });

  elements.plantImage?.addEventListener('change', event => {
    previewImage(event.target.files?.[0], elements.plantImagePreview, 'elementos/default.jpg');
  });

  elements.confirmDelete?.addEventListener('change', event => {
    if (elements.deleteAccountBtn) {
      elements.deleteAccountBtn.disabled = !event.target.checked;
    }
  });

  elements.deleteAccountBtn?.addEventListener('click', async () => {
    if (!window.confirm('Esta acción eliminará tu cuenta y todos tus datos. ¿Deseas continuar?')) {
      return;
    }
    try {
      await MILPA_API.deleteAccount();
      localStorage.removeItem('milpaToken');
      localStorage.removeItem('milpaUser');
      window.location.href = 'login.html';
    } catch (error) {
      showStatus(error.message || 'No se pudo eliminar la cuenta.', 'danger');
    }
  });

  elements.exportJsonBtn?.addEventListener('click', () => {
    const rows = [
      ['cultivo', 'nombre_visible', 'variedad', 'estado', 'progreso', 'siembra', 'cosecha_estimada'],
      ...state.crops.map(crop => [
        crop.crop_name || '',
        crop.display_name || '',
        crop.variety || '',
        crop.status || '',
        crop.progress ?? '',
        crop.planted_at || '',
        crop.expected_harvest_at || '',
      ]),
    ];
    const csv = rows.map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'milpa-cultivos.csv';
    link.click();
    URL.revokeObjectURL(link.href);
  });

  elements.exportPdfBtn?.addEventListener('click', () => {
    window.print();
  });

  elements.datasetLoadTemplateBtn?.addEventListener('click', () => {
    const weeks = Number(elements.datasetWeeks?.value || 24);
    const intervalDays = Number(elements.datasetIntervalDays?.value || 7);
    const template = buildDatasetTemplate(weeks, intervalDays);
    if (elements.datasetJsonInput) {
      elements.datasetJsonInput.value = JSON.stringify(template, null, 2);
    }
    showStatus('Plantilla de dataset cargada. Puedes editarla antes de importar.', 'info');
  });

  elements.datasetFileInput?.addEventListener('change', event => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (elements.datasetJsonInput) {
        elements.datasetJsonInput.value = String(reader.result || '');
      }
      showStatus('Archivo JSON cargado en el editor.', 'info');
    };
    reader.onerror = () => {
      showStatus('No se pudo leer el archivo JSON seleccionado.', 'danger');
    };
    reader.readAsText(file);
  });

  elements.datasetBootstrapBtn?.addEventListener('click', async () => {
    const targetUserId = Number(elements.datasetUserSelect?.value || getCurrentUserId());
    if (!targetUserId) {
      showStatus('Selecciona un usuario destino antes de generar datos.', 'warning');
      return;
    }
    try {
      const result = await MILPA_API.bootstrapDataset({
        target_user_id: targetUserId,
        clear_existing: Boolean(elements.datasetClearExisting?.checked),
        weeks: Number(elements.datasetWeeks?.value || 24),
        interval_days: Number(elements.datasetIntervalDays?.value || 7),
      });
      await reloadDatasetUsers();
      if (targetUserId === getCurrentUserId()) {
        await reloadCrops();
      }
      showStatus(result.message || 'Dataset demo generado correctamente.');
    } catch (error) {
      showStatus(error.message || 'No se pudo generar el dataset demo.', 'danger');
    }
  });

  elements.datasetImportBtn?.addEventListener('click', async () => {
    const targetUserId = Number(elements.datasetUserSelect?.value || getCurrentUserId());
    if (!targetUserId) {
      showStatus('Selecciona un usuario destino antes de importar.', 'warning');
      return;
    }

    const rawJson = elements.datasetJsonInput?.value?.trim() || '';
    if (!rawJson) {
      showStatus('Pega o carga un dataset JSON antes de importar.', 'warning');
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(rawJson);
    } catch {
      showStatus('El JSON del dataset es invalido.', 'danger');
      return;
    }

    try {
      const result = await MILPA_API.importDataset({
        target_user_id: targetUserId,
        clear_existing: Boolean(elements.datasetClearExisting?.checked),
        dataset: parsed,
      });
      await reloadDatasetUsers();
      if (targetUserId === getCurrentUserId()) {
        await reloadCrops();
      }
      showStatus(result.message || 'Dataset importado correctamente.');
    } catch (error) {
      showStatus(error.message || 'No se pudo importar el dataset.', 'danger');
    }
  });

  elements.datasetSyntheticBtn?.addEventListener('click', async () => {
    const targetUserId = Number(elements.syntheticUserSelect?.value || getCurrentUserId());
    if (!targetUserId) {
      showStatus('Selecciona un usuario destino antes de cargar datos sintéticos.', 'warning');
      return;
    }

    const weeks = Number(elements.syntheticWeeks?.value || 24);
    const intervalDays = Number(elements.syntheticIntervalDays?.value || 7);
    const clearExisting = Boolean(elements.syntheticClearExisting?.checked);

    // Desactivar botón durante la carga
    if (elements.datasetSyntheticBtn) {
      elements.datasetSyntheticBtn.disabled = true;
      elements.datasetSyntheticBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Cargando...';
    }
    if (elements.syntheticResult) elements.syntheticResult.style.display = 'none';

    try {
      // Construir dataset sintético rico en el frontend
      const dataset = buildDatasetTemplate(weeks, intervalDays);

      const result = await MILPA_API.importDataset({
        target_user_id: targetUserId,
        clear_existing: clearExisting,
        dataset,
      });

      await reloadDatasetUsers();
      if (targetUserId === getCurrentUserId()) {
        await reloadCrops();
      }

      // Mostrar resultado visual detallado
      const crops = dataset.crops.length;
      const readings = dataset.sensor_readings.length;
      const globals = dataset.global_readings.length;
      if (elements.syntheticResult) {
        elements.syntheticResult.style.display = '';
        elements.syntheticResult.innerHTML = `
          <div class="alert alert-success mb-0 py-2">
            <strong><i class="fas fa-check-circle me-1"></i>Datos cargados correctamente</strong>
            <div class="d-flex flex-wrap gap-3 mt-2 small">
              <span><i class="fas fa-seedling text-success me-1"></i>${crops} cultivos</span>
              <span><i class="fas fa-chart-line text-primary me-1"></i>${readings} lecturas de sensor</span>
              <span><i class="fas fa-globe text-info me-1"></i>${globals} lecturas globales</span>
              <span><i class="fas fa-calendar-week text-secondary me-1"></i>${weeks} semanas · cada ${intervalDays} día(s)</span>
            </div>
          </div>`;
      }
      showStatus(result.message || 'Dataset sintético importado correctamente.');
    } catch (error) {
      if (elements.syntheticResult) {
        elements.syntheticResult.style.display = '';
        elements.syntheticResult.innerHTML = `<div class="alert alert-danger mb-0 py-2"><i class="fas fa-exclamation-triangle me-1"></i>${escapeHtml(error.message || 'No se pudo importar el dataset sintético.')}</div>`;
      }
      showStatus(error.message || 'No se pudo importar el dataset sintético.', 'danger');
    } finally {
      if (elements.datasetSyntheticBtn) {
        elements.datasetSyntheticBtn.disabled = false;
        elements.datasetSyntheticBtn.innerHTML = '<i class="fas fa-bolt me-2"></i>Cargar datos sintéticos';
      }
    }
  });

  loadInitialState();
});