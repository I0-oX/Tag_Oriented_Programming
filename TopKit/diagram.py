"""Diagrams: an Agent's Geometry, or a Tag's Form, drawn as Mermaid or
Graphviz.

``Diagram`` returns chart text and ``Save`` writes it to files: Mermaid
``.mmd`` by default, which GitHub, VS Code and mermaid.live draw, or
Graphviz ``.dot`` with ``format="graphviz"``; both need nothing outside the
standard library. With ``format="graphviz"``, ``Save(..., image="svg")`` or
``image="png"`` also draws each file with Graphviz's ``dot`` command.
Mermaid files carry front matter that widens wrapping to 360.

Both formats draw one box per Tag: rounded for a Tag, a hexagon for a Pin
and a flag for a Flag, with the host as a capsule holding its name, a thin
divider and its own fields. On an Agent a box's title starts with its
Overlay place as a circled number (``①`` to ``⑳``, then ``21 ·``); a Pin
or Flag adds `` · Pin`` or `` · Flag``. Ripped Tags and a Tag's Form have
no number. A thin divider, then one line per declaration: the kind word
coloured blue for checks, green for state and purple for behaviour, then
the name. A Record shows what its Layer contributed: ``= value``,
``+ item, item`` for a list, tuple, string or dict, or ``+18 → 42`` for a
number. A Post shows ``✓ holds`` in green or ``✗ BROKEN`` in red. A quiet
italic ``now value`` line follows a changed value; ``↳ underlay Kin``,
``↳ replaces Kin`` or ``↳ deletes X`` names a Layer in another chart.
Layers in one chart get bold dashed arrows from the earlier Tag to the
later one, labelled with the relation and shared names and coloured
purple, amber or red; both formats join boxes, and Mermaid crosses out
replaces and deletes. Arrows also run from the host to a
Tag and from a Base to its Shape; Pins and Ripped Tags are linked with
dotted arrows. When a chart holds Tags of several modules, each module is
a box.

A diagram with more Tags than ``limit`` is divided by code: each family of
Tags joined through Bases goes to the module that declares its top Base,
and each part is named for its module. The limit is soft; a family is
never split, so one family larger than the limit stays one chart, and only
a module still above the limit is split, between families, into
``module (2)`` and so on.
"""

from __future__ import annotations

import re
import reprlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from .contracts import Contract
from .declarations import _UNDERLAY
from .declarations import _declarations_of
from .declarations import _has_flag
from .declarations import _is_flag
from .declarations import _is_pin
from .declarations import _takes_stored
from .geometry import _direct_bases
from .geometry import _form_of
from .geometry import _is_tag
from .state import _name_of
from .state import _state_of


LIMIT = 40
_HOST = None
_ESCAPES = {
        "#": "#35;",
        '"': "#quot;",
        "<": "#lt;",
        ">": "#gt;",
        "\n": " ",
        }
_HTML_ESCAPES = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "\n": " ",
        }
# Mermaid: strokes and text only, no fills. A .mmd is drawn in the viewer's
# theme, and a fill fixed for a light page leaves a dark theme's text
# unreadable, and the reverse.
_MERMAID_STYLES = {
        "host": "stroke-width:3px",
        "pin": "stroke:#d4a017,stroke-width:2px",
        "flag": "stroke:#0d9488,stroke-width:2px",
        "broken": "stroke:#ef4444,stroke-width:3px",
        "ripped": "stroke:#8b8b8b,stroke-dasharray:6 3,color:#8b8b8b",
        "module": "fill:none,stroke:#94a3b8,stroke-dasharray:4 4",
        }
# Each member kind by what it does: checks, state, behaviour.
_FAMILY = {
        "Pre": "check",
        "Post": "check",
        "Imprint": "check",
        "Record": "data",
        "Report": "data",
        "Action": "act",
        "Operation": "act",
        "Rip": "act",
        "Delete": "act",
        }
# Mid tones that read on a light page and on a dark one alike.
_COLORS = {"check": "#3b82f6", "data": "#10b981", "act": "#8b5cf6"}
# What a Tag is picks its box in Mermaid: rounded for a Tag, a hexagon for
# a Pin, a flag for a Flag.
_MERMAID_SHAPES = {
        "tag": ("(", ")"),
        "pin": ("{{", "}}"),
        "flag": (">", "]"),
        }
