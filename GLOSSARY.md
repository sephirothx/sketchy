# Glossary

The vocabulary of Sketchy: one agreed name per concept, for UI copy, docs, issues,
and conversation.

- **The canonical term is the one to use.** If a concept has a name here, use it
  everywhere it is visible — button labels, chat announcements, overlays, tooltips,
  screen-reader labels, README, issues, PR titles.
- **The listed alternatives are not synonyms, they are drift.** They mean the term
  next to them and nothing else, and they should not appear in new copy.
- **A new concept gets a name here before it ships.** If a change introduces
  something players can see and there is no word for it yet, add the entry in the
  same change.
- **Renaming a term means renaming it everywhere, in one change.** A half-finished
  rename is worse than none: `backend/tests/test_wire_contract.py` fails one that
  stops at the client or the server. Settings already stored in a player's browser
  are the exception that cannot be renamed at all — migrate them on load, the way
  `frontend/src/store/settingsMigrations.ts` does.
- UI copy is American English (*color*, not *colour*) and sentence case
  (*Buy letters*, not *Buy Letters*).

---

## Game structure

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Game** | One complete play-through in a room, from **Start game** to final scores. A room outlives the games played in it. | match, session |
| **Round** | One full rotation: every active player draws exactly once. Rooms are configured in rounds ("3 rounds each"). | — |
| **Turn** | One drawer's stint: they pick a prompt, draw it, and it is revealed. A round of *n* players contains *n* turns. **This is the unit almost everything is scored, timed, and limited by** — points, hint spend, and the drawing limit are all per turn, never per round. | round (for a single drawer's stint) |
| **Choosing** | The phase where the drawer picks one of their prompt options. Everyone else waits. | word select, prompt select, picking phase |
| **Drawing** | The phase where the drawer draws and everyone else guesses. Ends when the timer runs out or everyone has guessed. | play phase |
| **Turn results** | The short phase after each turn: the prompt is revealed and scores update. | round end, round results, intermission |
| **Game over** | The final screen: full standings, and the way through to the highlights and the drawing recap. | game end screen, results screen |
| **Highlights** | The short list of superlatives from the last game — hardest prompt, fastest guess, best drawer, quickest on average. Shown on a screen of their own, reached from the game over screen or the waiting room, rather than crowded onto either. Each is dropped when the game gives it nothing to say, so the list is often shorter than four. Never derived from points, so it reads the same in a no-scoring game. | awards, MVP, trophies, achievements |
| **Rematch** | Starting a new game with the players already in the room. | replay, new game |

The rule of thumb: **rounds contain turns**. Anything a single drawer does, is
awarded, or is limited to belongs to a *turn*. Only the room's configured length and
the rotation itself are counted in *rounds*.

## People

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Player** | Anyone in a room who can draw and guess. Spectators are not players. | user (that is an account), participant |
| **Active player** | A player who is connected and not AFK — the population that draws, is waited for, and counts toward vote majorities. | live player, ready player |
| **Drawer** | The player whose turn it is to draw. | artist, painter, sketcher |
| **Guesser** | Any player in the drawing phase who is not the drawer. Stays a guesser after guessing the prompt. | watcher, viewer |
| **Spectator** | Someone watching a room without playing. Never draws, never scores, never votes, and is never a moderation target. | observer, viewer, lurker |
| **Host** | The player who created the room and can start the game and change room settings. | owner, admin, leader |
| **Guest** | Someone playing under an unclaimed account. Shown in grey italics. | anonymous player, unregistered user |
| **Administrator** | A trusted service-wide operator. This is an account role, never the **host** of a room. | admin (for a room host), owner |
| **Avatar** | The deployment-hosted visual representing an account. The generated initial is the default. | profile picture, external avatar URL |
| **Signed-in device** | One revocable account login, labeled coarsely by browser and platform. | JWT, login token, active session |
| **Linked guest** | A former guest identity whose history now belongs to a registered account without rewriting past game seats. | abandoned guest, duplicate account |
| **Data export** | A private, versioned JSON download containing one player's own account and gameplay data. It never includes other players' profile fields or message bodies. | archive, backup, dump |
| **Deleted player** | The neutral name replacing a deleted account in retained shared game history. | removed user, anonymous, unknown |
| **AFK** | A status a player sets on themselves, or the room votes onto them. AFK players are skipped for turns and not waited for. Always the initialism, uppercase. | away, idle, inactive, afk |

