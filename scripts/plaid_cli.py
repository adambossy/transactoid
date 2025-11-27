#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import suppress
import datetime as dt
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import queue
import ssl
import sys
import tempfile
import threading
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

PLAID_ENV_MAP: dict[str, str] = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}

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


def getenv_or_die(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def plaid_base_url() -> str:
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    base_url = PLAID_ENV_MAP.get(env)
    if not base_url:
        print(
            f"Invalid PLAID_ENV={env!r}. "
            "Expected one of: sandbox, development, production.",
            file=sys.stderr,
        )
        sys.exit(1)
    return base_url


def plaid_secret() -> str:
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    if env == "production":
        return getenv_or_die("PLAID_PRODUCTION_SECRET")
    if env == "development":
        return getenv_or_die("PLAID_DEVELOPMENT_SECRET")
    if env == "sandbox":
        return getenv_or_die("PLAID_SANDBOX_SECRET")
    raise ValueError(f"Invalid PLAID_ENV={env}")


def plaid_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = plaid_base_url().rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - Plaid API URL constructed above.
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 - Outbound HTTPS request.
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "ignore")
        print(f"Plaid API error ({e.code}): {err_body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Network error calling Plaid API: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        print(f"Failed to parse Plaid response as JSON: {e}", file=sys.stderr)
        print(f"Raw response: {body}", file=sys.stderr)
        sys.exit(1)


def plaid_create_link_token(
    *,
    user_id: str,
    redirect_uri: str,
    products: list[str],
    client_name: str = "transactoid",
    language: str = "en",
    country_codes: list[str] | None = None,
) -> str:
    """Create a Plaid Link token and return it."""
    client_id = getenv_or_die("PLAID_CLIENT_ID")
    secret = plaid_secret()

    payload: dict[str, Any] = {
        "client_id": client_id,
        "secret": secret,
        "client_name": client_name,
        "language": language,
        "country_codes": country_codes or ["US"],
        "user": {"client_user_id": user_id},
        "products": products,
        "redirect_uri": redirect_uri,
    }

    resp = plaid_post("/link/token/create", payload)
    link_token = resp.get("link_token")
    if not link_token:
        print(
            f"Unexpected response from /link/token/create: {resp}",
            file=sys.stderr,
        )
        sys.exit(1)
    return link_token


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


def _start_redirect_server(
    *,
    host: str,
    port: int,
    path: str,
    token_queue: queue.Queue[str],
    state: dict[str, Any],
) -> tuple[ThreadingHTTPServer, threading.Thread, str, int]:
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


def cmd_sandbox_link(args: argparse.Namespace) -> None:
    """Create a sandbox item, exchange its public_token for an access_token,
    and write it to a JSON file."""
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    if env != "sandbox":
        print(
            "The 'sandbox-link' command only works with PLAID_ENV=sandbox.",
            file=sys.stderr,
        )
        sys.exit(1)

    client_id = getenv_or_die("PLAID_CLIENT_ID")

    institution_id = args.institution_id
    output_path = args.output

    create_payload: dict[str, Any] = {
        "client_id": client_id,
        "secret": plaid_secret(),
        "institution_id": institution_id,
        "initial_products": ["transactions"],
    }
    create_resp = plaid_post("/sandbox/public_token/create", create_payload)
    public_token = create_resp.get("public_token")
    if not public_token:
        print(
            f"Unexpected response from /sandbox/public_token/create: {create_resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    exchange_payload = {
        "client_id": client_id,
        "secret": plaid_secret(),
        "public_token": public_token,
    }
    exchange_resp = plaid_post("/item/public_token/exchange", exchange_payload)
    access_token = exchange_resp.get("access_token")
    item_id = exchange_resp.get("item_id")

    if not access_token:
        print(
            f"Unexpected response from /item/public_token/exchange: {exchange_resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = {
        "access_token": access_token,
        "item_id": item_id,
        "created_at": dt.datetime.utcnow().isoformat() + "Z",
        "environment": env,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote sandbox access token to {output_path}")
    print("Access token (copy this somewhere secure):")
    print(access_token)


def cmd_exchange_public_token(args: argparse.Namespace) -> None:
    """Exchange a Plaid Link public_token for an access_token."""
    client_id = getenv_or_die("PLAID_CLIENT_ID")
    secret = plaid_secret()
    public_token = args.public_token

    payload = {
        "client_id": client_id,
        "secret": secret,
        "public_token": public_token,
    }

    resp = plaid_post("/item/public_token/exchange", payload)

    access_token = resp.get("access_token")
    item_id = resp.get("item_id")
    if not access_token:
        print(
            f"Unexpected response from /item/public_token/exchange: {resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = {
        "access_token": access_token,
        "item_id": item_id,
        "environment": os.getenv("PLAID_ENV", "sandbox").lower(),
        "created_at": dt.datetime.utcnow().isoformat() + "Z",
        "request_id": resp.get("request_id"),
        "expiration": resp.get("expiration"),
        "scope": resp.get("scope"),
    }

    output_path = args.output
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote access token details to {output_path}")

    print("Access token (copy this somewhere secure):")
    print(access_token)


def _parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def cmd_transactions(args: argparse.Namespace) -> None:
    """Fetch transactions for an existing access token and print them as JSON."""
    client_id = getenv_or_die("PLAID_CLIENT_ID")
    secret = plaid_secret()

    access_token = args.access_token or os.getenv("PLAID_ACCESS_TOKEN")
    if not access_token:
        print(
            "Access token not provided. Use --access-token or set PLAID_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    today = dt.date.today()
    start_date = (
        _parse_date(args.start_date)
        if args.start_date
        else today - dt.timedelta(days=30)
    )
    end_date = _parse_date(args.end_date) if args.end_date else today

    payload: dict[str, Any] = {
        "client_id": client_id,
        "secret": secret,
        "access_token": access_token,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "options": {
            "count": args.count,
            "offset": 0,
        },
    }

    resp = plaid_post("/transactions/get", payload)

    if args.raw:
        json.dump(resp, sys.stdout, indent=2)
        print()
        return

    transactions = resp.get("transactions", [])
    print(json.dumps(transactions, indent=2))
    print(f"\nTotal transactions returned: {len(transactions)}")


def _ensure_production_env() -> str:
    """Ensure PLAID_ENV is set to production and return its value."""
    env = os.getenv("PLAID_ENV")
    if env is None:
        env = "production"
        os.environ["PLAID_ENV"] = env
    env = env.lower()

    if env != "production":
        print(
            f"Warning: PLAID_ENV is set to {env!r}. This command is intended for "
            "production credentials.",
            file=sys.stderr,
        )
    return env


def _create_redirect_server_and_uri(
    args: argparse.Namespace,
    *,
    redirect_path: str,
    token_queue: queue.Queue[str],
    state: dict[str, Any],
) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Start the local HTTPS redirect server and return its URI."""
    try:
        server, server_thread, bound_host, bound_port = _start_redirect_server(
            host=args.host,
            port=args.port,
            path=redirect_path,
            token_queue=token_queue,
            state=state,
        )
    except OSError as e:
        print(
            "Failed to start the local redirect server on "
            f"{args.host}:{args.port}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    redirect_host = args.host or bound_host
    try:
        host_is_unspecified = ipaddress.ip_address(redirect_host).is_unspecified
    except ValueError:
        host_is_unspecified = redirect_host == ""
    if host_is_unspecified:
        redirect_host = "localhost"

    redirect_uri = f"https://{redirect_host}:{bound_port}{redirect_path}"
    print(
        "Ensure this redirect URI is allow-listed in Plaid dashboard settings:\n"
        f"  {redirect_uri}"
    )
    return server, server_thread, redirect_uri


def _create_link_url(
    *,
    env: str,
    user_id: str,
    redirect_uri: str,
    products: list[str],
    country_codes: list[str],
    client_name: str,
    language: str,
    state: dict[str, Any],
) -> str:
    """Create a Link token and return the hosted Link URL."""
    print(
        f"Creating Plaid Link token for user {user_id!r} in PLAID_ENV={env}.",
    )

    link_token = plaid_create_link_token(
        user_id=user_id,
        redirect_uri=redirect_uri,
        products=products,
        client_name=client_name,
        language=language,
        country_codes=country_codes,
    )
    state["link_token"] = link_token

    return "https://cdn.plaid.com/link/v2/stable/link.html?token=" + urllib.parse.quote(
        link_token, safe=""
    )


def _open_link_in_browser(link_url: str, redirect_uri: str) -> None:
    print(f"Listening for Plaid redirect on {redirect_uri}")
    print(
        "Your browser may warn about a self-signed certificate; "
        "bypass it once to continue."
    )
    print("Opening Plaid Link in your default browser...")
    opened = webbrowser.open(link_url, new=1)
    if not opened:
        print(
            "Unable to automatically open the browser. "
            "Open the following URL manually:",
            file=sys.stderr,
        )
        print(link_url)


def _wait_for_public_token(
    token_queue: queue.Queue[str],
    *,
    timeout_seconds: int,
) -> str:
    print(
        f"Waiting for Plaid Link to complete. Timeout: {timeout_seconds} seconds.",
    )
    try:
        return token_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        print(
            "Timed out waiting for Plaid to redirect with a public_token. "
            "Restart the command to try again.",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted before Plaid Link completed.", file=sys.stderr)
        sys.exit(1)


def _shutdown_redirect_server(
    server: ThreadingHTTPServer,
    server_thread: threading.Thread,
) -> None:
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=1)


def _emit_public_token_result(
    *,
    public_token: str,
    env: str,
    output_path: str | None,
) -> None:
    result = {
        "public_token": public_token,
        "environment": env,
        "received_at": dt.datetime.utcnow().isoformat() + "Z",
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote public token details to {output_path}")

    print("Plaid public_token received. You can now exchange it for an access token:")
    print("  scripts/plaid_cli.py exchange-public-token <public_token>")
    print("\nPublic token (copy securely):")
    print(public_token)


def cmd_link_production(args: argparse.Namespace) -> None:
    """Drive a production Plaid Link flow via the hosted web experience."""
    env = _ensure_production_env()

    redirect_path = "/plaid-link-complete"
    token_queue: queue.Queue[str] = queue.Queue()
    state: dict[str, Any] = {}

    server, server_thread, redirect_uri = _create_redirect_server_and_uri(
        args,
        redirect_path=redirect_path,
        token_queue=token_queue,
        state=state,
    )

    user_id = args.user_id or f"cli-user-{uuid.uuid4()}"
    products = args.products or ["transactions"]
    country_codes = args.country_codes or ["US"]

    try:
        link_url = _create_link_url(
            env=env,
            user_id=user_id,
            redirect_uri=redirect_uri,
            products=products,
            country_codes=country_codes,
            client_name=args.client_name,
            language=args.language,
            state=state,
        )

        _open_link_in_browser(link_url, redirect_uri)
        public_token = _wait_for_public_token(
            token_queue,
            timeout_seconds=args.timeout,
        )
    finally:
        _shutdown_redirect_server(server, server_thread)

    _emit_public_token_result(
        public_token=public_token,
        env=env,
        output_path=args.output,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simple Plaid CLI: sandbox link + transactions fetch.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sandbox_parser = subparsers.add_parser(
        "sandbox-link",
        help="Create a sandbox item and write its access token to a JSON file.",
    )
    sandbox_parser.add_argument(
        "--institution-id",
        default="ins_109508",
        help="Sandbox institution ID (default: ins_109508 - Chase Sandbox)",
    )
    sandbox_parser.add_argument(
        "--output",
        default="plaid_access_token.json",
        help="File path to write access token JSON (default: plaid_access_token.json)",
    )
    sandbox_parser.set_defaults(func=cmd_sandbox_link)

    exchange_parser = subparsers.add_parser(
        "exchange-public-token",
        help="Exchange a Plaid Link public token for an access token.",
    )
    exchange_parser.add_argument(
        "public_token",
        help="public_token returned by Plaid Link",
    )
    exchange_parser.add_argument(
        "--output",
        help="Optional file path to write the resulting access token as JSON.",
    )
    exchange_parser.set_defaults(func=cmd_exchange_public_token)

    prod_link_parser = subparsers.add_parser(
        "link-production",
        help=(
            "Launch Plaid Link in production using the hosted web flow and capture the "
            "public_token via a browser redirect."
        ),
    )
    prod_link_parser.add_argument(
        "--user-id",
        help="Value for Plaid client_user_id. Defaults to a random UUID.",
    )
    prod_link_parser.add_argument(
        "--client-name",
        default="transactoid",
        help="Label shown inside Plaid Link (default: transactoid).",
    )
    prod_link_parser.add_argument(
        "--language",
        default="en",
        help="Plaid Link language code (default: en).",
    )
    prod_link_parser.add_argument(
        "--product",
        dest="products",
        action="append",
        help=(
            "Plaid product to request (e.g., transactions). "
            "Repeat to request multiple products. Default: transactions."
        ),
    )
    prod_link_parser.add_argument(
        "--country-code",
        dest="country_codes",
        action="append",
        help="Country code to include (default: US). Repeat for multiple countries.",
    )
    prod_link_parser.add_argument(
        "--host",
        default="localhost",
        help=(
            "Host interface for the local HTTPS redirect server (default: localhost). "
            "Must match a redirect URI registered in Plaid."
        ),
    )
    prod_link_parser.add_argument(
        "--port",
        type=int,
        default=0,
        help=(
            "Port for the redirect server. Use 0 to choose a random open port "
            "(default: 0)."
        ),
    )
    prod_link_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for Plaid Link to complete (default: 300).",
    )
    prod_link_parser.add_argument(
        "--output",
        help="Optional path to save the received public_token JSON payload.",
    )
    prod_link_parser.set_defaults(func=cmd_link_production)

    tx_parser = subparsers.add_parser(
        "transactions",
        help="Fetch transactions for an access token over a date range.",
    )
    tx_parser.add_argument(
        "--access-token",
        help="Plaid access token. If omitted, uses PLAID_ACCESS_TOKEN env var.",
    )
    tx_parser.add_argument(
        "--start-date",
        help="Start date (YYYY-MM-DD). Default: 30 days ago.",
    )
    tx_parser.add_argument(
        "--end-date",
        help="End date (YYYY-MM-DD). Default: today.",
    )
    tx_parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Max number of transactions to return (default: 100).",
    )
    tx_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the full Plaid /transactions/get JSON response.",
    )
    tx_parser.set_defaults(func=cmd_transactions)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        sys.exit(1)
    func(args)


if __name__ == "__main__":
    main()
