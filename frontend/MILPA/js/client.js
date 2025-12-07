// client.js

// 1) Inicializar Socket.IO
// Se incluye el token en el objeto 'auth' para la autenticación de la conexión del socket.
// El backend (server.js) necesitará verificar este token.
const token = localStorage.getItem('milpaToken');

const socket = io('http://localhost:4000', {
  reconnection: true,
  reconnectionAttempts: 5,
  auth: { // <--- MODIFICACIÓN: Enviar token para autenticar la conexión del socket
    token: token 
  }
});

// 2) Estado global del usuario
let currentUser = null; // Se poblará desde localStorage si el token y los datos de usuario existen.

// 3) Referencias a elementos del DOM (sin cambios en esta sección)
const UI = {
  chat: document.getElementById('chat'),
  inputMensaje: document.getElementById('inputMensaje'),
  btnEnviar: document.getElementById('btnEnviar'),
  // Intenta seleccionar el badge de notificación de manera más robusta.
  notificationBadge: document.querySelector('#notificationsDropdown .badge'), 
  notificationList: document.querySelector('ul.dropdown-menu[aria-labelledby="notificationsDropdown"]')
};

// 4) Al cargar la página
document.addEventListener('DOMContentLoaded', () => {
  // --- MODIFICACIÓN: Priorizar la verificación del token ---
  const storedToken = localStorage.getItem('milpaToken');
  const userDataString = localStorage.getItem('milpaUser'); // Asumimos que login.html guarda esto con userId y username

  if (!storedToken) { // Si no hay token, no hay sesión válida.
    return redirectToLogin();
  }

  if (!userDataString) { // Si hay token pero no datos de usuario, es un estado inconsistente.
    console.error('Token encontrado, pero faltan datos de usuario en localStorage. Redirigiendo a login.');
    // Opcionalmente, aquí podrías intentar obtener datos del usuario desde un endpoint /api/auth/me
    // usando el token, pero para simplificar, redirigimos.
    localStorage.removeItem('milpaToken'); // Limpiar token posiblemente inválido o solitario
    return redirectToLogin();
  }

  currentUser = JSON.parse(userDataString);

  // Si llegamos aquí, tenemos token y datos de usuario básicos.
  // La conexión del socket ya se intentó con el token al inicializar 'socket'.
  // Si el token es inválido, los eventos 'connect_error' o un evento personalizado del server lo indicarán.

  updateUserUI(); // Actualizar UI con nombre de usuario
  setupEventListeners(); // Configurar listeners de la UI

  // Pedir historial inicial de chat y notificaciones (asumiendo que la conexión socket fue exitosa)
  // Esto se podría mover a dentro del evento 'connect' del socket para asegurar que solo se pide si está conectado.
  if (socket.connected) {
      socket.emit('request_initial_data');
  } else {
      // Esperar a que se conecte (el evento 'connect' se encargará si la conexión inicial falla pero luego tiene éxito)
      console.log("Esperando conexión del socket para pedir datos iniciales...");
  }
});

// 5) Configurar listeners de UI de forma segura (sin cambios mayores aquí, solo se asegura que currentUser exista para handleChatMessage)
function setupEventListeners() {
  if (UI.btnEnviar && UI.inputMensaje) {
    UI.btnEnviar.addEventListener('click', handleChatMessage);
    UI.inputMensaje.addEventListener('keypress', e => {
      if (e.key === 'Enter') handleChatMessage();
    });
  }

  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', logout);
  }

  const refreshBtn = document.getElementById('refreshData'); // Asumo que este botón podría existir
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      if (socket.connected) {
        socket.emit('request_data_update');
      } else {
        showToast('Desconectado', 'No se pueden actualizar los datos, no hay conexión.', 'warning');
      }
    });
  }

  const clearBtn = document.getElementById('btnLimpiarChat');
  if (clearBtn && UI.chat) {
    clearBtn.addEventListener('click', () => {
      UI.chat.innerHTML = ''; // Limpieza local, no afecta al servidor/otros usuarios
    });
  }
}

// 6) Enviar mensaje al servidor
function handleChatMessage() {
  if (!currentUser) { // No enviar si no hay datos de usuario
    showToast('Error', 'No se ha identificado al usuario.', 'danger');
    return;
  }
  const texto = UI.inputMensaje.value.trim();
  if (!texto) return;

  socket.emit('mensaje_chat', {
    texto,
    usuario: currentUser.username,
    usuarioId: currentUser.userId 
  });

  UI.inputMensaje.value = '';
}

// 7) Eventos de Socket.IO

