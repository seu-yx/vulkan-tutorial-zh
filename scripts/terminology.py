"""Add source-grounded terminology hints to rendered Chinese, without changing MT cache keys.

The Google cache and English source are inputs only.  A compiled TermAnnotator can
be reused for every bilingual pair in the corpus.  Terms use english, chinese,
aliases, variants and optional normalize/context/excludeContext fields.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import re

from bs4 import BeautifulSoup, Comment, NavigableString


SKIP_TAGS = {"pre", "code", "kbd", "samp", "math", "script", "style", "svg"}
API_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*(?:::[A-Za-z_]\w*)+|vk[A-Z]\w+|VK_[A-Z0-9_]+"
    r"|[\w.-]+\.(?:spv|slang|vert|frag|comp|glsl|hlsl|cpp|hpp))\b", re.ASCII)
ADDRESS_RE = re.compile(r"(?:\b[a-z][a-z0-9+.-]*://|\bwww\.|\bmailto:)[^\s<>\"]+|\b[\w.+-]+@(?:[\w-]+\.)+[a-z]{2,}\b", re.I | re.ASCII)
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _identity(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


def _literal_pattern(value):
    """Whitespace is flexible; ASCII word boundaries also protect API identifiers."""
    pattern = r"\s+".join(re.escape(part) for part in value.strip().split())
    if value and re.match(r"[A-Za-z0-9_]", value[0]):
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if value and re.match(r"[A-Za-z0-9_]", value[-1]):
        pattern += r"(?![A-Za-z0-9_])"
    return pattern


def _target_identity(value):
    # Google inserts spaces around protected Chinese words. Those spaces are not
    # part of the term, but spaces outside the match must remain untouched.
    value = _identity(re.sub(r"(?<=[\u3400-\u9fff])[\s\u200b]+(?=[\u3400-\u9fff])", "", value))
    # Some cached Google prose leaves Markdown emphasis around untranslated words.
    return value.strip('_') if re.fullmatch(r"_*[A-Za-z0-9][A-Za-z0-9 _-]*", value) else value


def _target_literal_pattern(value):
    value = _target_identity(value)
    chunks = []
    for index, character in enumerate(value):
        if index and CJK_RE.fullmatch(character) and CJK_RE.fullmatch(value[index - 1]):
            chunks.append(r"[\s\u200b]*")
        chunks.append(r"\s+" if character.isspace() else re.escape(character))
    pattern = "".join(chunks)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]*", value):
        # Whole emphasized terms are useful aliases. A lone underscore can
        # belong to a longer label such as "_Buffer Viewer_" or an identifier.
        return r"(?<![A-Za-z0-9_])(?:_" + pattern + r"_|" + pattern + r")(?![A-Za-z0-9_])"
    if value and re.match(r"[A-Za-z0-9_]", value[0]):
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if value and re.match(r"[A-Za-z0-9_]", value[-1]):
        pattern += r"(?![A-Za-z0-9_])"
    return pattern


def _protected(node):
    return any(parent.name in SKIP_TAGS or "vt-term" in parent.get("class", []) for parent in node.parents)


def _simple_term(node):
    return (
        getattr(node, "name", None) == "span"
        and set(node.get("class", [])) == {"vt-term"}
        and set(node.attrs) <= {"class", "data-term", "title"}
        and all(isinstance(child, NavigableString) and not isinstance(child, Comment) for child in node.children)
    )


def _address_label(link):
    href = link.get("href", "")
    if not href.startswith(("https://", "http://", "mailto:")):
        return False
    return link.get_text() in (href, re.sub(r"^(?:https?://|mailto:)", "", href))


def _restore_address_labels(english, chinese):
    # The v5 Google cache may protect "shader" even inside a bare link's
    # visible URL. Only restore a label reconstructed exactly from the source.
    originals = {(a["href"], a.get_text()) for a in english.find_all("a", href=True) if _address_label(a)}
    if not originals:
        return
    for link in chinese.find_all("a", href=True):
        if any(not _simple_term(tag) or not tag.has_attr("data-term") for tag in link.find_all(True)):
            continue
        label = "".join(str(child) if isinstance(child, NavigableString) else child["data-term"]
                        for child in link.children)
        for candidate in (label, label.removeprefix("_").removesuffix("_")):
            if (link["href"], candidate) in originals and (link.find() or link.get_text() != candidate):
                link.string = candidate
                break


def _plain_prose(block):
    """Read inline prose across emphasis/links, excluding code and non-prose nodes."""
    if isinstance(block, str):
        block = BeautifulSoup(block, "html.parser")
    parts = []
    for node in block.find_all(string=True):
        if isinstance(node, Comment) or any(parent.name in SKIP_TAGS or parent.name == "a" and _address_label(parent) for parent in node.parents):
            parts.append("\0")
            continue
        parts.append(str(node))
    # A nested emphasis can separate two source words without changing the phrase.
    return API_RE.sub(" ", ADDRESS_RE.sub(" ", re.sub(r"\s+", " ", " ".join(parts))))


def _context_patterns(values, field="context"):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError(f"{field} must be a nonempty string or a list of nonempty strings")
    return [re.compile(_literal_pattern(value), re.I) for value in values]


class TermAnnotator:
    """Compile a display-only glossary once, then annotate individual paired blocks.

    A source phrase activates its corresponding Chinese aliases only in that pair.
    Long phrases win over overlapping short ones, and the source occurrence count
    caps how many Chinese occurrences are annotated.  normalize is opt-in, so an
    ambiguous translation can gain a tooltip without silently rewriting the text.
    context/requireAny and excludeContext/context/excludeAny accept literal English
    phrases; code is excluded when checking these guards as well.
    """

    def __init__(self, entries):
        if isinstance(entries, dict):
            if "terms" not in entries:
                raise ValueError("Terminology configuration must contain a terms list")
            entries = entries["terms"]
        if not isinstance(entries, list):
            raise ValueError("Terminology terms must be a list")
        self.terms = {}
        allowed_fields = {"english", "chinese", "aliases", "exactAliases", "variants", "normalize", "context", "includeContext", "excludeContext"}
        for index, entry in enumerate(entries):
            field = f"terms[{index}]"
            if not isinstance(entry, dict):
                raise ValueError(f"{field} must be an object")
            unknown = entry.keys() - allowed_fields
            if unknown:
                raise ValueError(f"{field} has unknown terminology fields: {', '.join(sorted(map(str, unknown)))}")
            english, chinese = entry.get("english"), entry.get("chinese")
            if not isinstance(english, str) or not english.strip() or not isinstance(chinese, str) or not chinese.strip():
                raise ValueError(f"{field} needs nonempty english and chinese strings")
            key = _identity(english)
            if key in self.terms:
                raise ValueError(f"{field} has duplicate canonical English term: {english.strip()}")
            if "normalize" in entry and type(entry["normalize"]) is not bool:
                raise ValueError(f"{field}.normalize must be a boolean")
            context = entry.get("context", {})
            if not isinstance(context, dict):
                raise ValueError(f"{field}.context must be an object")
            unknown_context = context.keys() - {"requireAny", "excludeAny"}
            if unknown_context:
                raise ValueError(f"{field}.context has unknown fields: {', '.join(sorted(map(str, unknown_context)))}")
            # Validate all supplied guards, including a shortcut overridden by a
            # corresponding context field, so a typo never remains latent.
            for name in ("includeContext", "excludeContext"):
                if name in entry:
                    _context_patterns(entry[name], f"{field}.{name}")
            for name in ("requireAny", "excludeAny"):
                if name in context:
                    _context_patterns(context[name], f"{field}.context.{name}")
            variants = entry.get("variants", [])
            aliases = entry.get("aliases", [])
            exact_aliases = entry.get("exactAliases", [])
            if not all(isinstance(values, list) for values in (variants, aliases, exact_aliases)) or not all(isinstance(value, str) and value.strip() for value in variants + aliases + exact_aliases):
                raise ValueError(f"{field}.variants, aliases and exactAliases must be lists of nonempty strings")
            self.terms[key] = {
                "english": english.strip(), "chinese": chinese.strip(),
                "variants": [english.strip(), *variants],
                "aliases": [chinese.strip(), *aliases, english.strip(), *variants],
                "exactAliases": exact_aliases,
                "normalize": entry.get("normalize") is True,
                "require": _context_patterns(context.get("requireAny", entry.get("includeContext", [])), f"{field}.context.requireAny"),
                "exclude": _context_patterns(context.get("excludeAny", entry.get("excludeContext", [])), f"{field}.context.excludeAny"),
            }
        source_aliases = {}
        # Explicit canonical entries take precedence over another term's variant.
        for key, term in self.terms.items():
            for alias in term["variants"]:
                source_aliases.setdefault(_identity(alias), key)
        source_aliases.update({key: key for key in self.terms})
        self.source_aliases = source_aliases
        source_alternatives = sorted(source_aliases, key=len, reverse=True)
        self.source_pattern = re.compile("|".join(_literal_pattern(value) for value in source_alternatives) or r"(?!)", re.I)
        target_aliases = {}
        exact_target_aliases = {}
        for key, term in self.terms.items():
            for alias in term["aliases"]:
                keys = target_aliases.setdefault(_target_identity(alias), [])
                if key not in keys:
                    keys.append(key)
            for alias in term["exactAliases"]:
                keys = exact_target_aliases.setdefault(_target_identity(alias), [])
                if key not in keys:
                    keys.append(key)
        self.target_aliases = target_aliases
        self.exact_target_aliases = exact_target_aliases
        self.target_patterns = OrderedDict()

    def _target_pattern(self, active, exact):
        # An inactive long alias must not swallow an active shorter term. Cache
        # common source-term combinations rather than recompiling for each pair.
        key = (tuple(sorted(active)), tuple(sorted(exact)))
        if key not in self.target_patterns:
            aliases = [alias for alias, terms in self.target_aliases.items() if any(term in active for term in terms)]
            aliases.extend(alias for alias, terms in self.exact_target_aliases.items() if any(term in exact for term in terms) and alias not in aliases)
            aliases.sort(key=len, reverse=True)
            self.target_patterns[key] = re.compile("|".join(_target_literal_pattern(alias) for alias in aliases) or r"(?!)", re.I)
            if len(self.target_patterns) > 256:
                self.target_patterns.popitem(last=False)
        self.target_patterns.move_to_end(key)
        return self.target_patterns[key]

    def _target_key(self, text, remaining, exact):
        alias = _target_identity(text)
        keys = set(self.target_aliases.get(alias, []))
        keys.update(key for key in self.exact_target_aliases.get(alias, []) if key in exact)
        possible = [key for key in keys if remaining[key] > 0]
        # An alias shared by two active meanings cannot be assigned reliably.
        return possible[0] if len(possible) == 1 else None

    def _term_span(self, factory, key, original):
        term = self.terms[key]
        span = factory.new_tag("span")
        span["class"] = ["vt-term"]
        span["data-term"] = term["english"]
        span["title"] = term["english"]
        span.string = term["chinese"] if term["normalize"] else original
        return span

    def _merge_split_terms(self, chinese_block, source_counts, existing_counts, remaining, added, normalized, factory, target_pattern, exact):
        """Merge a longer term split only by old, unformatted glossary spans.

        Links, emphasis, code, bookmarks and custom attributes form boundaries.
        Every removed old span must be fully covered; unmatched siblings retain
        their original DOM nodes and attributes.
        """
        removed = 0
        for parent in [chinese_block, *chinese_block.find_all(True)]:
            if parent.name in SKIP_TAGS or "vt-term" in parent.get("class", []) or _protected(parent):
                continue
            runs, run = [], []
            for child in list(parent.children):
                if isinstance(child, NavigableString) and not isinstance(child, Comment) or _simple_term(child):
                    run.append(child)
                else:
                    if run:
                        runs.append(run)
                    run = []
            if run:
                runs.append(run)
            for children in runs:
                if not any(_simple_term(child) for child in children):
                    continue
                value, components = "", []
                for child in children:
                    text = str(child) if isinstance(child, NavigableString) else child.get_text()
                    components.append((len(value), len(value) + len(text), child, text))
                    value += text
                accepted = []
                protected_ranges = [match.span() for pattern in (API_RE, ADDRESS_RE) for match in pattern.finditer(value)]
                for match in target_pattern.finditer(value):
                    if any(match.start() < end and match.end() > start for start, end in protected_ranges):
                        continue
                    old_terms = [(start, end, child) for start, end, child, _ in components if _simple_term(child) and match.start() < end and match.end() > start]
                    if not old_terms or any(match.start() > start or match.end() < end for start, end, _ in old_terms):
                        continue
                    key = self._target_key(match.group(), remaining, exact)
                    # A cached label can cover only part of its own alias, e.g.
                    # <term>帧缓冲</term>区. Reuse its source occurrence to extend it.
                    old_key = self.source_aliases.get(_identity(old_terms[0][2].get("data-term", "")))
                    if (key is None and len(old_terms) == 1 and source_counts[old_key]
                            and old_key in self.target_aliases.get(_target_identity(match.group()), ())):
                        key = old_key
                    if key is None:
                        continue
                    if len(old_terms) == 1 and old_terms[0][:2] == match.span():
                        # Replace an equally wide old hint only if the English
                        # source supplies a longer, more specific compound.
                        if old_key == key or old_key not in self.terms or not any(
                            re.search(_literal_pattern(short), phrase, re.I)
                            for short in self.terms[old_key]["variants"]
                            for phrase in self.terms[key]["variants"]
                        ):
                            continue
                    span = self._term_span(factory, key, match.group())
                    accepted.append((match.start(), match.end(), span))
                    added[key] += 1
                    normalized[key] += int(span.get_text() != match.group())
                    remaining[key] -= 1
                    for _, _, old_term in old_terms:
                        old_key = self.source_aliases.get(_identity(old_term.get("data-term") or old_term.get("title") or ""))
                        if old_key:
                            existing_counts[old_key] -= 1
                            remaining[old_key] = max(0, source_counts[old_key] - existing_counts[old_key] - added[old_key])
                        removed += 1
                if not accepted:
                    continue

                def original_slice(start, end):
                    pieces = []
                    for left, right, child, text in components:
                        if left >= end or right <= start:
                            continue
                        if isinstance(child, NavigableString):
                            pieces.append(NavigableString(text[max(0, start - left):min(len(text), end - left)]))
                        else:
                            pieces.append(child)
                    return pieces

                pieces, cursor = [], 0
                for start, end, span in accepted:
                    pieces.extend(original_slice(cursor, start))
                    pieces.append(span)
                    cursor = end
                pieces.extend(original_slice(cursor, len(value)))
                marker = NavigableString("")
                children[0].insert_before(marker)
                for piece in pieces:
                    marker.insert_before(piece)
                for child in children:
                    if child.parent is parent:
                        # Reused old spans were moved before the marker; preserve
                        # them, while removing original text and replaced spans.
                        if not any(child is piece for piece in pieces):
                            child.extract()
                marker.extract()
        return removed

    def annotate(self, english_block, chinese_block):
        exact_block = BeautifulSoup(english_block, "html.parser") if isinstance(english_block, str) else english_block
        _restore_address_labels(exact_block, chinese_block)
        source = _plain_prose(exact_block)
        exact_source = _identity(exact_block.get_text(" ", strip=True))
        source_counts = Counter()
        excluded = set()
        # Phrases may overlap even when they start at different words. In
        # "to transfer queue family ownership", the longer noun phrase is
        # "queue family ownership"; "transfer" is a verb.
        candidates = []
        start = 0
        while match := self.source_pattern.search(source, start):
            candidates.append(match)
            start = match.start() + 1
        used_ranges = []
        for match in sorted(candidates, key=lambda item: item.start() - item.end()):
            key = self.source_aliases[_identity(match.group())]
            term = self.terms[key]
            if term["require"] and not any(pattern.search(source) for pattern in term["require"]):
                continue
            if any(pattern.search(source) for pattern in term["exclude"]):
                excluded.add(key)
                continue
            if any(match.start() < stop and match.end() > begin for begin, stop in used_ranges):
                continue
            used_ranges.append(match.span())
            source_counts[key] += 1
        existing_counts = Counter()
        added, normalized = Counter(), Counter()
        existing_nodes = chinese_block.select(".vt-term")
        unwrapped = 0
        for node in existing_nodes:
            key = self.source_aliases.get(_identity(node.get("data-term") or node.get("title") or ""))
            if key:
                if key in excluded and _simple_term(node) and not _protected(node):
                    node.unwrap()
                    unwrapped += 1
                    continue
                existing_counts[key] += 1
                if _simple_term(node) and not _protected(node):
                    term = self.terms[key]
                    node["data-term"] = node["title"] = term["english"]
                    original = node.get_text()
                    if (source_counts[key] and term["normalize"] and original != term["chinese"]
                            and key in self.target_aliases.get(_target_identity(original), ())):
                        node.string = term["chinese"]
                        normalized[key] += 1
        remaining = source_counts - existing_counts
        factory = BeautifulSoup("", "html.parser")
        exact = {key for key in source_counts if any(exact_source == _identity(variant) for variant in self.terms[key]["variants"])}
        target_pattern = self._target_pattern(source_counts, exact)
        removed = self._merge_split_terms(chinese_block, source_counts, existing_counts, remaining, added, normalized, factory, target_pattern, exact)
        for node in list(chinese_block.find_all(string=True)):
            if isinstance(node, Comment) or not str(node).strip():
                continue
            if _protected(node) or any(parent.name == "a" and _address_label(parent) for parent in node.parents):
                continue
            value = str(node)
            protected_ranges = [match.span() for pattern in (API_RE, ADDRESS_RE) for match in pattern.finditer(value)]
            pieces = []
            cursor = 0
            for match in target_pattern.finditer(value):
                if any(match.start() < end and match.end() > start for start, end in protected_ranges):
                    continue
                key = self._target_key(match.group(), remaining, exact)
                if key is None:
                    continue
                if match.start() > cursor:
                    pieces.append(NavigableString(value[cursor:match.start()]))
                span = self._term_span(factory, key, match.group())
                pieces.append(span)
                added[key] += 1
                if span.get_text() != match.group():
                    normalized[key] += 1
                remaining[key] -= 1
                cursor = match.end()
            if pieces:
                if cursor < len(value):
                    pieces.append(NavigableString(value[cursor:]))
                node.replace_with(*pieces)
        by_term = {
            self.terms[key]["english"]: {
                "source": source_counts[key], "existing": existing_counts[key],
                "added": added[key], "normalized": normalized[key], "unmatched": remaining[key],
            }
            for key in source_counts
        }
        return {
            "source": sum(source_counts.values()), "existing": len(existing_nodes) - removed - unwrapped,
            "added": sum(added.values()), "normalized": sum(normalized.values()),
            "unmatched": sum(remaining.values()), "byTerm": by_term,
        }


def annotate_terms(english_block, chinese_block, terms):
    """Annotate a pair; pass a TermAnnotator to avoid repeated regex compilation."""
    annotator = terms if isinstance(terms, TermAnnotator) else TermAnnotator(terms)
    return annotator.annotate(english_block, chinese_block)
