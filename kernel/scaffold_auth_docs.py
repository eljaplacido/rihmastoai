"""The operator's guide to a product's sign-in (`factory/SIGN-IN.md`) and the README's section on it, for
kernel/scaffold_auth.py."""

# What a deployment made before the sign-in arrived needs once: kept in the guide and in the sign_in_added record.
VOLUME_NOTE = ("the service runs as the unprivileged user 10001, which owns /data in the image; a data volume made "
               "before the sign-in was added may belong to root, so hand it over once before the first release with "
               "sign-in starts: docker run --rm --user 0 -v <the volume>:/data <this release's image> "
               "chown -R 10001:10001 /data")

SIGN_IN_MD = """# Sign-in: how to run it

This product is a web app people sign in to. The paved road added the sign-in (`app/sign_in.py`) and
its checks (`tests/test_road_sign_in.py`); the road owns both, so no builder may change them.

## First start

Set two environment variables for the first start only:

| Variable | What it is |
|---|---|
| `FIRST_ADMIN_USER` | the first admin's name |
| `FIRST_ADMIN_PASSWORD` | their first password, at least 12 characters; they set a new one at first sign-in |

The service creates the admin only while it has no account, and takes both variables out of its
environment once read. Without them nobody can sign in, and the sign-in page says so. The admin adds
the other accounts on the **Your account** page (`/account`).

## What it does

- Passwords are stored as salted PBKDF2-SHA256 hashes in `DATA_DIR/accounts.json`, never as text, and
  never in the traffic log.
- The session cookie is HttpOnly and SameSite=Lax, and Secure when the request came over TLS: the
  road's ingress sends `X-Forwarded-Proto: https`, or set `PUBLIC_URL=https://...`.
- Every form and every state-changing request carries a CSRF token (the form field `csrf`, or the
  `X-CSRF-Token` header).
- After 5 failed sign-ins in a row an account waits 15 minutes. The answer never says whether the name
  exists.
- Sessions live in the service's memory: a restart signs everyone out.

## Your organisation's sign-in (OIDC)

Run an identity-aware proxy in front of the product, as Rihmasto's own cockpit does
(Rihmasto's `docs/guides/access.md`, "Setting up an identity-aware proxy"; oauth2-proxy is one). The
proxy signs people in with your identity provider and passes the user on in a header, with a shared
secret. Then set:

| Variable | What it is |
|---|---|
| `SIGN_IN_MODE` | `proxy` |
| `SIGN_IN_PROXY_SECRET` | the secret the proxy sends; the same value in the proxy's environment |
| `SIGN_IN_PROXY_SECRET_HEADER` | the header that carries it (default `X-Proxy-Secret`) |
| `SIGN_IN_PROXY_USER_HEADER` | the header with the signed-in user (default `X-Forwarded-Email`) |
| `SIGN_IN_PROXY_ADMINS` | users who are admins here, separated by commas |
| `SIGN_IN_PROXY_SIGN_OUT` | where Sign out goes (default `/oauth2/sign_out`) |

A request is signed in only when it carries the proxy's secret, compared in constant time, and the
user and secret headers each exactly once. Let only the proxy reach the product.

## Calling it from another program

`GET /sign-in` with `Accept: application/json` answers `{"csrf": ...}` and a form cookie;
`POST /sign-in` with JSON `{"username", "password", "csrf"}` and that cookie answers the session cookie
and the session's own `csrf`. Send the cookie with every request, and the token in `X-CSRF-Token` with
every POST, PUT, PATCH and DELETE.

## The service's user and its data volume

The container runs the service as the unprivileged user `10001`, which owns `/data` in the image. A
data volume made before the sign-in was added may still belong to root, and the service cannot write
to it. Hand it over once, before the first release with sign-in starts:

    docker run --rm --user 0 -v <the volume>:/data <this release's image> chown -R 10001:10001 /data

## The factory's own checks

The factory's holdout runner, its probes and its shadow replay of recorded traffic carry no session
yet. A request of theirs that the sign-in turns away is recorded as **not measured**, never as failed
or passed.
"""

README_SECTION = """
## Sign-in

People sign in to this product: `factory/SIGN-IN.md` says how to set up the first admin, and how to
use your organisation's own sign-in through an identity-aware proxy. The road owns `app/sign_in.py`
and `tests/test_road_sign_in.py`: never edit or remove them. In a handler, `req.user` names who is
signed in.
"""
