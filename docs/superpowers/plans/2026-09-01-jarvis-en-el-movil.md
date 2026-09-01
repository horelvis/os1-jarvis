# JARVIS on the Phone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold a button on an iPhone anywhere in the house, speak, release, and JARVIS answers on that phone — same session, same memory, over the local network only.

**Architecture:** The phone is a **peripheral of the widget**, not a new platform. A new `remote.py` serves one HTTPS page and a WebSocket on the house network, inside the widget's existing asyncio loop; audio arriving there enters `dispatch(pcm)`, the same path the desk microphone uses. The gateway never learns the phone exists — one strip, one session, and `adapter.py` is untouched. The reply is routed back to the endpoint that spoke by making `Speaker`'s sink swappable.

**Tech Stack:** Python 3.12, `aiohttp` (already present), `openssl` (system, 3.0.13), `qrcode[png]` (new), vanilla JS + Web Audio in the page. No framework, no build step.

**Spec:** `docs/superpowers/specs/2026-09-01-jarvis-en-el-movil-design.md`

## Global Constraints

- **Code and comments in English; user-facing strings in Spanish** (CLAUDE.md §2.9). The page's visible text is Spanish.
- **New work lives in `widget/`.** Never in `backend/` or `frontend/` (§3).
- **Tests:** `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v`. `PYTHONNOUSERSITE=1` is mandatory — the venv is `--system-site-packages` and otherwise also sees `~/.local/lib`. It is **303 passing** before this plan starts.
- **Lint:** `./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .`. ruff's select is `["E4","E7","E9","E402","F","RUF"]` — **never write `# noqa: BLE001`**, `BLE` is not selected and the suppression itself becomes an RUF100 error.
- **Bind to one interface, never `0.0.0.0`.** This box has twelve Docker bridges; no container has any business reaching JARVIS. The LAN address is `192.168.100.58` on `wlo1` and must be discovered at runtime, not hardcoded.
- **Behind this socket is an agent holding the `terminal` toolset** — §12 (2026-08-26): "he can run ANY command on this box". Every auth decision is load-bearing.
- **Secrets are 0600 under `~/.samantha/`** and never enter the repository.
- **`qrcode[png]` is the only new dependency**, approved by the user 2026-09-01. Verified on this box: writes a 501-byte PNG through `pypng` with Pillow never imported. Do not add `cryptography` — certificates are made by shelling out to the system `openssl`.

---

### Task 1: Who may connect

The pure half: the shared secret and the origin check. No sockets, no TLS, no audio. This is the security boundary, so it is built and tested alone.

**Files:**
- Create: `widget/samantha_widget/remote_auth.py`
- Test: `widget/tests/test_remote_auth.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_or_create_secret(path: Path | None = None) -> str`, and `Guard(secret: str, origin: str)` with `token_ok(offered: str) -> bool` and `origin_ok(origin: str) -> bool`. Tasks 3 and 5 use both.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_remote_auth.py`:

```python
"""Who is allowed to open the phone socket.

Behind that socket is an agent holding the `terminal` toolset — CLAUDE.md
§12 (2026-08-26) says plainly "he can run ANY command on this box". Until
this feature the whole of the project's authentication was "only from
this machine"; these two checks are what replaces it.
"""

import stat

import pytest

from samantha_widget.remote_auth import Guard, load_or_create_secret


def test_a_secret_is_created_once_and_reused(tmp_path) -> None:
    path = tmp_path / "remote.token"

    first = load_or_create_secret(path)
    second = load_or_create_secret(path)

    assert first == second
    assert len(first) >= 32


def test_the_secret_file_is_not_readable_by_others(tmp_path) -> None:
    """It is the only thing standing between the wifi and a shell."""
    path = tmp_path / "remote.token"
    load_or_create_secret(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_right_token_passes_and_a_wrong_one_does_not() -> None:
    guard = Guard(secret="s" * 32, origin="https://brain.local:8443")

    assert guard.token_ok("s" * 32) is True
    assert guard.token_ok("x" * 32) is False
    assert guard.token_ok("") is False
    assert guard.token_ok(None) is False


def test_token_comparison_is_constant_time() -> None:
    """A timing oracle on a 32-char secret over a LAN is not theoretical."""
    import inspect

    from samantha_widget import remote_auth

    assert "compare_digest" in inspect.getsource(remote_auth.Guard.token_ok)


@pytest.mark.parametrize(
    "origin",
    [
        "https://brain.local:8443",
        "",  # non-browser clients send none; see the docstring
    ],
)
def test_allowed_origins(origin: str) -> None:
    guard = Guard(secret="s" * 32, origin="https://brain.local:8443")

    assert guard.origin_ok(origin) is True


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://brain.local:8443",       # scheme matters
        "https://brain.local:9999",      # port matters
        "https://brain.local.evil.com",  # suffix attack
        "null",
    ],
)
def test_refused_origins(origin: str) -> None:
    guard = Guard(secret="s" * 32, origin="https://brain.local:8443")

    assert guard.origin_ok(origin) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.remote_auth'`

- [ ] **Step 3: Write minimal implementation**

Create `widget/samantha_widget/remote_auth.py`:

```python
"""Who may open the phone socket.

Pure, so it can be tested without a socket or a certificate — and it is
worth testing alone, because it is the whole of the authentication that
replaces "only from this machine". What is behind it is an agent with
the `terminal` toolset.

The origin check is the same one `Hermes/plugins/jarvis/adapter.py`
makes, and for the same reason written there: WebSockets are not subject
to the same-origin policy, so without it any page in any browser on the
network could open the socket and talk to an agent with tools. An absent
Origin is allowed because non-browser clients do not send one and are
not the attacker this is about; browsers always do.
"""

from __future__ import annotations

import os
import secrets
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_SECRET_PATH = Path.home() / ".samantha" / "remote.token"

# 32 URL-safe characters. It travels in a link that is added to a phone's
# home screen, so it has to survive being a URL and being looked at.
_SECRET_BYTES = 24


def load_or_create_secret(path: Path | None = None) -> str:
    """The shared secret, made once and reused.

    Written 0600 before anything is put in it: creating it world-readable
    and chmod'ing afterwards leaves a window in which the secret is on
    disk and readable.
    """
    target = Path(path or os.getenv("SAMANTHA_WIDGET_REMOTE_TOKEN")
                  or DEFAULT_SECRET_PATH)
    if target.is_file():
        return target.read_text().strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secret)
    return secret


class Guard:
    """The two questions asked of every connection."""

    def __init__(self, secret: str, origin: str) -> None:
        self.secret = secret
        self.origin = origin

    def token_ok(self, offered: str | None) -> bool:
        """Constant-time: a timing oracle on a LAN is not theoretical."""
        if not offered:
            return False
        return compare_digest(offered, self.secret)

    def origin_ok(self, origin: str) -> bool:
        if not origin:
            return True
        # Compared whole rather than by hostname suffix: a check that
        # accepted anything ending in the host name would accept
        # `brain.local.evil.com`.
        try:
            offered = urlsplit(origin)
            mine = urlsplit(self.origin)
        except ValueError:
            return False
        if not offered.scheme or not offered.hostname:
            return False
        return (
            offered.scheme == mine.scheme
            and offered.hostname == mine.hostname
            and (offered.port or (443 if offered.scheme == "https" else 80))
            == (mine.port or (443 if mine.scheme == "https" else 80))
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote_auth.py -v`
Expected: PASS, all cases.

