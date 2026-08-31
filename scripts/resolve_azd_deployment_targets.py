#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Resolve and persist exact deployment targets for an AZD preprovision hook."""

from __future__ import annotations

import sys

from resolve_deployment_targets import main


if __name__ == "__main__":
    sys.exit(main(["--write-azd-env"]))