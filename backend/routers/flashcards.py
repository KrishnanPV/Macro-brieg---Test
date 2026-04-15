"""Flash card deck and card CRUD endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db import get_session, FlashCardDeck, FlashCard
from backend.models.schemas import (
    FlashCardDeckCreate, FlashCardDeckOut,
    FlashCardCreate, FlashCardUpdate, FlashCardOut,
)

router = APIRouter(prefix="/api/workspaces/{ws_id}/flashcards", tags=["flashcards"])


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------

@router.get("/decks", response_model=list[FlashCardDeckOut])
async def list_decks(ws_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(FlashCardDeck).where(FlashCardDeck.workspace_id == ws_id)
    )
    decks = result.scalars().all()
    out = []
    for deck in decks:
        count_result = await db.execute(
            select(func.count(FlashCard.id)).where(FlashCard.deck_id == deck.id)
        )
        count = count_result.scalar() or 0
        out.append(_deck_out(deck, count))
    return out


@router.post("/decks", response_model=FlashCardDeckOut, status_code=201)
async def create_deck(ws_id: str, body: FlashCardDeckCreate, db: AsyncSession = Depends(get_session)):
    deck = FlashCardDeck(workspace_id=ws_id, name=body.name)
    deck.tags = body.tags
    db.add(deck)
    await db.commit()
    await db.refresh(deck)
    return _deck_out(deck, 0)


@router.delete("/decks/{deck_id}", status_code=204)
async def delete_deck(ws_id: str, deck_id: str, db: AsyncSession = Depends(get_session)):
    deck = await db.get(FlashCardDeck, deck_id)
    if not deck or deck.workspace_id != ws_id:
        raise HTTPException(404, "Deck not found")
    await db.delete(deck)
    await db.commit()


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

@router.get("/decks/{deck_id}/cards", response_model=list[FlashCardOut])
async def list_cards(ws_id: str, deck_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(FlashCard).where(FlashCard.deck_id == deck_id)
    )
    return [_card_out(c) for c in result.scalars().all()]


@router.post("/decks/{deck_id}/cards", response_model=FlashCardOut, status_code=201)
async def create_card(ws_id: str, deck_id: str, body: FlashCardCreate, db: AsyncSession = Depends(get_session)):
    deck = await db.get(FlashCardDeck, deck_id)
    if not deck or deck.workspace_id != ws_id:
        raise HTTPException(404, "Deck not found")

    card = FlashCard(
        deck_id=deck_id,
        front=body.front,
        back=body.back,
        source_cell_id=body.source_cell_id,
    )
    card.tags = body.tags
    card.next_review = datetime.now(timezone.utc)
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return _card_out(card)


@router.patch("/decks/{deck_id}/cards/{card_id}", response_model=FlashCardOut)
async def update_card(
    ws_id: str, deck_id: str, card_id: str,
    body: FlashCardUpdate, db: AsyncSession = Depends(get_session),
):
    card = await db.get(FlashCard, card_id)
    if not card or card.deck_id != deck_id:
        raise HTTPException(404, "Card not found")
    if body.front is not None:
        card.front = body.front
    if body.back is not None:
        card.back = body.back
    if body.tags is not None:
        card.tags = body.tags
    if body.ease_factor is not None:
        card.ease_factor = body.ease_factor
    if body.interval_days is not None:
        card.interval_days = body.interval_days
    await db.commit()
    await db.refresh(card)
    return _card_out(card)


@router.post("/decks/{deck_id}/cards/{card_id}/review")
async def review_card(
    ws_id: str, deck_id: str, card_id: str,
    quality: int,  # 0-5 SM-2 quality rating
    db: AsyncSession = Depends(get_session),
):
    """Apply SM-2 spaced repetition algorithm after a review."""
    card = await db.get(FlashCard, card_id)
    if not card or card.deck_id != deck_id:
        raise HTTPException(404, "Card not found")

    quality = max(0, min(5, quality))

    if quality >= 3:
        if card.repetitions == 0:
            card.interval_days = 1
        elif card.repetitions == 1:
            card.interval_days = 6
        else:
            card.interval_days = int(card.interval_days * card.ease_factor)
        card.repetitions += 1
    else:
        card.repetitions = 0
        card.interval_days = 1

    card.ease_factor = max(
        1.3,
        card.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)),
    )
    card.next_review = datetime.now(timezone.utc) + timedelta(days=card.interval_days)

    await db.commit()
    await db.refresh(card)
    return _card_out(card)


@router.get("/due", response_model=list[FlashCardOut])
async def get_due_cards(ws_id: str, db: AsyncSession = Depends(get_session)):
    """Get all cards due for review across all decks in this workspace."""
    now = datetime.now(timezone.utc)
    deck_result = await db.execute(
        select(FlashCardDeck.id).where(FlashCardDeck.workspace_id == ws_id)
    )
    deck_ids = [d for d in deck_result.scalars().all()]
    if not deck_ids:
        return []

    result = await db.execute(
        select(FlashCard)
        .where(FlashCard.deck_id.in_(deck_ids))
        .where((FlashCard.next_review <= now) | (FlashCard.next_review.is_(None)))
    )
    return [_card_out(c) for c in result.scalars().all()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deck_out(deck: FlashCardDeck, card_count: int) -> dict[str, Any]:
    return {
        "id": deck.id,
        "workspace_id": deck.workspace_id,
        "name": deck.name,
        "tags": deck.tags,
        "card_count": card_count,
        "created_at": deck.created_at.isoformat() if deck.created_at else "",
    }


def _card_out(card: FlashCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "deck_id": card.deck_id,
        "front": card.front,
        "back": card.back,
        "source_cell_id": card.source_cell_id,
        "tags": card.tags,
        "ease_factor": card.ease_factor,
        "interval_days": card.interval_days,
        "repetitions": card.repetitions,
        "next_review": card.next_review.isoformat() if card.next_review else None,
        "created_at": card.created_at.isoformat() if card.created_at else "",
    }