- [ ] **Step 5: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/remote_auth.py tests/test_remote_auth.py
git commit -m "feat(remote): the two questions asked of every phone that connects"
```

---

### Task 2: A certificate the iPhone will trust

A local CA and a leaf for both `brain.local` and the LAN IP, made by shelling out to the system `openssl` rather than adding `cryptography`.

**Files:**
- Create: `widget/samantha_widget/certs.py`
- Test: `widget/tests/test_certs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lan_address() -> str`, and `ensure_certificate(directory: Path, hostname: str, ip: str) -> tuple[Path, Path, Path]` returning `(ca_pem, cert_pem, key_pem)`. Task 3 builds an `ssl.SSLContext` from the last two; Task 6 serves the first.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_certs.py`:

```python
"""The certificate, and the address it is issued for.

Safari will not open a microphone outside a secure context. On a private
IP that means a certificate this house trusts, which means a local CA and
a two-minute ritual per iPhone. There is nothing to test about Safari
here; what IS testable is that the files come out with the right names in
them and the right permissions on them.
"""

import ssl
import subprocess

import pytest

from samantha_widget.certs import ensure_certificate, lan_address


def test_lan_address_is_a_real_private_address() -> None:
    """Never 0.0.0.0, never a Docker bridge. This box has twelve of those
    and none of them should be able to reach JARVIS."""
    import ipaddress

    address = ipaddress.ip_address(lan_address())

    assert address.is_private
    assert not address.is_loopback
    assert not str(address).startswith("172.1")
    assert not str(address).startswith("172.2")


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_a_certificate_is_made_once_and_reused(tmp_path) -> None:
    first = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")
    second = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    assert first == second
    for path in first:
        assert path.is_file()


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_leaf_carries_both_the_name_and_the_ip(tmp_path) -> None:
    """mDNS is the nice path and it fails on networks with client
    isolation, so the IP has to work as a fallback."""
    _ca, cert, _key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    text = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-text"],
        capture_output=True, text=True, check=True,
    ).stdout

    assert "DNS:brain.local" in text
    assert "IP Address:192.168.100.58" in text


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_private_key_is_not_readable_by_others(tmp_path) -> None:
    import stat

    _ca, _cert, key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    assert stat.S_IMODE(key.stat().st_mode) == 0o600


@pytest.mark.skipif(
    subprocess.run(["which", "openssl"], capture_output=True).returncode != 0,
    reason="openssl is not installed",
)
def test_the_pair_loads_into_an_ssl_context(tmp_path) -> None:
    """The only test that proves the files are usable rather than merely
    present — a mismatched key and cert pass every check above."""
    _ca, cert, key = ensure_certificate(tmp_path, "brain.local", "192.168.100.58")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_certs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.certs'`

- [ ] **Step 3: Write minimal implementation**

Create `widget/samantha_widget/certs.py`:

```python
"""A certificate this house trusts, made with the openssl that is already
installed.

`cryptography` would do this in Python and is deliberately not used: the
system `openssl` (3.0.13 here) is on any Ubuntu, the files it makes are
inspectable with the tools anyone already knows, and this project counts
its dependencies.

Issued for ten years. It is installed by hand on each iPhone, through
Settings → General → About → Certificate Trust Settings, and nobody
wants to do that twice.
"""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

_YEARS = 3650


def lan_address() -> str:
    """This box's address on the house network.

    Found by asking the routing table which source address would be used
    to reach the outside — which never picks a Docker bridge, and there
    are twelve of those here. No packet is sent; UDP connect only sets
    the socket's peer.
    """
    override = os.getenv("SAMANTHA_WIDGET_REMOTE_HOST")
    if override:
        return override
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routable, never routed
        return probe.getsockname()[0]
    finally:
        probe.close()


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"openssl failed: {' '.join(args)}\n{result.stderr}")


def ensure_certificate(
    directory: Path, hostname: str, ip: str
) -> tuple[Path, Path, Path]:
    """(ca_pem, cert_pem, key_pem), made once and reused."""
    directory.mkdir(parents=True, exist_ok=True)
    ca_key = directory / "ca.key"
    ca_pem = directory / "ca.pem"
    key_pem = directory / "jarvis.key"
    cert_pem = directory / "jarvis.pem"
    if ca_pem.is_file() and cert_pem.is_file() and key_pem.is_file():
        return ca_pem, cert_pem, key_pem

    _run(["openssl", "genrsa", "-out", str(ca_key), "2048"])
    os.chmod(ca_key, 0o600)
    _run([
        "openssl", "req", "-x509", "-new", "-nodes", "-key", str(ca_key),
        "-sha256", "-days", str(_YEARS), "-out", str(ca_pem),
        "-subj", "/CN=JARVIS Home CA",
    ])

    config = directory / "leaf.cnf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nreq_extensions=ext\nprompt=no\n"
        f"[dn]\nCN={hostname}\n"
        "[ext]\nbasicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName=DNS:{hostname},IP:{ip}\n"
    )
    csr = directory / "jarvis.csr"
    _run(["openssl", "genrsa", "-out", str(key_pem), "2048"])
    os.chmod(key_pem, 0o600)
    _run(["openssl", "req", "-new", "-key", str(key_pem), "-out", str(csr),
          "-config", str(config)])
    _run([
        "openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca_pem),
        "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(cert_pem),
        "-days", str(_YEARS), "-sha256",
        "-extfile", str(config), "-extensions", "ext",
    ])
    csr.unlink(missing_ok=True)
    return ca_pem, cert_pem, key_pem
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_certs.py -v`
Expected: PASS.