// --- MODIFICACIÓN: Manejar errores de autenticación del socket ---
socket.on('unauthorized', (error) => {
  console.error('Socket unauthorized:', error.message);
  showToast('Autenticación fallida', 'Tu sesión puede haber expirado. Por favor, inicia sesión de nuevo.', 'danger');
  logout(); // Forzar logout si la autenticación del socket falla
});

socket.on('connect', () => {
  showToast('Conectado', 'Conexión establecida con el servidor.', 'success');
  // Si la conexión se establece (o reestablece) y tenemos un usuario, pedir datos.
  if (currentUser) {
    console.log('Socket conectado, solicitando datos iniciales...');
    socket.emit('request_initial_data');
  }
});

socket.on('connect_error', (err) => {
  console.error('Error de conexión Socket.IO:', err.message);
  // Si el error es por un token inválido (el servidor debería indicarlo), podríamos querer desloguear.
  // Por ahora, solo mostramos un toast genérico. El evento 'unauthorized' es más específico.
  if (err.message === 'Authentication error' || err.message === 'invalid token') { // El servidor podría enviar estos mensajes
      showToast('Error de autenticación', 'Por favor, inicia sesión de nuevo.', 'danger');
      logout();
  } else {
      showToast('Error de conexión', 'Intentando reconectar...', 'danger');
  }
});

socket.on('push_notification', ({ type, title, message }) => {
  appendNotification({ type, title, message });
  showToast(title, message, type);
});

socket.on('data_update', data => {
  if (!UI.chat || !currentUser) return; // Asegurarse que el chat y currentUser existen
  UI.chat.innerHTML = '';
  data.forEach(msg => {
    const isOwn = msg.usuarioId === currentUser.userId;
    appendChatMessage({ ...msg, isOwn });
  });
});

socket.on('nuevo_mensaje', data => {
  if (!currentUser) return;
  const isOwn = data.usuarioId === currentUser.userId;
  appendChatMessage({ ...data, isOwn });
});


// 8) Renderizar un mensaje en el chat (sin cambios funcionales, solo asegurando que UI.chat exista)
function appendChatMessage({ texto, fecha, usuario, isOwn }) {
  if (!UI.chat) return;
  const hora = new Date(fecha).toLocaleTimeString('es-MX', {
    hour: '2-digit',
    minute: '2-digit'
  });
  // --- MODIFICACIÓN: clase 'own' en lugar de 'own-message' para coincidir con CSS de dashboard.html ---
  const clase = isOwn ? 'own' : ''; 

  const html = `
    <div class="message ${clase}">
      <div class="message-header">
        <span class="user fw-bold me-2">${isOwn ? 'Tú' : usuario}</span>
        <span class="time small text-muted">${hora}</span>
      </div>
      <div class="message-body">${texto}</div>
    </div>
  `;
  UI.chat.insertAdjacentHTML('beforeend', html);
  UI.chat.scrollTop = UI.chat.scrollHeight;
}

// 9) Notificaciones en el dropdown (sin cambios funcionales)
function appendNotification({ type, title, message }) {
  if (!UI.notificationList) return; // Salir si la lista no existe

  const iconMap = {
    alert: { class: 'fa-exclamation-circle', color: 'text-danger' },
    update: { class: 'fa-info-circle', color: 'text-info' },
    chat: { class: 'fa-comment', color: 'text-primary' },
    default: { class: 'fa-bell', color: 'text-secondary'}
  };
  const iconInfo = iconMap[type] || iconMap.default;

  const html = `
    <li class="notification-item">
      <a class="dropdown-item d-flex align-items-center py-2" href="#">
        <i class="fas ${iconInfo.class} ${iconInfo.color} me-2 fs-5"></i>
        <div>
          <div class="small fw-bold text-truncate" style="max-width: 250px;">${title}</div>
          <small class="text-muted d-block text-truncate" style="max-width: 250px;">${message}</small>
        </div>
      </a>
    </li>
  `;
  UI.notificationList.insertAdjacentHTML('afterbegin', html); // Insertar al principio para ver las más nuevas primero
  updateNotificationBadge();
}

// 10) Contador de notificaciones (sin cambios funcionales, solo asegurando que UI.notificationBadge exista)
function updateNotificationBadge() {
  if (!UI.notificationList || !UI.notificationBadge) return;
  const count = UI.notificationList.querySelectorAll('.notification-item').length;
  UI.notificationBadge.textContent = count > 0 ? count : '';
  UI.notificationBadge.style.display = count > 0 ? 'inline-block' : 'none'; // Mostrar/ocultar el badge
}

