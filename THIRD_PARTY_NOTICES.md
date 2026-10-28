# Third-party sources and notices

The root MIT license covers this project's original code. It does not replace upstream licenses, hardware-vendor terms or font licenses.

| Component | Source/version | Treatment |
|---|---|---|
| MKLink shared backend | [MicroKeen/Mklink-AI-Probe](https://github.com/MicroKeen/Mklink-AI-Probe), commit `3cc474bbaf4ac511945829fa554875d75a6f9112` | MIT at this exact commit; original copyright retained. Source fetched separately; Remote patch and adapters are maintained here. |
| MKLink native SDK | Official v0.4.0 Skill ZIP, SHA-256 `555710fff446f80776b3fab418343d1370b6a083faa38f7d568896ac63c3d300` | Downloaded separately and verified. Includes its LICENSE and notices; never modifies an installed skill. |
| ESP-IDF and managed components | ESP-IDF 5.5.2, versions in component manifests/lockfiles | Apache-2.0 and component-specific licenses. Fetched by ESP-IDF; not vendored here. |
| React, Vite, Radix Select, QRCode | Versions in package-lock.json | MIT; exact dependency metadata supplied by npm. Radix notice is also under public/third-party-notices. |
| Phosphor icons | @phosphor-icons/react; UI icon SVGs | MIT; notice under public/third-party-notices/phosphor-icons-react.txt. |
| Inter, IBM Plex Mono, Noto Sans SC | @fontsource packages in package-lock.json | SIL Open Font License; preserve the packages' license text when distributing compiled fonts. |
| Tauri and Rust dependencies | Cargo.lock | Tauri MIT/Apache-2.0; each dependency retains its own license. |
| pySerial | 3.5 | BSD-3-Clause; notice under desktop/mklink-wireless-config/tools/PYSERIAL-NOTICE.txt. |
| esptool | 5.6.0 | GPL-2.0-or-later; it is used by the separately packaged installer helper. Binary distribution must include corresponding licensing/source obligations. |
| PyInstaller | requirements-build.txt | GPL with distribution exception; preserve its applicable notices. |

Board photography was supplied for this project; interface illustrations and branding were prepared for this workbench. The repository does not include the supplier's original board documentation archive.

FLM algorithms, CMSIS packs and other SDK data retain their own vendor terms. Fetching a verified SDK is not a blanket relicensing of its contents. Review the specific assets and ship their notices before releasing bundled binaries. The source CI does not certify redistribution of every optional target pack. Do not publish a binary release just because the source build passes.