If `test_lan_address_is_a_real_private_address` fails because this box's
address is not private, the machine is on a different network than the
one this was written against; report it rather than weakening the test.

- [ ] **Step 5: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/certs.py tests/test_certs.py
git commit -m "feat(remote): a certificate this house trusts, from the openssl already here"
```

---

### Task 3: The audio contract

What arrives from a browser and what has to reach `dispatch()`. Pure arithmetic, no sockets — and the place a mistake would be silent, because wrong-rate audio transcribes as plausible nonsense rather than failing.

**Files:**
- Create: `widget/samantha_widget/remote_audio.py`
- Test: `widget/tests/test_remote_audio.py`

**Interfaces:**
- Consumes: `INPUT_RATE` from `samantha_widget.vad` (16000).
- Produces: `resample_to_input(pcm: bytes, source_rate: int) -> bytes` and `MAX_UTTERANCE_BYTES`. Task 4 uses both.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_remote_audio.py`:

```python
"""Turning what a browser hands us into what the pipeline speaks.

The pipeline is 16 kHz mono int16 everywhere — the VAD, Whisper, the
dumps. A browser gives whatever its device chose, usually 48 kHz. Getting
this wrong does not raise: it transcribes as confident nonsense, which is
the worst kind of failure this project has.
"""

import math
import struct

from samantha_widget.remote_audio import MAX_UTTERANCE_BYTES, resample_to_input
from samantha_widget.vad import INPUT_RATE


def _tone(samples: int, rate: int, hz: float = 440.0) -> bytes:
    return b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * hz * i / rate)))
        for i in range(samples)
    )


def test_a_matching_rate_is_returned_untouched() -> None:
    pcm = _tone(1600, INPUT_RATE)

    assert resample_to_input(pcm, INPUT_RATE) == pcm


def test_48k_becomes_16k_and_keeps_its_duration() -> None:
    """One second in, one second out. A length bug here shortens or
    stretches speech, and Whisper transcribes the result without complaint."""
    pcm = _tone(48000, 48000)

    out = resample_to_input(pcm, 48000)

    assert len(out) // 2 == INPUT_RATE


def test_44100_is_handled_too() -> None:
    """48 kHz is usual, not guaranteed — the rate is the device's choice
    and must be read from the AudioContext, never assumed."""
    pcm = _tone(44100, 44100)

    out = resample_to_input(pcm, 44100)

    assert abs(len(out) // 2 - INPUT_RATE) <= 1


def test_the_output_is_still_int16() -> None:
    pcm = _tone(4800, 48000)

    out = resample_to_input(pcm, 48000)

    assert len(out) % 2 == 0
    values = struct.unpack(f"<{len(out) // 2}h", out)
    assert max(values) > 1000  # a tone survived, it is not silence


def test_an_odd_number_of_bytes_is_refused() -> None:
    """Half a sample means the stream is misframed; guessing would put a
    click into the audio and hide the real bug."""
    import pytest

    with pytest.raises(ValueError):
        resample_to_input(b"\x00\x00\x00", 48000)


def test_there_is_a_ceiling_on_one_utterance() -> None:
    """A held button — or a hostile client — must not be able to make the
    widget allocate without bound. Thirty seconds is the same cap
    `vad.py` puts on a spoken turn."""
    assert MAX_UTTERANCE_BYTES == 30 * INPUT_RATE * 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote_audio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.remote_audio'`

- [ ] **Step 3: Write minimal implementation**

Create `widget/samantha_widget/remote_audio.py`:

```python
"""What a browser sends, in the format the pipeline speaks.

Everything downstream — the VAD, Whisper, the dumps — is 16 kHz mono
int16. A browser hands over whatever rate its device picked, and the page
reads that rate off the `AudioContext` rather than assuming 48 kHz,
because it is the device's choice.

Linear interpolation rather than a windowed filter: the input is speech
being handed to Whisper, the ratio is a downsample by three, and the
aliasing that a proper filter would remove sits above what a 16 kHz
pipeline keeps anyway. If a measurement ever shows transcription
suffering, this is the place to put a real filter.
"""

from __future__ import annotations

import array

from .vad import INPUT_RATE

# The same ceiling `vad.py` puts on a spoken turn, for the same reason
# plus one: a held button, or a client that lies, must not be able to
# make this process allocate without bound.
MAX_UTTERANCE_BYTES = 30 * INPUT_RATE * 2


def resample_to_input(pcm: bytes, source_rate: int) -> bytes:
    """16 kHz mono int16, from mono int16 at `source_rate`."""
    if len(pcm) % 2:
        raise ValueError("PCM must be a whole number of int16 samples")
    if source_rate == INPUT_RATE:
        return pcm
    if source_rate <= 0:
        raise ValueError(f"impossible sample rate: {source_rate}")

    source = array.array("h")
    source.frombytes(pcm)
    count = len(source)
    if count == 0:
        return b""
    wanted = round(count * INPUT_RATE / source_rate)
    out = array.array("h", bytes(2 * wanted))
    step = (count - 1) / max(1, wanted - 1) if wanted > 1 else 0.0
    for i in range(wanted):
        position = i * step
        left = int(position)
        right = min(left + 1, count - 1)
        weight = position - left
        out[i] = int(source[left] * (1 - weight) + source[right] * weight)
    return out.tobytes()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote_audio.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/remote_audio.py tests/test_remote_audio.py
git commit -m "feat(remote): what a browser sends, in the format the pipeline speaks"
```

---

### Task 4: The server, and one turn at a time

The socket itself: TLS, the two guards, the endpoint registry, and the rule that a second press during a running turn is refused rather than queued.

**Files:**
- Create: `widget/samantha_widget/remote.py`
- Test: `widget/tests/test_remote.py`

**Interfaces:**
- Consumes: `Guard`, `load_or_create_secret` (Task 1); `ensure_certificate`, `lan_address` (Task 2); `resample_to_input`, `MAX_UTTERANCE_BYTES` (Task 3).
- Produces: `Endpoint` with `write(pcm: bytes) -> None` (the sink protocol `Player` already satisfies) and `name: str`; and `RemoteDesk(guard, on_utterance)` with `busy: bool`, `claim(endpoint) -> bool`, `release() -> None`, `current: Endpoint | None`. Task 5 routes replies through `current`.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_remote.py`:

```python
"""The phone socket: who holds the turn, and what happens to the second
person who presses.

Three iPhones plus the desk can press at once. Queueing spoken orders
ages badly — he would answer something asked a minute ago — so a press
during a running turn is refused and the page says so.
"""

