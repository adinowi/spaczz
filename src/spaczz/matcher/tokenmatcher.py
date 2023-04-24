"""Module for TokenMatcher with an API semi-analogous to spaCy's Matcher."""
from copy import deepcopy
import typing as ty

from spacy.matcher import Matcher
from spacy.tokens import Doc
from spacy.vocab import Vocab
import srsly

from ..search import TokenSearcher


class TokenMatcher:
    """spaCy-like token matcher for finding flexible matches in `Doc` objects.

    Matches added patterns against the `Doc` object it is called on.
    Accepts labeled patterns in the form of lists of dictionaries
    where each list describes an individual pattern and each
    dictionary describes an individual token.

    Uses extended spaCy token matching patterns.
    "FUZZY" and "FREGEX" are the two additional spaCy token pattern options.

    For example:
        {"TEXT": {"FREGEX": "(database){e<=1}"}},
        {"LOWER": {"FUZZY": "access", "MIN_R": 85, "FUZZY_FUNC": "quick_lev"}}

    Make sure to use uppercase dictionary keys in patterns.

    Attributes:
        defaults: Keyword arguments to be used as default matching settings.
            See `TokenSearcher.match()` documentation for details.
        name: Class attribute - the name of the matcher.
        type: The kind of matcher object.
        _callbacks:
            On match functions to modify `Doc` objects passed to the matcher.
            Can make use of the matches identified.
        _patterns:
            Patterns added to the matcher.
    """

    name = "token_matcher"

    def __init__(self: "TokenMatcher", vocab: Vocab, **defaults: ty.Any) -> None:
        """Initializes the base phrase matcher with the given defaults.

        Args:
            vocab: A spacy `Vocab` object.
                Purely for consistency between spaCy
                and spaczz matcher APIs for now.
                spaczz matchers are currently pure
                Python and do not share vocabulary
                with spaCy pipelines.
            **defaults: Keyword arguments that will
                be used as default matching settings.
                These arguments will become the new defaults for matching.
                See `TokenSearcher.match()` documentation for details.
        """
        self.defaults = defaults
        self.type = "token"
        self._callbacks: ty.Dict[str, TokenCallback] = {}
        self._patterns: ty.DefaultDict[
            str, ty.List[ty.List[ty.Dict[str, ty.Any]]]
        ] = ty.DefaultDict(list)
        self._searcher = TokenSearcher(vocab=vocab)

    def __call__(
        self: "TokenMatcher", doc: Doc
    ) -> ty.List[ty.Tuple[str, int, int, int, str]]:
        """Find all sequences matching the supplied patterns in the doc.

        Args:
            doc: The `Doc` object to match over.

        Returns:
            A list of (key, start, end, ratio, pattern) tuples, describing the matches.
            The final None is a placeholder for future match details.

        Example:
            >>> import spacy
            >>> from spaczz.matcher import TokenMatcher
            >>> nlp = spacy.blank("en")
            >>> matcher = TokenMatcher(nlp.vocab)
            >>> doc = nlp("Rdley Scot was the director of Alien.")
            >>> matcher.add("NAME", [
                [{"TEXT": {"FUZZY": "Ridley"}},
                {"TEXT": {"FUZZY": "Scott"}}]
                ])
            >>> matcher(doc)
            [('NAME', 0, 2, None)]
        """
        matches = set()
        for label, patterns in self._patterns.items():
            for pattern in patterns:
                spaczz_matches = self._searcher.match(doc, pattern, **self.defaults)
                if spaczz_matches:
                    for spaczz_match in spaczz_matches:
                        matcher = Matcher(self.vocab)
                        matcher.add(label, [self._spacyfy(spaczz_match, pattern)])
                        spacy_matches = matcher(doc)
                        for match_id, start, end in spacy_matches:
                            matches.add(
                                (
                                    self.vocab.strings[match_id],
                                    start,
                                    end,
                                    round(
                                        sum(
                                            token_match[2]
                                            / sum(
                                                [len(token) for token in doc[start:end]]
                                            )
                                            * len(token)
                                            for token, token_match in zip(  # noqa: B905
                                                doc[start:end], spaczz_match
                                            )
                                        )
                                    ),
                                    srsly.json_dumps(pattern),
                                )
                            )
        sorted_matches = sorted(
            matches, key=lambda x: (-x[1], x[2] - x[1], x[3]), reverse=True
        )
        for i, (label, _start, _end, _ratio, _pattern) in enumerate(sorted_matches):
            on_match = self._callbacks.get(label)
            if on_match:
                on_match(self, doc, i, sorted_matches)
        return sorted_matches

    def __contains__(self: "TokenMatcher", label: str) -> bool:
        """Whether the matcher contains patterns for a label."""
        return label in self._patterns

    def __len__(self: "TokenMatcher") -> int:
        """The number of labels added to the matcher."""
        return len(self._patterns)

    def __reduce__(
        self: "TokenMatcher",
    ) -> ty.Tuple[ty.Any, ty.Any]:  # Precisely typing this would be really long.
        """Interface for pickling the matcher."""
        data = (
            self.__class__,
            self.vocab,
            self._patterns,
            self._callbacks,
            self.defaults,
        )
        return (unpickle_matcher, data)

    @property
    def labels(self: "TokenMatcher") -> ty.Tuple[str, ...]:
        """All labels present in the matcher.

        Returns:
            The unique string labels as a tuple.

        Example:
            >>> import spacy
            >>> from spaczz.matcher import TokenMatcher
            >>> nlp = spacy.blank("en")
            >>> matcher = TokenMatcher(nlp.vocab)
            >>> matcher.add("AUTHOR", [[{"TEXT": {"FUZZY": "Kerouac"}}]])
            >>> matcher.labels
            ('AUTHOR',)
        """
        return tuple(self._patterns.keys())

    @property
    def patterns(self: "TokenMatcher") -> ty.List[ty.Dict[str, ty.Any]]:
        """Get all patterns that were added to the matcher.

        Returns:
            The original patterns, one dictionary for each combination.

        Example:
            >>> import spacy
            >>> from spaczz.matcher import TokenMatcher
            >>> nlp = spacy.blank("en")
            >>> matcher = TokenMatcher(nlp.vocab)
            >>> matcher.add("AUTHOR", [[{"TEXT": {"FUZZY": "Kerouac"}}]])
            >>> matcher.patterns == [
                {
                    "label": "AUTHOR",
                    "pattern": [{"TEXT": {"FUZZY": "Kerouac"}}],
                    "type": "token",
                    },
                    ]
            True
        """
        all_patterns = []
        for label, patterns in self._patterns.items():
            for pattern in patterns:
                p = {"label": label, "pattern": pattern, "type": self.type}
                all_patterns.append(p)
        return all_patterns

    @property
    def vocab(self: "TokenMatcher") -> Vocab:
        """Returns the spaCy `Vocab` object utilized."""
        return self._searcher.vocab

    def add(
        self: "TokenMatcher",
        label: str,
        patterns: ty.List[ty.List[ty.Dict[str, ty.Any]]],
        on_match: "TokenCallback" = None,
    ) -> None:
        """Add a rule to the matcher, consisting of a label and one or more patterns.

        Patterns must be a list of dictionary lists where each dictionary
        list represent an individual pattern and each dictionary represents
        an individual token.

        Uses extended spaCy token matching patterns.
        "FUZZY" and "FREGEX" are the two additional spaCy token pattern options.

        For example:
            {"TEXT": {"FREGEX": "(database){e<=1}"}},
            {"LOWER": {"FUZZY": "access", "MIN_R": 85, "FUZZY_FUNC": "quick_lev"}}

        Args:
            label: Name of the rule added to the matcher.
            patterns: List of dictionary lists that will be matched
                against the `Doc` object the matcher is called on.
            on_match: Optional callback function to modify the
                `Doc` object the matcher is called on after matching.
                Default is `None`.

        Raises:
            TypeError: If patterns is not an iterable of `Doc` objects.
            ValueError: pattern cannot have zero tokens.

        Example:
            >>> import spacy
            >>> from spaczz.matcher import TokenMatcher
            >>> nlp = spacy.blank("en")
            >>> matcher = TokenMatcher(nlp.vocab)
            >>> matcher.add("AUTHOR", [[{"TEXT": {"FUZZY": "Kerouac"}}]])
            >>> "AUTHOR" in matcher
            True
        """
        for pattern in patterns:
            if len(pattern) == 0:
                raise ValueError("pattern cannot have zero tokens.")
            if isinstance(pattern, list):
                self._patterns[label].append(list(pattern))
            else:
                raise TypeError("Patterns must be lists of dictionaries.")
        self._callbacks[label] = on_match

    def remove(self: "TokenMatcher", label: str) -> None:
        """Remove a label and its respective patterns from the matcher.

        Args:
            label: Name of the rule added to the matcher.

        Raises:
            ValueError: If label does not exist in the matcher.

        Example:
            >>> import spacy
            >>> from spaczz.matcher import TokenMatcher
            >>> nlp = spacy.blank("en")
            >>> matcher = TokenMatcher(nlp.vocab)
            >>> matcher.add("AUTHOR", [[{"TEXT": {"FUZZY": "Kerouac"}}]])
            >>> matcher.remove("AUTHOR")
            >>> "AUTHOR" in matcher
            False
        """
        try:
            del self._patterns[label]
            del self._callbacks[label]
        except KeyError:
            raise ValueError(
                f"The label: {label} does not exist within the matcher rules."
            )

    @staticmethod
    def _spacyfy(
        match: ty.List[ty.Tuple[str, str, int]],
        pattern: ty.List[ty.Dict[str, ty.Any]],
    ) -> ty.List[ty.Dict[str, ty.Any]]:
        """Turns token searcher matches into spaCy `Matcher` compatible patterns."""
        new_pattern = deepcopy(pattern)
        for i, token in enumerate(match):
            if token[0]:
                del new_pattern[i][token[0]]
                new_pattern[i]["TEXT"] = token[1]
        return new_pattern


TokenCallback = ty.Optional[
    ty.Callable[
        [TokenMatcher, Doc, int, ty.List[ty.Tuple[str, int, int, int, str]]], None
    ]
]


def unpickle_matcher(
    matcher: ty.Type[TokenMatcher],
    vocab: Vocab,
    patterns: ty.DefaultDict[str, ty.List[ty.List[ty.Dict[str, ty.Any]]]],
    callbacks: ty.Dict[str, TokenCallback],
    defaults: ty.Any,
) -> TokenMatcher:
    """Will return a matcher from pickle protocol."""
    matcher_instance = matcher(vocab, **defaults)
    for key, specs in patterns.items():
        callback = callbacks.get(key)
        matcher_instance.add(key, specs, on_match=callback)
    return matcher_instance
