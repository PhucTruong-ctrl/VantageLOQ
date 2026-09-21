"""Shared hardware-access helpers for Vantage.

These functions read/write the Lenovo VPC platform sysfs attributes and the
touchpad kernel-input device. The write helpers are used by the privileged
helper (vantage_helper.py); reads are used directly by the client and are
unprivileged. Writes require root.
"""
import glob
import logging
import os

log = logging.getLogger("vantage.hardware")

VPC_GLOB = "/sys/bus/platform/devices/VPC2004:*"

# Feature key -> VPC sysfs attribute filename.
# Note: camera_power is intentionally omitted. On some models (e.g. Yoga Pro 7i
# Gen 11) the bit holds its value but does NOT actually gate the camera — that's
# done by a hardware privacy key/EC — so exposing a software toggle is misleading.
VPC_ATTRS = {
    "conservation_mode": "conservation_mode",
    "usb_charging": "usb_charging",
    "fan_mode": "fan_mode",
    "fn_lock": "fn_lock",
}

# Keyboard-backlight LED (Lenovo platform LED, e.g. platform::kbd_backlight).
KBD_LED_GLOB = "/sys/class/leds/*kbd_backlight*"


def vpc_dir():
    """Return the resolved VPC2004 device directory, or None if absent."""
    matches = glob.glob(VPC_GLOB)
    return matches[0] if matches else None


# ThinkPads expose controls via thinkpad_acpi (/proc/acpi/ibm) rather than the
# ideapad VPC2004 node. We route features by which interface is present rather
# than by DMI model — the kernel driver already normalises per-device EC quirks.
THINKPAD_PROC = "/proc/acpi/ibm"


def is_ideapad():
    """True if the ideapad_laptop VPC2004 platform device is present."""
    return vpc_dir() is not None


def is_thinkpad():
    """True if the thinkpad_acpi interface is present."""
    return os.path.isdir(THINKPAD_PROC)


def platform_family():
    """Return 'ideapad', 'thinkpad', or 'other'.

    ideapad takes precedence if both somehow resolve. Used for display only;
    feature routing is by individual interface presence, not this string.
    """
    if is_ideapad():
        return "ideapad"
    if is_thinkpad():
        return "thinkpad"
    return "other"


# Standard ACPI platform_profile — the cross-vendor performance/thermal mode.
# We read/write it directly as a fallback when power-profiles-daemon is absent;
# the firmware/EC keeps doing closed-loop thermal management, just biased.
PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
PLATFORM_PROFILE_CHOICES = "/sys/firmware/acpi/platform_profile_choices"


def read_platform_profile():
    """Return (current, [choices]) from the ACPI platform_profile, or (None, [])."""
    try:
        with open(PLATFORM_PROFILE) as fh:
            cur = fh.read().strip() or None
    except OSError:
        return None, []
    choices = []
    try:
        with open(PLATFORM_PROFILE_CHOICES) as fh:
            choices = fh.read().split()
    except OSError:
        pass
    return cur, choices


def write_platform_profile(value):
    """Write the ACPI platform_profile. Requires root. Rejects unlisted values."""
    _cur, choices = read_platform_profile()
    if choices and value not in choices:
        return False
    if not os.path.exists(PLATFORM_PROFILE):
        return False
    with open(PLATFORM_PROFILE, "w") as fh:
        fh.write(value)
    return True
# The kernel's global platform_profile interface only *reports* the firmware's
# "custom" mode — it refuses to select it (EINVAL). The EC-native powermode
# attribute of the legion driver accepts every mode, custom included, so it is
# the preferred write path when present.
POWERMODE_VALUES = {
    "low-power": 1,
    "balanced": 2,
    "performance": 3,
    "max-power": 224,
    "custom": 255,
}


def powermode_path():
    """Return the legion driver's EC powermode attribute, or None."""
    for path in sorted(glob.glob("/sys/devices/platform/*/powermode")):
        if os.path.exists(path):
            log.debug("powermode attr=%s", path)
            return path
    log.debug("powermode attr=None")
    return None


def powermode_available():
    return powermode_path() is not None


def _legion_attr(name):
    for path in sorted(glob.glob("/sys/devices/platform/*/%s" % name)):
        if os.path.exists(path):
            return path
    return None