import pytest

from samantha_widget.remote import RemoteDesk


class FakeEndpoint:
    def __init__(self, name: str) -> None:
        self.name = name
        self.written: list[bytes] = []
        self.refusals = 0

    def write(self, pcm: bytes) -> None:
        self.written.append(pcm)

    def refuse(self) -> None:
        self.refusals += 1


def test_the_first_to_press_holds_the_turn() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    phone = FakeEndpoint("iphone-cocina")

    assert desk.claim(phone) is True
    assert desk.busy is True
    assert desk.current is phone


def test_the_second_to_press_is_refused_not_queued() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    assert desk.claim(second) is False
    assert desk.current is first
    assert second.written == []


def test_releasing_lets_the_next_one_in() -> None:
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)
    desk.release()

    assert desk.busy is False
    assert desk.claim(second) is True


def test_the_utterance_is_delivered_with_the_endpoint_that_spoke() -> None:
    """The reply has to go back where the question came from, so the
    endpoint travels with the audio."""
    seen: list[tuple[bytes, object]] = []
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: seen.append((pcm, endpoint)))
    phone = FakeEndpoint("iphone-cocina")
    desk.claim(phone)

    desk.finish(b"\x01\x02" * 100, phone)

    assert seen == [(b"\x01\x02" * 100, phone)]


def test_a_release_by_a_phone_that_does_not_hold_the_turn_is_ignored() -> None:
    """Otherwise a second phone releasing frees the first one's turn."""
    desk = RemoteDesk(on_utterance=lambda pcm, endpoint: None)
    first, second = FakeEndpoint("a"), FakeEndpoint("b")
    desk.claim(first)

    desk.release(second)

    assert desk.current is first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.remote'`

- [ ] **Step 3: Write the turn-holding half**

Create `widget/samantha_widget/remote.py` with this first; the aiohttp
half is Step 5.

```python
"""JARVIS on a phone, inside the house's own network.

The phone is a peripheral of this process, not a platform: audio that
arrives here goes into the same `dispatch()` the desk microphone uses,
so it is the same session, the same memory and the same JARVIS. The
gateway never learns it exists.

What is behind this socket is an agent holding the `terminal` toolset,
so `remote_auth.Guard` is not a formality.
"""

from __future__ import annotations

from typing import Callable, Protocol


class Endpoint(Protocol):
    """Anywhere his voice can come out.

    Deliberately the same shape as `audio.Player`: one `write(pcm)`. That
    is what lets `Speaker` be pointed at a phone without knowing what a
    phone is.
    """

    name: str

    def write(self, pcm: bytes) -> None: ...

    def refuse(self) -> None: ...


class RemoteDesk:
    """Who is holding the turn.

    One at a time, and a second press is REFUSED rather than queued: a
    queued spoken order is answered a minute after it was asked, which
    reads as him being confused rather than busy.
    """

    def __init__(
        self, on_utterance: Callable[[bytes, Endpoint], None]
    ) -> None:
        self._on_utterance = on_utterance
        self.current: Endpoint | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None

    def claim(self, endpoint: Endpoint) -> bool:
        """True if this endpoint now holds the turn."""
        if self.current is not None and self.current is not endpoint:
            endpoint.refuse()
            return False
        self.current = endpoint
        return True

    def release(self, endpoint: Endpoint | None = None) -> None:
        """Give the turn back. A release from an endpoint that does not
        hold it is ignored — otherwise the second phone to press frees
        the first one's turn."""
        if endpoint is not None and self.current is not endpoint:
            return
        self.current = None

    def finish(self, pcm: bytes, endpoint: Endpoint) -> None:
        """The button was released: hand the utterance up with the
        endpoint that spoke, so the reply knows where to go."""
        self._on_utterance(pcm, endpoint)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote.py -v`
Expected: PASS.

- [ ] **Step 5: Add the aiohttp server**

Append to `widget/samantha_widget/remote.py`:

```python
import ssl
import sys
from pathlib import Path

from aiohttp import WSMsgType, web

from .certs import ensure_certificate, lan_address
from .remote_audio import MAX_UTTERANCE_BYTES, resample_to_input
from .remote_auth import Guard, load_or_create_secret

PORT = int(os.getenv("SAMANTHA_WIDGET_REMOTE_PORT", "8443"))
HOSTNAME = os.getenv("SAMANTHA_WIDGET_REMOTE_NAME", "brain.local")
CERT_DIR = Path.home() / ".samantha" / "certs"


class WebEndpoint:
    """One connected phone."""

    def __init__(self, ws: web.WebSocketResponse, name: str, loop) -> None:
        self._ws = ws
        self._loop = loop
        self.name = name

    def write(self, pcm: bytes) -> None:
        # Called from the Speaker on the asyncio loop already, but going
        # through call_soon_threadsafe costs nothing and makes this safe
        # from the audio thread too.
        self._loop.call_soon_threadsafe(
            lambda: self._loop.create_task(self._ws.send_bytes(pcm))
        )

    def refuse(self) -> None:
        self._loop.call_soon_threadsafe(
            lambda: self._loop.create_task(
                self._ws.send_json({"type": "busy"})
            )
        )


async def serve(desk: RemoteDesk, guard: Guard, loop) -> web.AppRunner:
    """Start the HTTPS server. Returns the runner so it can be stopped."""
    app = web.Application()
    app.router.add_get("/ws", _handler(desk, guard, loop))
    ca, cert, key = ensure_certificate(CERT_DIR, HOSTNAME, lan_address())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    runner = web.AppRunner(app)
    await runner.setup()
    # One interface, never 0.0.0.0: this box has twelve Docker bridges.
    site = web.TCPSite(runner, lan_address(), PORT, ssl_context=context)
    await site.start()
    print(
        f"móvil: escuchando en https://{HOSTNAME}:{PORT} "
        f"({lan_address()}), CA en {ca}",
        file=sys.stderr,
        flush=True,
    )
    return runner


def _handler(desk: RemoteDesk, guard: Guard, loop):
    async def handle(request: web.Request) -> web.WebSocketResponse:
        if not guard.origin_ok(request.headers.get("Origin", "")):
            raise web.HTTPForbidden()
        if not guard.token_ok(request.query.get("t")):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        endpoint = WebEndpoint(ws, request.remote or "phone", loop)
        buffer = bytearray()
        rate = 48000
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                import json

                frame = json.loads(message.data)
                if frame.get("type") == "start":
                    rate = int(frame.get("rate", 48000))
                    buffer.clear()
                    if not desk.claim(endpoint):
                        continue
                elif frame.get("type") == "end" and desk.current is endpoint:
                    desk.finish(resample_to_input(bytes(buffer), rate), endpoint)
                    buffer.clear()
            elif message.type == WSMsgType.BINARY:
                if desk.current is endpoint and len(buffer) < MAX_UTTERANCE_BYTES:
                    buffer += message.data
        desk.release(endpoint)
        return ws

    return handle
```

