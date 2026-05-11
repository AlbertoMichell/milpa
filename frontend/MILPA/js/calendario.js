document.addEventListener('DOMContentLoaded', async () => {
  const eventTypeMeta = {};

  let calendar = null;
  let events = [];

  const taskList = document.getElementById('upcomingTasksList');
  const eventCropId = document.getElementById('eventCropId');
  const eventTypeSelect = document.getElementById('eventType');
  const generatePlanBtn = document.getElementById('generatePlanBtn');
  const eventModalEl = document.getElementById('newEventModal');
  const eventModal = eventModalEl ? bootstrap.Modal.getOrCreateInstance(eventModalEl) : null;

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function getTypeMeta(type) {
    return eventTypeMeta[type] || eventTypeMeta.other;
  }

  async function loadEventTypes() {
    let rows = [];
    try {
      rows = await MILPA_API.getCalendarEventTypes();
    } catch (_) {
      rows = [];
    }

    const fallback = [
      { slug: 'sowing', label: 'Siembra', color_class: 'event-sowing', badge_class: 'bg-primary', border_color: '#0d6efd' },
      { slug: 'harvest', label: 'Cosecha', color_class: 'event-harvest', badge_class: 'bg-success', border_color: '#198754' },
      { slug: 'maintenance', label: 'Mantenimiento', color_class: 'event-maintenance', badge_class: 'bg-warning text-dark', border_color: '#ffc107' },
      { slug: 'pest', label: 'Plagas', color_class: 'event-pest', badge_class: 'bg-danger', border_color: '#dc3545' },
      { slug: 'other', label: 'General', color_class: 'event-other', badge_class: 'bg-secondary', border_color: '#6c757d' },
    ];

    const source = rows.length ? rows : fallback;
    Object.keys(eventTypeMeta).forEach(k => delete eventTypeMeta[k]);
    source.forEach(row => {
      eventTypeMeta[row.slug] = {
        label: row.label,
        className: row.color_class,
        badge: row.badge_class,
        border: row.border_color,
      };
    });
    if (!eventTypeMeta.other && source[0]) {
      eventTypeMeta.other = {
        label: source[0].label,
        className: source[0].color_class,
        badge: source[0].badge_class,
        border: source[0].border_color,
      };
    }

    if (eventTypeSelect) {
      eventTypeSelect.innerHTML = source.map(row => `<option value="${escapeHtml(row.slug)}">${escapeHtml(row.label)}</option>`).join('');
    }
  }

  function toCalendarEvent(event) {
    const meta = getTypeMeta(event.event_type);
    return {
      id: String(event.id),
      title: event.title,
      start: event.start_date,
      end: event.end_date || event.start_date,
      className: [meta.className],
      extendedProps: event,
    };
  }

  // Etiqueta de fuente: distinguimos entre actividades del usuario, IA operativa
  // (heurística desde planted_at) e IA RAG (con cita a documento de la biblioteca).
  function describeEventSource(event) {
    const desc = String(event.description || '');
    const ragMatch = desc.match(/Fuente RAG[^.\n]*/i);
    if (event.source_kind === 'ia' && ragMatch) {
      return {
        pill: '<span class="badge bg-success-subtle text-success border" title="' + escapeHtml(ragMatch[0]) + '"><i class="fas fa-book me-1"></i>Plan RAG con cita</span>',
        cite: ragMatch[0],
      };
    }
    if (event.source_kind === 'ia') {
      return { pill: '<span class="badge bg-info-subtle text-info border">Asignada por IA</span>', cite: null };
    }
    return { pill: '<span class="badge bg-secondary-subtle text-secondary border">Asignada por usuario</span>', cite: null };
  }

  function startOfToday() {
    const t = new Date();
    return new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();
  }

  /**
   * Próximas actividades = no canceladas + (a) sin completar y futuras, o
   * (b) vencidas hace menos de 14 días (las marcamos como "Vencida" para
   * que el agricultor reaccione, pero no inundamos la pantalla con tareas
   * de meses anteriores). El listado se ordena por urgencia: vencidas
   * primero, luego pendientes próximas.
   */
  function classifyUpcoming(events) {
    const today = startOfToday();
    const dayMs = 24 * 60 * 60 * 1000;
    const list = (events || [])
      .filter(e => e.status !== 'cancelado')
      .map(e => {
        const ts = new Date(e.start_date).getTime();
        let bucket = 'future';
        if (e.status === 'completado') bucket = 'done';
        else if (ts < today && (today - ts) <= 14 * dayMs) bucket = 'overdue';
        else if (ts < today) bucket = 'old';
        return { ...e, _bucket: bucket, _ts: ts };
      })
      .filter(e => e._bucket === 'overdue' || e._bucket === 'future' || e._bucket === 'done')
      .sort((a, b) => {
        const order = { overdue: 0, future: 1, done: 2 };
        if (order[a._bucket] !== order[b._bucket]) return order[a._bucket] - order[b._bucket];
        return a._ts - b._ts;
      });
    return list.slice(0, 10);
  }

  function renderUpcomingTasks() {
    if (!taskList) return;
    const pendingEvents = classifyUpcoming(events);

    if (!pendingEvents.length) {
      taskList.innerHTML = '<div class="text-center text-muted py-4">No hay actividades programadas todavía.</div>';
      return;
    }

    taskList.innerHTML = pendingEvents.map(event => {
      const meta = getTypeMeta(event.event_type);
      const formattedDate = new Date(event.start_date).toLocaleDateString('es-MX', { day: '2-digit', month: 'long', year: 'numeric' });
      const cropTag = event.crop_name ? `<p class="small text-muted mb-2">Cultivo: ${escapeHtml(event.crop_name)}</p>` : '';
      const src = describeEventSource(event);
      const description = event.description ? `<p class="small mt-2 mb-2">${escapeHtml(event.description)}</p>` : '';
      let statusTag = '';
      if (event.status === 'completado') {
        statusTag = '<span class="badge bg-success-subtle text-success border">Completado</span>';
      } else if (event._bucket === 'overdue') {
        statusTag = '<span class="badge bg-danger-subtle text-danger border" title="La fecha sugerida ya pasó">Vencida</span>';
      }
      return `<div class="card task-card mb-3" style="border-left-color:${meta.border};">
        <div class="card-body p-3">
          <div class="d-flex justify-content-between align-items-start gap-3">
            <div>
              <div class="d-flex align-items-center gap-2 mb-1">
                <h6 class="mb-0">${escapeHtml(event.title)}</h6>
                ${statusTag}
              </div>
              <small class="text-muted"><i class="fas fa-calendar-alt me-1"></i> ${formattedDate}</small>
              <div class="mt-1">${src.pill}</div>
            </div>
            <span class="badge ${meta.badge}">${meta.label}</span>
          </div>
          ${cropTag}
          ${description}
          <div class="d-flex justify-content-end gap-2 mt-2">
            <button type="button" class="btn btn-sm btn-outline-success" data-action="complete" data-event-id="${event.id}">Completar</button>
            <button type="button" class="btn btn-sm btn-outline-danger" data-action="delete" data-event-id="${event.id}">Eliminar</button>
          </div>
        </div>
      </div>`;
    }).join('');
  }

  async function loadCropOptions() {
    if (!eventCropId) return;
    try {
      const crops = await MILPA_API.getCrops();
      eventCropId.innerHTML = ['<option value="">General</option>']
        .concat(crops.map(crop => `<option value="${crop.id}">${escapeHtml(crop.display_name || crop.crop_name)}</option>`))
        .join('');
    } catch (error) {
      console.error('No se pudieron cargar cultivos para el calendario:', error);
    }
  }

  async function refreshEvents() {
    events = await MILPA_API.getCalendarEvents();
    renderUpcomingTasks();
    if (calendar) {
      calendar.removeAllEvents();
      calendar.addEventSource(events.map(toCalendarEvent));
    }
  }

  async function saveEvent() {
    const title = document.getElementById('eventTitle').value.trim();
    const eventType = document.getElementById('eventType').value;
    const eventDate = document.getElementById('eventDate').value;
    const description = document.getElementById('eventDescription').value.trim();

    if (!title || !eventDate) {
      window.alert('Indica título y fecha para la actividad.');
      return;
    }

    await MILPA_API.createCalendarEvent({
      title,
      event_type: eventType,
      start_date: eventDate,
      end_date: eventDate,
      description,
      user_crop_id: eventCropId?.value ? Number(eventCropId.value) : null,
    });

    document.getElementById('eventForm').reset();
    if (eventCropId) eventCropId.value = '';
    eventModal?.hide();
    await refreshEvents();
  }

  async function handleTaskAction(action, eventId) {
    if (action === 'complete') {
      await MILPA_API.updateCalendarEvent(eventId, { status: 'completado' });
      await refreshEvents();
      return;
    }

    if (action === 'delete') {
      if (!window.confirm('¿Eliminar esta actividad del calendario?')) {
        return;
      }
      await MILPA_API.deleteCalendarEvent(eventId);
      await refreshEvents();
    }
  }

  // Convierte una actividad del endpoint /api/calendar/rag-plan en un evento
  // persistible. La descripción guarda la justificación + la cita del documento
  // de la biblioteca (Fuente RAG — <título>, p. <pagina>) para que el render
  // posterior la pueda detectar y mostrar como "Plan RAG con cita".
  function buildEventFromRagActivity(activity) {
    const lines = [];
    if (activity.rationale_html) {
      const tmp = document.createElement('div');
      tmp.innerHTML = activity.rationale_html;
      lines.push(tmp.textContent.trim());
    }
    if (activity.evidence && activity.source) {
      const cite = [];
      if (activity.source.doc_title) cite.push(activity.source.doc_title);
      if (activity.source.page_start != null) cite.push(`p. ${activity.source.page_start}`);
      if (cite.length) lines.push(`Fuente RAG — ${cite.join(', ')}`);
    } else {
      lines.push('Sugerencia operativa (sin evidencia suficiente en la biblioteca).');
    }
    return {
      title: activity.title,
      event_type: activity.event_type || 'maintenance',
      start_date: activity.suggested_date,
      end_date: activity.suggested_date,
      description: lines.join(' · '),
      user_crop_id: activity.user_crop_id || null,
    };
  }

  // Dedup contra eventos ya existentes para evitar acumulación si el usuario
  // pulsa "Sincronizar IA" varias veces. Llave: title + start_date + crop_id.
  function alreadyHasEvent(activity) {
    const key = `${activity.title}|${activity.suggested_date}|${activity.user_crop_id || ''}`;
    return events.some(e => `${e.title}|${e.start_date}|${e.user_crop_id || ''}` === key);
  }

  /**
   * Genera "Próximas actividades" para todos los cultivos del usuario usando
   * el motor RAG real. Cada actividad cita el documento (título + página) de
   * la biblioteca MILPA en el que se basa. Si no hay evidencia suficiente,
   * la actividad se genera igualmente pero sin cita y queda marcada como tal.
   */
  async function generatePlan() {
    let crops = [];
    try { crops = await MILPA_API.getCrops(); } catch (_) { crops = []; }
    const activeCrops = crops.filter(c => (c.status || 'activo') === 'activo');
    if (!activeCrops.length) {
      window.alert('No hay cultivos activos. Carga una planta en Configuración antes de pedir un plan.');
      return;
    }

    const summary = { plans: 0, inserted: 0, withEvidence: 0, withoutEvidence: 0, skipped: 0, errors: 0, citations: [] };

    for (const crop of activeCrops) {
      let plan;
      try {
        plan = await MILPA_API.generateRagCalendarPlan(crop.id);
      } catch (err) {
        summary.errors += 1;
        console.warn('Plan RAG falló para cultivo', crop.id, err);
        continue;
      }
      summary.plans += 1;
      const activities = Array.isArray(plan?.activities) ? plan.activities : [];
      for (const act of activities) {
        if (alreadyHasEvent(act)) { summary.skipped += 1; continue; }
        try {
          const payload = buildEventFromRagActivity(act);
          await MILPA_API.createCalendarEvent({ ...payload, source_kind: 'ia' });
          summary.inserted += 1;
          if (act.evidence) {
            summary.withEvidence += 1;
            if (act.source?.doc_title) {
              const cite = `${act.source.doc_title}${act.source.page_start != null ? ', p. ' + act.source.page_start : ''}`;
              if (!summary.citations.includes(cite)) summary.citations.push(cite);
            }
          } else {
            summary.withoutEvidence += 1;
          }
        } catch (err) {
          summary.errors += 1;
          console.warn('No se pudo persistir actividad RAG:', err);
        }
      }
    }

    await refreshEvents();

    const lines = [
      `Plan RAG generado para ${summary.plans} cultivo(s).`,
      `Actividades nuevas: ${summary.inserted} (con cita: ${summary.withEvidence}, sin evidencia suficiente: ${summary.withoutEvidence}).`,
      `Sin cambios (ya existían): ${summary.skipped}.`,
      summary.errors ? `Errores: ${summary.errors}.` : '',
      '',
      'Cada actividad incluye, cuando hay evidencia, una "Fuente RAG" con el documento y página de la biblioteca MILPA en la que se respalda.',
    ];
    if (summary.citations.length) {
      lines.push('', 'Documentos citados:');
      summary.citations.slice(0, 5).forEach(c => lines.push(' · ' + c));
    }
    window.alert(lines.filter(Boolean).join('\n'));
  }

  const calendarEl = document.getElementById('calendar');
  if (calendarEl) {
    calendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      locale: 'es',
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,timeGridWeek,timeGridDay',
      },
      events: [],
      eventClick: function(info) {
        const event = info.event.extendedProps;
        const meta = getTypeMeta(event.event_type);
        const dateLabel = new Date(event.start_date).toLocaleDateString('es-MX');
        const src = describeEventSource(event);
        // Quita el HTML del pill para mostrarlo como texto en el alert.
        const sourceText = src.pill.replace(/<[^>]+>/g, '').trim() || (event.source_kind === 'ia' ? 'IA' : 'Usuario');
        const lines = [
          `${meta.label}: ${event.title}`,
          `Fecha: ${dateLabel}`,
          `Origen: ${sourceText}`,
        ];
        if (event.crop_name) lines.push(`Cultivo: ${event.crop_name}`);
        if (event.description) {
          lines.push('');
          lines.push(event.description);
        }
        if (src.cite) {
          lines.push('');
          lines.push(`Documento citado: ${src.cite.replace(/^Fuente RAG\s*[—-]?\s*/i, '')}`);
        }
        window.alert(lines.join('\n'));
      },
    });
    calendar.render();
  }

  document.getElementById('saveEventBtn')?.addEventListener('click', async () => {
    try {
      await saveEvent();
    } catch (error) {
      console.error('No se pudo guardar el evento:', error);
      window.alert(error.message || 'No se pudo guardar la actividad.');
    }
  });

  taskList?.addEventListener('click', async event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    try {
      await handleTaskAction(button.dataset.action, Number(button.dataset.eventId));
    } catch (error) {
      console.error('No se pudo actualizar la actividad:', error);
      window.alert(error.message || 'No se pudo actualizar la actividad.');
    }
  });

  generatePlanBtn?.addEventListener('click', async () => {
    const originalHtml = generatePlanBtn.innerHTML;
    generatePlanBtn.disabled = true;
    generatePlanBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generando...';
    try {
      await generatePlan();
    } catch (error) {
      console.error('No se pudo generar plan automático:', error);
      window.alert(error.message || 'No se pudo generar el plan automático.');
    } finally {
      generatePlanBtn.disabled = false;
      generatePlanBtn.innerHTML = originalHtml;
    }
  });

  await loadEventTypes();
  await loadCropOptions();
  await refreshEvents();
});