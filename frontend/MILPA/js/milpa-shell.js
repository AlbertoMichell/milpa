/**
 * Layout app MILPA: sidebar + navbar fija + marca ítem activo en menú + salida.
 * Requiere: body.milpa-page, #sidebar, #mainContent, .navbar.milpa-top-navbar, #sidebarToggle
 */
(function () {
  function setActiveNav() {
    const page = document.body?.dataset?.activePage;
    if (!page) return;
    document.querySelectorAll('.sidebar-nav-link').forEach(a => a.classList.remove('active'));
    document.querySelectorAll('.sidebar-nav-link').forEach(a => {
      const href = a.getAttribute('href');
      if (href && (href === page || href.endsWith(page))) {
        a.classList.add('active');
      }
    });
  }

  function applyLayoutStates() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    const topNavbar = document.querySelector('.navbar.milpa-top-navbar');
    if (!sidebar || !mainContent || !topNavbar) return;

    const isSmallScreen = window.innerWidth <= 768;
    const isSidebarCollapsed = sidebar.classList.contains('sidebar-collapsed');

    if (isSmallScreen) {
      sidebar.classList.add('sidebar-collapsed');
      mainContent.classList.add('main-content-expanded');
      topNavbar.style.left = '80px';
      topNavbar.style.width = 'calc(100% - 80px)';
    } else {
      if (isSidebarCollapsed) {
        mainContent.classList.add('main-content-expanded');
        topNavbar.style.left = '80px';
        topNavbar.style.width = 'calc(100% - 80px)';
      } else {
        sidebar.classList.remove('sidebar-collapsed');
        mainContent.classList.remove('main-content-expanded');
        topNavbar.style.left = '250px';
        topNavbar.style.width = 'calc(100% - 250px)';
      }
    }
  }

  async function milpaLogout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (_) {}
    localStorage.removeItem('milpaToken');
    localStorage.removeItem('milpaUser');
    window.location.href = 'login.html';
  }

  document.addEventListener('DOMContentLoaded', () => {
    setActiveNav();

    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    if (sidebarToggle && sidebar) {
      sidebarToggle.addEventListener('click', () => {
        sidebar.classList.toggle('sidebar-collapsed');
        applyLayoutStates();
      });
    }

    window.addEventListener('resize', applyLayoutStates);
    applyLayoutStates();

    document.querySelectorAll('#milpaLogoutBtn, #logoutBtn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.preventDefault();
        milpaLogout();
      });
    });
  });
})();