Add `import os` to the module's imports.

- [ ] **Step 6: Run the whole suite, lint and commit**

```bash
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/remote.py tests/test_remote.py
git commit -m "feat(remote): the socket, and the second phone to press is told so"
```

---

### Task 5: The answer goes back where the question came from

`Speaker` writes to a sink; the sink becomes swappable; the turn points it at the phone that spoke.

**Files:**
- Modify: `widget/samantha_widget/speech.py` (`Speaker.__init__`, `Speaker.say`)
- Modify: `widget/samantha_widget/__main__.py` (`say`, `dispatch`, startup)
- Test: `widget/tests/test_speech.py`

**Interfaces:**
- Consumes: `RemoteDesk`, `Endpoint`, `serve` (Task 4); `Guard`, `load_or_create_secret` (Task 1).
- Produces: `Speaker.route_to(sink) -> None` and `Speaker.route_home() -> None`.

- [ ] **Step 1: Write the failing test**

Append to `widget/tests/test_speech.py`:

```python
def test_the_speaker_can_be_pointed_somewhere_else() -> None:
    """The user, 2026-09-01: "la respuesta de JARVIS tiene que oírse por
    el canal que pregunta." The Speaker writes PCM to a sink; making the
    sink swappable is the whole of routing a reply to a phone.

    It is also what keeps two speakers from ever sounding at once, which
    is what made "he is in both places" affordable: cross-room feedback
    cannot happen if only one room is sounding.
    """
    from samantha_widget.speech import Speaker

    class Sink:
        def __init__(self) -> None:
            self.written: list[bytes] = []

        def write(self, pcm: bytes) -> None:
            self.written.append(pcm)

    home, phone = Sink(), Sink()
    speaker = Speaker(home)

    assert speaker.sink is home

    speaker.route_to(phone)
    assert speaker.sink is phone

    speaker.route_home()
    assert speaker.sink is home
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_speech.py -v`
Expected: FAIL — `AttributeError: 'Speaker' object has no attribute 'sink'`

- [ ] **Step 3: Make the sink swappable**

In `widget/samantha_widget/speech.py`, change `Speaker.__init__` and add
the two methods:

```python
    def __init__(self, player) -> None:
        self._player = player
        # Where the PCM goes. `player` is the desk; a phone that pressed
        # its button becomes this for the length of its own turn, which
        # is what "the answer is heard on the channel that asked" means
        # in code. Anything with `write(pcm)` qualifies.
        self.sink = player
        self._client = None
        self._generation = 0
        self._queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def route_to(self, sink) -> None:
        """Send what he says next to this sink instead of the desk."""
        self.sink = sink

    def route_home(self) -> None:
        """Back to the speaker in the room with the strip in it."""
        self.sink = self._player
```

And in `Speaker.say`, replace the write:

```python
            self.sink.write(chunk)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_speech.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Wire it into the turn**

In `widget/samantha_widget/__main__.py`, after the `speaker` and
`machine` exist and before the loop runs, add:

```python
        from .remote import RemoteDesk, serve
        from .remote_auth import Guard, load_or_create_secret

        def on_remote_utterance(pcm: bytes, endpoint) -> None:
            """A phone released its button.

            Two things the desk path does are deliberately skipped, and
            for the same reasons `on_typed` skips them: the wake word (a
            button was pressed — he is being addressed) and the VAD (the
            button is the utterance boundary). The echo filter still
            runs inside `dispatch`, and costs nothing here because the
            phone's microphone is closed while he answers.
            """
            speaker.route_to(endpoint)
            machine.heard(pcm)

        remote_desk = RemoteDesk(on_utterance=on_remote_utterance)
```

In `dispatch(pcm)`, replace the wake-word block so a phone utterance
skips it — the button is the address:

```python
            spoken = text if remote_desk.busy else wake.heard(text, time.monotonic())
```

And where a turn settles — in `on_done` and `on_error`, beside
`machine.done()` / `machine.error(...)` — return the voice to the room:

```python
            speaker.route_home()
            remote_desk.release()
```

Start the server on the loop, beside the other startup tasks:

```python
        secret = load_or_create_secret()
        guard = Guard(secret, f"https://{HOSTNAME}:{PORT}")
        self._spawn(serve(remote_desk, guard, loop))
```

(Import `HOSTNAME` and `PORT` from `.remote`.)

- [ ] **Step 6: Run the whole suite, lint and commit**

```bash
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/speech.py samantha_widget/__main__.py tests/test_speech.py
git commit -m "feat(widget): the answer is heard on the channel that asked"
```

---

### Task 6: The page

One button, vanilla JS, no build step. Spanish on screen.

**Files:**
- Create: `widget/samantha_widget/static/movil.html`
- Modify: `widget/samantha_widget/remote.py` (serve it)
- Test: `widget/tests/test_remote_page.py`

**Interfaces:**
- Consumes: the WebSocket contract from Task 4 — `{"type":"start","rate":N}`, binary PCM frames, `{"type":"end"}`; `{"type":"busy"}` comes back.
- Produces: nothing later tasks import.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_remote_page.py`:

```python
"""The page is not testable in a browser from here — that needs an
iPhone in a hand, exactly as §2.3 says of the strip's appearance. What IS
testable is that it does not lie about the contract and does not reach
the network."""

from pathlib import Path

PAGE = Path(__file__).parent.parent / "samantha_widget" / "static" / "movil.html"


def test_the_page_exists_and_is_self_contained() -> None:
    """§1.1: nothing leaves the house. A page that pulls a font or a
    framework from a CDN is the house talking to the internet every time
    somebody presses the button."""
    text = PAGE.read_text()

    assert "http://" not in text.replace("http://www.w3.org", "")
    assert "https://" not in text
    assert "cdn" not in text.lower()


def test_the_page_reads_the_rate_instead_of_assuming_it() -> None:
    """48 kHz is usual, not guaranteed — it is the device's choice."""
    text = PAGE.read_text()

    assert "sampleRate" in text
    assert "48000" not in text


def test_the_page_speaks_the_protocol_the_server_expects() -> None:
    text = PAGE.read_text()

    for token in ('"start"', '"end"', '"busy"'):
        assert token in text


def test_the_visible_text_is_spanish() -> None:
    """CLAUDE.md §2.9: user-facing strings in Spanish."""
    text = PAGE.read_text()

    assert "Mantén pulsado" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_remote_page.py -v`
