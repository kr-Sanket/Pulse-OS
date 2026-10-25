"""Reconcile an answer's ``[N]`` markers with the evidence it was generated from.

A generator returns two claims about provenance: the markers written into the answer text and
a separate list of cited indices. Neither is trusted on its own. The answer a caller receives
obeys one rule: **every marker in the text names an evidence item that was supplied, and every
returned citation appears as a marker in the text.**

* A marker naming an index that was not supplied (``[7]`` with three evidence items) is
  removed from the text — it points at nothing the reader can check.
* A listed index whose marker never appears in the text is dropped — the answer does not
  actually rely on it.
* Citations are rebuilt from the supplied evidence, never from generator-provided record ids.

What this cannot do: decide whether the sentence beside a valid marker is supported by that
evidence. That is a semantic judgement no string check makes; the clinician disclaimer stays.
"""

import re

from app.modules.ai.context import AssembledContext
from app.modules.ai.generation import CitationReference, GeneratedAnswer

# ``[3]`` and the grouped form ``[1, 3]``; nothing else is a citation (the prompt asks for [N]).
_MARKER = re.compile(r"\[(\d{1,4}(?:\s*,\s*\d{1,4})*)\]")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([.,;:!?])")
_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")


def reconcile_citations(generated: GeneratedAnswer, context: AssembledContext) -> GeneratedAnswer:
    """The answer with unsupported markers removed and citations limited to those in the text."""
    by_index = {item.citation_index: item for item in context.items}
    cited: list[int] = []

    def keep_supported(match: re.Match[str]) -> str:
        indices = [int(part) for part in match.group(1).split(",")]
        supported = [index for index in indices if index in by_index]
        for index in supported:
            if index not in cited:
                cited.append(index)
        if not supported:
            return ""
        if supported == indices:
            return match.group(0)
        return "[" + ", ".join(str(index) for index in supported) + "]"

    text = _MARKER.sub(keep_supported, generated.answer)
    if text != generated.answer:
        text = _DOUBLE_SPACE.sub(" ", _SPACE_BEFORE_PUNCT.sub(r"\1", text)).strip()

    citations = tuple(
        CitationReference(
            citation_index=index,
            record_id=by_index[index].record_id,
            category_code=by_index[index].category_code,
            chunk_index=by_index[index].chunk_index,
        )
        for index in sorted(cited)
    )
    return GeneratedAnswer(
        answer=text,
        citations=citations,
        provider=generated.provider,
        model=generated.model,
        generated_at=generated.generated_at,
    )
