// firebase-messaging-sw.js
// Este archivo DEBE estar en la raíz del servidor (mismo nivel que frontend.html)

importScripts('https://www.gstatic.com/firebasejs/9.23.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.23.0/firebase-messaging-compat.js');

firebase.initializeApp({
    apiKey:            "AIzaSyD8MhMCOUPIlHd8AK-F_eFiVdyDGKOpy0U",
    authDomain:        "altoyclaro-tfg.firebaseapp.com",
    projectId:         "altoyclaro-tfg",
    storageBucket:     "altoyclaro-tfg.firebasestorage.app",
    messagingSenderId: "800858574197",
    appId:             "1:800858574197:android:d83a20422a6cdb9104173c"
});

const messaging = firebase.messaging();

// Mostrar notificación cuando la app está en background
messaging.onBackgroundMessage(function(payload) {
    console.log('[SW] Notificación recibida en background:', payload);
    const notif = payload.notification || {};
    self.registration.showNotification(notif.title || 'Alto y Claro', {
        body:  notif.body  || '¿Cómo estás ahora mismo?',
        icon:  '/icon.png',
        badge: '/icon.png',
        data:  payload.data || {}
    });
});

// Al hacer click en la notificación, abrir la app
self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
            for (const client of clientList) {
                if ('focus' in client) return client.focus();
            }
            if (clients.openWindow) return clients.openWindow('/');
        })
    );
});