# The same shapes in Graphviz: rounded for a Tag, a hexagon for a Pin, a
# flag for a Flag.
_DOT_SHAPES = {
        "tag": "shape=box",
        "pin": "shape=hexagon",
        "flag": "shape=cds",
        }
# Layering arrows by how the later Tag covers the earlier one.
_LINK_COLORS = {"underlay": "#8b5cf6", "replaces": "#f59e0b", "deletes": "#ef4444"}
# Names that layer on an Agent, so a later Tag can extend or cover them.
_OVERLAID = frozenset(("Record", "Action", "Rip", "Post", "Delete"))
_REPR = reprlib.Repr(
        maxstring=30, maxother=30, maxlong=30,
        maxlist=4, maxtuple=4, maxset=4, maxfrozenset=4, maxdict=3, maxlevel=2,
        )
_MISSING = object()
# Graphviz draws its own page, so the look is fixed: soft lines, rounded boxes.
_RANKDIR = {"TD": "TB"}
_FONT = 'fontname="Helvetica,Arial,sans-serif"'
_DOT_GRAPH = f"{_FONT}, nodesep=0.35, ranksep=0.5, fontsize=11"
_DOT_NODE = f'shape=box, style=rounded, {_FONT}, fontsize=11, color="#64748b", margin="0.12,0.06"'
_DOT_EDGE = f'{_FONT}, fontsize=9, color="#64748b", fontcolor="#64748b", arrowsize=0.7'
_DOT_LOOKS = {
        "host": 'color="#334155", penwidth=1.8',
        "pin": 'color="#d4a017", penwidth=1.6',
        "flag": 'color="#0d9488", penwidth=1.6',
        "broken": 'color="#ef4444", penwidth=2',
        "ripped": 'style="rounded,dashed", color="#8b8b8b", fontcolor="#8b8b8b"',
        "module": 'style="rounded,dashed", color="#94a3b8", fontcolor="#64748b"',
        }


def _text(
        text: str,
        ) -> str:
    return "".join(_ESCAPES.get(c, c) for c in text)


@dataclass(frozen=True, slots=True)
class _Member:
    """One row of a Tag's box: a declaration the Tag makes itself."""

    kind: str
    name: str
    marks: tuple[str, ...]
    extends: bool    # it receives the earlier contribution of its name


def _members(
        tag: type,
        ) -> list[_Member]:
    """The declarations the Tag makes itself, conditions first."""

    found = _declarations_of(tag)
    rips = set(found.rips)

    def member(kind: str, name: str, function: object = None, public: bool = False) -> _Member:
        marks = [
                mark
                for mark, present in (
                    ("secret", name in found.secrets),
                    ("public", public or name in found.published),
                    ("constant", name in found.constants),
                    ("tool", name in found.tools),
                    )
                if present
                ]
        if function is None:
            extends = False
        elif kind == "Record":
            extends = _takes_stored(function)
        else:
            extends = _has_flag(function, _UNDERLAY)
        return _Member(kind, name, tuple(marks), extends)

    return [
            *(member("Pre", n, f) for n, f in found.preconditions),
            *(member("Post", n, f) for n, f in found.postconditions),
            *(member("Imprint", n, f) for n, f in found.imprints),
            *(member("Record", n, f) for n, f in found.records),
            *(member("Action", n, f) for n, f in found.actions if n not in rips),
            *(member("Rip", n, f) for n, f in found.actions if n in rips),
            *(member("Delete", n) for n in found.deletions),
            *(member("Report", n, None, p) for n, _, p in found.reports),
            *(member("Operation", n, None, p) for n, _, p in found.operations),
            ]


