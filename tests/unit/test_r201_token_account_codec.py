"""Tests for argus.executor.token_account_codec -- R2-01
(``argus-final-spec-recovery-002``)."""

from __future__ import annotations

import pytest
from solders.pubkey import Pubkey

from argus.executor.token_account_codec import (
    TokenAccountDecodeError,
    decode_token_account,
)


def _encode_token_account(
    *, mint: Pubkey, owner: Pubkey, amount: int, total_len: int = 165
) -> bytes:
    body = bytes(mint) + bytes(owner) + amount.to_bytes(8, "little", signed=False)
    return body + bytes(total_len - len(body))


def test_decode_token_account_round_trips_mint_owner_amount() -> None:
    mint = Pubkey.new_unique()
    owner = Pubkey.new_unique()
    data = _encode_token_account(mint=mint, owner=owner, amount=123_456_789)

    decoded = decode_token_account(data)

    assert decoded.mint == str(mint)
    assert decoded.owner == str(owner)
    assert decoded.amount_raw == 123_456_789


def test_decode_token_account_fails_closed_on_short_data() -> None:
    with pytest.raises(TokenAccountDecodeError):
        decode_token_account(b"\x00" * 10)


def test_decode_token_account_amount_is_little_endian() -> None:
    mint = Pubkey.new_unique()
    owner = Pubkey.new_unique()
    # 1 in little-endian u64 must decode as 1, never as a huge big-endian value.
    data = _encode_token_account(mint=mint, owner=owner, amount=1)

    decoded = decode_token_account(data)

    assert decoded.amount_raw == 1
