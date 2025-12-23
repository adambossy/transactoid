from __future__ import annotations

from collections.abc import Callable
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import ssl
import threading
from typing import Any, Protocol, cast
import urllib.parse
import uuid
import webbrowser


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


def _create_ssl_context() -> ssl.SSLContext:
    """Create an SSL context for the local Plaid redirect HTTPS server.

    The certificate is checked into source control; the private key is expected
    to exist only on the local filesystem and should not be committed.
    """
    project_root = Path(__file__).resolve().parents[1]
    cert_path = project_root / "configs" / "plaid_redirect_localhost.crt"
    default_key_path = project_root / "configs" / "plaid_redirect_localhost.key"
    key_path = Path(os.getenv("PLAID_REDIRECT_SSL_KEY_PATH", str(default_key_path)))

    if not cert_path.is_file():
        raise RedirectServerError(
            f"Missing SSL certificate file for Plaid redirect server: {cert_path}"
        )
    if not key_path.is_file():
        raise RedirectServerError(
            "Missing SSL private key for Plaid redirect server. "
            f"Expected key at: {key_path}. "
            "Generate a private key that matches the checked-in certificate "
            "and ensure it remains untracked (see .gitignore)."
        )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context


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

    server_address: tuple[str, int] = cast(tuple[str, int], server.server_address)
    actual_host, actual_port = server_address
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


def setup_redirect_server(
    *,
    token_queue: queue.Queue[str],
    state: dict[str, Any],
) -> tuple[ThreadingHTTPServer, threading.Thread, str] | None:
    """Set up the HTTPS redirect server for Plaid Link.

    Returns:
        Tuple of (server, server_thread, redirect_uri) on success, None on error.
    """
    redirect_path = "/plaid-link-complete"
    try:
        server, server_thread, actual_host, actual_port = start_redirect_server(
            host="localhost",
            port=8443,
            path=redirect_path,
            token_queue=token_queue,
            state=state,
        )
        redirect_uri = f"https://{actual_host}:{actual_port}{redirect_path}"
        # Ensure we use 'localhost' instead of '127.0.0.1' to match Plaid
        # allowlists commonly set to localhost.
        if actual_host == "127.0.0.1":
            redirect_uri = f"https://localhost:{actual_port}{redirect_path}"
        return server, server_thread, redirect_uri
    except (RedirectServerError, OSError):
        return None


class CreateLinkTokenFn(Protocol):
    """Protocol for create_link_token function signature."""

    def __call__(
        self,
        *,
        user_id: str,
        redirect_uri: str | None = None,
        products: list[str] | None = None,
        country_codes: list[str] | None = None,
        client_name: str | None = None,
    ) -> str: ...


class GetItemInfoFn(Protocol):
    """Protocol for get_item_info function signature."""

    def __call__(self, __access_token: str, /) -> dict[str, Any]: ...


def create_link_token_and_url(
    *,
    redirect_uri: str,
    state: dict[str, Any],
    create_link_token_fn: CreateLinkTokenFn,
    client_name: str,
) -> str:
    """Create a Plaid Link token and build the Link URL.

    Args:
        redirect_uri: Redirect URI for Plaid Link
        state: State dict to store link_token
        create_link_token_fn: Function to create link token
        client_name: Client name for Plaid Link

    Returns:
        Link URL string
    """
    user_id = f"transactoid-user-{uuid.uuid4()}"
    link_token = create_link_token_fn(
        user_id=user_id,
        redirect_uri=redirect_uri,
        products=["transactions"],
        country_codes=["US"],
        client_name=client_name,
    )
    state["link_token"] = link_token

    link_url = (
        "https://cdn.plaid.com/link/v2/stable/link.html?token="
        + urllib.parse.quote(link_token, safe="")
    )
    return link_url


def open_link_in_browser(link_url: str) -> dict[str, Any] | None:
    """Open Plaid Link URL in the user's browser.

    Returns:
        Error dict if browser couldn't be opened, None on success.
    """
    opened = webbrowser.open(link_url, new=1)
    if not opened:
        return {
            "status": "error",
            "message": (
                "Unable to open browser automatically. "
                f"Please open this URL manually: {link_url}"
            ),
        }
    return None


def wait_for_public_token_safe(
    *,
    token_queue: queue.Queue[str],
    timeout_seconds: int,
) -> str | None:
    """Wait for public token from Plaid Link.

    Returns:
        Public token string on success, None on timeout.
    """
    try:
        return wait_for_public_token(
            token_queue,
            timeout_seconds=timeout_seconds,
        )
    except PublicTokenTimeoutError:
        return None


def exchange_token_and_get_item_info(
    *,
    public_token: str,
    exchange_public_token_fn: Callable[[str], dict[str, Any]],
    get_item_info_fn: GetItemInfoFn,
) -> dict[str, Any] | None:
    """Exchange public token for access token and get item info.

    Args:
        public_token: Public token from Plaid Link
        exchange_public_token_fn: Function to exchange public token
        get_item_info_fn: Function to get item info

    Returns:
        Dict with access_token, item_id, institution_name, institution_id
        on success, None on error.
    """
    try:
        exchange_response = exchange_public_token_fn(public_token)
        access_token = exchange_response.get("access_token")
        item_id = exchange_response.get("item_id")

        if not access_token or not item_id:
            return None

        institution_name: str | None = None
        institution_id: str | None = None

        try:
            item_info = get_item_info_fn(access_token)
            institution_name = item_info.get("institution_name")
            institution_id = item_info.get("institution_id")
        except Exception:  # noqa: S110
            # Non-fatal: continue without institution info
            pass

        return {
            "access_token": access_token,
            "item_id": item_id,
            "institution_name": institution_name,
            "institution_id": institution_id,
        }
    except Exception:
        return None


def save_item_to_database(
    *,
    db: Any,
    item_id: str,
    access_token: str,
    institution_id: str | None,
    institution_name: str | None,
) -> dict[str, Any] | None:
    """Save Plaid item to database.

    Returns:
        Error dict on failure, None on success.
    """
    try:
        db.save_plaid_item(
            item_id=item_id,
            access_token=access_token,
            institution_id=institution_id,
            institution_name=institution_name,
        )
        return None
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to save Plaid item to database: {e}",
            "item_id": item_id,
        }


def build_success_message(
    *,
    item_id: str,
    institution_name: str | None,
) -> str:
    """Build success message for account connection.

    Returns:
        Human-readable success message string.
    """
    base_msg = "Successfully connected account"
    institution_part = f" from {institution_name}" if institution_name else ""
    item_part = f" (item_id={item_id[:8]}...)."
    return base_msg + institution_part + item_part
