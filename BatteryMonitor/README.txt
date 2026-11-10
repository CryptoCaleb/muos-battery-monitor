Battery Monitor v1.0 for muOS - created by Caleb Hinton

Live battery stats, graphs and health for your handheld.

Tabs (L1/R1 or D-pad left/right to switch)
  Overview  - charge level, time left (or time to full), drain/charge rate,
              voltage, temperature, power draw and the last 6 hours
  History   - battery level graph for 6h / 24h / 3 days / 7 days (Up/Down),
              charging periods shaded green, power draw (or temperature) below
  Sessions  - every play and charge session: when, how long, % used, %/hour
  Health    - estimated real capacity vs. design capacity, health grade,
              charge cycles, typical drain and charge speed, temperatures,
              and the voltage discharge curve
  Settings  - background logging, battery size, clear history, credits

Background logging
  Turn it on in Settings so the app can learn from your real use. It adds a
  tiny script to MUOS/init on your muOS card that records one reading a minute.
  It needs Configuration > Advanced Settings > User Init Scripts switched ON.
  The history is kept in data/battery.csv (trimmed to roughly 6 weeks).
  Without it, the app only records while it is open.

How the estimates work
  - Time left uses the current power draw, or your recent drain trend.
  - Battery health counts the current that flows out during long play sessions
    (10% or more) to measure the real capacity, then compares it with the
    design capacity (3300 mAh on the RG35XX Pro; change it in Settings).
  - Estimates get better the more sessions are logged.

Problems? See last_run.log in this folder.
