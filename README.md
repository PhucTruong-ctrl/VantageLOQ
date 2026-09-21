# Lenovo Vantage for Linux

A native GTK4 app that brings Lenovo Vantage controls to Linux — battery conservation, fan modes, thermal profiles, keyboard backlight, and more. Works across IdeaPad, Yoga, and Legion models.

![preview](images/preview.png)

## Features

**Power & Battery**
- Conservation Mode — cap charge at ~80% to extend battery lifespan
- Always-On USB — keep USB ports powered while suspended
- Power Profile — Low Power / Balanced / Performance (via `power-profiles-daemon`)
- Battery Health — shows capacity vs. design capacity, charge cycles, and current charge

**Thermal**
- Thermal Mode — Low Power, Balanced, Performance, Max Power, Custom (whichever the firmware advertises)
- Live fan RPM readout for both fans
- **Maximum Fan Speed** — forces both fans to full speed through the EC's own
  `fan_fullspeed` flag when the legion driver exposes it; the dependable way to
  spin the fans up on demand
- Optional **Tune** button for editing a ten-point fan curve when the kernel exposes writable `legion_hwmon` curve controls

**Graphics** (NVIDIA Optimus laptops)
- Graphics Mode — lock the machine to the integrated GPU (*Integrated*, blacklists
  the NVIDIA modules and powers the dGPU off via udev), or restore *Hybrid* so apps
  can render on the dGPU on demand. Wayland-only.

  > **Reboot required.** Switching modes rewrites a modprobe blacklist + udev rule
  > and rebuilds the initramfs, so the change only takes effect after a reboot. To
  > go back, pick the other mode in the app and reboot again — *Hybrid* removes the
  > files vantage added and restores the distro default. The initramfs rebuild is
  > distro-agnostic (works with `update-initramfs`, `mkinitcpio`/`limine-mkinitcpio`,
  > `dracut`, and `booster`); in *Integrated* mode CUDA/NVENC/PRIME offload are
  > unavailable until you switch back.

**Input**
- Fn Lock — use multimedia keys without holding Fn
- Keyboard Backlight — set illumination level
- Touchpad toggle — Wayland-native via kernel `inhibited` attribute

**Privacy & Network**
- Microphone mute via `pactl`
- Wi-Fi toggle via `nmcli`

**About**
- Device info panel — model, CPU, RAM, OS, serial number

Controls auto-hide when the underlying hardware isn't present, so the same app works across different Lenovo models. The Graphics Mode control appears only when an NVIDIA dGPU is detected. Legion-only controls (Super key lock, fast charge, display overdrive) appear automatically when the `LenovoLegionLinux` kernel module is loaded.

> **Note:** Camera privacy is not controlled in software. On many models (e.g. Yoga Pro 7i Gen 11) the `camera_power` sysfs bit is cosmetic and doesn't actually gate the sensor — use the laptop's physical camera key instead, which is EC-backed.

## Installation

