document.addEventListener('DOMContentLoaded', async () => {
  const elements = {
    searchInput: document.getElementById('knowledgeSearchInput'),
    searchBtn: document.getElementById('knowledgeSearchBtn'),
    reloadBtn: document.getElementById('knowledgeReloadBtn'),
    authorFilter: document.getElementById('knowledgeAuthorFilter'),
    yearFilter: document.getElementById('knowledgeYearFilter'),
    status: document.getElementById('knowledgeStatus'),
    answerCard: document.getElementById('knowledgeAnswerCard'),
    answerText: document.getElementById('knowledgeAnswerText'),
    citations: document.getElementById('knowledgeCitations'),
    documents: document.getElementById('knowledgeDocumentsList'),
    detailTitle: document.getElementById('knowledgeDetailTitle'),
    detailBody: document.getElementById('knowledgeDetailBody'),
    detailModalEl: document.getElementById('knowledgeDetailModal'),
    categoriesGrid: document.getElementById('knowledgeCategoriesGrid'),
    faqAccordion: document.getElementById('faqAccordion'),
  };

  const detailModal = elements.detailModalEl ? bootstrap.Modal.getOrCreateInstance(elements.detailModalEl) : null;

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function htmlToText(html) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(String(html || ''), 'text/html');
    return doc.body.textContent || '';
  }

  function showStatus(message, type = 'info') {
    if (!elements.status) return;
    elements.status.innerHTML = `<div class="alert alert-${type}">${escapeHtml(message)}</div>`;
  }

  function renderAnswer(payload) {
    if (!elements.answerCard || !elements.answerText || !elements.citations) return;
    if (!payload?.answer) {
      elements.answerCard.classList.add('d-none');
      elements.answerText.textContent = '';
      elements.citations.innerHTML = '';
      return;
    }

    elements.answerCard.classList.remove('d-none');
    elements.answerText.textContent = htmlToText(payload.answer);
    const citations = Array.isArray(payload.citations) ? payload.citations : [];
    const citeLine = c => {
      if (c == null) return '';
      if (typeof c === 'string') return escapeHtml(c);
      try {
        return escapeHtml(JSON.stringify(c));
      } catch {
        return escapeHtml(String(c));
      }
    };
    elements.citations.innerHTML = citations.length
      ? `<h6 class="mb-2">Citas</h6><ul class="mb-0">${citations.map(citation => `<li>${citeLine(citation)}</li>`).join('')}</ul>`
      : '<p class="text-muted mb-0">No se devolvieron citas estructuradas para esta consulta.</p>';
  }

  function renderDocuments(items) {
    if (!elements.documents) return;
    if (!items.length) {
      elements.documents.innerHTML = '<div class="list-group-item text-muted">No se encontraron documentos para los filtros actuales.</div>';
      return;
    }

    elements.documents.innerHTML = items.map(item => `
      <button type="button" class="list-group-item list-group-item-action article-card mb-2 text-start" data-doc-id="${escapeHtml(item.id)}">
        <div class="d-flex w-100 justify-content-between align-items-start gap-3">
          <div>
            <h5 class="mb-1">${escapeHtml(item.nombre)}</h5>
            <p class="mb-1">Autor: ${escapeHtml(item.autor || 'Sin autor')} · Tipo: ${escapeHtml(item.tipo || 'N/D')}</p>
            <small class="text-muted">Fuente: ${escapeHtml(item.extraido_de || 'N/D')}</small>
          </div>
          <span class="category-badge badge bg-success">${escapeHtml(item.año || 'Sin año')}</span>
        </div>
      </button>
    `).join('');
  }

  async function loadDetail(docId) {
    const detail = await MILPA_API.getLibraryDetail(docId);
    if (!elements.detailTitle || !elements.detailBody) return;
    elements.detailTitle.textContent = detail.nombre || 'Detalle del documento';

    const fragments = Array.isArray(detail.fragments) ? detail.fragments : [];
    const tables = Array.isArray(detail.tables) ? detail.tables : [];
    const fragmentMarkup = fragments.length
      ? fragments.map(fragment => `<div class="border rounded p-3 mb-2"><small class="text-muted d-block mb-2">Página ${escapeHtml(fragment.page_start ?? fragment.page ?? '?')}</small><p class="mb-0">${escapeHtml(fragment.text)}</p></div>`).join('')
      : '<p class="text-muted">No hay fragmentos extraídos disponibles.</p>';
    const tableMarkup = tables.length
      ? tables.map(table => `<div class="border rounded p-3 mb-3"><h6 class="mb-2">Tabla página ${escapeHtml(table.page || '?')}</h6><p class="small text-muted mb-0">${escapeHtml(`${table.n_rows || 0} filas · ${table.n_cols || 0} columnas`)}</p></div>`).join('')
      : '<p class="text-muted">No hay tablas detectadas para este documento.</p>';

    elements.detailBody.innerHTML = `
      <p><strong>Autor:</strong> ${escapeHtml(detail.autor || 'Sin autor')}</p>
      <p><strong>Clasificación:</strong> ${escapeHtml(detail.classification || 'N/D')} · <strong>Licencia:</strong> ${escapeHtml(detail.license || 'N/D')}</p>
      <hr>
      <h6>Fragmentos</h6>
      ${fragmentMarkup}
      <hr>
      <h6>Tablas</h6>
      ${tableMarkup}
    `;
    detailModal?.show();
  }

  function iconClassFor(slug, fallback) {
    const map = {
      siembra: 'fas fa-seedling',
      plagas: 'fas fa-bug',
      agua: 'fas fa-tint',
      calendario: 'fas fa-moon',
    };
    return map[slug] || (fallback ? fallback.replace('bi-', 'fas fa-') : 'fas fa-book');
  }

  async function loadCategories() {
    if (!elements.categoriesGrid) return;
    try {
      const categories = await MILPA_API.getLibraryCategories();
      if (!Array.isArray(categories) || !categories.length) {
        elements.categoriesGrid.innerHTML = '<div class="col-12 text-muted small">No hay categorías cargadas en la biblioteca.</div>';
        return;
      }
      elements.categoriesGrid.innerHTML = categories.map(cat => `
        <div class="col-md-6 col-lg-3">
          <div class="card knowledge-card border-0 shadow-sm text-center p-4 h-100">
            <i class="${iconClassFor(cat.slug, cat.icon)} knowledge-icon"></i>
            <h5>${escapeHtml(cat.title)}</h5>
            <p class="text-muted small">${escapeHtml(cat.description || '')}</p>
            <button type="button" class="btn btn-outline-forest-green btn-sm knowledge-query-btn" data-query="${escapeHtml(cat.query_example || cat.title)}">Explorar</button>
          </div>
        </div>
      `).join('');
      elements.categoriesGrid.querySelectorAll('.knowledge-query-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const q = btn.dataset.query || '';
          if (elements.searchInput) elements.searchInput.value = q;
          runKnowledgeSearch(q);
        });
      });
    } catch (error) {
      console.error('No se pudieron cargar categorías:', error);
      elements.categoriesGrid.innerHTML = '<div class="col-12 text-muted small">No se pudieron cargar las categorías.</div>';
    }
  }

  async function loadFaqs() {
    if (!elements.faqAccordion) return;
    try {
      const faqs = await MILPA_API.getFaqs();
      if (!Array.isArray(faqs) || !faqs.length) {
        elements.faqAccordion.innerHTML = '<div class="accordion-item border-0 shadow-sm"><div class="accordion-body text-muted small">Aún no hay preguntas frecuentes registradas.</div></div>';
        return;
      }
      // Cada FAQ guarda en BD `related_doc_id` opcional → si existe, exponemos
      // un botón "Ver fuente" que abre el detalle del documento de la biblioteca,
      // dejando explícito de qué libro/manual viene la respuesta.
      elements.faqAccordion.innerHTML = faqs.map((faq, idx) => {
        const collapseId = `faqCollapse${faq.id}`;
        const headingId = `faqHeading${faq.id}`;
        const expanded = idx === 0;
        const docButton = faq.related_doc_id
          ? `<button type="button" class="btn btn-sm btn-outline-forest-green mt-2 faq-source-btn" data-doc-id="${escapeHtml(faq.related_doc_id)}">
               <i class="fas fa-book me-1"></i>Ver fuente en biblioteca
             </button>`
          : `<small class="text-muted d-block mt-2">Sin documento de referencia ligado todavía.</small>`;
        return `
          <div class="accordion-item mb-2 border-0 shadow-sm">
            <h2 class="accordion-header" id="${headingId}">
              <button class="accordion-button ${expanded ? '' : 'collapsed'}" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}" aria-expanded="${expanded}" aria-controls="${collapseId}">
                ${escapeHtml(faq.question)}
                ${faq.crop_name ? `<span class="badge bg-success ms-2">${escapeHtml(faq.crop_name)}</span>` : ''}
              </button>
            </h2>
            <div id="${collapseId}" class="accordion-collapse collapse ${expanded ? 'show' : ''}" aria-labelledby="${headingId}" data-bs-parent="#faqAccordion">
              <div class="accordion-body">
                <p class="mb-2">${escapeHtml(faq.answer)}</p>
                <small class="text-muted d-block">Categoría: ${escapeHtml(faq.category || 'general')}</small>
                ${docButton}
              </div>
            </div>
          </div>
        `;
      }).join('');

      elements.faqAccordion.querySelectorAll('.faq-source-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
          try {
            await loadDetail(btn.dataset.docId);
          } catch (error) {
            console.error('No se pudo abrir la fuente FAQ:', error);
            showStatus(error.message || 'No se pudo abrir el documento de referencia.', 'danger');
          }
        });
      });
    } catch (error) {
      console.error('No se pudieron cargar las FAQ:', error);
      elements.faqAccordion.innerHTML = '<div class="accordion-item border-0 shadow-sm"><div class="accordion-body text-warning small">No se pudieron cargar las preguntas frecuentes.</div></div>';
    }
  }

  async function loadFacets() {
    try {
      const facets = await MILPA_API.getLibraryFacets();
      const authors = Array.isArray(facets.authors) ? facets.authors : [];
      const years = Array.isArray(facets.years) ? facets.years : [];
      if (elements.authorFilter) {
        elements.authorFilter.innerHTML = ['<option value="">Autor</option>']
          .concat(authors.map(author => `<option value="${escapeHtml(author)}">${escapeHtml(author)}</option>`))
          .join('');
      }
      if (elements.yearFilter) {
        elements.yearFilter.innerHTML = ['<option value="">Año</option>']
          .concat(years.map(year => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`))
          .join('');
      }
    } catch (error) {
      console.error('No se pudieron cargar las facetas de biblioteca:', error);
      showStatus('No se pudieron cargar autores y años disponibles.', 'warning');
    }
  }

  async function runKnowledgeSearch(queryOverride = null) {
    const query = (queryOverride ?? elements.searchInput?.value ?? '').trim();
    const author = elements.authorFilter?.value || '';
    const year = elements.yearFilter?.value || '';
    showStatus('Consultando biblioteca y RAG...', 'info');

    try {
      const [libraryResult, ragResult] = await Promise.allSettled([
        MILPA_API.getLibrary({ q: query, author, year, limit: 8 }),
        query ? MILPA_API.queryRAG(query, 6) : Promise.resolve(null),
      ]);

      const libraryPayload = libraryResult.status === 'fulfilled' ? libraryResult.value : { items: [] };
      renderDocuments(Array.isArray(libraryPayload.items) ? libraryPayload.items : []);
      const ragOk = ragResult.status === 'fulfilled' ? ragResult.value : null;
      if (!query) {
        renderAnswer(null);
      } else {
        renderAnswer(ragOk);
      }
      let msg = `Consulta completada. Documentos: ${(libraryPayload.items || []).length}.`;
      if (query && ragResult.status === 'rejected') {
        msg += ' RAG no disponible para esta consulta.';
        showStatus(msg, 'warning');
      } else {
        showStatus(msg, 'success');
      }
    } catch (error) {
      console.error('Error en búsqueda de conocimiento:', error);
      showStatus(error.message || 'No se pudo consultar la base de conocimiento.', 'danger');
      renderDocuments([]);
      renderAnswer(null);
    }
  }

  document.querySelectorAll('.knowledge-query-btn').forEach(button => {
    button.addEventListener('click', () => {
      const query = button.dataset.query || '';
      if (elements.searchInput) {
        elements.searchInput.value = query;
      }
      runKnowledgeSearch(query);
    });
  });

  elements.searchBtn?.addEventListener('click', () => {
    runKnowledgeSearch();
  });

  elements.searchInput?.addEventListener('keypress', event => {
    if (event.key === 'Enter') {
      runKnowledgeSearch();
    }
  });

  elements.reloadBtn?.addEventListener('click', () => {
    runKnowledgeSearch(elements.searchInput?.value || 'milpa');
  });

  elements.documents?.addEventListener('click', async event => {
    const item = event.target.closest('[data-doc-id]');
    if (!item) return;
    try {
      await loadDetail(item.dataset.docId);
    } catch (error) {
      console.error('No se pudo cargar el detalle del documento:', error);
      showStatus(error.message || 'No se pudo cargar el detalle del documento.', 'danger');
    }
  });

  if (elements.searchInput && !elements.searchInput.value) {
    elements.searchInput.value = 'milpa';
  }

  await Promise.all([loadFacets(), loadCategories(), loadFaqs()]);
  await runKnowledgeSearch('milpa');
});