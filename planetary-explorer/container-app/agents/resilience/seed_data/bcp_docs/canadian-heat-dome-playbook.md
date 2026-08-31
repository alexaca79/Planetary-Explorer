---
title: Canadian Heat-Dome Business Continuity Playbook
description: Synthetic 2026 response actions for heat events across the Canadian facility network.
---

**Owner:** Operations Resilience Team

**Last reviewed:** 2026-08

**Applies to:** All Canadian demo facilities

## Trigger Criteria

Activate this playbook when all of the following are forecast:

* Daily maximum temperature at or above 32 degrees C for three consecutive days
* A provincial grid operator issues a conservation or emergency alert
* Facility cooling demand is projected to exceed 90% of available capacity

## Tier 1 Actions

1. Toronto Advanced Manufacturing and Calgary Data Centre:
   * Pre-cool process and data-hall systems during off-peak hours
   * Defer non-critical maintenance and thermal loads
   * Confirm water and backup-power reserves
2. Edmonton Systems Assembly and Saskatoon Sub-Assembly:
   * Stage one shift of critical component inventory
   * Move heat-sensitive work to cooler shifts
3. Vancouver, Winnipeg, and Halifax distribution sites:
   * Move outdoor loading to morning and evening windows
   * Verify refrigerated-container and generator fuel reserves

## Tier 2 Actions

* Curtail non-critical production at `on-fab-toronto-01`
* Shift `on-rd-ottawa-01` to remote work and close auxiliary HVAC zones
* Activate alternate distribution through Winnipeg and Halifax

## Recovery

* Stand down 24 hours after grid alerts clear and forecast highs remain below 30 degrees C for 48 hours
* Record lessons learned within five business days
* Update the playbook within 30 days