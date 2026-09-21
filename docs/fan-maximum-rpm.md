# Lenovo LOQ fan maximum RPM

## Short answer

No: `fan1_max`/`fan2_max` showing **10000 RPM does not establish a 10,000-RPM hardware maximum**, and the observed 2600 RPM is not proven to be the model maximum. The installed driver hard-codes `MAX_RPM 10000` and its `fan_max()` show function always prints that constant ([`legion-laptop.c`, lines 2334, 5569–5573](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L2334-L2339)); it is a scale/advertised value, not a tachometer measurement. Determine this machine’s practical maximum by observing `fan1_input` and `fan2_input` under sustained, repeatable load until both plateau.

## What the attributes mean

The Linux hwmon ABI defines `fanY_input` as the measured fan speed in RPM, read-only, and `fanY_max` as a fan maximum value in RPM, “only rarely supported by the hardware” ([kernel ABI](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/ABI/testing/sysfs-class-hwmon), `fanY_max`/`fanY_input` entries). It defines `fanY_target` as the desired RPM and says it only makes sense for closed-loop control based on measured speed (same source, `fanY_target` entry).

This driver exposes `fan1_input`/`fan2_input` as read-only sensors and `fan1_target`/`fan2_target` as read-only attributes ([`legion-laptop.c`, lines 5514–5528, 5546–5565](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L5514-L5565)). It reads the current RPM from EC registers ([lines 2843–2866](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L2843-L2866)); targets are separate EC values multiplied by 100 ([lines 2791–2807](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L2791-L2807)). Thus the observed `fan*_target=0` means this target register currently reports zero; it is not evidence that the fan is stopped or that 2600 RPM is a target. The ABI cautions that targets are meaningful only with closed-loop target control.

## What `fan*_max` means here

