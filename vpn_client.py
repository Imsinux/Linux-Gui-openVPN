#!/usr/bin/env python3
"""OpenVPN GUI Client - GTK4/Adwaita client for Surfshark OpenVPN configs."""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import glob
import os
import socket
import subprocess
import threading
import time
from enum import Enum, auto
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "vpn-client"
CREDENTIALS_FILE = CONFIG_DIR / "credentials"
MGMT_HOST = "127.0.0.1"
MGMT_PORT = 7505


class State(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    DISCONNECTING = auto()


STATE_COLORS = {
    State.DISCONNECTED: "#888888",
    State.CONNECTING: "#e5a50a",
    State.CONNECTED: "#2ec27e",
    State.DISCONNECTING: "#e5a50a",
}

STATE_LABELS = {
    State.DISCONNECTED: "Disconnected",
    State.CONNECTING: "Connecting...",
    State.CONNECTED: "Connected",
    State.DISCONNECTING: "Disconnecting...",
}


def discover_configs():
    """Find all .ovpn files in the app directory."""
    files = sorted(glob.glob(str(APP_DIR / "*.ovpn")))
    configs = {}
    for f in files:
        name = Path(f).stem
        configs[name] = f
    return configs


class VPNClient(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.vpnclient.app")
        self.connect("activate", self.on_activate)
        self.state = State.DISCONNECTED
        self.ovpn_process = None
        self.monitor_thread = None
        self.mgmt_socket = None
        self.connect_time = None
        self.assigned_ip = None
        self.bytes_in = 0
        self.bytes_out = 0
        self.configs = discover_configs()
        self._stop_monitor = threading.Event()

    # ── UI ──────────────────────────────────────────────────────────────

    def on_activate(self, app):
        self.win = Adw.ApplicationWindow(application=app, title="VPN Client")
        self.win.set_default_size(520, 640)

        # Main layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        box.append(header)

        # GitHub link button in header
        gh_btn = Gtk.Button()
        gh_btn.set_icon_name("help-about-symbolic")
        gh_btn.set_tooltip_text("GitHub: imsinux/Linux-Gui-openVPN")
        gh_btn.connect("clicked", self._open_github)
        header.pack_end(gh_btn)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        # ── Server selector ────────────────────────────────────────────
        server_group = Adw.PreferencesGroup(title="Server")
        self.server_row = Adw.ComboRow(title="OpenVPN Config")
        server_list = Gtk.StringList()
        for name in self.configs:
            server_list.append(name)
        self.server_row.set_model(server_list)
        server_group.add(self.server_row)
        content.append(server_group)

        # ── Credentials ────────────────────────────────────────────────
        cred_group = Adw.PreferencesGroup(title="Credentials")
        self.user_row = Adw.EntryRow(title="Username")
        self.pass_row = Adw.PasswordEntryRow(title="Password")
        cred_group.add(self.user_row)
        cred_group.add(self.pass_row)
        content.append(cred_group)

        # Save credentials button
        save_btn = Gtk.Button(label="Save Credentials")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save_credentials)
        content.append(save_btn)

        # ── Status ─────────────────────────────────────────────────────
        status_group = Adw.PreferencesGroup(title="Status")

        # Status row with colored dot
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_margin_top(8)
        status_box.set_margin_bottom(8)

        self.status_dot = Gtk.DrawingArea()
        self.status_dot.set_size_request(16, 16)
        self.status_dot.set_valign(Gtk.Align.CENTER)
        self.status_dot.set_draw_func(self._draw_dot)
        status_box.append(self.status_dot)

        self.status_label = Gtk.Label(label="Disconnected")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.add_css_class("heading")
        status_box.append(self.status_label)

        status_group.add(status_box)

        # Connection info
        self.info_label = Gtk.Label(label="")
        self.info_label.set_halign(Gtk.Align.START)
        self.info_label.set_wrap(True)
        self.info_label.add_css_class("dim-label")
        status_group.add(self.info_label)

        content.append(status_group)

        # ── Connect / Disconnect ───────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.connect_btn = Gtk.Button(label="Connect")
        self.connect_btn.add_css_class("suggested-action")
        self.connect_btn.add_css_class("pill")
        self.connect_btn.set_hexpand(True)
        self.connect_btn.connect("clicked", self.on_connect_clicked)
        btn_box.append(self.connect_btn)

        self.disconnect_btn = Gtk.Button(label="Disconnect")
        self.disconnect_btn.add_css_class("destructive-action")
        self.disconnect_btn.add_css_class("pill")
        self.disconnect_btn.set_hexpand(True)
        self.disconnect_btn.set_sensitive(False)
        self.disconnect_btn.connect("clicked", self.on_disconnect_clicked)
        btn_box.append(self.disconnect_btn)

        content.append(btn_box)

        # ── Log viewer ─────────────────────────────────────────────────
        log_group = Adw.PreferencesGroup(title="Log")

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_monospace(True)
        self.log_view.add_css_class("card")
        self.log_buffer = self.log_view.get_buffer()

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_child(self.log_view)
        log_scroll.set_min_content_height(180)
        log_scroll.set_vexpand(True)
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        log_group.add(log_scroll)
        content.append(log_group)

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(content)
        scroll.set_vexpand(True)

        box.append(scroll)
        self.win.set_content(box)

        # Load saved credentials
        self._load_credentials()

        self.win.present()

    def _draw_dot(self, area, cr, width, height):
        color = STATE_COLORS[self.state]
        r = int(color[1:3], 16) / 255
        g = int(color[3:5], 16) / 255
        b = int(color[5:7], 16) / 255
        cr.arc(width / 2, height / 2, min(width, height) / 2 - 1, 0, 6.2832)
        cr.set_source_rgb(r, g, b)
        cr.fill()

    def _open_github(self, *_):
        Gio.AppInfo.launch_default_for_uri(
            "https://github.com/imsinux/Linux-Gui-openVPN", None
        )

    # ── Credentials ────────────────────────────────────────────────────

    def _load_credentials(self):
        if CREDENTIALS_FILE.exists():
            lines = CREDENTIALS_FILE.read_text().strip().splitlines()
            if len(lines) >= 2:
                self.user_row.set_text(lines[0])
                self.pass_row.set_text(lines[1])

    def on_save_credentials(self, btn):
        user = self.user_row.get_text().strip()
        passwd = self.pass_row.get_text().strip()
        if not user or not passwd:
            self._log("Please enter both username and password.")
            return
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_FILE.write_text(f"{user}\n{passwd}\n")
        os.chmod(CREDENTIALS_FILE, 0o600)
        self._log("Credentials saved.")

    # ── Connection management ──────────────────────────────────────────

    def on_connect_clicked(self, btn):
        if self.state != State.DISCONNECTED:
            return

        user = self.user_row.get_text().strip()
        passwd = self.pass_row.get_text().strip()
        if not user or not passwd:
            self._log("Error: Enter credentials before connecting.")
            return

        # Save credentials to temp file for openvpn
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_FILE.write_text(f"{user}\n{passwd}\n")
        os.chmod(CREDENTIALS_FILE, 0o600)

        # Get selected config
        idx = self.server_row.get_selected()
        config_name = list(self.configs.keys())[idx]
        config_path = self.configs[config_name]

        self._set_state(State.CONNECTING)
        self._log(f"Connecting to {config_name}...")

        # Launch openvpn via pkexec
        cmd = [
            "pkexec", "openvpn",
            "--config", config_path,
            "--auth-user-pass", str(CREDENTIALS_FILE),
            "--management", MGMT_HOST, str(MGMT_PORT),
            "--management-query-passwords",
        ]

        self._stop_monitor.clear()

        try:
            self.ovpn_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            self._set_state(State.DISCONNECTED)
            self._log("Error: pkexec or openvpn not found.")
            return

        # Start log reader thread
        self.monitor_thread = threading.Thread(
            target=self._read_openvpn_output, daemon=True
        )
        self.monitor_thread.start()

    def on_disconnect_clicked(self, btn):
        if self.state not in (State.CONNECTING, State.CONNECTED):
            return
        self._set_state(State.DISCONNECTING)
        self._log("Disconnecting...")

        # Try management interface first for clean shutdown
        threading.Thread(target=self._send_mgmt_signal, daemon=True).start()

    def _send_mgmt_signal(self):
        """Send SIGTERM via management socket, fall back to process kill."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((MGMT_HOST, MGMT_PORT))
            # Read greeting
            s.recv(4096)
            s.sendall(b"signal SIGTERM\r\n")
            time.sleep(0.5)
            s.close()
            GLib.idle_add(self._log, "Sent SIGTERM via management interface.")
        except Exception:
            # Fallback: kill the process
            if self.ovpn_process and self.ovpn_process.poll() is None:
                try:
                    subprocess.run(
                        ["pkexec", "kill", str(self.ovpn_process.pid)],
                        timeout=10,
                    )
                except Exception:
                    pass
            GLib.idle_add(self._log, "Sent kill signal to OpenVPN process.")

    def _read_openvpn_output(self):
        """Read stdout from openvpn process and parse state changes."""
        proc = self.ovpn_process
        if not proc or not proc.stdout:
            return

        for line in proc.stdout:
            if self._stop_monitor.is_set():
                break
            line = line.rstrip("\n")
            GLib.idle_add(self._log, line)

            # Parse state transitions
            if "Initialization Sequence Completed" in line:
                GLib.idle_add(self._on_connected)
            elif "SIGTERM" in line or "process exiting" in line:
                GLib.idle_add(self._on_process_exit)
            elif "AUTH_FAILED" in line:
                GLib.idle_add(
                    self._log,
                    "Authentication failed. Check your credentials.",
                )
                GLib.idle_add(self._on_process_exit)
            elif "scramble" in line.lower() and "error" in line.lower():
                GLib.idle_add(
                    self._log,
                    "ERROR: Your openvpn build does not support 'scramble obfuscate'. "
                    "Install openvpn-xor or a patched openvpn.",
                )
            elif "Options error" in line and "scramble" in line:
                GLib.idle_add(
                    self._log,
                    "ERROR: Your openvpn does not support 'scramble obfuscate'. "
                    "Install openvpn-xor or a patched openvpn.",
                )
            # Try to capture assigned IP
            if "ifconfig" in line.lower() and "tun" in line.lower():
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.lower() == "ifconfig":
                        if i + 1 < len(parts):
                            ip_candidate = parts[i + 1]
                            if self._is_ip(ip_candidate):
                                self.assigned_ip = ip_candidate

        # Process ended
        proc.wait()
        GLib.idle_add(self._on_process_exit)

    @staticmethod
    def _is_ip(s):
        parts = s.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    def _on_connected(self):
        self.connect_time = time.time()
        self._set_state(State.CONNECTED)
        self._log("Connection established.")
        # Start status polling
        threading.Thread(target=self._poll_status, daemon=True).start()

    def _on_process_exit(self):
        if self.state == State.DISCONNECTED:
            return
        self.ovpn_process = None
        self.connect_time = None
        self.assigned_ip = None
        self.bytes_in = 0
        self.bytes_out = 0
        self._stop_monitor.set()
        self._set_state(State.DISCONNECTED)
        self._update_info()
        self._log("Disconnected.")

    def _poll_status(self):
        """Poll the management interface for status info while connected."""
        time.sleep(2)  # Give management socket time to be ready
        while self.state == State.CONNECTED and not self._stop_monitor.is_set():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((MGMT_HOST, MGMT_PORT))
                s.recv(4096)  # greeting
                s.sendall(b"status\r\n")
                time.sleep(0.3)
                data = s.recv(8192).decode("utf-8", errors="replace")
                s.close()
                self._parse_status(data)
            except Exception:
                pass
            time.sleep(5)

    def _parse_status(self, data):
        """Parse management 'status' output for bytes transferred."""
        for line in data.splitlines():
            if line.startswith("TCP/UDP read bytes,"):
                try:
                    self.bytes_in = int(line.split(",")[1])
                except (IndexError, ValueError):
                    pass
            elif line.startswith("TCP/UDP write bytes,"):
                try:
                    self.bytes_out = int(line.split(",")[1])
                except (IndexError, ValueError):
                    pass
        GLib.idle_add(self._update_info)

    # ── UI updates ─────────────────────────────────────────────────────

    def _set_state(self, new_state):
        self.state = new_state
        self.status_label.set_text(STATE_LABELS[new_state])
        self.status_dot.queue_draw()

        is_connected_or_connecting = new_state in (State.CONNECTING, State.CONNECTED)
        self.connect_btn.set_sensitive(new_state == State.DISCONNECTED)
        self.disconnect_btn.set_sensitive(is_connected_or_connecting)
        self.server_row.set_sensitive(new_state == State.DISCONNECTED)
        self.user_row.set_sensitive(new_state == State.DISCONNECTED)
        self.pass_row.set_sensitive(new_state == State.DISCONNECTED)

        self._update_info()

    def _update_info(self):
        if self.state == State.CONNECTED:
            parts = []
            if self.assigned_ip:
                parts.append(f"IP: {self.assigned_ip}")
            if self.connect_time:
                elapsed = int(time.time() - self.connect_time)
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                parts.append(f"Duration: {h:02d}:{m:02d}:{s:02d}")
            if self.bytes_in or self.bytes_out:
                parts.append(
                    f"In: {self._fmt_bytes(self.bytes_in)}  "
                    f"Out: {self._fmt_bytes(self.bytes_out)}"
                )
            self.info_label.set_text("  |  ".join(parts) if parts else "")
        else:
            self.info_label.set_text("")

    @staticmethod
    def _fmt_bytes(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def _log(self, msg):
        end_iter = self.log_buffer.get_end_iter()
        timestamp = time.strftime("%H:%M:%S")
        self.log_buffer.insert(end_iter, f"[{timestamp}] {msg}\n")
        # Auto-scroll to bottom
        mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
        self.log_view.scroll_mark_onscreen(mark)
        self.log_buffer.delete_mark(mark)


def main():
    app = VPNClient()
    app.run()


if __name__ == "__main__":
    main()
