/**
 * Cookie-authenticated notifications WebSocket.
 * URL is derived from window.location (never hardcode 127.0.0.1).
 */

function wsNotificationsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
  // If VITE_API_BASE_URL is absolute, derive WS from it; else same-origin /api/v1/ws/...
  if (/^https?:\/\//i.test(base)) {
    const u = new URL(base);
    const wsProto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProto}//${u.host}/api/v1/ws/notifications`;
  }
  return `${proto}//${host}/api/v1/ws/notifications`;
}

/**
 * @param {{
 *   onHello?: (msg: { items: any[], unreadCount: number }) => void,
 *   onNotification?: (msg: { item: any, unreadCount?: number }) => void,
 *   onClose?: () => void,
 *   onError?: (err: Event) => void,
 * }} handlers
 * @returns {{ close: () => void }}
 */
export function connectNotificationsWs(handlers = {}) {
  let ws = null;
  let closed = false;
  let retryMs = 1500;
  let timer = null;

  const connect = () => {
    if (closed) return;
    try {
      ws = new WebSocket(wsNotificationsUrl());
    } catch (err) {
      handlers.onError?.(err);
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      retryMs = 1500;
    };

    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg?.type === 'hello') {
        handlers.onHello?.(msg);
      } else if (msg?.type === 'notification') {
        handlers.onNotification?.(msg);
      }
    };

    ws.onerror = (ev) => {
      handlers.onError?.(ev);
    };

    ws.onclose = (ev) => {
      handlers.onClose?.(ev);
      ws = null;
      if (closed) return;
      // 1008 = auth/policy — back off harder so Vite proxy isn't spammed
      if (ev?.code === 1008) {
        retryMs = Math.max(retryMs, 30_000);
      }
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closed || timer) return;
    timer = window.setTimeout(() => {
      timer = null;
      retryMs = Math.min(retryMs * 1.5, 45_000);
      connect();
    }, retryMs);
  };

  connect();

  return {
    close() {
      closed = true;
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
      ws = null;
    },
  };
}
