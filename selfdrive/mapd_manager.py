#!/usr/bin/env python3
"""Korea-only offline OSM bridge for pfeiferj mapd.

The current branch no longer publishes geodetic position in livePose, so this
uses the same device GPS service selected by timed/carrot_serv and forwards its
latitude, longitude, and bearing to mapd through shared-memory Params.
"""

import glob
import json
import os
import shutil

import cereal.messaging as messaging

from openpilot.common.gps import get_gps_location_service
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog


COMMON_DIR = "/data/media/0/osm"
MAPD_BIN_DIR = "/data/openpilot/third_party/pfeiferj-mapd"
MAPD_PATH = os.path.join(MAPD_BIN_DIR, "mapd")
OSM_COUNTRY_CODE = "KR"
OSM_COUNTRY_TITLE = "South Korea"


def ensure_map_directories() -> None:
  os.makedirs(COMMON_DIR, exist_ok=True)


def map_database_present() -> bool:
  offline_path = os.path.join(COMMON_DIR, "offline")
  if os.path.isdir(offline_path):
    with os.scandir(offline_path) as entries:
      return any(entries)
  return False


def remove_existing_map_data() -> None:
  # Targets are deliberately restricted to mapd's dedicated storage directory.
  for path in [os.path.join(COMMON_DIR, "db"), *glob.glob(os.path.join(COMMON_DIR, "v*"))]:
    if os.path.commonpath((COMMON_DIR, os.path.abspath(path))) != COMMON_DIR:
      continue
    if os.path.islink(path) or os.path.isfile(path):
      os.unlink(path)
    elif os.path.isdir(path):
      shutil.rmtree(path)


def request_korea_download(mem_params: Params) -> None:
  request = {"nations": [OSM_COUNTRY_CODE], "states": []}
  # OSMDownloadLocations is a typed JSON Param. Pass the dictionary so Params
  # serializes it; passing an already encoded string raises TypeError.
  mem_params.put("OSMDownloadLocations", request)
  cloudlog.info(f"mapd: requested offline map data for {OSM_COUNTRY_TITLE} ({OSM_COUNTRY_CODE})")


def handle_download_request(params: Params, mem_params: Params) -> bool:
  """Start a download only after the user presses the MAP download/update button."""
  if not params.get_bool("OsmDbUpdatesCheck"):
    return False
  remove_existing_map_data()
  params.put_bool("OsmDbUpdatesCheck", False)
  request_korea_download(mem_params)
  return True


def main() -> None:
  params = Params()
  mem_params = Params("/dev/shm/params")
  gps_service = get_gps_location_service(params)
  sm = messaging.SubMaster([gps_service], poll=gps_service)
  rk = Ratekeeper(1.0, print_delay_threshold=None)

  ensure_map_directories()
  mem_params.put("LastGPSPosition", "{}")

  while True:
    sm.update(1000)

    handle_download_request(params, mem_params)

    gps = sm[gps_service]
    if sm.updated[gps_service] and sm.valid[gps_service] and gps.hasFix:
      position = {
        "latitude": gps.latitude,
        "longitude": gps.longitude,
        "bearing": gps.bearingDeg,
      }
      mem_params.put("LastGPSPosition", json.dumps(position, separators=(",", ":")))

    rk.keep_time()


if __name__ == "__main__":
  main()
