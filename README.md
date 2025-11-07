# Excel → Flashcards (Streamlit)

Build Leitner-style flashcards straight from an Excel vocabulary list. Upload a `.xlsx` file, study with spaced repetition, filter/search cards, and export to Anki-friendly CSV.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the local Streamlit URL (usually `http://localhost:8501`) in your browser.

## Usage

1. Upload a vocabulary workbook (`.xlsx`). A sample deck is provided as `sample.xlsx`.
2. If the workbook has multiple sheets, pick the target sheet from the dropdown.
3. Study cards:
   - Front shows the English word in large type.
   - Click **Show Back** to reveal the translation plus example sentences (split on `;`).
   - Use **I forgot** / **I knew it** to move cards through a 3-box Leitner system (box 1 = most frequent).
   - Navigation buttons: **Previous**, **Next**, **Shuffle**, **Restart**.
4. Use the sidebar search box (covers english/translation/sentences) and optional tag filter (`tag` column) to focus on subsets.
5. Progress indicators show studied count plus Box 1/2/3 totals. Low-box cards appear first when looping the deck, and each box shuffles independently when shuffle mode is enabled (default).
6. Export the current filtered deck via **Export deck to CSV** (`Front;Back;Tags`, compatible with Anki). Sentences are stacked on new lines in the back field.

## Excel format

| Column      | Required | Notes                                           |
| ----------- | -------- | ----------------------------------------------- |
| `english`   | ✔︎        | Card front. Case-insensitive duplicate entries are deduped. |
| `translation` | ✔︎      | Card back (first line).                         |
| `sentence`  | ✔︎        | Example sentence(s); split on `;` into bullets. |
| `tag`       | optional | Used for filtering/exported tags.               |

Additional sheets are supported—the app loads the first sheet by default but lets you choose another.

## Persistence

Leitner boxes, the last-studied index/card, shuffle preference, and studied progress persist between sessions. State is written to `.deck_state.json` in the project root (one entry per deck, keyed by a hash of the uploaded file + sheet). Delete that file to reset all saved progress.

## Testing & validation

- Upload `sample.xlsx` to verify the full flow (3 cards, tag filter, sentences split correctly).
- Use the navigation buttons to confirm Leitner box transitions:
  - **I forgot** sends a card to Box 1.
  - **I knew it** advances up to Box 3.
- Refresh the page and re-upload the same file to ensure progress, Leitner state, and your last position persist.
# flashcard_game-