Expected: FAIL — `FileNotFoundError`.

- [ ] **Step 3: Write the page**

Create `widget/samantha_widget/static/movil.html`:

```html
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>JARVIS</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; height:100dvh; display:grid; place-items:center;
         background:#141210; color:#d1684e;
         font-family:-apple-system,system-ui,sans-serif; }
  #talk { width:70vw; height:70vw; max-width:320px; max-height:320px;
          border-radius:50%; border:2px solid #d1684e; background:transparent;
          color:#d1684e; font-size:1.1rem; -webkit-user-select:none;
          user-select:none; touch-action:none; }
  #talk[data-state="rec"]  { background:#d1684e; color:#141210; }
  #talk[data-state="busy"] { opacity:.35; }
  #state { position:fixed; bottom:2rem; opacity:.7; font-size:.9rem; }
</style>
<button id="talk" data-state="idle">Mantén pulsado</button>
<div id="state"></div>
<script>
const talk = document.getElementById('talk');
const state = document.getElementById('state');
const token = location.hash.slice(1);
let ws, ctx, node, stream;

function say(text) { state.textContent = text; }

function connect() {
  ws = new WebSocket(`wss://${location.host}/ws?t=${encodeURIComponent(token)}`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => say('Listo');
  ws.onclose = () => { say('Sin conexión'); setTimeout(connect, 2000); };
  ws.onmessage = async (event) => {
    if (typeof event.data === 'string') {
      const frame = JSON.parse(event.data);
      if (frame.type === 'busy') { talk.dataset.state = 'busy'; say('Está ocupado'); }
      return;
    }
    play(event.data);
  };
}

// His voice: 24 kHz int16 from CosyVoice, played as it arrives.
let playAt = 0;
function play(buffer) {
  if (!ctx) return;
  const pcm = new Int16Array(buffer);
  const audio = ctx.createBuffer(1, pcm.length, 24000);
  const channel = audio.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
  const source = ctx.createBufferSource();
  source.buffer = audio;
  source.connect(ctx.destination);
  playAt = Math.max(playAt, ctx.currentTime);
  source.start(playAt);
  playAt += audio.duration;
}

async function begin() {
  // Safari requires the AudioContext to be born of a user gesture, and
  // pressing this button is that gesture.
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  await ctx.resume();
  if (!stream) stream = await navigator.mediaDevices.getUserMedia({audio:true});
  talk.dataset.state = 'rec';
  say('Escuchando');
  // The device chooses the rate; we report it rather than assume it.
  ws.send(JSON.stringify({type:'start', rate: ctx.sampleRate}));
  const source = ctx.createMediaStreamSource(stream);
  node = ctx.createScriptProcessor(4096, 1, 1);
  node.onaudioprocess = (event) => {
    if (talk.dataset.state !== 'rec' || ws.readyState !== 1) return;
    const input = event.inputBuffer.getChannelData(0);
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      out[i] = s < 0 ? s * 32768 : s * 32767;
    }
    ws.send(out.buffer);
  };
  source.connect(node);
  node.connect(ctx.destination);
}

function end() {
  if (talk.dataset.state !== 'rec') return;
  talk.dataset.state = 'idle';
  say('Pensando');
  if (node) { node.disconnect(); node = null; }
  ws.send(JSON.stringify({type:'end'}));
}

talk.addEventListener('pointerdown', (e) => { e.preventDefault(); begin(); });
talk.addEventListener('pointerup', (e) => { e.preventDefault(); end(); });
talk.addEventListener('pointercancel', end);
connect();
</script>
```

- [ ] **Step 4: Serve it**

In `widget/samantha_widget/remote.py`, inside `serve()`, before
`ensure_certificate`:

```python
    static = Path(__file__).parent / "static"

    async def page(request: web.Request) -> web.FileResponse:
        return web.FileResponse(static / "movil.html")

    app.router.add_get("/", page)
```

And add `"samantha_widget.static"` package data so the file ships. In
`widget/pyproject.toml`, under `[tool.setuptools]`:

```toml
[tool.setuptools.package-data]
samantha_widget = ["static/*.html"]
```

- [ ] **Step 5: Run the suite, lint and commit**

```bash
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/static/movil.html samantha_widget/remote.py \
        tests/test_remote_page.py pyproject.toml
git commit -m "feat(remote): one button, and it reads the rate instead of assuming it"
```

---

### Task 7: Enrolment — the QR, and the profile

The step the user actually has to do, made into a gesture: he shows you the code on the strip and you point a phone at it.

**Files:**
- Create: `widget/samantha_widget/enrol.py`
- Modify: `widget/samantha_widget/remote.py` (the welcome page over plain HTTP, and `/ca`)
- Modify: `widget/pyproject.toml` (`qrcode[png]`)
- Test: `widget/tests/test_enrol.py`

**Interfaces:**
- Consumes: `ensure_certificate`, `lan_address` (Task 2); the secret (Task 1).
- Produces: `write_qr(url: str, path: Path) -> Path` and `mobileconfig(ca_pem: Path) -> bytes`.

- [ ] **Step 1: Install the dependency**

```bash
cd widget && ./.venv/bin/pip install --ignore-installed "qrcode[png]>=8"
./.venv/bin/pip list --local | grep -iE "qrcode|pypng"
```

`--ignore-installed` and `pip list --local` are both required: the venv is
`--system-site-packages`, so a plain install can be a silent no-op and
only `--local` shows what the venv itself holds.

Add to `dependencies` in `widget/pyproject.toml`:

```toml
    # The enrolment QR. Pure Python, and writes PNG through pypng — with
    # `[png]` it never imports Pillow, verified on this box 2026-09-01
    # (a 501-byte file, `PIL` absent from sys.modules).
    "qrcode[png]>=8",