// 11) Toast de Bootstrap (sin cambios funcionales)
function showToast(title, message, type = 'info') {
  const toastEl = document.getElementById('liveToast');
  if (!toastEl) return; // Salir si el toast no existe

  const toast = bootstrap.Toast.getOrCreateInstance(toastEl); // Usar getOrCreateInstance

  // --- MODIFICACIÓN: Mapeo de tipos a clases de Bootstrap para consistencia ---
  let bgClass = 'bg-info'; // default
  if (type === 'success') bgClass = 'bg-success';
  else if (type === 'danger' || type === 'alert') bgClass = 'bg-danger';
  else if (type === 'warning') bgClass = 'bg-warning';
  else if (type === 'update') bgClass = 'bg-primary';


  const toastHeader = toastEl.querySelector('.toast-header');
  if (toastHeader) {
    toastHeader.className = `toast-header ${bgClass} text-white`; // Asegurar que se apliquen clases
  }
  const toastTitleEl = toastEl.querySelector('#toastTitle');
  if (toastTitleEl) toastTitleEl.textContent = title;
  
  const toastMessageEl = toastEl.querySelector('#toastMessage');
  if (toastMessageEl) toastMessageEl.textContent = message;

  toast.show();
}

// 12) Actualizar nombre de usuario en pantalla
function updateUserUI() {
  if (!currentUser) return;
  // En dashboard.html, el nombre de usuario en la navbar tiene id="userDisplayName"
  const userDisplayName = document.getElementById('userDisplayName');
  if (userDisplayName) {
      userDisplayName.textContent = currentUser.username;
  }
  // En dashboard.html, el nombre en la tarjeta de perfil tiene id="profileName"
  const profileName = document.getElementById('profileName');
  if (profileName) {
      profileName.textContent = currentUser.username;
  }
  // Si tienes otros elementos con una clase genérica (como '.user-display' que tenías antes)
  // document.querySelectorAll('.user-display').forEach(el => {
  //   el.textContent = currentUser.username;
  // });
}

// 13) Cerrar sesión
function logout() {
  // --- MODIFICACIÓN: Asegurarse de remover ambos items ---
  localStorage.removeItem('milpaUser');
  localStorage.removeItem('milpaToken'); // <--- IMPORTANTE: Remover el token
  if(socket) socket.disconnect();
  redirectToLogin();
}

// 14) Redirigir a login (sin cambios)
function redirectToLogin() {
  window.location.href = 'login.html';
}

// --- NUEVO: Función helper para llamadas fetch a la API REST ---
/**
 * Realiza una petición fetch a la API, incluyendo automáticamente el token JWT.
 * @param {string} url - El endpoint de la API (ej. '/api/cultivos')
 * @param {object} options - Opciones para fetch (method, headers, body, etc.)
 * @returns {Promise<any>} - La respuesta parseada como JSON.
 */
async function fetchAPI(url, options = {}) {
  const storedToken = localStorage.getItem('milpaToken');

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers, // Permite sobreescribir o añadir más headers
  };

  if (storedToken) {
    headers['Authorization'] = `Bearer ${storedToken}`;
  }

  try {
    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      // Token inválido, expirado o no autorizado
      showToast('Sesión expirada', 'Por favor, inicia sesión nuevamente.', 'danger');
      logout(); // Desloguear al usuario
      return Promise.reject({ status: 401, message: 'No autorizado o token expirado.' });
    }

    if (!response.ok) {
      // Intentar parsear el error del backend si existe
      const errorData = await response.json().catch(() => ({ message: response.statusText }));
      return Promise.reject({ status: response.status, message: errorData.error || errorData.message || 'Error en la petición.' });
    }
    
    // Si la respuesta no tiene contenido (ej. 204 No Content), devolver null o un objeto vacío.
    if (response.status === 204) {
        return null; 
    }
    return response.json(); // Parsear y devolver los datos

  } catch (error) {
    console.error('Error en fetchAPI:', error);
    showToast('Error de red', 'No se pudo conectar con el servidor.', 'danger');
    return Promise.reject({ message: 'Error de red o conexión.' });
  }
}

// Ejemplo de cómo usarías fetchAPI (esto no se ejecuta aquí, es solo un ejemplo):
/*
async function cargarCultivos() {
  try {
    const cultivos = await fetchAPI('/api/cultivos'); // Asume que existe este endpoint
    console.log('Cultivos cargados:', cultivos);
    // Lógica para mostrar cultivos en la UI
  } catch (error) {
    console.error('No se pudieron cargar los cultivos:', error.message);
    // No necesitas redirigir a login aquí, fetchAPI ya lo haría si es un 401.
    // Solo maneja otros errores específicos de esta llamada.
  }
}
*/