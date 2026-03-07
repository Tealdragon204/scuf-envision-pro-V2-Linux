# Token discipline
- Use `rg` first; open only the few relevant files.
- Don’t paste full logs; quote only relevant lines.
- Avoid repo-wide scans unless necessary.
- Keep replies short unless asked.

# Key reference projects
- **OpenLinkHub** — https://github.com/jurkovic-nikola/OpenLinkHub
  Comprehensive Linux userspace driver for Corsair USB devices (iCUE ecosystem: fans, coolers, lighting hubs, etc.). Covers far more hardware than this project needs, but is the primary reference for Corsair HID/hidraw protocol work, USB control transfer patterns, and device communication. Consult it when investigating rumble packets, HID report structures, or any Corsair-specific USB behaviour.