```

- [ ] **Step 2: Write the failing test**

Create `widget/tests/test_enrol.py`:

```python
"""Getting a phone enrolled without typing a token on a touchscreen."""

import plistlib

from samantha_widget.enrol import mobileconfig, write_qr


def test_the_qr_is_a_png_that_is_not_empty(tmp_path) -> None:
    path = write_qr("https://brain.local:8443/#tok", tmp_path / "qr.png")

    assert path.is_file()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_making_the_qr_does_not_drag_in_pillow(tmp_path) -> None:
    """The dependency was approved on the strength of being small."""
    import sys

    write_qr("https://brain.local:8443/#tok", tmp_path / "qr.png")

    assert "PIL" not in {name.split(".")[0] for name in sys.modules}


def test_the_profile_is_a_plist_carrying_the_certificate(tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")

    profile = plistlib.loads(mobileconfig(ca))

    assert profile["PayloadType"] == "Configuration"
    payload = profile["PayloadContent"][0]
    assert payload["PayloadType"] == "com.apple.security.root"
    assert payload["PayloadContent"] == ca.read_bytes()


def test_the_profile_identifies_itself_recognisably(tmp_path) -> None:
    """It appears in Settings under whatever name this gives it, and the
    user has to find it there to trust it."""
    ca = tmp_path / "ca.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")

    profile = plistlib.loads(mobileconfig(ca))

    assert "JARVIS" in profile["PayloadDisplayName"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_enrol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.enrol'`

- [ ] **Step 4: Write the implementation**

Create `widget/samantha_widget/enrol.py`:

```python
"""Getting a phone enrolled, without typing a token on a touchscreen.

One QR, pointing at a welcome page served over PLAIN HTTP — deliberately,
because of a chicken-and-egg: HTTPS cannot be used before the certificate
it depends on is trusted. That page carries nothing sensitive; the link
with the secret in it is behind the second button, over HTTPS.
"""

from __future__ import annotations

import plistlib
import uuid
from pathlib import Path


def write_qr(url: str, path: Path) -> Path:
    """A PNG of `url`. Pillow is never imported — see pyproject."""
    import qrcode
    from qrcode.image.pure import PyPNGImage

    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url, image_factory=PyPNGImage, box_size=8, border=2).save(str(path))
    return path


def mobileconfig(ca_pem: Path) -> bytes:
    """An iOS profile that installs the house CA as a trusted root.

    Installing it is only half: iOS then needs the switch under
    Settings → General → About → Certificate Trust Settings, which no
    profile can set for you. `widget/README.md` carries the steps.
    """
    return plistlib.dumps(
        {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": "casa.jarvis.ca",
            "PayloadUUID": str(uuid.uuid4()),
            "PayloadDisplayName": "JARVIS — certificado de casa",
            "PayloadDescription": (
                "Permite que este iPhone confíe en JARVIS dentro de casa."
            ),
            "PayloadContent": [
                {
                    "PayloadType": "com.apple.security.root",
                    "PayloadVersion": 1,
                    "PayloadIdentifier": "casa.jarvis.ca.root",
                    "PayloadUUID": str(uuid.uuid4()),
                    "PayloadDisplayName": "JARVIS Home CA",
                    "PayloadCertificateFileName": "ca.pem",
                    "PayloadContent": ca_pem.read_bytes(),
                }
            ],
        }
    )
```

- [ ] **Step 5: Serve the welcome page and the profile**

In `widget/samantha_widget/remote.py`, add a **second, plain-HTTP** site
inside `serve()`, after the HTTPS one starts:

```python
    # Plain HTTP, and only these two routes. The certificate cannot be
    # fetched over a connection that requires trusting it.
    welcome = web.Application()

    async def _welcome(request: web.Request) -> web.Response:
        target = f"https://{HOSTNAME}:{PORT}/#{guard.secret}"
        return web.Response(
            content_type="text/html",
            text=(
                "<!doctype html><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>JARVIS</title>"
                "<style>body{font-family:-apple-system,sans-serif;margin:2rem;"
                "background:#141210;color:#d1684e}a{display:block;margin:1.5rem 0;"
                "padding:1rem;border:1px solid #d1684e;border-radius:.5rem;"
                "color:inherit;text-decoration:none;text-align:center}</style>"
                "<h1>JARVIS en casa</h1>"
                "<a href='/ca'>1 · Instalar el certificado</a>"
                "<p>Después: Ajustes → General → Información → "
                "Ajustes de confianza de certificados → activar "
                "<b>JARVIS Home CA</b>.</p>"
                f"<a href='{target}'>2 · Abrir JARVIS</a>"
            ),
        )

    async def _ca(request: web.Request) -> web.Response:
        return web.Response(
            body=mobileconfig(ca),
            content_type="application/x-apple-aspen-config",
        )

    welcome.router.add_get("/", _welcome)
    welcome.router.add_get("/ca", _ca)
    welcome_runner = web.AppRunner(welcome)
    await welcome_runner.setup()
    await web.TCPSite(welcome_runner, lan_address(), PORT + 1).start()

    qr = write_qr(f"http://{lan_address()}:{PORT + 1}/",
                  Path.home() / ".samantha" / "enrol-qr.png")
    print(f"móvil: alta en http://{lan_address()}:{PORT + 1}/ · QR {qr}",
          file=sys.stderr, flush=True)
```

Import `mobileconfig` and `write_qr` from `.enrol`.

- [ ] **Step 6: Show it on the strip**

In `widget/samantha_widget/__main__.py`, beside the other switches, add
one that puts the QR in the band — the same call `on_photo` makes:

```python
        if os.getenv("SAMANTHA_WIDGET_SHOW_QR") == "1":
            # The band already draws a PNG for the cameras; this is the
            # same gesture. It carries the secret, so it goes away with
            # the band's own fade rather than staying on a screen.
            GLib.timeout_add_seconds(
                3,
                lambda: (
                    band.show_photo(
                        str(Path.home() / ".samantha" / "enrol-qr.png"), "alta"
                    ),
                    False,
                )[1],
            )
```

- [ ] **Step 7: Run the suite, lint and commit**

```bash
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/enrol.py samantha_widget/remote.py \
        samantha_widget/__main__.py tests/test_enrol.py pyproject.toml
git commit -m "feat(remote): he shows you the code, you point a phone at it"
```

---

### Task 8: The documents, and the one thing only a person can check

**Files:**
- Modify: `CLAUDE.md` (§0, §1.1, §2.1, §9, §12)
- Modify: `widget/README.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: The environment switches**

Add to the table in `widget/README.md`:

```markdown
| `SAMANTHA_WIDGET_REMOTE_PORT` | Where the phone page listens (default 8443). The enrolment page is this plus one, over plain HTTP, because a certificate cannot be fetched over a connection that requires trusting it. |
| `SAMANTHA_WIDGET_REMOTE_NAME` | The name on the certificate (default `brain.local`; avahi is running, so mDNS resolves it). The certificate also carries the LAN IP, because client isolation breaks mDNS on some networks. |
| `SAMANTHA_WIDGET_REMOTE_HOST` | Override the LAN address if the routing-table guess is wrong. It is guessed by asking which source address would reach the outside, which never picks one of this box's twelve Docker bridges. |
| `SAMANTHA_WIDGET_REMOTE_TOKEN` | Where the shared secret lives (default `~/.samantha/remote.token`, 0600). Delete it to rotate; every phone then needs the link again. |
| `SAMANTHA_WIDGET_SHOW_QR=1` | Put the enrolment QR on the strip a few seconds after start. The QR itself is a plain LAN URL, no secret in it; what is short-lived is the enrolment WINDOW behind it (`remote.ENROLMENT_SECONDS`, 300 s), not the code on screen. `SIGUSR1` opens the same window with no flag and no restart — see the ritual below. |
```

And, in the setup section, the ritual per iPhone:

```markdown
### Putting him on a phone

1. Point the phone's camera at the QR (`SAMANTHA_WIDGET_SHOW_QR=1` at start,
   or any time with `systemctl --user kill -s USR1 samantha-widget.service`
   — no restart needed).
