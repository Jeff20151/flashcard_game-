from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Excel → Flashcards", layout="wide")


STATE_FILE = Path(".deck_state.json")
REQUIRED_COLUMNS = ["english", "translation", "sentence"]
OPTIONAL_COLUMNS = ["tag"]


@dataclass
class Card:
    id: str
    english: str
    translation: str
    sentences: List[str]
    tag: Optional[str] = None


def read_state_file() -> Dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as state_handle:
            return json.load(state_handle)
    except json.JSONDecodeError:
        return {}


def write_state_file(payload: Dict[str, dict]) -> None:
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_saved_state(deck_id: str) -> Optional[dict]:
    return read_state_file().get(deck_id)


def save_deck_state(deck_id: str, data: dict) -> None:
    all_state = read_state_file()
    all_state[deck_id] = data
    write_state_file(all_state)


@st.cache_data(show_spinner=False)
def list_sheet_names(file_bytes: bytes) -> List[str]:
    buffer = io.BytesIO(file_bytes)
    with pd.ExcelFile(buffer) as workbook:
        return workbook.sheet_names


@st.cache_data(show_spinner=False)
def parse_cards(file_bytes: bytes, sheet_name: str | int) -> List[Card]:
    buffer = io.BytesIO(file_bytes)
    df = pd.read_excel(buffer, sheet_name=sheet_name)
    df = normalize_columns(df)
    df = drop_blank_rows(df)

    seen_english = set()
    cards: List[Card] = []

    for _, row in df.iterrows():
        english = sanitize_text(row["english"])
        translation = sanitize_text(row["translation"])
        sentence_blob = sanitize_text(row["sentence"])
        tag_value = sanitize_text(row.get("tag", ""))

        if not english or not translation:
            continue

        normalized_key = english.lower()
        if normalized_key in seen_english:
            continue
        seen_english.add(normalized_key)

        sentences = split_sentences(sentence_blob)
        hash_seed = "||".join([english, translation, sentence_blob, tag_value])
        card_id = hashlib.md5(hash_seed.encode("utf-8")).hexdigest()
        cards.append(Card(card_id, english, translation, sentences, tag_value or None))

    return cards


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {col: str(col).strip().lower() for col in df.columns}
    df = df.rename(columns=rename_map)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        human_list = ", ".join(missing)
        raise ValueError(f"Missing required column(s): {human_list}")
    return df


def drop_blank_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.replace({pd.NA: "", None: ""})
    for column in REQUIRED_COLUMNS:
        df[column] = df[column].apply(lambda value: sanitize_text(value))
    df = df[df["english"].astype(bool)]
    df = df.drop_duplicates(subset=["english"], keep="first")
    df = df.reset_index(drop=True)
    return df


def sanitize_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if pd.isna(value):
        return ""
    return str(value).strip()


def split_sentences(blob: str) -> List[str]:
    if not blob:
        return []
    parts = re.split(r"[;\n]", blob)
    return [segment.strip() for segment in parts if segment.strip()]


def compute_deck_id(file_bytes: bytes, sheet_name: str | int) -> str:
    hasher = hashlib.md5()
    hasher.update(file_bytes)
    hasher.update(str(sheet_name).encode("utf-8"))
    return hasher.hexdigest()