## Names

Three different things, never used for one another:

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Nickname** | The name a player is playing under in a room — what appears in the player list, chat, and scores. | handle, alias, screen name |
| **Username** | The account login name, chosen when an account is claimed. A registered player's nickname is always their username. | user ID, login |
| **Display name** | The name saved on an account and used as the default nickname. | profile name, real name |
| **Name color** | The color a player's name renders in. Guests have no name color. | name colour, player color |

## The prompt

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Prompt** | The word or phrase the drawer has to draw and the guessers have to name. Roughly a third of the shipped entries are more than one word (*bow and arrow*, *roller coaster*), so the term has to hold both. | word, solution, answer, secret word, term |
| **Prompt concept** | The stable identity of what is being drawn, independent of language, wording, or the lists that explicitly reference it. Equal text never merges two concepts by itself. | prompt ID, canonical prompt, master prompt |
| **Prompt version** | One immutable language-specific form of a **Prompt concept**, including its canonical display answer, matching rules, aliases, editorial difficulty, content rating, and tags. | translation, prompt row, wording |
| **Prompt alias** | An alternative accepted guess scoped to one **Prompt concept** and language, and explicitly enabled for exact **Prompt versions**. It is never a player or identity alias. | synonym, alternate spelling, answer |
| **Prompt language** | The BCP-47 content language shared by every selected **Prompt list** in one room. It selects the game's answer-matching rules; it is distinct from the interface locale used for translated catalogue copy. | locale, UI language, list language |
| **Prompt-list localization** | Optional translated name and description used to present a **Prompt list** in an interface locale. It does not translate prompts or change the room's **Prompt language**. | translation, localized list, content language |
| **Editorial difficulty** | An author/editor classification—Unspecified, Easy, Medium, or Hard—stored on a **Prompt version**. It is distinct from measured difficulty in **Prompt stats**. | difficulty rating, live difficulty |
| **Content rating** | The intended audience classification—Everyone, Teen, or Mature—stored on a **Prompt version**. | NSFW flag, age rating |
| **Prompt tag** | A stable, explicit category attached to a **Prompt version** for organization and later discovery. | category string, label |
| **Word** | Keeps its ordinary English meaning, and only that: the individual words making up a multi-word prompt, and the letters and words hints and close guesses work on. It is never a name for the prompt itself. | — |
| **Prompt options** | The three prompts offered to the drawer during the choosing phase. | word options, word choices, candidates |
| **Masked prompt** | The prompt shown to guessers as underscores, with any revealed letters filled in and the word breaks visible. | masked word, hidden word, blanks |
| **Prompt list** | A curated set of prompts in exactly one **Prompt language** that a room draws from (currently Standard English and Extended English). | word list, dictionary, prompt pack, category |
| **Custom prompts** | Prompts the host adds when creating the room, on top of or instead of the prompt lists. | custom words, own words, private words |
| **Prompt stats** | The page, reached from the lobby, listing every prompt in a list and how it has actually played: how often it is picked when offered, and what share of guessers name it. A prompt is only ranked once enough guessers have faced it; the rest are listed as unranked. | word stats, difficulty ratings, prompt leaderboard |

