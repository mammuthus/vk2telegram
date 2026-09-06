import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import logging


log = logging.getLogger(__name__)


class RelayMetrics(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.relay_up = 0
        self.longpoll_connected = 0
        self.last_event_timestamp = 0
        self.last_success_timestamp = 0
        self.vk_errors = {}
        self.manual_action_code = None
        self.last_error_timestamp = 0
        self.forwarded_messages = 0
        self.blocked_messages = 0
        self.forward_errors = {}
        self.last_forward_timestamp = 0

    def set_relay_up(self, value):
        with self.lock:
            self.relay_up = int(bool(value))

    def set_longpoll_connected(self, value):
        with self.lock:
            self.longpoll_connected = int(bool(value))

    def longpoll_response(self):
        with self.lock:
            self.last_success_timestamp = time.time()

    def incoming_event(self):
        with self.lock:
            self.last_event_timestamp = time.time()

    def vk_error(self, code):
        with self.lock:
            code = str(code or 'unknown')
            self.vk_errors[code] = self.vk_errors.get(code, 0) + 1

    def load_manual_action_state(self):
        from data.models import RelayState

        try:
            state = RelayState.objects.filter(pk=1).first()
        except Exception:
            log.exception('Unable to load persistent VK manual-action state')
            return
        with self.lock:
            self.manual_action_code = state.manual_action_code if state else None
            self.last_error_timestamp = state.manual_action_timestamp if state and state.manual_action_timestamp else 0

    def set_manual_action(self, code):
        from data.models import RelayState

        timestamp = time.time()
        try:
            RelayState.objects.update_or_create(
                pk=1,
                defaults={'manual_action_code': str(code), 'manual_action_timestamp': timestamp},
            )
        except Exception:
            log.exception('Unable to persist VK manual-action state')
            return False
        with self.lock:
            self.manual_action_code = str(code)
            self.last_error_timestamp = timestamp
        return True

    def clear_manual_action(self):
        with self.lock:
            if not self.manual_action_code:
                return
        from data.models import RelayState

        try:
            RelayState.objects.filter(pk=1).update(
                manual_action_code=None,
                manual_action_timestamp=None,
            )
        except Exception:
            log.exception('Unable to clear persistent VK manual-action state')
            return
        with self.lock:
            self.manual_action_code = None
            self.last_error_timestamp = 0

    def forwarded_message(self):
        with self.lock:
            self.forwarded_messages += 1
            self.last_forward_timestamp = time.time()

    def blocked_message(self):
        with self.lock:
            self.blocked_messages += 1

    def forward_error(self, error_type):
        with self.lock:
            error_type = str(error_type or 'unknown')
            self.forward_errors[error_type] = self.forward_errors.get(error_type, 0) + 1

    def render(self):
        with self.lock:
            lines = [
                '# TYPE tgvk_relay_up gauge',
                'tgvk_relay_up {}'.format(self.relay_up),
                '# TYPE tgvk_vk_longpoll_connected gauge',
                'tgvk_vk_longpoll_connected {}'.format(self.longpoll_connected),
                '# TYPE tgvk_vk_last_event_timestamp_seconds gauge',
                'tgvk_vk_last_event_timestamp_seconds {:.3f}'.format(self.last_event_timestamp),
                '# TYPE tgvk_vk_last_success_timestamp_seconds gauge',
                'tgvk_vk_last_success_timestamp_seconds {:.3f}'.format(self.last_success_timestamp),
                '# TYPE tgvk_vk_errors_total counter',
                '# TYPE tgvk_vk_manual_action_required gauge',
                '# TYPE tgvk_vk_last_error_timestamp_seconds gauge',
                'tgvk_vk_last_error_timestamp_seconds {:.3f}'.format(self.last_error_timestamp),
                '# TYPE tgvk_forwarded_messages_total counter',
                'tgvk_forwarded_messages_total {}'.format(self.forwarded_messages),
                '# TYPE tgvk_blocked_messages_total counter',
                'tgvk_blocked_messages_total {}'.format(self.blocked_messages),
                '# TYPE tgvk_forward_errors_total counter',
                '# TYPE tgvk_last_forward_timestamp_seconds gauge',
                'tgvk_last_forward_timestamp_seconds {:.3f}'.format(self.last_forward_timestamp),
            ]
            lines.extend('tgvk_vk_errors_total{{code="{}"}} {}'.format(code, count)
                         for code, count in sorted(self.vk_errors.items()))
            if self.manual_action_code:
                lines.append('tgvk_vk_manual_action_required{{code="{}"}} 1'.format(self.manual_action_code))
            lines.extend('tgvk_forward_errors_total{{type="{}"}} {}'.format(error_type, count)
                         for error_type, count in sorted(self.forward_errors.items()))
        return '\n'.join(lines) + '\n'


metrics = RelayMetrics()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        body = metrics.render().encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def start_metrics_server(host='0.0.0.0', port=9102):
    server = HTTPServer((host, port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    metrics.set_relay_up(True)
    return server