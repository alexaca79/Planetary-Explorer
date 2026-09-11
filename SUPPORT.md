---
title: Planetary Explorer Support
description: Report reproducible problems and request community help without exposing tenant credentials or private data.
---

## Getting Help

Planetary Explorer is sample software, not a supported Microsoft product.
There is no support SLA or guarantee of suitability for operational decisions.

Use the Issues page of the fork you are running for bugs, questions and
feature requests. Search existing issues first. Do not create upstream
issues or pull requests unless you intend to engage that repository's
maintainers.

Include the commit, deployment path, operating system, browser, failing
command or workflow, expected result, actual result, and a minimal public-data
example. Distinguish an application error from a disabled feature, missing
dataset, quota/policy restriction or authentication prerequisite.

Do not attach keys, tokens, signed asset URLs, raw environment files or
tenant-private data. Redact screenshots and logs before sharing. Report
security vulnerabilities using [SECURITY.md](SECURITY.md), not public issues.

## Before Reporting Deployment Problems

Check the [deployment guide](documentation/deployment.md), confirm the exact
tenant/resource targets, and verify that real application images replaced
bootstrap images. A created resource or HTTP 200 alone does not prove that
model, data and workflow dependencies are usable.

Azure service support and subscriptions are governed by their own support
plans; deploying this sample does not add product support coverage.