The driver declares both max files, but their show function returns only `MAX_RPM` ([`legion-laptop.c`, lines 5569–5573, 5820–5821, 6091–6093](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L5569-L5573)). `MAX_RPM` is 10000 ([lines 2334–2339](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L2334-L2339)). For LOQ fan curves the driver selects `FAN_SPEED_UNIT_RPM_HUNDRED` ([lines 3482–3493](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L3482-L3493), and converts between an 8-bit controller value and RPM using the fixed 10000 constant ([lines 2430–2439, 2467–2479](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L2430-L2479)). Therefore 10000 is the driver’s conversion ceiling/scale, not a measured specification for the LOQ 15IAX9 fan.

## `fan_fullspeed` and `fan_maxspeed`

`fan_fullspeed` is a vendor control state. The source comments identify WMI methods 1/2 as setting the fan to maximal speed/dust-cleaning mode and note it only works in custom power mode ([`legion-laptop.c`, lines 1891–1898](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L1891-L1898)). On WMI3 models it goes through the “other method” feature `OtherMethodFeature_FAN_FULLSPEED` ([lines 3745–3761](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L3745-L3761)); the generic dispatcher selects EC, WMI, or WMI3 according to model configuration ([lines 3764–3797](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L3764-L3797)). The sysfs getter reports the returned state, not RPM ([lines 4926–4940](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L4926-L4940)). “Enabled” therefore means the controller was commanded into its full-speed mode; it does **not** prove a particular RPM, nor that the command bypasses every EC/thermal limitation.

`fan_maxspeed` is a different WMI attribute. Method ID 3 is named “max speed of fan” ([lines 1891–1899](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L1891-L1899), exposed by `fan_maxspeed_show()` at lines 4965–4971 ([source](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L4965-L4971)). The helper executes a no-argument WMI method, multiplies the returned integer by scale 1, and prints it ([lines 2725–2750, 4357–4375](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L2725-L2750)). Thus this machine’s `fan_maxspeed=0` is the firmware/WMI response to that method, not proof that the physical fans have zero maximum. No primary upstream documentation available in the installed 1.0.0 source assigns a model-specific RPM meaning to a zero response; treat its meaning as **[UNVERIFIED]**.

## How to determine the maximum empirically

Use only reads. First identify the hwmon node by name, then sample both tachometers:

```sh
for h in /sys/class/hwmon/hwmon*; do
  [ "$(cat "$h/name" 2>/dev/null)" = legion_hwmon ] && H="$h"
done
printf 'node=%s fullspeed=%s maxspeed=%s\n' "$H" \
  "$(cat /sys/devices/platform/legion/fan_fullspeed)" \
  "$(cat /sys/devices/platform/legion/fan_maxspeed 2>/dev/null || echo unavailable)"
while sleep 1; do
  date +%T
  printf 'fan1=%s fan2=%s target1=%s target2=%s\n' \
    "$(cat "$H/fan1_input")" "$(cat "$H/fan2_input")" \
    "$(cat "$H/fan1_target")" "$(cat "$H/fan2_target")"
done
```

Run the sampler while applying a sustained CPU/GPU workload using your normal, known-safe load tool; do not write any sysfs control. Repeat with the machine on AC and with the desired power/thermal profile, because the kernel platform-profile API describes profiles as affecting performance, temperature, fan and other hardware characteristics, and explicitly says achieved performance can be limited by heat, airflow and other conditions ([kernel platform-profile documentation](https://www.kernel.org/doc/Documentation/userspace-api/sysfs-platform_profile.rst)). The practical maximum is the highest stable plateau reached by each `fan*_input` under a stated configuration and adequate duration—not `fan*_max`. A higher plateau under another profile/load would show that the earlier reading was policy-limited; a repeatable plateau near 2600 RPM would support 2600 RPM as the observed maximum for that test setup, but not as a universal factory specification.

## How to tell whether they are at maximum now

Read `fan_fullspeed`, both `fan*_input`, and the workload/profile context together. `fan_fullspeed=1` says the vendor full-speed mode is enabled; current RPM still comes from the EC tachometer, so compare the live `fan*_input` with the previously measured plateau for the same AC/profile/load condition. Do not compare it with `fan*_max=10000`: that value is the driver’s fixed scale. `fan*_target=0` cannot answer the question because the ABI target is only meaningful for closed-loop target control, and this driver reads the target registers independently of the current tachometer.

## Power-button LED colour

The installed driver's documented mode colours are balanced **white**, performance **red**, quiet **blue**, and custom **pink** ([`legion-laptop.c`, lines 25–33](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L25-L33)). This is the only primary-source colour mapping found; no upstream LenovoLegionLinux or Lenovo document located here verifies a separate purple mapping for this LOQ model, so “Custom should be purple” is **[UNVERIFIED]**.

The driver's LED sysfs class devices are not a power-button LED: this machine exposes `platform::ioport` and `platform::kbd_backlight` under `/sys/devices/platform/legion/leds/` (read-only inventory). Source names the additional lights `platform::ylogo` and `platform::ioport`, and initializes them with WMI light IDs 0x03 and 0x05 ([`legion-laptop.c`, lines 4046–4051, 6634–6644](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L4046-L4051)); keyboard backlight is `platform::kbd_backlight` ([lines 6346–6355](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L6346-L6355)). All three brightness paths call WMI GUID `8C5B9127-ECD4-4657-980F-851019F99CA5`, methods `0x1` (get) and `0x2` (set) ([lines 1910–1913, 4053–4107](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L1910-L1913)).

The driver maps WMI custom mode 255 to `PLATFORM_PROFILE_CUSTOM` and max-power 224 to `PLATFORM_PROFILE_MAX_POWER` ([`legion-laptop.c`, lines 3812–3818, 3829–3833, 5290–5305](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L3812-L3818)); it does not implement a mode-to-power-button-LED colour callback. Therefore a pink-looking LED while readback is custom is compatible with the source's “custom (pink)” mapping. Whether firmware reuses that colour, displays pink identically to max-power, or whether custom inherits max-power limits when no custom limits are configured is **[UNVERIFIED]** by these sources; the driver only exposes separate mode values and optional custom fan-curve/power-limit controls, not a proof of inheritance.

### Can the colour be set from software?

No — with the interfaces this driver exposes, the colour is not addressable:

- The WMI light interface (`8C5B9127-ECD4-4657-980F-851019F99CA5`, methods `0x1` get / `0x2` set) is **brightness-only**; `legion_wmi_light_set()` writes a single brightness byte ([`legion-laptop.c`, lines 4083–4107](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L4083-L4107)). No colour parameter exists.
- Only three light IDs are defined — keyboard `0x00`, `ylogo` `0x03`, `ioport` `0x05` ([lines 4046–4051](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L4046-L4051)) — and only those become LED class devices ([lines 6408–6440](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L6408-L6440)). No power-button light ID is defined, so no `/sys/class/leds` node can reach it.
- The EC mode values the driver writes are `QUIET=2`, `BALANCED=0`, `PERFORMANCE=1`, `CUSTOM=3`, `EXTREME=7` ([lines 3804–3810](file:///usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c#L3804-L3810)); the LED colour is a firmware reaction to those values, and no mode in the documented palette is purple.

So the LED is a firmware status indicator, not an RGB device: the colour follows the mode the EC is in, and “purple” is not in this EC's documented palette. Changing it would require Lenovo firmware behaviour, not a userspace write. Probing undefined light IDs through raw WMI (e.g. `acpi_call`) is unsupported, changes brightness at best, and writes to the EC — not recommended.

## Sources

- Installed LenovoLegionLinux 1.0.0: `/usr/src/LenovoLegionLinux-1.0.0/legion-laptop.c`, cited line ranges above.
- Linux hwmon ABI: https://raw.githubusercontent.com/torvalds/linux/master/Documentation/ABI/testing/sysfs-class-hwmon
- Linux hwmon sysfs interface: https://www.kernel.org/doc/Documentation/hwmon/sysfs-interface
- Linux platform-profile userspace API: https://www.kernel.org/doc/Documentation/userspace-api/sysfs-platform_profile.rst