Vantage uses the [Meson](https://mesonbuild.com/) build system, the standard
for GTK/GNOME applications.

```bash
git clone https://github.com/isshin1/vantage.git
cd vantage
./install.sh                 # install runtime + build dependencies
meson setup build
sudo meson install -C build
```

Then launch **Lenovo Vantage** from your applications menu, or run `vantage` from the terminal.

### Command-line options

```
vantage [-h] [-t] [-d] [-v]

  -h, --help     show this help message and exit
  -t, --tray     start minimised to the system tray (no window)
  -d, --debug    enable verbose debug logging to stderr
  -v, --version  show the version and exit
```

Run with no options to open the settings window.

### Manual dependency install

`./install.sh` handles dependencies automatically. If you prefer to install them yourself, you need the runtime libraries plus the build tools (`meson`, `ninja`, `gettext`, and the GLib schema/AppStream utilities):

**Arch Linux**
```bash
sudo pacman -S python-gobject gtk4 libadwaita polkit networkmanager \
               meson ninja gettext glib2 appstream
```

**Debian / Ubuntu / Mint / Pop!_OS**
```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 policykit-1 \
                 meson ninja-build gettext libglib2.0-bin appstream
```

**Fedora**
```bash
sudo dnf install python3-gobject gtk4 libadwaita polkit NetworkManager pipewire-pulseaudio \
                 meson ninja-build gettext glib2-devel appstream
```

**openSUSE Tumbleweed**
```bash
sudo zypper install python3-gobject gtk4 libadwaita typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 \
                    polkit NetworkManager pipewire-pulseaudio meson ninja gettext-tools \
                    glib2-tools appstream
```

## Uninstall

```bash
sudo ninja -C build uninstall
```

## Architecture

Vantage ships two executables backed by a shared Python package:

- **`vantage`** — GTK4 + libadwaita settings window with grouped switch/combo rows for every control. The system-tray icon is built in (no separate process or daemon).
- **`vantage-helper`** — a minimal root helper that performs privileged sysfs writes. Invoked via `pkexec`, gated by polkit (`auth_admin_keep`) — you authenticate once per session, not per change. No long-running daemon.

State is read directly from sysfs (no root needed for reads). Unprivileged operations (microphone, Wi-Fi, power profile) run with no prompt. The *Run in Background* preference is persisted with GSettings.

### Project layout

```
vantage/
├── meson.build              # top-level build definition
├── data/                    # desktop entry, AppStream metainfo, GSettings
│   ├── org.vantage.Vantage.desktop.in
│   ├── org.vantage.Vantage.metainfo.xml.in
│   ├── org.vantage.Vantage.gschema.xml
│   ├── org.vantage.helper.policy.in
│   └── icons/               # hicolor app + symbolic icons
├── src/
│   ├── vantage.in           # launcher → /usr/bin/vantage
│   ├── vantage-helper.in    # privileged launcher → /usr/bin/vantage-helper
│   └── vantage/             # importable Python package
│       ├── main.py          # entry point + GApplication
│       ├── window.py        # GTK4 settings window
│       ├── client.py        # backend facade + GSettings config
│       ├── hardware.py      # low-level sysfs access
│       ├── tray.py          # SNI tray + dbusmenu
│       └── helper.py        # whitelisted privileged writes
└── po/                      # gettext translation catalogs
```

The app ID is `org.vantage.Vantage`; the *Run in Background* preference is stored
in GSettings under that schema.

### Running from source

Because the preference lives in GSettings, an uninstalled run needs the schema
compiled and on the schema path:

```bash
glib-compile-schemas data
GSETTINGS_SCHEMA_DIR=$PWD/data PYTHONPATH=$PWD/src python3 -m vantage.main
```

**System tray:** enable *Run in Background* in the app settings. When active, closing the window hides it to a tray icon; left-click toggles the window; right-click shows a full quick-toggle menu. The tray is implemented via the `org.kde.StatusNotifierItem` D-Bus protocol and works on KDE, Hyprland + Waybar, Sway, and any compositor with SNI support. Run `vantage --tray` to start directly in the background without showing the window.

## Requirements

**Runtime**
- Python 3 + `python-gobject`
- GTK4 + libadwaita
- `polkit` / `pkexec`
- `networkmanager`
- `pulseaudio` or `pipewire-pulse`
- `power-profiles-daemon` *(optional — required for Power Profile control)*
- a StatusNotifierItem host *(optional — required for the system tray; e.g. KDE, Waybar)*

**Build**
- `meson` + `ninja`
- `gettext`
- `glib2` schema tools (`glib-compile-schemas`)
- `appstream` *(optional — used to validate the metainfo)*

## Tested hardware

- **Lenovo LOQ 15IAX9 (machine type 83GS)** — Kernel DMI reports
  `product_name=83GS` and `product_version=LOQ 15IAX9`. This is the tested
  hardware; compatible LOQ and Legion models may expose the same capabilities.

  When `/sys/class/platform-profile/platform-profile-*/name` reports
  `lenovo-legion` and the platform-profile files are readable, Vantage selects
  **Thermal Mode** through that generic provider rather than a hard-coded
  machine-type list. It offers every value advertised by
  `/sys/firmware/acpi/platform_profile_choices`; on the tested machine those
  values are `low-power`, `balanced`, `performance`, `max-power`, and `custom`.

  The legacy Fan Mode selector is hidden when this platform-profile capability
  is present. Machines without it retain the existing `fan_mode` behaviour;
  this is capability-specific, not a global change. Fan 1 / Fan 2 RPM
  telemetry remains available independently.

  The **Tune** button appears only when a readable `legion_hwmon` hwmon node
  exposes writable `pwm*_auto_point*_...` controls. Its editor covers ten
  CPU/GPU curve points, maximum temperatures, hysteresis, and fan PWM values;
  it validates temperatures, hysteresis, and PWM ranges before applying through
  the privileged helper. Models without those controls keep telemetry but do
  not show Tune and do not gain custom-curve support.

### Thermal Mode ownership

The platform-profile interface is provided by the out-of-tree **legion_laptop**
kernel module (LenovoLegionLinux DKMS). Each write is forwarded to the embedded
controller through WMI (`SETSMARTFANMODE`); the firmware/EC performs the
closed-loop thermal management.

If **power-profiles-daemon** is running, it mirrors this node. It notices
external changes within a few seconds and adopts the standard profiles
(`balanced`, `performance`, and `low-power` as its power-saver profile), but
cannot represent `max-power` or `custom`. It logs a warning and keeps
reporting its previous profile for those values, and does not write the node
back in this configuration. It is therefore not the source of truth, and
Vantage does not round-trip those values through it.

Reads are live reads of the embedded controller — the kernel module issues a
`GETSMARTFANMODE` WMI call per read — so the profile can change without any
userspace writer at all: the Fn+Q hotkey is handled by the firmware/EC itself
and never shows up as a profile write in the kernel log. Vantage therefore
reads the raw kernel value on every refresh and writes through the privileged
helper, and caches nothing: Fn+Q and any other external change appear as-is
after a refresh or when the window is reopened.

`custom` is advertised in `platform_profile_choices`, but the global
platform-profile interface refuses to select it (`EINVAL`): it is a reported
state meaning that no standard profile currently represents the settings, not
a selectable one. Vantage still lists it because it can be the reported
current state, and shows a toast if the kernel rejects the selection.

When the legion driver exposes its EC-native `powermode` attribute, Vantage
selects thermal modes through it because the generic `platform_profile`
interface cannot select `custom`. A custom fan curve is kept only in Custom
thermal mode; the EC silently discards curve writes in other modes. Applying
a fan curve therefore switches to Custom mode first, and the editor reports
failure if that mode cannot be established. The live mode is always read back from
the kernel, so the selector shows `custom` once Custom mode is active.

Even in Custom mode the kernel's curve interface is read-modify-write *per
attribute*: every single write re-reads the whole curve from the EC and writes
it all back, so a later attribute can revert an earlier one from a stale read.
Measured on the tested machine, some points are silently dropped this way while
the sysfs write still returns success. Vantage therefore writes, re-reads,
retries, and verifies the result, and the editor reloads the stored curve after
Apply — it reports success only for changes the EC actually kept. Fan speeds are
stored as RPM/100, so a PWM value comes back quantised by a few units.

The kernel exposes only the profile selector on this machine, plus the optional
`legion_hwmon` fan-curve controls described above. Vantage does not invent
fan-curve, CPU-limit, or GPU-TGP mappings for `custom`; curve editing is
available only when those controls are actually exposed and writable.
