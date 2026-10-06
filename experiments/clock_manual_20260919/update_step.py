"""Existing update exports; ResultUpdater owns request and candidate validation.

Formal record publication remains in register_update.
"""
from register_update import sibling

_updater = sibling('result_updater')
history = _updater.history
known_regions = _updater.known_regions
build_update_request = _updater.build_update_request
route_update = _updater.route_update
