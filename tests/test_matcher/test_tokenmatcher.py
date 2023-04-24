"""Tests for tokenmatcher module."""
import pickle
import typing as ty

import pytest
import spacy
from spacy.errors import MatchPatternError
from spacy.language import Language
from spacy.tokens import Doc
from spacy.tokens import Span

from spaczz.matcher import TokenMatcher


def add_name_ent(
    matcher: TokenMatcher,
    doc: Doc,
    i: int,
    matches: ty.List[ty.Tuple[str, int, int, None]],
) -> None:
    """Callback on match function. Adds "NAME" entities to doc."""
    _match_id, start, end, _ratio = matches[i]
    entity = Span(doc, start, end, label="NAME")
    doc.ents += (entity,)  # type: ignore


@pytest.fixture
def matcher(nlp: Language) -> TokenMatcher:
    """It returns a token matcher."""
    matcher = TokenMatcher(vocab=nlp.vocab)
    matcher.add(
        "DATA",
        [
            [
                {"TEXT": "SQL"},
                {"LOWER": {"FREGEX": "(database){s<=1}"}},
                {"LOWER": {"FUZZY": "access"}},
            ],
            [{"TEXT": {"FUZZY": "Sequel"}}, {"LOWER": "db"}],
        ],
    )
    matcher.add("NAME", [[{"TEXT": {"FUZZY": "Garfield"}}]], on_match=add_name_ent)
    return matcher


@pytest.fixture
def doc(nlp: Language) -> Doc:
    """Example doc for search."""
    return nlp(
        """The manager gave me SQL databesE acess so now I can acces the Sequal DB.
        My manager's name is Grfield.
        """
    )


def test_adding_patterns(matcher: TokenMatcher) -> None:
    """It adds the "TEST" label and some patterns to the matcher."""
    assert matcher.patterns == [
        {
            "label": "DATA",
            "pattern": [
                {"TEXT": "SQL"},
                {"LOWER": {"FREGEX": "(database){s<=1}"}},
                {"LOWER": {"FUZZY": "access"}},
            ],
            "type": "token",
        },
        {
            "label": "DATA",
            "pattern": [{"TEXT": {"FUZZY": "Sequel"}}, {"LOWER": "db"}],
            "type": "token",
        },
        {
            "label": "NAME",
            "pattern": [{"TEXT": {"FUZZY": "Garfield"}}],
            "type": "token",
        },
    ]


def test_add_without_list_of_patterns_raises_error(matcher: TokenMatcher) -> None:
    """Trying to add non-sequences of patterns raises a TypeError."""
    with pytest.raises(TypeError):
        matcher.add("TEST", [{"TEXT": "error"}])  # type: ignore


def test_add_with_zero_len_pattern(matcher: TokenMatcher) -> None:
    """Trying to add zero-length patterns raises a ValueError."""
    with pytest.raises(ValueError):
        matcher.add("TEST", [[]])


def test_len_returns_count_of_labels_in_matcher(matcher: TokenMatcher) -> None:
    """It returns the sum of unique labels in the matcher."""
    assert len(matcher) == 2


def test_in_returns_bool_of_label_in_matcher(matcher: TokenMatcher) -> None:
    """It returns whether a label is in the matcher."""
    assert "DATA" in matcher


def test_labels_returns_label_names(matcher: TokenMatcher) -> None:
    """It returns a tuple of all unique label names."""
    assert all(label in matcher.labels for label in ("DATA", "NAME"))


def test_vocab_prop_returns_vocab(matcher: TokenMatcher, nlp: Language) -> None:
    """It returns the vocab it was initialized with."""
    assert matcher.vocab == nlp.vocab


def test_remove_label(matcher: TokenMatcher) -> None:
    """It removes a label from the matcher."""
    matcher.add("TEST", [[{"TEXT": "test"}]])
    assert "TEST" in matcher
    matcher.remove("TEST")
    assert "TEST" not in matcher


def test_remove_label_raises_error_if_label_not_in_matcher(
    matcher: TokenMatcher,
) -> None:
    """It raises a ValueError if trying to remove a label not present."""
    with pytest.raises(ValueError):
        matcher.remove("TEST")


def test_matcher_returns_matches(matcher: TokenMatcher, doc: Doc) -> None:
    """Calling the matcher on a `Doc` object returns matches."""
    assert matcher(doc) == [
        ("DATA", 4, 7, None),
        ("DATA", 13, 15, None),
        ("NAME", 22, 23, None),
    ]


def test_matcher_returns_matches_in_expected_order(nlp: Language) -> None:
    """Calling the matcher on a `Doc` object returns matches in expected order."""
    matcher = TokenMatcher(nlp.vocab)
    matcher.add(
        "COMPANY",
        [
            [
                {"IS_UPPER": True, "OP": "+"},
                {"IS_PUNCT": True, "OP": "?"},
                {"TEXT": {"REGEX": r"S\.\s?[A-Z]\.?\s?[A-Z]?\.?"}},
                {"IS_PUNCT": True, "OP": "?"},
            ]
        ],
    )
    doc = nlp("My company is called LARGO AND MARMG S.L.")
    matches = matcher(doc)
    assert doc[matches[0][1] : matches[0][2]].text == "LARGO AND MARMG S.L."


def test_matcher_returns_empty_list_if_no_matches(nlp: Language) -> None:
    """Calling the matcher on a `Doc` object with no matches returns empty list."""
    matcher = TokenMatcher(nlp.vocab)
    matcher.add("TEST", [[{"TEXT": {"FUZZY": "blah"}}]])
    doc = nlp("No matches here.")
    assert matcher(doc) == []


def test_matcher_uses_on_match_callback(matcher: TokenMatcher, doc: Doc) -> None:
    """It utilizes callback on match functions passed when called on a Doc object."""
    matcher(doc)
    ent_text = [ent.text for ent in doc.ents]
    assert "Grfield" in ent_text


def test_pickling_matcher(nlp: Language) -> None:
    """It pickles the matcher object."""
    matcher = TokenMatcher(nlp.vocab)
    matcher.add("NAME", [[{"TEXT": {"FUZZY": "Ridley"}}, {"TEXT": {"FUZZY": "Scott"}}]])
    bytestring = pickle.dumps(matcher)
    assert type(bytestring) == bytes


def test_unpickling_matcher(nlp: Language) -> None:
    """It unpickles the matcher object."""
    matcher = TokenMatcher(nlp.vocab)
    matcher.add("NAME", [[{"TEXT": {"FUZZY": "Ridley"}}, {"TEXT": {"FUZZY": "Scott"}}]])
    bytestring = pickle.dumps(matcher)
    matcher = pickle.loads(bytestring)
    doc = nlp("Rdley Scot was the director of Alien.")
    assert matcher(doc) == [("NAME", 0, 2, None)]
