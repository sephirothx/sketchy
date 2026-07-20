import { emitWithAck } from "../lib/socket";

interface WordDisplayProps {
  isDrawer: boolean;
  myWord: string | null;
  maskedWord: string;
  wordChoices: string[];
}

export function WordDisplay({ isDrawer, myWord, maskedWord, wordChoices }: WordDisplayProps) {
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
      {isDrawer && myWord ? (
        <span className="word-reveal">{myWord}</span>
      ) : (
        <span className="word-masked">{maskedWord}</span>
      )}
    </div>
  );
}
