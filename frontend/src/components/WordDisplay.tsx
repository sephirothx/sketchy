import { emitWithAck } from "../lib/socket";
import { splitMaskedWord } from "../lib/maskedWord";

interface WordDisplayProps {
  isDrawer: boolean;
  myWord: string | null;
  maskedWord: string;
  wordChoices: string[];
  revealedWord?: string | null;
}

// tightly spaced blanks per word, followed by each word's letter count (in
// order) at the very end. Digits only ever appear in that trailing count
// list, so splitting on the first digit cleanly separates the two parts.
function renderMaskedWord(masked: string) {
  const { blanks, counts } = splitMaskedWord(masked);
  if (counts.length === 0) {
    return blanks;
  }
  return (
    <>
      {blanks}
      <span className="word-lengths">
        {counts.map((count, index) => (
          <sup key={index}>{count}</sup>
        ))}
      </span>
    </>
  );
}

export function WordDisplay({
  isDrawer,
  myWord,
  maskedWord,
  wordChoices,
  revealedWord,
}: WordDisplayProps) {
  if (isDrawer && wordChoices.length > 0 && !myWord) {
    return (
      <div className="word-display choosing">
        <p>Choose a word to draw:</p>
        <div className="word-choices">
          {wordChoices.map((word) => (
            <button key={word} onClick={() => emitWithAck("select_word", { word })}>
              {word}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="word-display">
      {revealedWord ? (
        <span className="word-reveal">{revealedWord}</span>
      ) : isDrawer && myWord ? (
        <span className="word-reveal">{myWord}</span>
      ) : (
        <span className="word-masked">{renderMaskedWord(maskedWord)}</span>
      )}
    </div>
  );
}
