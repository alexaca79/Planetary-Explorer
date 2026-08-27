#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Run the shared Container Apps postdeploy configurator for GeoFM."""

from __future__ import annotations

import sys

from configure_api_postdeploy import main


if __name__ == "__main__":
    sys.exit(main(["--profile", "geofm"]))