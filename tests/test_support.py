"""The local support check (src/relay/support.py)."""

from relay.support import check


def test_numbers_must_appear_in_the_quote():
    assert check("It has 16 heads and 6 layers.", "the Depth Transformer has 6 layers and 16 attention heads")[0]
    assert not check("It has 32 heads.", "the Depth Transformer has 16 attention heads")[0]


def test_number_words_count_as_numbers():
    assert check("It uses six layers and sixteen attention heads.", "has 6 layers, and 16 attention heads")[0]


def test_word_forms_match_by_stem():
    assert check("a single head would average these signals", "With a single attention head, averaging inhibits this.")[0]


def test_claim_that_adds_content_is_flagged():
    ok, cov, missing = check("The decoder restores the original sequence length for final output.",
                             "H-Net comprises encoder networks, main network, and decoder networks")
    assert not ok and cov < 0.6 and "resto" in missing