def fan_fullspeed_available():
    return _legion_attr("fan_fullspeed") is not None


def read_fan_fullspeed():
    """Return the EC's 'both fans at full speed' flag, or None if unavailable."""
    path = _legion_attr("fan_fullspeed")
    if not path:
        return None
    try:
        with open(path) as fh:
            return fh.read().strip() == "1"
    except OSError:
        return None


def write_fan_fullspeed(enabled):
    """Force both fans to full speed (or hand them back to the curve).

    Unlike a fan-curve write this is a single EC flag the firmware honours
    directly, so it is the dependable way to spin the fans up.
    """
    path = _legion_attr("fan_fullspeed")
    if not path:
        return False
    try:
        with open(path, "w") as fh:
            fh.write("1" if enabled else "0")
    except OSError:
        log.debug("fan_fullspeed write failed")
        return False
    log.debug("fan_fullspeed -> %s", bool(enabled))
    return True


def write_powermode(name):
    """Select a thermal mode through the EC-native attribute.

    Accepts the same names as platform_profile (low-power, balanced,
    performance, max-power, custom) and returns False for anything unknown or
    unwritable, so callers never claim a mode change that did not happen.
    """
    value = POWERMODE_VALUES.get(name)
    path = powermode_path()
    if value is None or path is None:
        log.debug("powermode write refused: name=%r path=%r", name, path)
        return False
    try:
        with open(path, "w") as fh:
            fh.write(str(value))
    except OSError:
        log.debug("powermode write failed for %r", name)
        return False
    log.debug("powermode %r -> %d", name, value)
    return True


# ---- ThinkPad BIOS settings via think_lmi (firmware-attributes) --------------
# Some ThinkPad features (Always-On USB, Fn-key default) aren't exposed by
# thinkpad_acpi at all — they're BIOS settings, surfaced by the think_lmi driver
# under /sys/class/firmware-attributes/thinklmi. current_value is root-only
# (0600) so reads/writes both go through the helper; possible_values is world-
# readable, so presence detection stays unprivileged. Changes are firmware
# settings and may only take effect after a reboot.
THINKLMI = "/sys/class/firmware-attributes/thinklmi"
THINKLMI_ATTRS = THINKLMI + "/attributes"


def bios_attr_dir(attr):
    """Return the think_lmi attribute directory if present, else None."""
    path = os.path.join(THINKLMI_ATTRS, attr)
    return path if os.path.isdir(path) else None


def bios_possible_values(attr):
    """Return the allowed values for an enumeration attribute, or [] (unpriv)."""
    base = bios_attr_dir(attr)
    if not base:
        return []
    try:
        with open(os.path.join(base, "possible_values")) as fh:
            return [v for v in fh.read().strip().split(";") if v]
    except OSError:
        return []


def bios_attr_present(attr):
    """True if the BIOS attribute exists and advertises values (unprivileged)."""
    return bool(bios_possible_values(attr))


def read_bios_attr(attr):
    """Read a think_lmi attribute's current_value. Requires root; None if not."""
    base = bios_attr_dir(attr)
    if not base:
        return None
    try:
        with open(os.path.join(base, "current_value")) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def write_bios_attr(attr, value):
    """Write a think_lmi BIOS attribute's current_value. Requires root.

    Rejects values outside possible_values. May only take effect after a reboot
    (see bios_pending_reboot). Fails if a BIOS Admin password is set and no
    authentication was supplied.
    """
    base = bios_attr_dir(attr)
    if not base:
        return False
    allowed = bios_possible_values(attr)
    if allowed and value not in allowed:
        return False
    path = os.path.join(base, "current_value")
    with open(path, "w") as fh:
        fh.write(value)
    return True


def bios_pending_reboot():
    """True if a BIOS attribute change is awaiting a reboot to take effect."""
    try:
        with open(os.path.join(THINKLMI_ATTRS, "pending_reboot")) as fh:
            return fh.read().strip() == "1"
    except OSError:
        return False


def bios_admin_locked():
    """True if a BIOS Admin password is set (writes then need authentication)."""
    try:
        with open(os.path.join(THINKLMI, "authentication", "Admin",
                               "is_enabled")) as fh:
            return fh.read().strip() == "1"
    except OSError:
        return False


