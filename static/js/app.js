(() => {
  const menuButton = document.querySelector('[data-menu-toggle]');
  const nav = document.querySelector('[data-nav]');
  if (menuButton && nav) {
    menuButton.addEventListener('click', () => {
      const opened = nav.classList.toggle('open');
      menuButton.setAttribute('aria-expanded', String(opened));
      menuButton.setAttribute('aria-label', opened ? 'Close navigation' : 'Open navigation');
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
      if (!navigator.geolocation) { if (status) status.textContent = 'This browser does not support device location.'; return; }
      const accepted = window.confirm('Share your approximate location for nearby-place sorting? The platform stores a rounded area for this visit, visible to authorized administrators. You can cancel and search by area instead.');
      if (!accepted) { if (status) status.textContent = 'No location shared. You can search by town or estate instead.'; return; }
      button.disabled = true; button.textContent = 'Finding location…';
      if (status) status.textContent = 'Waiting for your device permission…';
      navigator.geolocation.getCurrentPosition(async (position) => {
        try {
          await postLocation(position.coords.latitude, position.coords.longitude);
          const url = new URL(window.location.href);
          url.pathname = '/homes';
          url.searchParams.set('lat', position.coords.latitude);
          url.searchParams.set('lon', position.coords.longitude);
          if (status) status.textContent = 'Location shared. Sorting results nearby…';
          window.location.href = url.toString();
        } catch (error) {
          if (status) status.textContent = error.message || 'Could not save location.';
          button.disabled = false; button.textContent = 'Use my location';
        }
      }, (error) => {
        const messages = {1: 'Location permission was denied. You can search by area instead.', 2: 'Your location is unavailable. Try again or search by area.', 3: 'Location request timed out. Try again.'};
        if (status) status.textContent = messages[error.code] || 'Location could not be read.';
        button.disabled = false; button.textContent = 'Use my location';
      }, {enableHighAccuracy: false, timeout: 12000, maximumAge: 60000});
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
    const syncMode = () => { if (originInput) originInput.hidden = !mode || mode.value !== 'place'; };
    if (mode) { mode.addEventListener('change', syncMode); syncMode(); }
    if (!goButton || !destination) return;
    goButton.addEventListener('click', () => {
      if (!mode || mode.value === 'place') {
        const origin = (originInput && originInput.value || '').trim();
        if (!origin) { if (status) status.textContent = 'Enter a starting place, such as Nairobi CBD or Westlands.'; originInput && originInput.focus(); return; }
        const route = 'https://www.google.com/maps/dir/?api=1&origin=' + encodeURIComponent(origin) + '&destination=' + encodeURIComponent(destination) + '&travelmode=driving';
        window.open(route, '_blank', 'noopener');
        if (status) status.textContent = 'Opening the route from ' + origin + ' to the property in Maps.';
        return;
      }
      if (!navigator.geolocation) { if (status) status.textContent = 'This browser does not support device location. Choose a starting place instead.'; return; }
      const tab = window.open('about:blank', '_blank');
      if (!tab) { if (status) status.textContent = 'Allow pop-ups to open the route, or choose a starting place instead.'; return; }
      goButton.disabled = true; goButton.textContent = 'Finding your location…';
      navigator.geolocation.getCurrentPosition((position) => {
        const origin = position.coords.latitude + ',' + position.coords.longitude;
        const route = 'https://www.google.com/maps/dir/?api=1&origin=' + encodeURIComponent(origin) + '&destination=' + encodeURIComponent(destination) + '&travelmode=driving';
        tab.location.href = route;
        if (status) status.textContent = 'Your current location is being used only to open the route in Maps; it is not submitted to site visitor analytics by this directions action.';
        goButton.disabled = false; goButton.textContent = 'Open route in Maps ↗';
      }, (error) => {
        tab.close();
        if (status) status.textContent = error.code === 1 ? 'Location permission denied. Choose a starting place instead.' : 'Could not read location. Choose a starting place instead.';
        goButton.disabled = false; goButton.textContent = 'Open route in Maps ↗';
      }, {enableHighAccuracy: false, timeout: 12000, maximumAge: 60000});
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
