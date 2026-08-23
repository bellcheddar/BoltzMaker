"""Landlord -- on-device narration of finished BoltzMaker campaigns.

Named after Timothy Taylor's flagship, as BoltzMaker is named after their Boltmaker.

The package is deliberately split so that the only part which can be absent is the
model. `factblock` computes; `fallback` renders without a model; `validate` checks
whatever a model returns. A machine with no Apple Intelligence, or no Swift binary,
still gets a summary -- it just gets the template one.
"""