def vpc_path(attr):
    base = vpc_dir()
    if not base:
        return None
    path = os.path.join(base, attr)
    return path if os.path.exists(path) else None


def read_attr(attr):
    """Read a VPC attribute as a stripped string, or None if unavailable."""
    path = vpc_path(attr)
    if not path:
        log.debug("vpc attr %r: not present", attr)
        return None
    try:
        with open(path) as fh:
            val = fh.read().strip()
        log.debug("vpc attr %r = %r", attr, val)
        return val
    except OSError as exc:
        log.debug("vpc attr %r: read error: %s", attr, exc)
        return None


def write_attr(attr, value):
    """Write a value to a VPC attribute. Requires root. Returns True on success."""
    path = vpc_path(attr)
    if not path:
        return False
    with open(path, "w") as fh:
        fh.write(str(value))
    return True


def touchpad_inhibit_path():
    """Locate the touchpad's kernel-input 'inhibited' attribute (Wayland-safe)."""
    for name_file in glob.glob("/sys/class/input/event*/device/name"):
        try:
            with open(name_file) as fh:
                name = fh.read().strip()
        except OSError:
            continue
        if "touchpad" in name.lower():
            return os.path.join(os.path.dirname(name_file), "inhibited")
    return None


def read_touchpad_inhibited():
    path = touchpad_inhibit_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def write_touchpad_inhibited(value):
    path = touchpad_inhibit_path()
    if not path:
        return False
    with open(path, "w") as fh:
        fh.write("1" if value else "0")
    return True


DMI_DIR = "/sys/class/dmi/id"


def read_dmi(field):
    """Read a DMI/SMBIOS field (e.g. product_version). Returns None if missing.

    Note: *_serial and *_uuid fields are root-only (mode 0400); reading those
    requires running through the privileged helper.
    """
    try:
        with open(os.path.join(DMI_DIR, field)) as fh:
            val = fh.read().strip()
        return val or None
    except OSError:
        return None


def read_dmi_serial():
    """Read the system serial number (root-only). Returns None if unavailable."""
    return read_dmi("product_serial")


# ---- Model-specific thermal routing ------------------------------------------
# On some Lenovo models the VPC2004 fan_mode attribute exists and accepts writes
# but does not persist them: writing "4" and reading it straight back returns 0.
# The ACPI platform_profile is the authoritative persistent thermal mode there,
# so the generic fan_mode selector is suppressed (see use_platform_thermal_profile).
# Low-level model detection is kept separate from the capability decision so more
# models can join the set without any UI changes.
def machine_type():
    """Return the Lenovo DMI machine type (product_name), e.g. '83GS'."""
    return read_dmi("product_name")


def is_loq_15iax9():
    """True on a Lenovo LOQ 15IAX9 (DMI machine type 83GS)."""
    return machine_type() == "83GS"


def platform_profile_provider():
    for path in sorted(glob.glob("/sys/class/platform-profile/platform-profile-*/name")):
        try:
            with open(path) as fh:
                name = fh.read().strip()
            if name:
                log.debug("platform profile provider=%r", name)
                return name
        except OSError:
            continue
    log.debug("platform profile provider=None")
    return None


def use_platform_thermal_profile():
    """Return whether the generic platform-profile backend is available."""
    provider = platform_profile_provider()
    use_profile = (provider is not None
                   and provider.lower() == "lenovo-legion"
                   and os.path.exists(PLATFORM_PROFILE))
    log.debug("DMI product_name=%r product_version=%r provider=%r -> thermal backend: %s",
              machine_type(), read_dmi("product_version"), provider,
              "platform_profile" if use_profile else "fan_mode")
    return use_profile


def fan_curve_dir():
    for name_path in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
        directory = os.path.dirname(name_path)
        try:
            with open(name_path) as fh:
                name = fh.read().strip()
            if (name == "legion_hwmon"
                    and os.path.exists(os.path.join(directory, "pwm1_auto_point1_pwm"))
                    and os.path.exists(os.path.join(directory, "pwm2_auto_point1_pwm"))):
                log.debug("fan curve dir=%s", directory)
                return directory
        except OSError:
            continue
    log.debug("fan curve dir=None")
    return None


