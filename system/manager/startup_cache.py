#!/usr/bin/env python3
"""Build non-critical selector caches outside the manager process.

This must remain a separate managed process. A Params-writing thread in manager
can hold /data/params/.lock while manager forks another Python process. The
child then inherits the locked file descriptor and can block pandad forever.
"""

import os
import subprocess
import sys

from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog


SUPPORTED_CAR_LISTS = {
  "SupportedCars": "hyundai",
  "SupportedCars_gm": "gm",
  "SupportedCars_toyota": "toyota",
  "SupportedCars_mazda": "mazda",
  "SupportedCars_honda": "honda",
  "SupportedCars_ford": "ford",
  "SupportedCars_tesla": "tesla",
  "SupportedCars_volkswagen": "volkswagen",
}


def generate_missing_supported_car_lists(params: Params) -> None:
  """Populate cached selector lists outside the boot critical path."""
  for key, brand in SUPPORTED_CAR_LISTS.items():
    if params.get(key):
      continue
    values_py = os.path.join(BASEDIR, "opendbc", "car", brand, "values.py")
    try:
      result = subprocess.run([sys.executable, values_py], check=True, capture_output=True,
                              text=True, encoding="utf-8")
      supported_cars = result.stdout.strip()
      if supported_cars:
        params.put(key, supported_cars)
      else:
        cloudlog.warning(f"empty supported-car list for {brand}")
    except Exception:
      cloudlog.exception(f"failed to build {key}")


def seed_local_update_branches(params: Params, current_branch: str, enumerate_refs: bool = True) -> None:
  """Keep the software branch selector useful without a background network check."""
  branches: list[str] = []

  def add_branch(branch: str | None) -> None:
    if not branch:
      return
    branch = branch.strip()
    if branch.startswith("origin/"):
      branch = branch[len("origin/"):]
    if branch and branch != "HEAD" and branch not in branches:
      branches.append(branch)

  add_branch(current_branch)
  add_branch(params.get("UpdaterTargetBranch"))
  for branch in (params.get("UpdaterAvailableBranches") or "").split(","):
    add_branch(branch)

  if enumerate_refs:
    try:
      result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"],
        cwd=BASEDIR, check=True, capture_output=True, text=True, encoding="utf-8",
      )
      for branch in result.stdout.splitlines():
        add_branch(branch)
    except Exception:
      cloudlog.exception("failed to enumerate local update branches")

  if branches:
    params.put("UpdaterAvailableBranches", ",".join(branches))
  if current_branch:
    params.put("UpdaterTargetBranch", current_branch)


def main() -> None:
  params = Params()
  try:
    generate_missing_supported_car_lists(params)
    seed_local_update_branches(params, params.get("GitBranch") or "")
  finally:
    # Prevent manager from restarting this one-shot process every update loop.
    params.put_bool("StartupCacheDone", True)


if __name__ == "__main__":
  main()
