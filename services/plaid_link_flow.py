from __future__ import annotations

import json
import queue
import ssl
import tempfile
import threading
import urllib.parse
from contextlib import suppress
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class PlaidLinkError(Exception):
    """Base error for Plaid Link redirect server failures."""


class RedirectServerError(PlaidLinkError):
    """Raised when the local redirect server cannot be started."""


class PublicTokenTimeoutError(PlaidLinkError):
    """Raised when we time out waiting for a Plaid public_token."""


REDIRECT_SUCCESS_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Plaid Link Complete</title>
  <style>
    body { font-family: sans-serif; margin: 3rem; }
    .card {
      max-width: 32rem;
      padding: 2rem;
      border: 1px solid #ccc;
      border-radius: 0.5rem;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Link successful</h1>
    <p>You can return to the terminal. This window can be closed.</p>
  </div>
</body>
</html>
"""

REDIRECT_ERROR_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Plaid Link Error</title>
  <style>
    body { font-family: sans-serif; margin: 3rem; color: #941a1d; }
    .card {
      max-width: 32rem;
      padding: 2rem;
      border: 1px solid #f5a9ab;
      border-radius: 0.5rem;
      background: #fff5f5;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>Link failed</h1>
    <p>The CLI did not receive a Plaid public_token.</p>
    <p>Please review the terminal output.</p>
  </div>
</body>
</html>
"""

OAUTH_REDIRECT_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Completing Plaid Link...</title>
  <style>
    body {{ font-family: sans-serif; margin: 3rem; }}
    .card {{
      max-width: 32rem;
      padding: 2rem;
      border: 1px solid #ccc;
      border-radius: 0.5rem;
    }}
  </style>
  <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
</head>
<body>
  <div class="card" id="status">
    <h1>Finishing connection...</h1>
    <p>Please wait a moment while we complete the Plaid Link flow.</p>
  </div>
  <script>
    (function() {{
      var handler = Plaid.create({{
        token: "{link_token}",
        receivedRedirectUri: window.location.href,
        onSuccess: function(public_token, metadata) {{
          fetch(window.location.pathname, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ public_token: public_token }})
          }}).then(function() {{
            document.body.innerHTML = `{success_html}`;
          }}).catch(function() {{
            document.body.innerHTML = `{error_html}`;
          }});
        }},
        onExit: function(err, metadata) {{
          document.body.innerHTML = `{error_html}`;
        }}
      }});

      handler.open();
    }})();
  </script>
