(() => {
  const menuButton = document.querySelector('[data-menu-toggle]');
  const nav = document.querySelector('[data-nav]');
  const homesSidebar = document.querySelector('[data-homes-sidebar]');
  const sidebarBackdrop = document.querySelector('[data-sidebar-close]');
  if (menuButton && homesSidebar) {
    const setSidebarOpen = (opened) => {
      homesSidebar.classList.toggle('is-open', opened);
      if (sidebarBackdrop) sidebarBackdrop.hidden = !opened;
      menuButton.setAttribute('aria-expanded', String(opened));
      menuButton.setAttribute('aria-label', opened ? 'Close categories' : 'Open categories');
    };
    menuButton.addEventListener('click', () => {
      if (window.matchMedia('(max-width: 900px)').matches) {
        setSidebarOpen(!homesSidebar.classList.contains('is-open'));
      } else {
        const layout = homesSidebar.closest('.browse-layout');
        const collapsed = layout && layout.classList.toggle('sidebar-collapsed');
        menuButton.setAttribute('aria-expanded', String(!collapsed));
        menuButton.setAttribute('aria-label', collapsed ? 'Show categories' : 'Hide categories');
      }
    });
    if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', () => setSidebarOpen(false));
    homesSidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setSidebarOpen(false)));
  } else if (menuButton && nav) {
    menuButton.addEventListener('click', () => {
      const opened = nav.classList.toggle('open');
      menuButton.setAttribute('aria-expanded', String(opened));
      menuButton.setAttribute('aria-label', opened ? 'Close menu' : 'Open menu');
    });
    nav.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
      nav.classList.remove('open'); menuButton.setAttribute('aria-expanded', 'false');
    }));
  }

  const offlineBanner = document.getElementById('offlineBanner');
  const reflectConnection = () => { if (offlineBanner) offlineBanner.hidden = navigator.onLine; };
  window.addEventListener('online', reflectConnection);
  window.addEventListener('offline', reflectConnection);
  reflectConnection();

  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
  }

  let installPrompt = null;
  const installButtons = document.querySelectorAll('[data-install-pwa]');
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault(); installPrompt = event;
    installButtons.forEach((button) => { button.hidden = false; });
  });
  installButtons.forEach((button) => button.addEventListener('click', async () => {
    if (!installPrompt) {
      alert('On Android, open your browser menu and choose “Install app” or “Add to Home screen”.');
      return;
    }
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    installButtons.forEach((node) => { node.hidden = true; });
  }));

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm || 'Continue?')) event.preventDefault();
    });
  });

  const postLocation = async (latitude, longitude) => {
    const response = await fetch('/api/location', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CSRF || ''},
      body: JSON.stringify({latitude, longitude, consent: true})
    });
    if (!response.ok) throw new Error('Location could not be saved. Refresh the page and try again.');
    return response.json();
  };

  document.querySelectorAll('[data-location-search]').forEach((button) => {
    button.addEventListener('click', () => {
      const status = document.querySelector('[data-location-status]');
      if (!navigator.geolocation) { if (status) status.textContent = 'This browser does not support device location. Search by area instead.'; return; }
      button.disabled = true; button.textContent = 'Finding location…';
      if (status) status.textContent = 'Your browser will ask permission to use your location.';
      navigator.geolocation.getCurrentPosition(async (position) => {
        try {
          // The visitor has explicitly pressed “Use my location”. Browser permission is the consent gate.
          // Save only the approximate rounded location for the admin's consent-based analytics.
          await postLocation(position.coords.latitude, position.coords.longitude).catch(() => {});
          const url = new URL(window.location.href);
          url.pathname = '/homes';
          url.searchParams.set('lat', position.coords.latitude.toFixed(6));
          url.searchParams.set('lon', position.coords.longitude.toFixed(6));
          if (status) status.textContent = 'Location found. Showing nearby places first…';
          window.location.href = url.toString();
        } catch (error) {
          if (status) status.textContent = error.message || 'Could not use this location. Search by area instead.';
          button.disabled = false; button.textContent = 'Use my location';
        }
      }, (error) => {
        const messages = {1: 'Location permission was denied. Search by area instead.', 2: 'Your location is unavailable. Try again or search by area.', 3: 'Location request timed out. Try again.'};
        if (status) status.textContent = messages[error.code] || 'Location could not be read.';
        button.disabled = false; button.textContent = 'Use my location';
      }, {enableHighAccuracy: false, timeout: 20000, maximumAge: 120000});
    });
  });

  document.querySelectorAll('[data-share-visitor-location]').forEach((button) => {
    button.addEventListener('click', () => {
      const status = button.parentElement && button.parentElement.querySelector('[data-location-status]');
      if (!navigator.geolocation) { if (status) status.textContent = 'This browser does not support device location.'; return; }
      const accepted = window.confirm('Share your approximate location for site analytics? The site stores a rounded area for this visit that authorized administrators can see. Your choice is optional.');
      if (!accepted) { if (status) status.textContent = 'No location shared.'; return; }
      button.disabled = true; button.textContent = 'Finding location…';
      navigator.geolocation.getCurrentPosition(async (position) => {
        try {
          await postLocation(position.coords.latitude, position.coords.longitude);
          if (status) status.textContent = 'Approximate area shared. You can continue using the site.';
          button.textContent = 'Location shared';
        } catch (error) {
          if (status) status.textContent = error.message || 'Could not save location.';
          button.disabled = false; button.textContent = 'Share my approximate location';
        }
      }, (error) => {
        if (status) status.textContent = error.code === 1 ? 'Permission denied. No location was shared.' : 'Could not read location. Try again later.';
        button.disabled = false; button.textContent = 'Share my approximate location';
      }, {enableHighAccuracy: false, timeout: 12000, maximumAge: 60000});
    });
  });

  document.querySelectorAll('[data-directions-panel]').forEach((panel) => {
    const mode = panel.querySelector('[data-route-origin-mode]');
    const originInput = panel.querySelector('[data-route-origin-place]');
    const goButton = panel.querySelector('[data-route-go]');
    const status = panel.querySelector('[data-route-status]');
    const destination = panel.dataset.destination;
    const preview = panel.querySelector('[data-route-map-preview]');
    const frame = panel.querySelector('[data-route-map-frame]');
    const openLink = panel.querySelector('[data-route-open]');
    const syncMode = () => { if (originInput) originInput.hidden = !mode || mode.value !== 'place'; };
    if (mode) { mode.addEventListener('change', syncMode); syncMode(); }
    if (!goButton || !destination) return;

    const showRoute = (origin, originLabel) => {
      const embed = 'https://maps.google.com/maps?saddr=' + encodeURIComponent(origin) + '&daddr=' + encodeURIComponent(destination) + '&output=embed';
      const route = 'https://www.google.com/maps/dir/?api=1&origin=' + encodeURIComponent(origin) + '&destination=' + encodeURIComponent(destination) + '&travelmode=driving';
      if (frame) frame.src = embed;
      if (preview) preview.hidden = false;
      if (openLink) openLink.href = route;
      if (status) status.textContent = 'Route from ' + originLabel + ' to this property. Use the full directions link for turn-by-turn navigation.';
      goButton.disabled = false;
      goButton.textContent = 'Update route';
    };

    goButton.addEventListener('click', () => {
      if (mode && mode.value === 'place') {
        const origin = (originInput && originInput.value || '').trim();
        if (!origin) { if (status) status.textContent = 'Enter a starting place, estate or landmark.'; originInput && originInput.focus(); return; }
        showRoute(origin, origin);
        return;
      }
      if (!navigator.geolocation) { if (status) status.textContent = 'This browser does not support device location. Choose a starting place instead.'; return; }
      goButton.disabled = true; goButton.textContent = 'Finding your location…';
      if (status) status.textContent = 'Allow location access in your browser to draw the route from here.';
      navigator.geolocation.getCurrentPosition((position) => {
        const origin = position.coords.latitude.toFixed(6) + ',' + position.coords.longitude.toFixed(6);
        showRoute(origin, 'your current location');
      }, (error) => {
        if (status) status.textContent = error.code === 1 ? 'Location permission denied. Choose a starting place instead.' : 'Could not read location. Choose a starting place instead.';
        goButton.disabled = false; goButton.textContent = 'Draw route to this place';
      }, {enableHighAccuracy: false, timeout: 20000, maximumAge: 120000});
    });
  });

  document.querySelectorAll('[data-copy-url]').forEach((button) => {
    button.addEventListener('click', async () => {
      const value = button.getAttribute('data-copy-url') || window.location.origin + '/';
      const initialText = button.textContent;
      try {
        await navigator.clipboard.writeText(value);
        button.textContent = 'Link copied';
        button.setAttribute('aria-live', 'polite');
        window.setTimeout(() => { button.textContent = initialText; }, 1800);
      } catch (_) {
        window.prompt('Copy this invite link:', value);
      }
    });
  });

  const propertyLocationButton = document.querySelector('[data-property-location]');
  if (propertyLocationButton) {
    propertyLocationButton.addEventListener('click', () => {
      const status = document.querySelector('[data-property-location-status]');
      if (!navigator.geolocation) { if (status) status.textContent = 'This browser does not support device location.'; return; }
      if (status) status.textContent = 'Use only when physically at the property or setting its known pin. Waiting for permission…';
      propertyLocationButton.disabled = true;
      navigator.geolocation.getCurrentPosition((position) => {
        const lat = document.getElementById('latitudeInput');
        const lon = document.getElementById('longitudeInput');
        if (lat) lat.value = position.coords.latitude.toFixed(6);
        if (lon) lon.value = position.coords.longitude.toFixed(6);
        if (status) status.textContent = 'Coordinates filled. Confirm they point to the actual property before saving.';
        propertyLocationButton.disabled = false;
      }, (error) => {
        if (status) status.textContent = error.code === 1 ? 'Permission denied. You can type known coordinates manually.' : 'Could not read location. Type known coordinates manually.';
        propertyLocationButton.disabled = false;
      }, {enableHighAccuracy: true, timeout: 12000, maximumAge: 10000});
    });
  }
})();