2. **1 · Instalar el certificado** → Settings shows "Profile Downloaded" →
   Install.
3. **Settings → General → About → Certificate Trust Settings** → turn on
   **JARVIS Home CA**. iOS cannot be made to do this step from a profile.
4. **2 · Abrir JARVIS** → Share → Add to Home Screen.

Two minutes, once per phone. The certificate is issued for ten years.
```

- [ ] **Step 2: CLAUDE.md §0 and §9**

In §0, under the process diagram, add a line to the stack list:

```markdown
- **Phones:** three iPhones on the house network reach him through
  `widget/samantha_widget/remote.py` — a page with one button, held to
  speak. The phone is a peripheral of the widget, not a platform: the
  gateway still sees one strip and one session (§12, 2026-09-01).
```

In §9's table:

```markdown
| The phone: socket, auth, audio, enrolment | `widget/samantha_widget/{remote,remote_auth,remote_audio,enrol,certs}.py` |
| The page it serves | `widget/samantha_widget/static/movil.html` |
```

- [ ] **Step 3: CLAUDE.md §1.1 and §2.1 — the premise that changed**

In §1.1, after the two leaks already listed, add a third:

```markdown
   - **He now listens on the house network**, not only on loopback
     (2026-09-01). Nothing leaves the house, so this principle's letter
     holds — but the premise underneath it changed: authentication used
     to be "only from this machine" and is now a shared secret plus an
     origin check, and what is behind them is an agent holding
     `terminal`. The threat model is **whoever is on the wifi**, guests
     included.
```

In §2.1's implications, after "every service in §0's diagram is on
loopback", add:

```markdown
- **Except one, since 2026-09-01:** the phone page binds the LAN
  interface. Never `0.0.0.0` — this box has twelve Docker bridges and no
  container has any business reaching JARVIS.
```

- [ ] **Step 4: CLAUDE.md §12**

Add an entry at the TOP of the Decision Log:

```markdown
### 2026-09-01 — He stops being tied to the desk

**Decision (the user's):** *"la idea es darle movilidad"*, over the
house's own network and not the internet. Three iPhones reach him through
a page the widget serves; hold the button, speak, release, and **he
answers on the phone that spoke** — the user's own rule: *"la respuesta
de JARVIS tiene que oírse por el canal que pregunta."*

**The phone is a peripheral, not a platform.** Audio that arrives enters
`dispatch()`, the same path the desk microphone uses, so it is the same
session and the same memory. The gateway never learns it exists — one
strip, and `adapter.py`'s origin check and one-strip swap are untouched.

**Four things were checked rather than assumed**, and each closes a door:
Home Assistant does not exist on this box (port closed, no container, one
comment in a config) — which also invalidates a decision taken the same
day in the parked observability work; a browser will not open a
microphone outside a secure context, and on iOS every browser is WebKit;
Apple's Walkie-Talkie is watchOS over FaceTime with no third-party API;
and iOS 16's `PushToTalk` framework does give background audio from the
lock screen but needs a native app, an Apple entitlement and **APNs**, so
its best feature leaves the house.

**Push-to-talk removes three subsystems from the phone's path**, each
deliberately: no VAD (the button is the boundary), no wake word (pressing
is addressing him), and no echo problem — because only one room ever
sounds at a time. That last one is what made "he is in both places"
affordable: listening happens in both, speaking in one.

**Cost, stated:** authentication was "only from this machine" and is now
a shared secret; the threat model becomes whoever is on the wifi. A
certificate must be trusted by hand on each iPhone (two minutes, ten
years). And `qrcode[png]` joins the dependency list — verified here to
write a 501-byte PNG without importing Pillow.

**Out of scope, and not by accident:** cameras on the phone.
`JARVIS_PLATFORM` is hard-coded in `samantha_vision/__init__.py` exactly
so an image of the inside of this house cannot reach another surface
(§12, 2026-08-25). Showing them on a phone reopens that decision; it does
not extend this one.
```

- [ ] **Step 5: PROGRESS.md**

Add an entry at the top, in Spanish, matching the voice of the entries
already there. It MUST say what is not yet proven: **nobody has held the
button on a real iPhone.** Everything above is unit-tested logic and a
server that starts; that Safari captures and plays is exactly the class
of thing §2.3 says no test can settle, and it waits on a phone in a hand.

- [ ] **Step 6: Verify and commit**

```bash
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
cd .. && git add -A
git commit -m "docs(mobile): the premise that changed, and the step only a person can do"
```

---

## What this plan deliberately does not do

- **Cameras or photos on the phone.** See §12 (2026-08-25); it is a
  separate decision, not an extension.
- **Always-listening on the phone.** Needs a native app, an Apple
  entitlement and Apple's push servers.
- **A second conversation.** The phone is the same session by design.
- **Certificates from a real domain.** The user chose to try the local CA
  on one iPhone first and decide from the real friction.
