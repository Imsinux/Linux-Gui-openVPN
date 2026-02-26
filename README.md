# OpenVPN GUI Client

> A lightweight, modern OpenVPN graphical client built with **GTK4** and **libadwaita** — integrates natively into the GNOME desktop.

---

## Features

| Feature | Details |
|---|---|
| **Server selector** | Auto-discovers all `.ovpn` files in the app directory |
| **Credentials manager** | Username/password saved securely to `~/.config/vpn-client/credentials` |
| **Live status** | Color-coded indicator (grey / amber / green) |
| **Connection info** | Assigned VPN IP, session duration, bytes in/out |
| **Real-time log** | Timestamped OpenVPN output with auto-scroll |
| **Clean disconnect** | Sends `SIGTERM` via management socket; falls back to `pkexec kill` |

---

## Requirements

| Dependency | Package (Fedora / Debian / Arch) |
|---|---|
| Python 3.9+ | `python3` |
| PyGObject | `python3-gobject` / `python3-gi` / `python-gobject` |
| GTK 4 | `gtk4` / `gir1.2-gtk-4.0` / `gtk4` |
| libadwaita | `libadwaita` / `gir1.2-adw-1` / `libadwaita` |
| OpenVPN | `openvpn` |
| polkit (pkexec) | `polkit` / `policykit-1` / `polkit` |

---

## Installation

### Quick install (recommended)

```bash
git clone https://github.com/imsinux/Linux-Gui-openVPN
cd vpn-client

# Install dependencies + app
sudo bash install.sh --install-deps
```

### Install only (deps already present)

```bash
sudo bash install.sh
```

### Verify dependencies without installing

```bash
bash install.sh --check
```

### Uninstall

```bash
sudo bash install.sh --uninstall
```

---

## Adding VPN Configs

Place your `.ovpn` configuration files in the **same directory** as `vpn_client.py` before installing, or copy them to `/opt/vpn-client/` afterward:

```bash
sudo cp my-server.ovpn /opt/vpn-client/
```

The application discovers all `.ovpn` files automatically on startup and lists them in the **Server** dropdown.

---

## Usage

Launch from your application menu or run:

```bash
vpn-client
```

```
┌─────────────────────────────────────┐
│  VPN Client                    [×]  │
├─────────────────────────────────────┤
│  Server                             │
│  ┌─ OpenVPN Config ──────────────┐  │
│  │  my-server            ▾       │  │
│  └───────────────────────────────┘  │
│                                     │
│  Credentials                        │
│  ┌─ Username ─────────────────────┐ │
│  ├─ Password ─────────────────────┤ │
│  └───────────────────────────────┘  │
│  [ Save Credentials ]               │
│                                     │
│  Status                             │
│  ● Connected                        │
│  IP: 10.8.0.2  |  00:12:34         │
│  In: 1.2 MB   Out: 340.5 KB        │
│                                     │
│  [ Connect ]      [ Disconnect ]    │
│                                     │
│  Log                                │
│  ┌───────────────────────────────┐  │
│  │ [14:01:22] Connecting to...   │  │
│  │ [14:01:25] Initialization ... │  │
│  │ [14:01:25] Connection establ. │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

1. Select a server from the dropdown.
2. Enter your VPN username and password (optionally save them).
3. Click **Connect** — `pkexec` will prompt for your sudo password.
4. Click **Disconnect** to terminate cleanly.

---

## How It Works

```
vpn_client.py
     │
     ├─ Discovers *.ovpn  ──►  /opt/vpn-client/*.ovpn
     │
     ├─ on Connect ──► pkexec openvpn --config <file>
     │                              --auth-user-pass <creds>
     │                              --management 127.0.0.1 7505
     │
     ├─ Monitor thread  ──► reads stdout, parses state transitions
     │
     └─ Poll thread (connected) ──► TCP socket → management port 7505
                                     sends "status", parses bytes I/O
```

State machine:

```
DISCONNECTED ──connect──► CONNECTING ──established──► CONNECTED
     ▲                                                    │
     └──────────────── DISCONNECTING ◄──disconnect────────┘
```

---

## Security Notes

- Credentials are stored with `chmod 600` at `~/.config/vpn-client/credentials`.
- OpenVPN runs as **root** via `pkexec` (polkit authentication); the GUI itself runs as your user.
- No credentials are logged or transmitted beyond what OpenVPN requires.

---

## Author

**imsinux** — [github.com/imsinux](https://github.com/imsinux)

---

## License

MIT — see [LICENSE](LICENSE) for details.