## Hints

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Hint** | A revealed letter of the prompt. | clue, reveal |
| **Hint mode** | The room setting choosing how hints work: **No hints**, **Timed hints**, **Buy letters**, or **Wheel of Fortune**. Use those four labels verbatim. | hint type, hint style |
| **Timed hints** | Letters of the prompt revealed to everyone automatically as the drawing timer runs down. | checkpoint hints, auto hints, free hints |
| **Buy letters** | Each guesser spends against their turn score to reveal a letter position, visible only to them. | purchase hints, paid hints |
| **Wheel of Fortune** | Each guesser buys a specific letter, priced by how common it is, visible only to them. | wheel hints, letter wheel |
| **Hint spend** | What a guesser has committed to hints this turn. Hints are bought on credit: the spend is taken out of that turn's guess points, never out of the running score. | hint cost, hint debt, hint charge |
| **Hint spend limit** | The maximum hint spend a guesser may commit in one turn. | hint budget, hint cap |

## Guessing

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Guess** | A chat message from a guesser during the drawing phase, checked against the prompt. | answer, attempt, submission |
| **Correct guess** | A guess that matches the prompt. Announced to the room without revealing it. | win, hit |
| **Close guess** | A guess one small edit away from the prompt, or one that gets some words of a multi-word prompt right. Shown only to the guesser who made it. | near miss, almost |
| **Chat** | The room's message stream. **Spectator chat** is the restricted stream that only the drawer, spectators, and correct guessers can see. | messages, log, feed |

## Drawing

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Canvas** | The shared drawing surface. | board, whiteboard, sketchpad |
| **Brush** | The freehand drawing tool. Its size control is **Brush size**, and what it lays down is a **brush stroke**. | pen, pencil, marker, draw tool |
| **Eraser** | The freehand erasing tool. Its size control is **Eraser size**. | rubber, undo tool |
| **Fill** | The tool that floods an enclosed area with the current color. | bucket, paint bucket, flood |
| **Shape** | The rectangle, ellipse, and triangle tools, collectively. Name the individual ones **rectangle**, **ellipse**, **triangle**. | box, circle/oval, square |
| **Stroke** | One continuous mark, from the moment the drawer presses down to the moment they lift. What the brush and eraser produce. | line, scribble, path |
| **Color** | The current drawing color, chosen from the palette or, where the room's **color mode** allows it, a custom picker. | colour, ink, shade |
| **Undo** | Removes the drawer's most recent mark for everyone. | back, revert, erase |
| **Clear** | Empties the canvas for everyone. | reset, wipe, erase all |
| **Drawing limit** | The ceiling on how much one turn's drawing may cost the room to load. Tools grey out for the rest of the turn once it is reached, and the reason names the tool, not the mechanism. | budget, quota, cap, replay cost |
| **Drawing rules** | The room's **allowed tools** and **color mode** together. Only ever a collective name for the pair; neither setting is called "the drawing rules" on its own. | drawing restrictions, canvas rules, tool preset |
| **Allowed tools** | The room setting turning **Brush**, **Fill**, and **Shapes** on and off independently. At least one of Brush and Shapes stays on. The eraser is not separately switchable: it goes wherever the brush goes. | tool preset, tool mode, enabled tools |
| **Color mode** | The room setting choosing which colors a drawer may use: **All colors**, **Palette only**, **Colorblind-safe**, or **Black and white**. Use those four labels verbatim. Every mode permits white, because that is what erasing sends. | color preset, palette mode, color restrictions |
| **Save image** | Downloading the current canvas as a PNG. | export, download drawing, screenshot |
| **Recap** | The gallery of every drawing from a finished game, shown on the game over screen. Individual entries are **drawings**, labeled by round and turn. | gallery, replay, history, snapshot |

