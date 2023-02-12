"""Module for TokenSearcher: flexible token searching in spaCy `Doc` objects."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import regex
from spacy.tokens import Doc
from spacy.tokens import Token
from spacy.vocab import Vocab

from ..registry import fuzzy_funcs
from ..util import n_wise


class TokenSearcher:
    """Class for flexbile token searching in spaCy `Doc` objects.

    Uses individual (and extended) spaCy token matching patterns to find
    match candidates. Candidates are used to generate new patterns to add
    to a spaCy `Matcher`.

    "FUZZY" and "FREGEX" are the two additional spaCy token pattern options.

    For example:
        {"TEXT": {"FREGEX": "(database){e<=1}"}},
        {"LOWER": {"FUZZY": "access", "MIN_R": 85, "FUZZY_FUNC": "quick_lev"}}

    Make sure to use uppercase dictionary keys in patterns.

    Attributes:
        vocab (Vocab): The shared vocabulary.
            Included for consistency and potential future-state.
        _fuzzy_funcs (FuzzyFuncs):
            Container class housing fuzzy matching functions.
            Functions are accessible via the classes `get()` method
            by their given key name. The following rapidfuzz matching
            functions with default settings are available:
            "simple" = `ratio`
            "quick" = `QRatio`
            "quick_lev" = `quick_lev_ratio`
    """

    def __init__(self: TokenSearcher, vocab: Vocab) -> None:
        """Initializes a token searcher.

        Args:
            vocab: A spaCy `Vocab` object.
                Purely for consistency between spaCy
                and spaczz matcher APIs for now.
                spaczz matchers are mostly pure-Python
                currently and do not share vocabulary
                with spaCy pipelines.
        """
        self.vocab = vocab

    def fuzzy_compare(
        self: TokenSearcher,
        s1: str,
        s2: str,
        ignore_case: bool = True,
        score_cutoff: int = 0,
        fuzzy_func: str = "simple",
    ) -> int:
        """Peforms fuzzy matching between two strings.

        Applies the given fuzzy matching algorithm (fuzzy_func)
        to two strings and returns the resulting fuzzy ratio.

        Args:
            s1: First string for comparison.
            s2: Second string for comparison.
            ignore_case: Whether to lower-case a and b
                before comparison or not. Default is `True`.
            score_cutoff: Score threshold as a float between `0` and `100`.
                For ratio < score_cutoff, `0` is returned instead.
                Default is `0`, which deactivates this behaviour.
            fuzzy_func: Key name of fuzzy matching function to use.
                The following rapidfuzz matching functions with default
                settings are available:
                "simple" = `ratio`
                "quick" = `QRatio`
                Default is `"simple"`.

        Returns:
            The fuzzy ratio between a and b.

        Example:
            >>> import spacy
            >>> from spaczz.search import TokenSearcher
            >>> nlp = spacy.blank("en")
            >>> searcher = TokenSearcher(nlp.vocab)
            >>> searcher.fuzzy_compare("spaczz", "spacy")
            73
        """
        if ignore_case:
            s1 = s1.lower()
            s2 = s2.lower()
        return round(fuzzy_funcs.get(fuzzy_func)(s1, s2, score_cutoff=score_cutoff))

    def match(
        self: TokenSearcher,
        doc: Doc,
        pattern: List[Dict[str, Any]],
        min_r: int = 75,
        fuzzy_func: str = "simple",
    ) -> List[List[Optional[Tuple[str, str]]]]:
        """Finds potential token pattern matches in a `Doc` object.

        Make sure to use uppercase dictionary keys in patterns.

        Args:
            doc: `Doc` object to search over.
            pattern: Individual spaCy token pattern.
            min_r: Minimum match ratio required for fuzzy matching.
                Can be overwritten with token pattern options.
                Default is `75`.
            fuzzy_func: Fuzzy matching function to use.
                Can be overwritten with token pattern options.
                Default is `simple`.

        Returns:
            A list of lists with each inner list representing a potential match.
            The inner lists will be populated with key, value tuples of token matches
            and `None` for placeholder tokens representing non-fuzzy tokens.

        Raises:
            TypeError: doc must be a `Doc` object.
            TypeError: pattern must be a `Sequence`.
            ValueError: pattern cannot have zero tokens.

        Example:
            >>> import spacy
            >>> from spaczz.search import TokenSearcher
            >>> nlp = spacy.blank("en")
            >>> searcher = TokenSearcher(nlp)
            >>> doc = nlp("I was prescribed zithramax and advar")
            >>> pattern = [
                {"TEXT": {"FUZZY": "zithromax"}},
                {"POS": "CCONJ"},
                {"TEXT": {"FREGEX": "(advair){e<=1}"}}
                ]
            >>> searcher.match(doc, pattern)
            [[('TEXT', 'zithramax'), None, ('TEXT', 'advar')]]
        """
        if not isinstance(doc, Doc):
            raise TypeError("doc must be a Doc object.")
        if not isinstance(pattern, list):
            raise TypeError(
                "pattern must be a list",
                "Make sure pattern is wrapped in a list.",
            )
        if len(pattern) == 0:
            raise ValueError("pattern cannot have zero tokens.")
        matches = []
        for seq in n_wise(doc, len(pattern)):
            seq_matches = self._iter_pattern(seq, pattern, min_r, fuzzy_func)
            if seq_matches:
                matches.append(seq_matches)
        if matches:
            return [
                match for i, match in enumerate(matches) if match not in matches[:i]
            ]
        return matches

    @staticmethod
    def regex_compare(text: str, pattern: str, ignore_case: bool = False) -> bool:
        """Performs fuzzy-regex supporting regex matching between two strings.

        Args:
            text: The string to match against.
            pattern: The regex pattern string.
            ignore_case: Whether to lower-case text
                before comparison or not. Default is `False`.

        Returns:
            `True` if match, `False` if not.

        Example:
            >>> import spacy
            >>> from spaczz.search import TokenSearcher
            >>> nlp = spacy.blank("en")
            >>> searcher = TokenSearcher(nlp)
            >>> searcher.regex_compare("sequel", "(sql){i<=3}")
            True
        """
        if ignore_case:
            text = text.lower()
        if regex.match(pattern, text):
            return True
        else:
            return False

    def _iter_pattern(
        self: TokenSearcher,
        seq: Tuple[Token, ...],
        pattern: List[Dict[str, Any]],
        min_r: int,
        fuzzy_func: str,
    ) -> List[Optional[Tuple[str, str]]]:
        """Evaluates each token in a pattern against a doc token sequence."""
        seq_matches: List[Optional[Tuple[str, str]]] = []
        for i, token in enumerate(pattern):
            pattern_dict, case, case_bool = self._parse_case(token)
            if isinstance(pattern_dict, dict):
                pattern_text, pattern_type = self._parse_type(pattern_dict)
                if pattern_text and pattern_type == "FUZZY":
                    min_r_ = pattern_dict.get("MIN_R", min_r)
                    if (
                        self.fuzzy_compare(
                            seq[i].text,
                            pattern_text,
                            case_bool,
                            min_r_,
                            pattern_dict.get("FUZZY_FUNC", fuzzy_func),
                        )
                        >= min_r_
                    ):
                        seq_matches.append((case, seq[i].text))
                    else:
                        return []
                elif pattern_text and pattern_type == "FREGEX":
                    if self.regex_compare(seq[i].text, pattern_text, case_bool):
                        seq_matches.append((case, seq[i].text))
                    else:
                        return []
                else:
                    seq_matches.append(None)
            else:
                seq_matches.append(None)
        return seq_matches

    @staticmethod
    def _parse_case(token: Dict[str, Any]) -> Tuple[Union[str, Dict, None], str, bool]:
        """Parses the case of a token pattern."""
        text = token.get("TEXT")
        if text:
            return text, "TEXT", False
        return token.get("LOWER"), "LOWER", True

    @staticmethod
    def _parse_type(pattern_dict: Dict[str, Any]) -> Tuple[str, str]:
        """Parses the type of a token pattern."""
        fuzzy_text = pattern_dict.get("FUZZY")
        regex_text = pattern_dict.get("FREGEX")
        if isinstance(fuzzy_text, str):
            return fuzzy_text, "FUZZY"
        elif isinstance(regex_text, str):
            return regex_text, "FREGEX"
        return "", ""
