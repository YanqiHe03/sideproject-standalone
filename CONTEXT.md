# The Side Project

A continuously generated text display and its probability monitor, with optional printed pages.

## Language

**Display round**:
The text accumulated on the square from a fresh start until a click, tap, or overflow starts another round. Each round has its own starting character, temperature, and pace.

**Memory flush**:
The model discarding its recent context after reaching the generation limit and continuing from a new character. A memory flush can occur within a display round; it does not itself clear the square.

**Probability monitor**:
The companion view of the active display round's current token, candidate tokens, probabilities, and generation settings.

**Finished page**:
The previous round's square retained at restart for optional printing, independent of the next round's text.