</body>
</html>
"""

LOCALHOST_CERT_PEM = """\
-----BEGIN CERTIFICATE-----
MIICpDCCAYwCCQDeylxbozqsWDANBgkqhkiG9w0BAQsFADAUMRIwEAYDVQQDDAls
b2NhbGhvc3QwHhcNMjUxMTI2MDIwODI4WhcNMzUxMTI0MDIwODI4WjAUMRIwEAYD
VQQDDAlsb2NhbGhvc3QwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDZ
9suqHgb2P7Q7+tEjjQuhel7MaVp/RLM2j4QfRs46CJguZtiim2h/BI0OpYx8r7Km
i2uTZqjpHa8iU5vwBAz90X6Q4ACZm50opKBDxHyP/Hyy4JKMvr0iqy5n1IOQamtQ
BctJA69jAoHKgTL+Ciz2Ul0vcYjTaUX+9jizoatYJbbA+uM/SgFGBhOmcefo11QE
Fv74PbVy3QQwJu3QTbPVQkDud0X8wi8q0jDbGQw3gwuolHgGmZ4/44D1X6d1O2Z/
78JJ/ZyaCcsU2lzUSXcY/+wVVsXJJEkl/u/S4GED7bVy3xrHqksrALfE+v6H/rq8
hj1sWlLAxPc3M7BC7AGNAgMBAAEwDQYJKoZIhvcNAQELBQADggEBAFTrs/cT4hQA
noCiQmUTTJSpz5+ZUYTcffJoueGUnbtPJJdO3s8va6GtOaYR3Vx2jwfWShUBJWbS
mANm21wWIN0pD8VCB6W18C4F704hOJk2nJn7tY+d1jsEQxkCVeaaHwWXlslzwbRV
vzNmQCWuwp0hzWYjQmXS94iV3oD2dXS6J+CaMMBcsVaxAWYx99wzJ06DefNPzqSC
RchRcw+hrXLzOl0Faim2s1eMm2HG+RPVwfOP4FLvFlnNVva/qP60j7X9krzNRY3f
cxVGVeJQy6yb7uMBGjAqXlDDQITuO7nPjHjnNJHrthk0wcYXPplD2DYp6akF4+El
wP9ZmW2p9Ww=
-----END CERTIFICATE-----
"""

LOCALHOST_KEY_PEM = """\
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDZ9suqHgb2P7Q7
+tEjjQuhel7MaVp/RLM2j4QfRs46CJguZtiim2h/BI0OpYx8r7Kmi2uTZqjpHa8i
U5vwBAz90X6Q4ACZm50opKBDxHyP/Hyy4JKMvr0iqy5n1IOQamtQBctJA69jAoHK
gTL+Ciz2Ul0vcYjTaUX+9jizoatYJbbA+uM/SgFGBhOmcefo11QEFv74PbVy3QQw
Ju3QTbPVQkDud0X8wi8q0jDbGQw3gwuolHgGmZ4/44D1X6d1O2Z/78JJ/ZyaCcsU
2lzUSXcY/+wVVsXJJEkl/u/S4GED7bVy3xrHqksrALfE+v6H/rq8hj1sWlLAxPc3
M7BC7AGNAgMBAAECggEBAJhK30zSxCyEoEsUWdKMN2cxWFFc/1VTTCDAMCGmWGum
G6a4R39+NIojROfJ9hocrSe+3IBWR4jyK69BWgBe5DDokpVpXiH1395JAI25GQuF
8B8P2HWsw/wYPUlg7DgYkziLg9lVUNNOKh+zHEzyES5eqCuBGYgV00ltAntIZ68j
CKvG8bBB7wgl5Gfy6ZWTatgyqbMZqrS9w/drga3JbmG5yOv6dahqtBxZdpe2eoxn
uTlaCnEscTkpXe6+Tga2rkTnCpu5G/CVdyPIR9AIUunvzBR7/JSbJLBfLD+ZO6bi
H1Een1YpifZsGEB9hozBZO7jDEOlFUUfEF+2McPsgGUCgYEA7q1pj23hMz+Tqvk/
21CA2McLJ146CWJyHxzQyZlYaDPSYSHuXninY3LvBwF+reJiR8cbMxQGEDHL1VWP
41TlNCNm1ahKGc0gdiE3xHPzKHbNFgEG40t7d+3Jaj9DEf+PUdmYR7dfTUCs7WNz
lSBp0jxRVnJ0eq/rIKa0sQrK+bMCgYEA6ciIVcjnD8ryRkAanxx7tmrUoTvzPJ5T
wcOfcIOIQrq+q5yjSG4ag2dDCB7ujl+Ut3astbKtH8m0aJBuMy8QZHHOMHJ5JwET
Q1WTJ/yCoq513h9nSWTgteruRBEpCgc3MS5iZoMGOJEVfZLjx5rezRgR/8n+1xM8
e1li3L8w978CgYEAn+k1sXA4EwMEp+epPgJ44USyl2TNU55OwcOnq3p/PgmCaau3
Ljp+Q+YsebAptMzZdifTdGx1B4Klg8B40CIAEuepLXs8cn75wcvNtmTNRI4cKCL1
/3GCPr7lVLcf874awwcbvOkCBBtSARbByOdXnxDkmhvDKLQWv+CRbZDCn3sCgYBY
ZSaHqSsU4ZuxzFNEjjSIyOQVAuH5rbPls935YQKImKu3n8ZtgJQt00GZNHjnBGTq
6chr+19SgaXhU5sXZ1g/YnigAOimQtXRw+2cVPHgKS8QCbe4HJiKsIXe3s4xqIDJ
68vxDuGvScxiasQNmRVdXxiPKwVctT1NNoMXDIOraQKBgAncmTe110ZLbwcmr7hy
2G/p3enMQ3j9a+m19bfApBX7k6TvqjNpCWgsMApDYJ3JnfaO/uo97Q3kFCIq85RD
stvFJgSsRGtjLwDOP6YRycOZV2iheMtx8nuV47nASY+YQSdo82xffssULgb6O71r
8ouYXQsQ+s7TxA+Io2km671D
-----END PRIVATE KEY-----
"""


def _create_ssl_context() -> ssl.SSLContext:
    cert_file = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    key_file = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    try:
        cert_file.write(LOCALHOST_CERT_PEM)
        cert_file.flush()
        key_file.write(LOCALHOST_KEY_PEM)
        key_file.flush()

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)
        return context
    finally:
        cert_file.close()
        key_file.close()
        with suppress(FileNotFoundError):
            os.unlink(cert_file.name)
        with suppress(FileNotFoundError):
            os.unlink(key_file.name)


def _build_redirect_handler(
    token_queue: queue.Queue[str],
    expected_path: str,
    state: dict[str, Any],
):
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != expected_path:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            params = urllib.parse.parse_qs(parsed.query)
            public_token = params.get("public_token", [None])[0]

            # Non-OAuth institutions may return public_token directly.
            if public_token:
                token_queue.put(public_token)
                body = REDIRECT_SUCCESS_HTML
                status = HTTPStatus.OK
            else:
                link_token = state.get("link_token")
                if not link_token:
                    body = REDIRECT_ERROR_HTML
                    status = HTTPStatus.SERVICE_UNAVAILABLE
                else:
                    body = OAUTH_REDIRECT_HTML_TEMPLATE.format(
                        link_token=html_escape(str(link_token)),
                        success_html=REDIRECT_SUCCESS_HTML,
                        error_html=REDIRECT_ERROR_HTML,
                    )
                    status = HTTPStatus.OK

            body_bytes = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != expected_path:
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0

            raw_body = self.rfile.read(content_length).decode("utf-8")
            public_token: str | None = None
            if raw_body:
                try:
                    data = json.loads(raw_body)
                    public_token = data.get("public_token")
                except json.JSONDecodeError:
                    public_token = raw_body.strip() or None

            if public_token:
                token_queue.put(public_token)
                body = REDIRECT_SUCCESS_HTML
                status = HTTPStatus.OK
            else:
                body = REDIRECT_ERROR_HTML
                status = HTTPStatus.BAD_REQUEST

            body_bytes = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            # Silence default stdout logging to keep CLI output clean.
            return

    return RedirectHandler


def start_redirect_server(
    *,
    host: str,
    port: int,
    path: str,
    token_queue: queue.Queue[str],
    state: dict[str, Any],
) -> tuple[ThreadingHTTPServer, threading.Thread, str, int]:
    """Start the HTTPS redirect server for Plaid Link."""
    handler_cls = _build_redirect_handler(token_queue, path, state)
    server = ThreadingHTTPServer((host, port), handler_cls)
    ssl_context = _create_ssl_context()
    server.socket = ssl_context.wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(
        target=server.serve_forever,
        name="PlaidRedirectServer",
        daemon=True,
    )
    thread.start()

    actual_host, actual_port = server.server_address
    return server, thread, actual_host, actual_port


def wait_for_public_token(
    token_queue: queue.Queue[str],
    *,
    timeout_seconds: int,
) -> str:
    """Block until a public_token is received or the timeout elapses."""
    try:
        return token_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        raise PublicTokenTimeoutError(
            "Timed out waiting for Plaid to redirect with a public_token."
        ) from None


def shutdown_redirect_server(
    server: ThreadingHTTPServer,
    server_thread: threading.Thread,
) -> None:
    """Stop the HTTPS redirect server."""
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=1)