CURVE_FIELDS = ("fan1_pwm", "fan2_pwm", "cpu_temp", "cpu_hyst", "gpu_temp", "gpu_hyst")


def read_fan_curve():
    directory = fan_curve_dir()
    if not directory:
        return []
    points = []
    try:
        for point in range(1, 11):
            values = {}
            for key, prefix, suffix in (
                ("fan1_pwm", "pwm1", "pwm"), ("fan2_pwm", "pwm2", "pwm"),
                ("cpu_temp", "pwm1", "temp"), ("cpu_hyst", "pwm1", "temp_hyst"),
                ("gpu_temp", "pwm2", "temp"), ("gpu_hyst", "pwm2", "temp_hyst")):
                with open(os.path.join(directory, "%s_auto_point%d_%s" %
                                       (prefix, point, suffix))) as fh:
                    values[key] = int(fh.read().strip())
            points.append(values)
    except (OSError, ValueError):
        log.debug("fan curve read failed")
        return []
    log.debug("fan curve read count=%d", len(points))
    return points


def write_fan_curve(points, attempts=3):
    """Write the curve and verify the EC kept it.

    The driver's hwmon store is read-modify-write *per attribute*: every single
    write re-reads the whole curve from the EC and writes it all back, so a
    later attribute can revert an earlier one from a stale read. Measured on a
    LOQ 15IAX9, that silently drops some points while the store still returns
    success. So the write is retried and then verified against the readback:
    this returns True only when every value that actually needed changing stuck.
    """
    try:
        if not isinstance(points, list) or len(points) != 10:
            raise ValueError("expected 10 points")
        for index, point in enumerate(points):
            if not isinstance(point, dict) or any(key not in point for key in CURVE_FIELDS):
                raise ValueError("missing curve field")
            values = {key: int(point[key]) for key in CURVE_FIELDS}
            if not (0 <= values["fan1_pwm"] <= 255 and 0 <= values["fan2_pwm"] <= 255):
                raise ValueError("PWM out of range")
            for key in ("cpu_temp", "cpu_hyst", "gpu_temp", "gpu_hyst"):
                if not 0 <= values[key] <= 127:
                    raise ValueError("temperature out of range")
            if values["cpu_hyst"] > values["cpu_temp"] or values["gpu_hyst"] > values["gpu_temp"]:
                raise ValueError("hysteresis exceeds temperature")
            if index and (values["cpu_temp"] < previous["cpu_temp"]
                          or values["gpu_temp"] < previous["gpu_temp"]):
                raise ValueError("temperatures not monotonic")
            previous = values
        directory = fan_curve_dir()
        if not directory:
            raise OSError("curve unavailable")

        before = read_fan_curve()
        if len(before) != 10:
            raise OSError("curve unavailable")
        # Only fields the caller actually changes can be verified: an unchanged
        # field may legitimately read back as anything the EC already had.
        intended = [(index, key) for index, point in enumerate(points)
                    for key in CURVE_FIELDS
                    if _curve_close(int(point[key]), before[index][key]) is False]

        for attempt in range(max(1, attempts)):
            for index, point in enumerate(points, 1):
                for key, prefix, suffix in (
                    ("fan1_pwm", "pwm1", "pwm"), ("fan2_pwm", "pwm2", "pwm"),
                    ("cpu_temp", "pwm1", "temp"), ("cpu_hyst", "pwm1", "temp_hyst"),
                    ("gpu_temp", "pwm2", "temp"), ("gpu_hyst", "pwm2", "temp_hyst")):
                    with open(os.path.join(directory, "%s_auto_point%d_%s" %
                                           (prefix, index, suffix)), "w") as fh:
                        fh.write(str(int(point[key])))
            if not intended:
                return True
            after = read_fan_curve()
            if len(after) != 10:
                continue
            missing = [(index, key) for index, key in intended
                       if _curve_close(int(points[index][key]),
                                       after[index][key]) is False]
            if not missing:
                return True
            log.debug("fan curve attempt %d: EC ignored %s", attempt + 1, missing)
    except (OSError, ValueError, TypeError):
        log.debug("fan curve write rejected")
        return False
    return False


