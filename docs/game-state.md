# GameState

Every observation has `value` (null = unknown), confidence in [0,1], source and observation time. Zero LP, empty list and null are different values. Self/opponent contain LP, hand count and named monster/spell-trap/extra-monster zones, graveyard, banished and extra deck observations. Hidden identities remain unknown. Turn number, turn player and phase are independent observations.

Cards have ID/name/confidence and face-up identity only when matched. Unmatched zones remain unknown; no automatic hidden-card reconstruction. Current state also carries calibrated visible UI action candidates. A session-local sequence and capture time provide freshness. Tracking logs observable value changes, not causal NORMAL_SUMMON claims from ambiguous card movement. A transition through unknown clears comparison evidence.

Actions use typed names, optional card/target and UI provenance. No action can reach a game input method. Decisions and UI expose uncertainty and reasons for abstaining.