## Scoring

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Points** | What a single guess or turn is worth. | score (for one award) |
| **Score** | A player's running total across the game. Never goes down. | points (for a total), rating |
| **Scoring mode** | The room setting chosen at creation: **Default**, **Pressure**, or **No scoring**. Use those three labels verbatim. | points mode, scoring type, "Just for fun", "Points on" |
| **Default** | A correct guess is worth 100–300 points, falling steadily as the timer runs down. | normal, standard, classic |
| **Pressure** | A correct guess decays from 300 points, and decays faster for everyone once the first player gets the prompt. | hardcore, fast, decay |
| **No scoring** | Guesses are still detected and turns still end, but everyone stays on zero and no standings are shown. | casual, fun mode, unscored |
| **Standings** | The ranked list of scores. Players level on points share a place, and the places they crowd out are skipped — two tied for first are both first, and the next player is third. Medals follow the place, so a shared first awards two golds and no silver. | leaderboard, ranking, scoreboard |

## Rooms

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Room** | The place people play in — created by a host, joined by code or from the lobby, and outliving individual games. | game (for the place), channel, table |
| **Lobby** | The browsable list of public rooms. **The lobby is one place, and it is not inside a room.** | browser, room list, home |
| **Waiting room** | A room's state before a game starts or between games, where players gather and the host starts the game. | lobby, pre-game, staging |
| **Public room** | A room listed in the lobby, joinable by anyone. | open room |
| **Private room** | A room reachable only by its code or invite link. | closed room, locked room |
| **Room code** | The short code that identifies a room to join. The shareable URL carrying it is the **invite link**. | friend code, game code, PIN, room ID |
| **Room settings** | The host-controlled configuration: rounds, drawing time, max players, prompt lists, hint mode, scoring mode, spectator rules. | options, config, preferences, rules |
| **Player settings** | A player's own preferences, which travel with them between rooms. | user settings, profile settings |
| **Colorblind-safe preference** | A private **Player setting** asking hosts to prefer **Colorblind-safe** room colors. Only an anonymous aggregate suggestion may reach a host; never expose who enabled it. | disability flag, accessibility request |
| **Colorblind-safe suggestion** | The unattributed, host-only notice that at least one seated player enabled the **Colorblind-safe preference**. It never names or counts players, never changes the room automatically, ignores spectators, and may be dismissed for the live room. | accessibility alert, player flag |
| **Clear guesses after sending** | The **Player setting** choosing whether a sent guess empties the guess field or remains available to edit and resend. | clear chat, keep guesses |

## Votes and moderation

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Report** | A private request for a moderator to review another player's behavior, with a reason, the reporter's details, and bounded context evidence. Reports are never room announcements or public profile data. | complaint, flag |
| **Moderation evidence** | The protected context retained with a **Report** so a reviewer can understand what happened. It may outlive account anonymization and is never ordinary public history. | telemetry, public replay |
| **Suspension** | A temporary or permanent service-wide block imposed by a moderator or administrator. It revokes signed-in devices and prevents HTTP and Socket.IO authentication while active. | ban (in player-facing copy), kick |
| **Block** | A player's private, directional choice to hide another player's ordinary chat and prevent future direct invites. It never hides game-critical state and is not a **Kick vote** or **Suspension**. | mute, ignore, ban |
| **Restart vote** | A proposal to restart the current game, carried by a strict majority of active players. | vote restart, game restart, reset vote |
| **Kick vote** | A proposal to remove a player from the room. | vote kick, vote-kick, boot |
| **AFK vote** | A proposal to mark a player AFK. | vote AFK, idle vote |
| **Majority** | Strictly more than half of the eligible voters. Spectators never vote and are never targets. | quorum, consensus |

## Connection

| Term | Meaning | Avoid |
| --- | --- | --- |
| **Disconnected** | A player whose connection dropped. They keep their score and place in the rotation until the grace period expires. | offline, dropped, gone |
| **Grace period** | The 30 seconds a disconnected player has to return before they are removed from the game. | timeout, reconnect window |
| **Reconnect** | Returning within the grace period and resuming with score and turn position intact. | rejoin, resume |
| **Rejoin** | Entering a room again as a new arrival, after the grace period has passed. | reconnect |