def _curve_close(want, got):
    """True if `got` is the EC's stored form of `want`.

    Fan speeds are stored as RPM/100 (unit 3, 10000 RPM full scale), so a PWM
    request comes back quantised; anything else must match exactly.
    """
    if want == got:
        return True
    speed = min(255, (want * 10000 + 100 * 255 - 1) // (100 * 255))
    return abs(speed * 255 * 100 // 10000 - got) <= 2


def fan_curve_available():
    return bool(fan_curve_dir())


def read_fan_rpms():
    """Return [(label, rpm_int), ...] for every readable hwmon fan, or [].

    Lenovo laptops expose fan tachometers via a hwmon node (e.g.
    'lenovo_wmi_other' with fan1_input/fan2_input). Empty/non-numeric inputs
    (such as acpi_fan's stub) are skipped. Unprivileged.
    """
    fans = []
    inputs = sorted(glob.glob("/sys/class/hwmon/hwmon*/fan*_input"))
    log.debug("hwmon fan inputs found: %s", inputs or "(none)")
    for inp in inputs:
        try:
            with open(inp) as fh:
                txt = fh.read().strip()
            rpm = int(txt)
        except (OSError, ValueError):
            continue
        label = None
        try:
            with open(inp[:-len("_input")] + "_label") as fh:
                label = fh.read().strip() or None
        except OSError:
            pass
        log.debug("fan %s: %r = %d RPM", inp, label, rpm)
        fans.append((label, rpm))
    if not fans:
        log.debug("no readable fan RPM sensors found")
    return fans


BATTERY_GLOB = "/sys/class/power_supply/BAT*"


def _read_int(path):
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def read_battery():
    """Return a dict of battery health/status, or None if no battery.

    health_pct = energy_full / energy_full_design (charge_* on batteries that
    report in charge units). All unprivileged sysfs reads.
    """
    matches = sorted(glob.glob(BATTERY_GLOB))
    base = matches[0] if matches else None
    if not base:
        return None
    info = {}
    for full, design in (("energy_full", "energy_full_design"),
                         ("charge_full", "charge_full_design")):
        f = _read_int(os.path.join(base, full))
        d = _read_int(os.path.join(base, design))
        if f and d:
            info["health_pct"] = f / d * 100.0
            break
    cyc = _read_int(os.path.join(base, "cycle_count"))
    if cyc is not None:
        info["cycle_count"] = cyc
    for key in ("capacity", "status"):
        try:
            with open(os.path.join(base, key)) as fh:
                info[key] = fh.read().strip()
        except OSError:
            pass
    return info or None


# ---- ThinkPad manual fan control (thinkpad_acpi) -----------------------------
# Mirrors thinkfan's mechanism: write "level <N>" to /proc/acpi/ibm/fan plus a
# "watchdog" dead-man's-switch so the EC reverts to "auto" if we stop writing.
# Gated by the fan_control=1 module param, which is off by default for safety —
# so the control self-hides on machines where manual control isn't permitted.
IBM_FAN = os.path.join(THINKPAD_PROC, "fan")
FAN_CONTROL_PARAM = "/sys/module/thinkpad_acpi/parameters/fan_control"
FAN_WATCHDOG_SECS = 120
# Writable fan levels, in display order: Auto, 0-7, then unthrottled full-speed.
FAN_LEVELS = ["auto", "0", "1", "2", "3", "4", "5", "6", "7", "full-speed"]


def fan_control_enabled():
    """True if thinkpad_acpi was loaded with fan_control=1 (writes permitted)."""
    try:
        with open(FAN_CONTROL_PARAM) as fh:
            return fh.read().strip() in ("Y", "1")
    except OSError:
        return False


def fan_writable():
    """True if manual ThinkPad fan control is present and permitted."""
    return os.path.exists(IBM_FAN) and fan_control_enabled()


def read_fan_level():
    """Return the current fan level string from /proc/acpi/ibm/fan, or None.

    The 'level:' line reports 'auto', '0'-'7', 'disengaged', or 'full-speed';
    'disengaged' is normalised to its writable spelling 'full-speed'.
    """
    try:
        with open(IBM_FAN) as fh:
            for line in fh:
                if line.startswith("level:"):
                    val = line.split(":", 1)[1].strip()
                    return "full-speed" if val == "disengaged" else val
    except OSError:
        pass
    return None


def write_fan_level(level):
    """Set the ThinkPad fan level via /proc/acpi/ibm/fan. Requires root.

    Borrows thinkfan's safety model: a manual level also arms the EC watchdog,
    so if no further write arrives within FAN_WATCHDOG_SECS the firmware reverts
    the fan to 'auto'. Selecting 'auto' clears the watchdog. Returns False if the
    level is unknown or manual control isn't permitted.
    """
    if level not in FAN_LEVELS or not fan_writable():
        return False
    with open(IBM_FAN, "w") as fh:
        fh.write("level %s" % level)
    # Arm (manual) or clear (auto) the dead-man's-switch watchdog. Best-effort:
    # not all firmware exposes it, so a failure here doesn't fail the level set.
    try:
        with open(IBM_FAN, "w") as fh:
            fh.write("watchdog %d" % (0 if level == "auto" else FAN_WATCHDOG_SECS))
    except OSError:
        pass
    return True


CHARGE_START_ATTR = "charge_control_start_threshold"
CHARGE_END_ATTR = "charge_control_end_threshold"


def _battery_dir():
    matches = sorted(glob.glob(BATTERY_GLOB))
    return matches[0] if matches else None


def charge_thresholds():
    """Return (start, end) charge-control thresholds as ints, or None.

    ThinkPads (thinkpad_acpi) expose user-settable battery charge limits via the
    standard power_supply attrs. Returns None when the attrs are absent (e.g. on
    ideapads, which use conservation_mode instead). All reads unprivileged.
    """
    base = _battery_dir()
    if not base:
        return None
    start = _read_int(os.path.join(base, CHARGE_START_ATTR))
    end = _read_int(os.path.join(base, CHARGE_END_ATTR))
    if end is None:
        return None
    return (start if start is not None else 0, end)


def write_charge_thresholds(start, end):
    """Write the battery charge start/end thresholds. Requires root.

    The kernel enforces start <= end, so writes are ordered to keep the
    invariant satisfied at every intermediate step: when lowering the window,
    drop start first; when raising it, raise end first. Values clamped to 0-100.
    """
    base = _battery_dir()
    if not base:
        return False
    start = max(0, min(100, int(start)))
    end = max(0, min(100, int(end)))
    if start > end:
        start = end
    start_path = os.path.join(base, CHARGE_START_ATTR)
    end_path = os.path.join(base, CHARGE_END_ATTR)
    cur = charge_thresholds()
    # Lowering end below the current start would transiently violate start<=end,
    # so push start down first; otherwise raise end first.
    if cur is not None and end < cur[0]:
        order = ((start_path, start), (end_path, end))
    else:
        order = ((end_path, end), (start_path, start))
    ok = False
    for path, value in order:
        if not os.path.exists(path):
            continue
        with open(path, "w") as fh:
            fh.write(str(value))
        ok = True
    return ok


def kbd_led_dir():
    """Return the keyboard-backlight LED directory, or None if absent."""
    matches = glob.glob(KBD_LED_GLOB)
    return matches[0] if matches else None


def read_kbd_backlight():
    """Return (brightness, max_brightness) as strings, or (None, None)."""
    base = kbd_led_dir()
    if not base:
        return None, None
    try:
        with open(os.path.join(base, "brightness")) as fh:
            cur = fh.read().strip()
        with open(os.path.join(base, "max_brightness")) as fh:
            mx = fh.read().strip()
        return cur, mx
    except OSError:
        return None, None


def write_kbd_backlight(value):
    """Set the keyboard-backlight brightness. Requires root. Clamped to [0, max]."""
    base = kbd_led_dir()
    if not base:
        return False
    try:
        with open(os.path.join(base, "max_brightness")) as fh:
            mx = int(fh.read().strip())
    except (OSError, ValueError):
        mx = None
    level = int(value)
    if level < 0:
        level = 0
    if mx is not None and level > mx:
        level = mx
    with open(os.path.join(base, "brightness"), "w") as fh:
        fh.write(str(level))
    return True
