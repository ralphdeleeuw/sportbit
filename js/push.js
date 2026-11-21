    // push.js — Service worker-registratie en Web Push-abonnement.
    // Registreer service worker
    let swRegistration = null;
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sportbit/sw.js').then(reg => {
        swRegistration = reg;
      });
    }

    function _urlBase64ToUint8Array(base64String) {
      const padding = '='.repeat((4 - base64String.length % 4) % 4);
      const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
      const raw = atob(base64);
      return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
    }

    async function subscribeToPush() {
      if (!('Notification' in window) || !('PushManager' in window)) {
        showToast('Push notificaties worden niet ondersteund door deze browser.', { type: 'error' });
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        showToast('Notificatietoestemming geweigerd.', { type: 'error' });
        return;
      }
      if (!swRegistration) {
        swRegistration = await navigator.serviceWorker.ready;
      }
      try {
        const subscription = await swRegistration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: _urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
        });
        await _savePushSubscription(subscription);
        localStorage.setItem('huppa_push_subscribed', '1');
        renderActiesTab(null);
        showToast('Notificaties ingeschakeld! 🎉', { type: 'ok' });
      } catch (err) {
        console.error('Push subscribe mislukt:', err);
        showToast('Inschrijven voor notificaties mislukt: ' + err.message, { type: 'error', duration: 6000 });
      }
    }

    async function _savePushSubscription(subscription) {
      const token = document.getElementById('githubToken').value.trim();
      const gistId = currentGistId;
      if (!token || !gistId) throw new Error('GitHub token of Gist ID ontbreekt');
      await fetch(`https://api.github.com/gists/${gistId}`, {
        method: 'PATCH',
        headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: { 'push_subscription.json': { content: JSON.stringify(subscription.toJSON(), null, 2) } },
        }),
      }).then(r => { if (!r.ok) throw new Error(`Gist PATCH mislukt: ${r.status}`); });
    }