def _shown(
        value: object,
        ) -> str:
    """A short picture of a value; a failing ``repr`` shows the type."""

    try:
        text = _REPR.repr(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    return text if len(text) <= 40 else text[:39] + "…"


def _same(
        one: object,
        other: object,
        ) -> bool:
    """Whether two held values are the same; a failing ``==`` says no."""

    try:
        return one is other or bool(one == other)
    except Exception:
        return False


def _change(
        before: object,
        after: object,
        ) -> str:
    """What a Record layer added to the value under it: new items of a list,
    tuple, string or dict, or the step of a number; else the new value."""

    try:
        if (
                isinstance(before, (list, tuple)) and isinstance(after, (list, tuple))
                and len(after) > len(before) and list(after[:len(before)]) == list(before)
                ):
            return "+ " + ", ".join(_shown(item) for item in after[len(before):])
        if (
                isinstance(before, str) and isinstance(after, str)
                and len(after) > len(before) and after.startswith(before)
                ):
            return "+ " + _shown(after[len(before):])
        if (
                isinstance(before, dict) and isinstance(after, dict)
                and len(after) > len(before) and all(k in after and _same(v, after[k]) for k, v in before.items())
                ):
            return "+ " + ", ".join(f"{_shown(k)}: {_shown(v)}" for k, v in after.items() if k not in before)
        if type(before) in (int, float) and type(after) in (int, float) and before != after:
            return f"{after - before:+g} → {_shown(after)}"
    except Exception:
        pass

    return f"= {_shown(after)}"


def _namespace(
        subject: object,
        ) -> dict:
    """The subject's own dictionary, read without its attribute hooks."""

    try:
        namespace = object.__getattribute__(subject, "__dict__")
    except AttributeError:
        return {}
    return namespace if isinstance(namespace, dict) else {}


class _Graph:
    """What one diagram draws, before it is divided into parts."""

    def __init__(
            self,
            subject: object,
            ) -> None:
        self.host = _name_of(subject)
        self.has_host = not _is_tag(subject)
        self.tags: list[type] = []
        self.carried: set[type] = set()
        self.ripped: set[type] = set()
        # (source, Shape, label); source is _HOST for the host.
        self.arrows: list[tuple[object, type, str | None]] = []

        if _is_tag(subject):
            form = _form_of(subject)
            self.tags.extend(form)

            for tag in form:
                self.arrows.extend(
                        (base, tag, None)
                        for base in _direct_bases(tag)
                        if base in form
                        )

        state = _state_of(subject)
        active = list(state.active) if state is not None else []
        ripped = (
                sorted(
                        state.ever - set(active),
                        key=lambda t: (t.__name__, t.__module__, t.__qualname__),
                        )
                if state is not None else []
                )
        # A Post name is checked once, on its latest Layer. A Constant Post
        # outlives its Tag's Rip, so that Layer's Tag may be a Ripped one.
        self.broken: dict[type, set[str]] = {}
        self.status: dict[tuple[type, str], bool] = {}
        verdicts = Contract.Status(subject) if state is not None else {}

        for name, holds in verdicts.items():
            layers = state.post_layers.get(name, ())

            if layers:
                self.status[layers[-1].tag, name] = holds

                if not holds:
                    self.broken.setdefault(layers[-1].tag, set()).add(name)

        source = _HOST if self.has_host else subject
        carry = None if self.has_host else "pins"
        live = set(active)
        # Base-first, even after a Base was Ripped and Tagged again: then it
        # comes after its Shape in `active`. A family then starts at its top
        # Base, whose module it goes to.
        forming = dict.fromkeys(t for tag in active for t in _form_of(tag) if t in live)

        for tag in forming:
            self._add(tag)
            self.carried.add(tag)
            bases = [base for base in _direct_bases(tag) if base in self.carried]
            self.arrows.extend((base, tag, None) for base in bases)

            if not bases:
                self.arrows.append((source, tag, carry))

        for tag in ripped:
            self._add(tag)
            self.ripped.add(tag)
            self.arrows.append((source, tag, "ripped"))

        self.members = {tag: _members(tag) for tag in self.tags}
        # (later Tag, its row, earlier Tag, its row, how the later covers
        # it), for each name two active Layers give, in Overlay order: the
        # Agent's application order, or a Tag's Form.
        self.links: list[tuple[type, int, type, int, str]] = []
        latest: dict[str, tuple[type, int]] = {}

        for tag in (active if self.has_host else _form_of(subject)):
            for index, member in enumerate(self.members.get(tag, ())):
                if member.kind not in _OVERLAID:
                    continue

                prior = latest.get(member.name)

                if prior is not None and self.members[prior[0]][prior[1]].kind != "Delete":
                    relation = (
                            "deletes" if member.kind == "Delete"
                            else "underlay" if member.extends
                            else "replaces"
                            )
                    self.links.append((tag, index, *prior, relation))

                latest[member.name] = (tag, index)

        # What each Record layer put in, read from the snapshot TopKit keeps
        # after each Tag: a Record that extends shows what it added
        # (``+ 'Magic Missile'``), one that sets shows its value; the
        # visible layer adds what the Agent holds now when that changed since.
        self.values: dict[tuple[type, str], str] = {}
        self.now: dict[tuple[type, str], str] = {}
        self.layers: dict[type, int] = {}
        self.fields: list[tuple[str, str]] = []

        if self.has_host:
            namespace = _namespace(subject)
            self.layers = {tag: number for number, tag in enumerate(active, 1)}
            snapshots = state.snapshots if state is not None else {}

            def held(tag: type, name: str) -> object:
                snapshot = snapshots.get(tag)
                return _MISSING if snapshot is None else snapshot.records.get(name, _MISSING)

            before: dict[str, object] = {}

            for tag in active:
                for member in self.members.get(tag, ()):
                    if member.kind == "Delete":
                        before.pop(member.name, None)
                        continue
                    if member.kind != "Record" or "secret" in member.marks:
                        continue

                    after = held(tag, member.name)

                    if after is _MISSING:
                        continue

                    prior = before.get(member.name, _MISSING)
                    self.values[tag, member.name] = (
                            _change(prior, after) if member.extends and prior is not _MISSING
                            else f"= {_shown(after)}"
                            )
                    before[member.name] = after

            for name, (tag, index) in latest.items():
                member = self.members[tag][index]
                now = namespace.get(name, _MISSING)

                if member.kind != "Record" or "secret" in member.marks or now is _MISSING:
                    continue

                had = held(tag, name)

                if had is _MISSING:
                    self.values[tag, name] = f"= {_shown(now)}"
                elif not _same(had, now):
                    self.now[tag, name] = _shown(now)

            taken = {m.name for rows in self.members.values() for m in rows}

            if state is not None:
                taken |= {*state.records, *state.actions, *state.deleted}

            self.fields = [
                    (name, _shown(value))
                    for name, value in namespace.items()
                    if isinstance(name, str) and not name.startswith("_") and name not in taken
                    ]

    def _add(
            self,
            tag: type,
            ) -> None:
        if tag not in self.tags:
            self.tags.append(tag)

    def parts(
            self,
            limit: int,
            ) -> tuple[list[list[type]], list[str]]:
        """The parts and their names. Up to ``limit`` Tags draw as one part,
        named for the host. Above it, each family of Tags joined through
        Bases goes to the module that declares its top Base, and each
        module is one part, named for the module. The limit is soft: a
        module above it is split between families, never inside one, and
        its later parts are numbered: ``module (2)``."""

        if len(self.tags) <= limit:
            return [list(self.tags)], [self.host]

        root = {tag: tag for tag in self.tags}

        def find(tag: type) -> type:
            while root[tag] is not tag:
                root[tag] = root[root[tag]]
                tag = root[tag]
            return tag

        # Every arrow but the host's joins a family, so no arrow is cut:
        # a Tag's own drawing, Form and Pins, is one family.
        for source, shape, _ in self.arrows:
            if source is not _HOST:
                root[find(source)] = find(shape)

        families: dict[type, list[type]] = {}
        for tag in self.tags:
            families.setdefault(find(tag), []).append(tag)

        modules: dict[str, list[list[type]]] = {}
        for family in families.values():
            modules.setdefault(_module_of(family[0]), []).append(family)

        parts: list[list[type]] = []
        names: list[str] = []

        for module, members in modules.items():
            count = 0
            part: list[type] = []

            for family in [*members, None]:
                if part and (family is None or len(part) + len(family) > limit):
                    count += 1
                    parts.append(part)
                    names.append(module if count == 1 else f"{module} ({count})")
                    part = []

                if family is not None:
                    part.extend(family)

        if len(parts) == 1:                    # one family: nothing to divide
            names = [self.host]

        return parts, names


def _module_of(
        tag: type,
        ) -> str:
    """The module that declares a Tag; a script by its file name."""

    module = tag.__module__

    if module == "__main__":
        script = getattr(sys.modules.get(module), "__file__", None)

        if script:
            return Path(script).stem

    return module


def _kind(
        tag: type,
        ) -> str:
    """What a Tag is, which picks its box's shape: a Pin, a Flag or a Tag."""

    if _is_pin(tag):
        return "pin"
    if _is_flag(tag):
        return "flag"
    return "tag"


def _look(
        graph: _Graph,
        tag: type,
        ) -> str | None:
    """The one mark a Tag box's lines carry: a broken promise outranks a
    Rip, and either outranks the color of a Pin or a Flag."""

    if tag in graph.broken:
        return "broken"
    if tag in graph.ripped:
        return "ripped"
    kind = _kind(tag)
    return kind if kind != "tag" else None


def _by_module(
        part: list[type],
        ) -> dict[str, list[type]]:
    """The part's Tags under the module that declares each one."""

    modules: dict[str, list[type]] = {}

    for tag in part:
        modules.setdefault(_module_of(tag), []).append(tag)

    return modules


def _title(
        graph: _Graph,
        tag: type,
        ) -> str:
    """A Tag box's title: on an Agent its place in the Overlay, counted
    from the first Tag applied; its name; and what it is when not a plain
    Tag."""

    layer = graph.layers.get(tag)
    kind = _kind(tag)
    title = tag.__name__ if kind == "tag" else f"{tag.__name__} · {kind.title()}"

    if layer is None:
        return title
    # ① to ⑳ read as a place in the stack; past twenty, a plain number.
    mark = chr(0x2460 + layer - 1) if layer <= 20 else f"{layer} ·"
    return f"{mark} {title}"


def _row(
        graph: _Graph,
        tag: type,
        member: _Member,
        now: bool = True,
        ) -> str:
    """A row's text: kind, name, what the layer put in it, what the Agent
    holds now when that changed since (unless ``now`` is false) and marks."""

    text = f"{member.kind} {member.name}"
    value = graph.values.get((tag, member.name))
    held = graph.now.get((tag, member.name)) if now else None

    if value is not None:
        text += f" {value}"
    if held is not None:
        text += f" → now {held}"
    if member.marks:
        text += f" ({', '.join(member.marks)})"
    return text


def _holds(
        graph: _Graph,
        tag: type,
        member: _Member,
        ) -> bool | None:
    """Whether a Post row holds now; None when nothing checks it here."""

    return graph.status.get((tag, member.name)) if member.kind == "Post" else None


def _notes(
        graph: _Graph,
        part: list[type],
        every: bool,
        ) -> dict[tuple[type, int], list[str]]:
    """How a row covers an earlier Layer, as words on the row: for every
    link, or only for those whose earlier Layer is in another chart."""

    drawn = set(part)
    notes: dict[tuple[type, int], list[str]] = {}

    for tag, index, prior, _, relation in graph.links:
        if tag in drawn and (every or prior not in drawn):
            notes.setdefault((tag, index), []).append(f"↳ {relation} {prior.__name__}")

    return notes


def _layerings(
        graph: _Graph,
        part: list[type],
        ) -> dict[tuple[type, type, str], list[str]]:
    """The layerings drawn as arrows in a chart, one per pair of Tags and
    relation, with the names they share: ``(Elf, Wizard, "underlay")`` →
    ``["spells"]``. Those reaching into another chart stay as words."""

    drawn = set(part)
    arrows: dict[tuple[type, type, str], list[str]] = {}

    for tag, index, prior, _, relation in graph.links:
        if tag in drawn and prior in drawn:
            arrows.setdefault((prior, tag, relation), []).append(graph.members[tag][index].name)

    return arrows


def _paint(
        color: str,
        html: str,
        ) -> str:
    """Colored text in a Mermaid label. An ``rgb()`` color, because ``#``
    followed by ``;`` reads as an entity there."""

    return f"<span style='color:{color}'>{html}</span>"


def _rgb(
        color: str,
        ) -> str:
    return "rgb({},{},{})".format(*(int(color[i:i + 2], 16) for i in (1, 3, 5)))


@dataclass(frozen=True, slots=True)
class _Line:
    """One declaration as both formats draw it."""

    kind: str
    text: str                 # name, what the layer put in, marks
    holds: bool | None        # a Post's verdict here, else None
    extras: tuple[str, ...]   # quiet lines under it: now …, ↳ underlay …


def _lines(
        graph: _Graph,
        tag: type,
        notes: dict[tuple[type, int], list[str]],
        ) -> list[_Line]:
    """The box's lines, one per declaration. What the Agent holds now and
    how the row layers each go on a quiet line of their own, so no line
    grows long enough to wrap mid-phrase."""

    lines = []

    for index, member in enumerate(graph.members[tag]):
        now = graph.now.get((tag, member.name))
        lines.append(_Line(
                member.kind,
                _row(graph, tag, member, now=False)[len(member.kind) + 1:],
                _holds(graph, tag, member),
                tuple(([f"now {now}"] if now is not None else []) + notes.get((tag, index), [])),
                ))

    return lines


def _summary(
        graph: _Graph,
        tag: type,
        notes: dict[tuple[type, int], list[str]],
        ) -> list[str]:
    """The box's lines after its title, as Mermaid label HTML: a quiet
    divider, then each declaration with its kind colored by what it does.
    A Ripped Tag's lines stay plain: its class greys them."""

    plain = tag in graph.ripped
    rows = []

    for line in _lines(graph, tag, notes):
        kind = _text(line.kind)
        html = (kind if plain else _paint(_rgb(_COLORS[_FAMILY[line.kind]]), kind))
        html += " " + _text(line.text)

        if line.holds is False:
            html += " " + _paint(_rgb("#ef4444"), "✗ BROKEN")
        elif line.holds and not plain:
            html += " " + _paint(_rgb("#10b981"), "✓ holds")

        html += "".join(f"<br><i>{_text(extra)}</i>" for extra in line.extras)
        rows.append(html)

    return ["─" * 14, *rows] if rows else []


def _mermaid(
        graph: _Graph,
        part: list[type],
        name: str | None,
        direction: str,
        ) -> str:
    ids: dict[object, str] = {tag: f"t{i}" for i, tag in enumerate(graph.tags)}
    ids[_HOST] = "host"
    # Wider wrapping than Mermaid's default, so a declaration's line does
    # not break mid-phrase. GitHub honours this front matter.
    lines = ["---", "config:", "  flowchart:", "    wrappingWidth: 360", "---", f"flowchart {direction}"]
    classes = []

    if graph.has_host:
        # The part's name in the box, not a title: not every renderer
        # draws Mermaid titles.
        head = [_text(graph.host), *([_text(name)] if name else [])]
        fields = [_text(f"{field} = {value}") for field, value in graph.fields]
        lines.append(f'  host(["{"<br>".join([*head, *(["─" * 14, *fields] if fields else [])])}"])')
        classes.append("  class host host")

    notes = _notes(graph, part, every=False)
    modules = _by_module(part)
    boxed = len(modules) > 1

    for number, (module, tags) in enumerate(modules.items()):
        indent = "    " if boxed else "  "

        if boxed:
            lines.append(f'  subgraph m{number}["{_text(module)}"]')

        for tag in tags:
            label = "<br>".join([_text(_title(graph, tag)), *_summary(graph, tag, notes)])
            opening, closing = _MERMAID_SHAPES[_kind(tag)]
            lines.append(f'{indent}{ids[tag]}{opening}"{label}"{closing}')
            look = _look(graph, tag)

            if look:
                classes.append(f"  class {ids[tag]} {look}")

        if boxed:
            lines.append("  end")
            classes.append(f"  class m{number} module")

    drawn = set(part)
    count = 0                                  # Mermaid numbers its links
    painted: dict[str, list[int]] = {}

    for source, shape, label in graph.arrows:
        if shape in drawn:
            arrow = f"-.->|{label}|" if label else "-->"
            lines.append(f"  {ids[source]} {arrow} {ids[shape]}")
            count += 1

    # Layering runs from the earlier Tag to the later one, as the stack grows.
    for (prior, tag, relation), names in _layerings(graph, part).items():
        head = "-.->" if relation == "underlay" else "-.-x"
        label = _text(f"{relation} {', '.join(names)}")
        lines.append(f"  {ids[prior]} {head}|{label}| {ids[tag]}")
        painted.setdefault(relation, []).append(count)
        count += 1

    used = {line.rsplit(" ", 1)[1] for line in classes}
    lines.extend(
            f"  classDef {look} {style}"
            for look, style in _MERMAID_STYLES.items()
            if look in used
            )
    lines.extend(classes)
    lines.extend(
            f"  linkStyle {','.join(map(str, numbers))} stroke:{_LINK_COLORS[relation]},"
            "stroke-width:2.5px,stroke-dasharray:8 5"
            for relation, numbers in painted.items()
            )

    return "\n".join(lines) + "\n"


def _html(
        text: str,
        ) -> str:
    return "".join(_HTML_ESCAPES.get(c, c) for c in text)


def _quoted(
        text: str,
        ) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _table(
        title: str,
        rows: list[tuple[str, str]],
        ) -> str:
    """An HTML label: a title, a rule, then one centered row per port, as
    the Mermaid box sets them."""

    head = f"<TR><TD>{title}</TD></TR>"
    body = "".join(f'<TR><TD PORT="{port}">{html}</TD></TR>' for port, html in rows)
    return (
            '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2">'
            f"{head}{'<HR/>' if rows else ''}{body}</TABLE>>"
            )


def _graphviz(
        graph: _Graph,
        part: list[type],
        name: str | None,
        direction: str,
        ) -> str:
    ids: dict[object, str] = {tag: f"t{i}" for i, tag in enumerate(graph.tags)}
    ids[_HOST] = "host"
    small = '<FONT POINT-SIZE="9">{}</FONT>'
    tint = '<FONT COLOR="{}">{}</FONT>'
    lines = [
            f"digraph {_quoted(name or graph.host)} {{",
            f"  graph [rankdir={_RANKDIR.get(direction, direction)}, {_DOT_GRAPH}];",
            f"  node [{_DOT_NODE}];",
            f"  edge [{_DOT_EDGE}];",
            ]

    if graph.has_host:
        title = _html(graph.host) + (f"<BR/>{small.format(_html(name))}" if name else "")
        rows = [
                (f"f{i}", small.format(tint.format("#475569", _html(f"{field} = {value}"))))
                for i, (field, value) in enumerate(graph.fields)
                ]
        lines.append(f"  host [label={_table(title, rows)}, {_DOT_LOOKS['host']}];")

    notes = _notes(graph, part, every=False)
    modules = _by_module(part)
    boxed = len(modules) > 1

    for number, (module, tags) in enumerate(modules.items()):
        indent = "    " if boxed else "  "

        if boxed:
            lines.append(f"  subgraph cluster_{number} {{")
            lines.append(f"    graph [label={_quoted(module)}, {_DOT_LOOKS['module']}];")

        for tag in tags:
            plain = tag in graph.ripped
            title = _html(_title(graph, tag))
            rows = []

            # The same lines as the Mermaid box, said the same way.
            for index, line in enumerate(_lines(graph, tag, notes)):
                kind = _html(line.kind)
                html = kind if plain else tint.format(_COLORS[_FAMILY[line.kind]], kind)
                html += " " + _html(line.text)

                if line.holds is False:
                    html += " " + tint.format("#ef4444", "✗ BROKEN")
                elif line.holds and not plain:
                    html += " " + tint.format("#10b981", "✓ holds")

                html += "".join(f"<BR/><I>{_html(extra)}</I>" for extra in line.extras)
                rows.append((f"m{index}", small.format(html)))

            look = _look(graph, tag)
            extra = f", {_DOT_LOOKS[look]}" if look else ""
            lines.append(f"{indent}{ids[tag]} [label={_table(title, rows)}, {_DOT_SHAPES[_kind(tag)]}{extra}];")

        if boxed:
            lines.append("  }")

    drawn = set(part)

    for source, shape, label in graph.arrows:
        if shape in drawn:
            extra = f" [style=dashed, label={_quoted(f' {label} ')}]" if label else ""
            lines.append(f"  {ids[source]} -> {ids[shape]}{extra};")

    # Layering runs from the earlier Tag to the later one, as the stack
    # grows: the same arrows as the Mermaid chart, bold and dashed so they
    # stand apart from the thin Base arrows.
    for (prior, tag, relation), names in _layerings(graph, part).items():
        color = _LINK_COLORS[relation]
        head = "normal" if relation == "underlay" else "tee"
        label = f" {relation} {', '.join(names)} "
        lines.append(
                f"  {ids[prior]} -> {ids[tag]} [style=dashed, penwidth=2.2,"
                f' arrowsize=1, color="{color}", fontcolor="{color}", fontsize=10,'
                f" arrowhead={head}, label={_quoted(label)}];"
                )

    lines.append("}")

    return "\n".join(lines) + "\n"


_FORMATS = {
        "mermaid": (_mermaid, ".mmd"),
        "graphviz": (_graphviz, ".dot"),
        }
_IMAGES = ("svg", "png")


def Diagram(
        subject: object,
        *,
        limit: int = LIMIT,
        direction: str = "TD",
        format: str = "mermaid",
        ) -> dict[str, str]:
    """Charts of an Agent's Geometry or a Tag's Form, by name: Mermaid
    flowcharts, or Graphviz DOT with ``format="graphviz"``.

    One chart, named for the subject; or, with more than ``limit`` Tags,
    one for each module that declares them, named for the module. Inside a
    chart, the Tags of each module sit in a box named for it."""

    if limit < 1:
        raise ValueError("a diagram part holds at least one Tag")

    if format not in _FORMATS:
        raise ValueError(f"format is one of {', '.join(_FORMATS)}")

    draw = _FORMATS[format][0]
    graph = _Graph(subject)
    parts, names = graph.parts(limit)
    divided = len(parts) > 1

    return {
            names[index]: draw(graph, parts[index], names[index] if divided else None, direction)
            for index in range(len(parts))
            }


def _painter(
        image: str,
        ):
    """A function that draws one DOT chart to ``image`` bytes with ``dot``."""

    dot = shutil.which("dot")

    if dot is None:
        raise FileNotFoundError(
                f"image={image!r} draws with Graphviz's dot command; install"
                " Graphviz (https://graphviz.org/download/). Without image=,"
                " Save writes the .dot files alone."
                )

    def paint(text: str) -> bytes:
        done = subprocess.run(
                [dot, f"-T{image}"],
                input=text.encode("utf-8"),
                capture_output=True,
                check=False,
                )

        if done.returncode != 0:
            raise RuntimeError(f"dot could not draw the chart: {done.stderr.decode().strip()}")

        return done.stdout

    return paint


def Save(
        subject: object,
        path: str | PathLike[str],
        *,
        limit: int = LIMIT,
        direction: str = "TD",
        format: str = "mermaid",
        image: str | None = None,
        ) -> tuple[Path, ...]:
    """Write ``Diagram(subject)`` as text files: Mermaid ``.mmd``, or
    Graphviz ``.dot`` with ``format="graphviz"``.

    One part is written to ``path`` with that suffix; several parts beside
    it, each named ``<stem>-<part name>``, with characters other than
    letters, digits, ``_`` and ``-`` made ``_``. With ``format="graphviz"``,
    ``image="svg"`` or ``image="png"`` also draws each part beside its
    ``.dot`` with Graphviz's ``dot`` command. A ``.mmd`` needs no picture:
    GitHub, VS Code and mermaid.live draw it. Returns the written paths."""

    if format not in _FORMATS:
        raise ValueError(f"format is one of {', '.join(_FORMATS)}")

    if image is not None and image not in _IMAGES:
        raise ValueError(f"image is one of {', '.join(_IMAGES)}, or None")

    if image is not None and format != "graphviz":
        raise ValueError(
                "image= draws Graphviz charts: pass format='graphviz'. A .mmd"
                " is drawn by its viewer, such as GitHub, VS Code or mermaid.live."
                )

    paint = _painter(image) if image is not None else None
    diagrams = Diagram(
            subject,
            limit=limit,
            direction=direction,
            format=format,
            )
    suffix = _FORMATS[format][1]
    path = Path(path)
    stems: list[str] = []
    written: list[Path] = []

    for name, text in diagrams.items():
        stem = path.stem

        if len(diagrams) > 1:
            # Distinct names can share a slug ("game.feats" and "game_feats").
            slug = re.sub(r"[^\w-]+", "_", name).strip("_") or "part"
            stem = f"{path.stem}-{slug}"
            count = 1

            while stem in stems:
                count += 1
                stem = f"{path.stem}-{slug}-{count}"

        stems.append(stem)
        source = path.with_name(f"{stem}{suffix}")
        source.write_text(text, encoding="utf-8")
        written.append(source)

        if paint is not None:
            out = path.with_name(f"{stem}.{image}")
            out.write_bytes(paint(text))
            written.append(out)

    return tuple(written)
