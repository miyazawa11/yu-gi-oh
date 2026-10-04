# Scoped card recognition

Start with user-provided visible card crops for a 20–50 card deck. Calibration maps zone regions to reference templates labeled by card ID. Match artwork/crop similarity only when absolute score and separation from other card IDs pass thresholds; unknown otherwise. Distinct exemplars of one card are one class. Include lighting, animation, perspective and unrelated cards in holdout data.

Recognition does not infer face-down cards, deck order, or opponent hand. No card art is fetched automatically. Populate the SQLite metadata database with a local JSON import containing ID, name, type, attribute, race, level/rank/link, ATK/DEF and effect text. Recognition labels must resolve through that database; missing metadata remains explicit. Knowledge-graph relationships are deferred.

Real cards/ground truth are unavailable in the current Linux environment. Synthetic similarity tests validate algorithmic rejection and integration only. Card deployment remains gated on real-game LP/turn/phase evaluation and a scoped card dataset.
