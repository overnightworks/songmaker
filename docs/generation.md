# Creation and generation

For anyone building or reviewing how a take is generated and scored: the ruled product sentences, each under the ID its test cites.

### REQ-CREATE-01: A musician can start audio generation for a song.

### REQ-CREATE-02: Songmaker refuses to start generation when the song version used for that generation has no lyrics or no style prompt.

### REQ-MODEL-01: Starting generation requires a currently available model; Songmaker does not silently substitute a different model.

### REQ-PARAM-01: A generation uses the generation settings that apply to the chosen model; Songmaker does not silently drop them.

### REQ-SEED-01: A musician can pin a previous take's seed and generate again with changed settings.

### REQ-SEED-02: A pinned non-negative seed is a fixed seed; when the musician does not pin a seed, generation is random.

### REQ-SEED-03: A generated take records the seed that produced its audio.

### REQ-SCORE-01: Scoring a take does not select or change that song's Pick.

### REQ-SCORE-02: When a take has a sung transcription, Songmaker presents it as information and does not treat it as a replacement for the lyrics.
