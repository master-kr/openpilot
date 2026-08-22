#!/usr/bin/env python3
import datetime
import subprocess
import time
from typing import NoReturn

import cereal.messaging as messaging
from openpilot.common.time_helpers import min_date, system_time_valid
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params


def set_time(new_time):
  utc_now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
  diff = utc_now - new_time
  if abs(diff) < datetime.timedelta(seconds=10):
    cloudlog.debug(f"Time diff too small: {diff}")
    return

  cloudlog.debug(f"Setting time to {new_time}")
  try:
    subprocess.run(["date", "-u", "-s", new_time.strftime("%Y-%m-%d %H:%M:%S")], check=True)
  except subprocess.CalledProcessError:
    cloudlog.exception("timed.failed_setting_time")


def main() -> NoReturn:
  """
    timed has two responsibilities:
    - getting the current time from GPS
    - publishing the time in the logs

    AGNOS will also use NTP to update the time.
  """

  params = Params()
  preferred_gps_service = "gpsLocationExternal" if params.get_bool("UbloxAvailable") else "gpsLocation"
  gps_location_services = [preferred_gps_service]
  gps_location_services.append("gpsLocation" if preferred_gps_service == "gpsLocationExternal" else "gpsLocationExternal")

  pm = messaging.PubMaster(['clocks'])
  sm = messaging.SubMaster(gps_location_services)
  while True:
    sm.update(1000)

    msg = messaging.new_message('clocks')
    msg.valid = system_time_valid()
    msg.clocks.wallTimeNanos = time.time_ns()
    pm.send('clocks', msg)

    gps_time = None
    for gps_location_service in gps_location_services:
      gps = sm[gps_location_service]
      if not sm.updated[gps_location_service] or (time.monotonic() - sm.logMonoTime[gps_location_service] / 1e9) > 2.0:
        continue
      if not gps.hasFix:
        continue

      # GPS timestamps are UTC. Keep the system clock in UTC and let the UI
      # apply the configured local timezone (Asia/Seoul on Korean devices).
      candidate_time = datetime.datetime.fromtimestamp(gps.unixTimestampMillis / 1000., datetime.UTC).replace(tzinfo=None)
      if candidate_time >= min_date():
        gps_time = candidate_time
        break

    if gps_time is None:
      continue

    set_time(gps_time)
    time.sleep(10)

if __name__ == "__main__":
  main()
