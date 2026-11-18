# Material 3 style for the Electrum QML GUI — screenshots

Screenshots of the optional Material 3 style of the Electrum QML (Android) GUI, next to the current ("Classic") style.
The style is chosen in Settings → Interface style and applies after a restart.

## How they were taken

- **Rows 1–10** — desktop `run_electrum -g qml` (Qt 6.10, OpenGL through Mesa) in a phone-sized portrait window
  (360 × 800 dp at 2× scale, so 720 × 1600 px), on **regtest**: a local bitcoind and electrumx, a wallet with a few
  on-chain transactions and one Lightning channel to a second local Electrum node. All amounts, labels, addresses,
  node IDs and channel IDs are regtest throwaway values. The top 32 dp and the bottom 48 dp are reserved for the
  status bar and the navigation bar, as on a phone with edge-to-edge (the desktop does not draw the system bars
  themselves).
- **Row 11** — Android 14 emulator (Pixel 6 profile, 1080 × 2400 scaled to 720 × 1600): a new empty mainnet wallet,
  no network ("Disconnected"); here the real status bar and navigation bar are visible, with the light status bar of
  the light Material 3 theme.

Classic has a single dark look, so it has one column. "—" means the screen is not shown for that column.

| # | Screen | Material 3, light | Material 3, dark | Classic |
|---|---|---|---|---|
| 1 | Wallet home (balance, recent history) | ![](01-home-m3-light.png) | ![](01-home-m3-dark.png) | ![](01-home-classic.png) |
| 2 | Send: a Lightning invoice before paying | ![](02-send-m3-light.png) | ![](02-send-m3-dark.png) | — ¹ |
| 3 | Receive: a payment request with QR code | ![](03-receive-m3-light.png) | ![](03-receive-m3-dark.png) | ![](03-receive-classic.png) |
| 4 | Transaction details | ![](04-transaction-m3-light.png) | ![](04-transaction-m3-dark.png) | ![](04-transaction-classic.png) |
| 5 | Lightning channels | ![](05-channels-m3-light.png) | ![](05-channels-m3-dark.png) | ![](05-channels-classic.png) |
| 6 | Open a Lightning channel | ![](06-open-channel-m3-light.png) | ![](06-open-channel-m3-dark.png) | ![](06-open-channel-classic.png) |
| 7 | Settings (with the Interface style switch) | ![](07-settings-m3-light.png) | ![](07-settings-m3-dark.png) | ![](07-settings-classic.png) |
| 8 | New wallet wizard (first page) | ![](08-new-wallet-m3-light.png) | ![](08-new-wallet-m3-dark.png) | ![](08-new-wallet-classic.png) |
| 9 | Password dialog | ![](09-password-m3-light.png) | ![](09-password-m3-dark.png) | ![](09-password-classic.png) |
| 10 | Switching back to Classic (the confirmation opened from the Material 3 menu) | ![](10-style-switch-m3-light.png) | ![](10-style-switch-m3-dark.png) | — |
| 11 | Android 14 emulator: wallet home, empty wallet | ![](11-android14-home-m3-light.png) | ![](11-android14-home-m3-dark.png) | ![](11-android14-home-classic.png) ² |

¹ The classic Send dialog opens the QR scanner first, and the desktop setup used here has no camera.

² Classic leaves the status bar black, and with a light system theme its icons are dark, so they cannot be seen.

## Together with the Lightning routing patches

- **Rows 12–13** — the same Android 14 emulator, a new empty wallet, no network; the APK is built from the branch
  [`material3-routing`](https://github.com/Perlover/electrum/tree/material3-routing): this PR together with our open
  Lightning routing PRs. The settings those PRs add to the classic Preferences are shown in Material 3 (commit
  `dfe9e057c` of that branch). The APK was built from the same code on the older master these branches were started from
  (`4f36c4489`); the branch itself is on the current master.

| # | Screen | Material 3, light | Material 3, dark | Classic |
|---|---|---|---|---|
| 12 | Settings → Lightning: background updates of the network graph, with the battery restriction warning | ![](12-android14-routing-settings-m3-light.png) | ![](12-android14-routing-settings-m3-dark.png) | — |
| 13 | Settings → Advanced → Share log file: what the file contains, asked before anything is shared | ![](13-android14-share-log-m3-light.png) | — | — |