def ensure_session_defaults() -> None:
    defaults = {
        "cards": [],
        "deck_id": "",
        "leitner": {},
        "current_idx": 0,
        "current_card_id": "",
        "show_back": False,
        "studied_ids": set(),
        "shuffle_mode": True,
        "shuffle_seed": random.randint(0, 1_000_000),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def initialize_deck_state(deck_id: str, cards: Sequence[Card]) -> None:
    saved = load_saved_state(deck_id)
    ensure_session_defaults()

    if st.session_state.deck_id == deck_id:
        st.session_state.cards = list(cards)
        refresh_missing_cards(cards)
        return

    st.session_state.deck_id = deck_id
    st.session_state.cards = list(cards)
    st.session_state.leitner = (
        saved.get("leitner", {}) if saved else {card.id: 1 for card in cards}
    )
    refresh_missing_cards(cards)
    st.session_state.current_card_id = saved.get("current_card_id", "") if saved else ""
    st.session_state.current_idx = saved.get("current_idx", 0) if saved else 0
    st.session_state.show_back = False
    st.session_state.shuffle_mode = saved.get("shuffle_mode", True) if saved else True
    st.session_state.shuffle_seed = (
        saved.get("shuffle_seed") if saved and "shuffle_seed" in saved else random.randint(0, 1_000_000)
    )
    studied_list = saved.get("studied_ids", []) if saved else []
    st.session_state.studied_ids = set(studied_list)
    persist_state()


def refresh_missing_cards(cards: Sequence[Card]) -> None:
    for card in cards:
        st.session_state.leitner.setdefault(card.id, 1)


def persist_state() -> None:
    if not st.session_state.deck_id:
        return
    payload = {
        "leitner": st.session_state.leitner,
        "current_idx": st.session_state.current_idx,
        "current_card_id": st.session_state.current_card_id,
        "studied_ids": sorted(list(st.session_state.studied_ids)),
        "shuffle_mode": st.session_state.shuffle_mode,
        "shuffle_seed": st.session_state.shuffle_seed,
    }
    save_deck_state(st.session_state.deck_id, payload)


def apply_filters(cards: Sequence[Card], query: str, tags: Sequence[str]) -> List[Card]:
    filtered = []
    normalized_query = query.lower().strip()
    tag_set = {tag.lower() for tag in tags if tag}

    for card in cards:
        matches_query = True
        if normalized_query:
            searchable = " ".join([card.english, card.translation, " ".join(card.sentences)]).lower()
            matches_query = normalized_query in searchable

        matches_tag = True
        if tag_set:
            card_tag = (card.tag or "").lower()
            matches_tag = card_tag in tag_set

        if matches_query and matches_tag:
            filtered.append(card)

    return filtered


def prioritize_cards(cards: Sequence[Card]) -> List[Card]:
    buckets: Dict[int, List[Card]] = {1: [], 2: [], 3: []}
    for card in cards:
        box = st.session_state.leitner.get(card.id, 1)
        buckets[box].append(card)

    ordered: List[Card] = []
    rng = random.Random(st.session_state.shuffle_seed)
    for box in (1, 2, 3):
        bucket = buckets.get(box, [])
        if st.session_state.shuffle_mode:
            rng.shuffle(bucket)
        ordered.extend(bucket)

    return ordered


def resolve_current_index(visible_cards: Sequence[Card]) -> int:
    if not visible_cards:
        st.session_state.current_idx = 0
        st.session_state.current_card_id = ""
        return 0
    changed = False
    current_id = st.session_state.current_card_id
    if current_id:
        prev_idx = st.session_state.current_idx
        for idx, card in enumerate(visible_cards):
            if card.id == current_id:
                st.session_state.current_idx = idx
                if idx != prev_idx:
                    persist_state()
                return idx

    new_idx = min(st.session_state.current_idx, len(visible_cards) - 1)
    new_idx = max(new_idx, 0)
    if new_idx != st.session_state.current_idx:
        changed = True
    st.session_state.current_idx = new_idx
    new_id = visible_cards[new_idx].id
    if new_id != st.session_state.current_card_id:
        changed = True
    st.session_state.current_card_id = new_id
    if changed:
        persist_state()
    return st.session_state.current_idx


def move_index(step: int, visible_cards: Sequence[Card]) -> None:
    if not visible_cards:
        return
    new_idx = (st.session_state.current_idx + step) % len(visible_cards)
    st.session_state.current_idx = new_idx
    st.session_state.current_card_id = visible_cards[new_idx].id
    st.session_state.show_back = False
    persist_state()


def update_leitner(card_id: str, box: int) -> None:
    st.session_state.leitner[card_id] = box
    persist_state()


def handle_feedback(card: Card, remembered: bool, visible_cards: Sequence[Card]) -> None:
    box = st.session_state.leitner.get(card.id, 1)
    if remembered:
        box = min(3, box + 1)
    else:
        box = 1
    update_leitner(card.id, box)
    st.session_state.studied_ids.add(card.id)
    st.session_state.show_back = False
    move_index(1, visible_cards)
    persist_state()


def restart_session(cards: Sequence[Card]) -> None:
    st.session_state.leitner = {card.id: 1 for card in cards}
    st.session_state.current_idx = 0
    st.session_state.current_card_id = cards[0].id if cards else ""
    st.session_state.show_back = False
    st.session_state.studied_ids = set()
    st.session_state.shuffle_seed = random.randint(0, 1_000_000)
    persist_state()


def build_export_payload(cards: Sequence[Card]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["Front", "Back", "Tags"])
    for card in cards:
        back_lines = [card.translation] + card.sentences
        back = "\n".join([line for line in back_lines if line]).strip()
        writer.writerow([card.english, back, card.tag or ""])
    return buffer.getvalue()


def render_card(card: Card, target=None) -> None:
    target = target or st
    if "_card_style_injected" not in st.session_state:
        target.markdown(
            """
            <style>
            .flashcard {
                border: 1px solid #ccc;
                border-radius: 10px;
                padding: 2rem;
                min-height: 240px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                background: var(--card-bg, rgba(31, 31, 31, 0.05));
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }
            .flashcard__front {
                text-align: center;
                font-size: 2.5rem;
                font-weight: 700;
                margin-bottom: 1rem;
            }
            .flashcard__back {
                font-size: 1.2rem;
                line-height: 1.6;
            }
            .flashcard__examples {
                margin-top: 0.5rem;
                padding-left: 1.25rem;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.session_state["_card_style_injected"] = True

    wrapper_id = f"flashcard-{card.id}"
    front_html = f"<div class='flashcard__front'>{escape(card.english) or '—'}</div>"
    back_html = ""
    if st.session_state.show_back:
        translation_html = f"<p><strong>{escape(card.translation)}</strong></p>"
        if card.sentences:
            examples = "".join(f"<li>{escape(sentence)}</li>" for sentence in card.sentences)
            sentences_html = f"<div><strong>Example(s)</strong><ul class='flashcard__examples'>{examples}</ul></div>"
        else:
            sentences_html = "<em>No example provided.</em>"
        back_html = f"<div class='flashcard__back'>{translation_html}{sentences_html}</div>"

    card_html = f"<div id='{wrapper_id}' class='flashcard'>{front_html}{back_html}</div>"
    target.markdown(card_html, unsafe_allow_html=True)


def main() -> None:
    st.title("Excel → Flashcards (Streamlit)")
    st.write("Upload your vocabulary Excel file to start a Leitner-based study session.")

    uploaded = st.file_uploader("Upload .xlsx file", type=["xlsx"])
    if not uploaded:
        st.info("Use the uploader above to add your vocabulary deck.")
        return

    file_bytes = uploaded.getvalue()
    sheet_names = list_sheet_names(file_bytes)
    sheet_name: str | int
    if len(sheet_names) == 1:
        sheet_name = sheet_names[0]
    else:
        sheet_name = st.selectbox("Select sheet", sheet_names, index=0)

    try:
        cards = parse_cards(file_bytes, sheet_name)
    except ValueError as err:
        st.error(str(err))
        return

    if not cards:
        st.warning("No valid cards found.")
        return

    deck_id = compute_deck_id(file_bytes, sheet_name)
    initialize_deck_state(deck_id, cards)

    tag_options = sorted({card.tag for card in cards if card.tag})
    with st.sidebar:
        st.header("Filters & Settings")
        query = st.text_input(
            "Search (english, translation, sentence)",
            key="query",
            placeholder="Type to filter cards…",
        )
        selected_tags: List[str] = []
        if tag_options:
            selected_tags = st.multiselect("Filter by tag", tag_options)
        prev_shuffle_mode = st.session_state.shuffle_mode
        st.checkbox(
            "Shuffle mode",
            key="shuffle_mode",
            help="When ON, cards inside each Leitner box are shuffled each loop.",
        )
        if st.session_state.shuffle_mode != prev_shuffle_mode:
            st.session_state.show_back = False
            persist_state()

    visible_cards = apply_filters(st.session_state.cards, query, selected_tags)
    if not visible_cards:
        st.warning("No cards matched your filters.")
        return

    prioritized_cards = prioritize_cards(visible_cards)

    current_idx = resolve_current_index(prioritized_cards)
    current_card = prioritized_cards[current_idx]

    progress = len(st.session_state.studied_ids)
    total_cards = len(st.session_state.cards)
    st.progress(progress / total_cards if total_cards else 0.0, text=f"{progress} / {total_cards} studied")

    box_counts = {1: 0, 2: 0, 3: 0}
    for card in st.session_state.cards:
        box = st.session_state.leitner.get(card.id, 1)
        box_counts[box] = box_counts.get(box, 0) + 1

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Box 1", box_counts.get(1, 0))
    col_b.metric("Box 2", box_counts.get(2, 0))
    col_c.metric("Box 3", box_counts.get(3, 0))

    card_holder = st.empty()
    flip_clicked = st.button(
        "Flip card",
        key=f"flip-card-{current_card.id}",
        help="按一下翻面顯示中文與例句",
        use_container_width=True,
    )
    if flip_clicked:
        st.session_state.show_back = not st.session_state.show_back
        persist_state()

    render_card(current_card, card_holder)

    action_row = st.columns([1, 1, 1, 1, 1, 1, 1])
    if action_row[0].button("Show Back" if not st.session_state.show_back else "Hide Back"):
        st.session_state.show_back = not st.session_state.show_back

    action_row[1].button("Previous", on_click=move_index, args=(-1, prioritized_cards))
    action_row[2].button("Next", on_click=move_index, args=(1, prioritized_cards))

    action_row[3].button(
        "I forgot",
        on_click=handle_feedback,
        args=(current_card, False, prioritized_cards),
        disabled=not st.session_state.show_back,
    )
    action_row[4].button(
        "I knew it",
        on_click=handle_feedback,
        args=(current_card, True, prioritized_cards),
        disabled=not st.session_state.show_back,
    )
    if action_row[5].button("Shuffle"):
        st.session_state.shuffle_seed = random.randint(0, 1_000_000)
        st.session_state.show_back = False
        persist_state()
    if action_row[6].button("Restart"):
        restart_session(st.session_state.cards)

    export_payload = build_export_payload(prioritized_cards)
    st.download_button(
        "Export deck to CSV",
        data=export_payload,
        file_name="deck.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
