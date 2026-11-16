"""Diagrams: an Agent's Geometry, or a Tag's Form, drawn as Mermaid or
Graphviz.

``Diagram`` returns chart text and ``Save`` writes it to files: Mermaid
``.mmd`` by default, which GitHub, VS Code and mermaid.live draw, or
Graphviz ``.dot`` with ``format="graphviz"``; both need nothing outside the
standard library. With ``format="graphviz"``, ``Save(..., image="svg")`` or
``image="png"`` also draws each file with Graphviz's ``dot`` command.
Mermaid files carry front matter that widens wrapping to 360.

By default both formats draw the code's structure, not one object's state:
one box per Tag, rounded for a Tag, a hexagon for a Pin and a flag for a
Flag, with the host as a capsule holding its name, a thin divider and its
own field names. On an Agent a box's title starts with its Overlay place
as a circled number (``①`` to ``⑳``, then ``21 ·``); a Pin or Flag adds
`` · Pin`` or `` · Flag``. A Tag's Form has no number. A thin divider,
then one line per declaration: the kind word coloured blue for checks,
green for state and purple for behaviour, then the name. ``↳ underlay Kin``
or ``↳ replaces Kin`` / ``↳ deletes X`` names a Layer in another chart.
Layers in one chart get bold dashed arrows from the earlier Tag to
the later one, labelled with the relation and shared names and coloured
purple, amber or red; both formats join boxes, and Mermaid crosses out
replaces and deletes. Arrows also run from the host to a Tag and from a
Base to its Shape; Pins are linked with dotted arrows. When a chart holds
Tags of several modules, each module is a box.

``live=True`` adds one object's state: host field values; a Record's
contribution (``= value``, ``+ item, item`` for a list, tuple, string or
dict, or ``+18 → 42`` for a number); a Post's ``✓ holds`` in green or
``✗ BROKEN`` in red, with a red border on a broken Tag; a quiet italic
``now value`` line; and Ripped Tags, dashed with a ``ripped`` arrow. The
general view runs no user checks and shows none of these.

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
from dataclasses import dataclass, field
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
            live: bool = False,
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
                if live and state is not None else []
                )
        # A Post name is checked once, on its latest Layer. A Constant Post
        # outlives its Tag's Rip, so that Layer's Tag may be a Ripped one.
        self.broken: dict[type, set[str]] = {}
        self.status: dict[tuple[type, str], bool] = {}
        # The general view draws no verdicts and runs no user checks.
        verdicts = Contract.Status(subject) if live and state is not None else {}

        for name, holds in verdicts.items():
            layers = state.post_layers.get(name, ())

            if layers:
                self.status[layers[-1].tag, name] = holds

                if not holds:
                    self.broken.setdefault(layers[-1].tag, set()).add(name)

        source = _HOST if self.has_host else subject
        carry = None if self.has_host else "pins"
        in_form = set(active)
        # Base-first, even after a Base was Ripped and Tagged again: then it
        # comes after its Shape in `active`. A family then starts at its top
        # Base, whose module it goes to.
        forming = dict.fromkeys(t for tag in active for t in _form_of(tag) if t in in_form)

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

        # The general view keeps only structure: the Overlay order above,
        # the rows below and the arrows between them. Values, verdicts and
        # Ripped Tags belong to one object, and come only with ``live``.
        self.values: dict[tuple[type, str], str] = {}
        self.now: dict[tuple[type, str], str] = {}
        self.layers: dict[type, int] = {}
        self.fields: list[str] = []

        if self.has_host:
            namespace = _namespace(subject)
            self.layers = {tag: number for number, tag in enumerate(active, 1)}
            taken = {m.name for rows in self.members.values() for m in rows}

            if state is not None:
                taken |= {*state.records, *state.actions, *state.deleted}

            def field(name: str, value: object) -> str:
                return f"{name} = {_shown(value)}" if live else name

            self.fields = [
                    field(name, value)
                    for name, value in namespace.items()
                    if isinstance(name, str) and not name.startswith("_") and name not in taken
                    ]

            if live:
                # What each Record layer put in, read from the snapshot
                # TopKit keeps after each Tag: a Record that extends shows
                # what it added (``+ 'Magic Missile'``), one that sets shows
                # its value; the visible layer adds what the Agent holds now
                # when that changed since. Snapshots hold values by
                # reference, so one changed in place shows only its end.
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
        fields = [_text(field) for field in graph.fields]
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
                (f"f{i}", small.format(tint.format("#475569", _html(field))))
                for i, field in enumerate(graph.fields)
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


_LANE_ROW_H = 18
_LANE_TITLE_H = 24
_LANE_PAD = "2,1"
_LANE_GRID = "#94a3b8"
_LANE_RIPPED = "#8b8b8b"
_LANE_TEXT = "#0f172a"


def _lane_port(
        name: str,
        ) -> str:
    """A declaration's name as a Graphviz port, quoted when it is not one."""

    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else _quoted(name)


def _lane_tint(
        color: str,
        ) -> str:
    """A pale row tint made from a family's own colour, not a new scheme."""

    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * 0.88):02x}" for c in channels)


@dataclass(frozen=True, slots=True)
class _LaneColumn:
    """One column of a lanes chart: a host, a Tag or a Ripped Tag."""

    id: str
    title: str
    cells: dict[str, str]         # global row name → the cell's HTML
    tints: dict[str, str]         # global row name → its background colour
    key: str | None = None        # the Tag, when this column has one
    ripped: bool = False
    fields: tuple[str, ...] = ()  # host field texts, with values when live
    lines: tuple[tuple[str, _Line], ...] = ()   # Tag rows, with their declarations
    words: dict[str, list[str]] = field(default_factory=dict)  # row → ↳ relation words


def _lane_rows(
        graph: _Graph,
        columns: list[_LaneColumn],
        fields: list[str],
        ) -> list[str]:
    """The chart's global row list, in first-appearance order."""

    rows: list[str] = []

    for field in fields:
        name = field.split(" = ", 1)[0]
        if name not in rows:
            rows.append(name)

    for column in columns:
        for name in column.cells:
            if name not in rows:
                rows.append(name)

    return rows


def _lane_columns(
        graph: _Graph,
        part: list[type],
        notes: dict[tuple[type, int], list[str]],
        ) -> tuple[list[_LaneColumn], list[str]]:
    """The columns in Overlay order, Ripped Tags last, with their rows.
    Both formats use this one list, so their columns say the same things."""

    ordered = sorted(
            (tag for tag in part if tag not in graph.ripped),
            key=lambda tag: (graph.layers.get(tag, len(part) + 1), tag.__name__),
            )
    ripped = sorted(
            (tag for tag in part if tag in graph.ripped),
            key=lambda tag: (tag.__name__, tag.__module__),
            )
    columns: list[_LaneColumn] = []
    fields = list(graph.fields)
    layering_words: dict[tuple[type, str], list[str]] = {}
    for (prior, tag, relation), names in _layerings(graph, part).items():
        for row in names:
            layering_words.setdefault((tag, row), []).append(
                    f"↳ {relation} {prior.__name__}"
                    )

    if graph.has_host:
        cells = {}
        for field in fields:
            name = field.split(" = ", 1)[0]
            color = _LANE_TEXT
            cells[name] = (
                    f'<FONT COLOR="{color}" POINT-SIZE="10"><B>{_html(field)}</B></FONT>'
                    )

        columns.append(_LaneColumn("host", _html(graph.host), cells, {}, fields=tuple(fields)))

    for tag in [*ordered, *ripped]:
        is_ripped = tag in graph.ripped
        title = _html(_title(graph, tag))

        if not is_ripped:
            bases = [
                    source.__name__
                    for source, base, label in graph.arrows
                    if source is not tag and base is tag and label is None and source in graph.tags
                    ]
            if bases:
                title += f' · on {", ".join(bases)}'
        else:
            title += " · ripped"

        cells: dict[str, str] = {}
        member_lines: list[tuple[str, _Line]] = []
        tints: dict[str, str] = {}

        for index, (member, line) in enumerate(zip(graph.members[tag], _lines(graph, tag, notes))):
            kind = _html(line.kind)
            color = _LANE_RIPPED if is_ripped else _COLORS[_FAMILY[line.kind]]
            text_color = _LANE_RIPPED if is_ripped else _LANE_TEXT
            html = f'<FONT COLOR="{color}" POINT-SIZE="9"><B>{kind}</B></FONT>'
            html += f' <FONT COLOR="{text_color}" POINT-SIZE="10">{_html(line.text)}</FONT>'

            if line.holds is False:
                html += f' <FONT COLOR="#ef4444"><B>✗ BROKEN</B></FONT>'
            elif line.holds and not is_ripped:
                html += f' <FONT COLOR="#10b981"><B>✓ holds</B></FONT>'
            if line.extras:
                html += (
                        f' <FONT COLOR="{_LANE_GRID}" POINT-SIZE="8"><I>'
                        + _html("; ".join(line.extras)) + "</I></FONT>"
                        )
            if (tag, member.name) in layering_words:
                html += (
                        f' <FONT COLOR="{_LANE_GRID}" POINT-SIZE="8"><I>'
                        + _html("; ".join(layering_words[tag, member.name]))
                        + "</I></FONT>"
                        )

            cells[member.name] = html
            member_lines.append((member.name, line))
            tints[member.name] = "#f1f5f9" if is_ripped else _lane_tint(color)

        columns.append(_LaneColumn(
                f"t{graph.tags.index(tag)}", title, cells, tints,
                key=tag, ripped=is_ripped, lines=tuple(member_lines),
                words={row: words for (owner, row), words in layering_words.items()
                       if owner is tag},
                ))

    return columns, _lane_rows(graph, columns, fields)


def _lane_table(
        column: _LaneColumn,
        rows: list[str],
        width: int,
        ) -> str:
    """One HTML-table node per column: a title, a rule, then one fixed-height
    cell for every global row, blank where the Tag does not declare it."""

    border = _LANE_RIPPED if column.ripped else _LANE_GRID
    title_bg = "#f8fafc" if column.ripped else "#e2e8f0"
    title_color = _LANE_RIPPED if column.ripped else _LANE_TEXT
    body = [
            f'<TR><TD PORT="title" HEIGHT="{_LANE_TITLE_H}" WIDTH="{width}" '
            f'ALIGN="CENTER" BGCOLOR="{title_bg}">'
            f'<B><FONT COLOR="{title_color}" POINT-SIZE="11">{column.title}</FONT></B></TD></TR>',
            f'<TR><TD HEIGHT="3" WIDTH="{width}" BGCOLOR="{border}" BORDER="0"></TD></TR>',
            ]

    for name in rows:
        height = f'HEIGHT="{_LANE_ROW_H}" WIDTH="{width}" ALIGN="LEFT"'

        if name in column.cells:
            body.append(
                    f'<TR><TD PORT="{_html(name)}" {height} '
                    f'BGCOLOR="{column.tints.get(name, "#ffffff")}">{column.cells[name]}</TD></TR>'
                    )
        else:
            body.append(f"<TR><TD {height}>&nbsp;</TD></TR>")

    dashed = ' STYLE="dashed"' if column.ripped else ""
    return (
            f'<<TABLE BORDER="1" COLOR="{border}" CELLBORDER="0" CELLSPACING="0" '
            f'CELLPADDING="{_LANE_PAD}"{dashed}>\n'
            + "\n".join(body)
            + "\n</TABLE>>"
            )


def _lane_width(
        column: _LaneColumn,
        ) -> int:
    """A column is as wide as its longest visible line, not the chart's."""

    texts = [column.title, *column.cells.values()]
    longest = max((len(re.sub(r"<[^>]*>", "", text)) for text in texts), default=0)
    return min(260, max(86, int(longest * 5.4) + 16))


def _graphviz_lanes(
        graph: _Graph,
        part: list[type],
        name: str | None,
        direction: str,
        ) -> str:
    """Graphviz lanes: one table node per column, in a single rank, with
    straight port-to-port layering arrows."""

    notes = _notes(graph, part, every=False)
    columns, rows = _lane_columns(graph, part, notes)
    widths = {column.id: _lane_width(column) for column in columns}
    ids = [column.id for column in columns]
    lines = [
            f"digraph {_quoted(name or graph.host)} {{",
            f'  graph [rankdir=TB, splines=line, nodesep=0.18, ranksep=0.5, '
            f'pad="0.3", bgcolor="#ffffff", {_FONT}];',
            f'  node [shape=plain, {_FONT}];',
            f'  edge [{_FONT}, fontsize=9, arrowsize=0.9];',
            "",
            "  // one row of columns, host first",
            "  { rank=same; " + "; ".join(ids) + "; }",
            "  " + " -> ".join(ids) + " [style=invis, weight=100];",
            "",
            ]

    for column in columns:
        lines.append(f"  {column.id} [label={_lane_table(column, rows, widths[column.id])}];")

    lines.append("")
    lines.append("  // layering: earlier member to later member, same row")

    for (prior, tag, relation), names in _layerings(graph, part).items():
        port = _lane_port(names[0])
        color = _LINK_COLORS[relation]
        head = "normal" if relation == "underlay" else "tee"
        lines.append(
                f"  t{graph.tags.index(prior)}:{port}:e -> t{graph.tags.index(tag)}:{port}:w "
                f"[constraint=false, style=dashed, penwidth=2.2, arrowsize=1, "
                f'color="{color}", arrowhead={head}];'
                )

    lines.append("}")
    return "\n".join(lines) + "\n"


# Mermaid lanes are the wiki's swimlanes: a column per Tag, with the nodes
# of a declaration in the column. The lists and arrows are the same as the
# boxes chart's; only the frame changes.
_SWIM_SHAPES = {
        "check": ("{{", "}}"),
        "data": ("[", "]"),
        "act": ("(", ")"),
        }
_SWIM_MAX_ITEMS = 4


def _swim_node(
        column: _LaneColumn,
        name: str,
        ) -> str:
    """A node's id in one swimlane column."""

    return f"{column.id}_{re.sub(r'[^A-Za-z0-9_]', '_', name).strip('_') or 'row'}"


def _swim_items(
        text: str,
        ) -> tuple[str, list[str]]:
    """Split a Record's contribution into the node's text and the list items
    that hang off it: ``+ 'a', 'b'`` becomes ``()`` and ``['a', 'b']``."""

    match = re.search(r" \+ (.+)$", text)
    if not match:
        return text, []

    pieces = [piece.strip().strip("'\"") for piece in match.group(1).split(", ")]
    items = pieces[:_SWIM_MAX_ITEMS]

    if len(pieces) > _SWIM_MAX_ITEMS:
        items.append("…")

    return text[:match.start()], items


def _mermaid_lanes(
        graph: _Graph,
        part: list[type],
        name: str | None,
        direction: str,
        ) -> str:
    """Mermaid lanes: `swimlane-beta TD`, one subgraph per column, with only
    real declaration nodes and unlabelled layering links; the relation words
    sit in the later node's text."""

    columns, rows = _lane_columns(graph, part, _notes(graph, part, every=False))
    lines = [
            "---",
            "config:",
            "  flowchart:",
            "    wrappingWidth: 360",
            "    nodeSpacing: 18",
            "    rankSpacing: 22",
            "    padding: 6",
            "---",
            "swimlane-beta TD",
            ]
    classes: list[str] = []
    count = 0                       # Mermaid numbers every edge, even plain ones
    painted: dict[str, list[int]] = {}

    for column in columns:
        lines.append(f'  subgraph {column.id}["{column.title}"]')
        nodes: list[str] = []
        hanging: list[tuple[str, list[str]]] = []
        broken: list[str] = []
        fields = {field.split(" = ", 1)[0]: field for field in column.fields}
        declared = dict(column.lines)

        for row in rows:                 # source order is the global row order
            if row in fields:
                node = _swim_node(column, row)
                lines.append(f'    {node}["{_text(fields[row].replace(" = ", ": ", 1))}"]')
                nodes.append(node)
                continue

            line = declared.get(row)

            if line is None:
                continue

            family = _FAMILY[line.kind]
            color = _rgb(_COLORS[family])
            text = line.text

            if line.kind == "Record" and not column.ripped:
                text, items = _swim_items(text)
            else:
                items = []

            word = _text(line.kind) if column.ripped else _paint(color, _text(line.kind))
            label = f"{word} {_text(text)}"

            if line.holds is False:
                label += " " + _paint(_rgb("#ef4444"), "✗ BROKEN")
            elif line.holds and not column.ripped:
                label += " " + _paint(_rgb("#10b981"), "✓ holds")
            if line.extras:
                label += "".join(f"<br/><i>{_text(extra)}</i>" for extra in line.extras)
            for word in column.words.get(row, ()):
                label += (
                        "<br/><span style='color:#94a3b8'><i>"
                        + _text(word) + "</i></span>"
                        )
            node = _swim_node(column, row)

            opening, closing = _SWIM_SHAPES[family]
            lines.append(f"    {node}{opening}\"{label}\"{closing}")
            nodes.append(node)

            if line.holds is False:
                broken.append(node)
            if items:
                hanging.append((node, items))

        # Items hang below the column's rows, so they do not stagger them.
        for parent, items in hanging:
            for index, item in enumerate(items):
                extra = f"{parent}_i{index}"
                lines.append(f'    {extra}["{_text(item)}"]')
                lines.append(f"    {parent} ---|+| {extra}")
                count += 1

        look = "ripped" if column.ripped else (
                _look(graph, column.key) if column.key is not None else None
                )
        if look == "broken":          # only the Post that fails owns the verdict
            look = None
        classes.extend(f"  class {node} {look}" for node in nodes if look)
        classes.extend(f"  class {node} broken" for node in broken)
        lines.append("  end")

    for (prior, tag, relation), names in _layerings(graph, part).items():
        source = _swim_node(next(c for c in columns if c.key is prior), names[0])
        target = _swim_node(next(c for c in columns if c.key is tag), names[0])
        head = "-.->" if relation == "underlay" else "-.-x"
        lines.append(f"  {source} {head} {target}")
        painted.setdefault(relation, []).append(count)
        count += 1

    used = {line.rsplit(" ", 1)[1] for line in classes}
    lines.extend(
            f"  classDef {look} {style}"
            for look, style in _MERMAID_STYLES.items()
            if look in used and look != "module"
            )
    lines.extend(classes)
    lines.extend(
            f"  linkStyle {','.join(map(str, numbers))} stroke:{_LINK_COLORS[relation]},"
            "stroke-width:2.5px,stroke-dasharray:8 5"
            for relation, numbers in painted.items()
            )

    return "\n".join(lines) + "\n"


_FORMATS = {
        "mermaid": (_mermaid, ".mmd"),
        "graphviz": (_graphviz, ".dot"),
        }
_LANES = {
        "mermaid": (_mermaid_lanes, ".mmd"),
        "graphviz": (_graphviz_lanes, ".dot"),
        }
_LAYOUTS = ("boxes", "lanes")
_IMAGES = ("svg", "png")


def _check_layout(
        layout: str,
        direction: str,
        ) -> None:
    """Lanes are columns; only boxes may head another way."""

    if layout not in _LAYOUTS:
        raise ValueError(f"layout is one of {', '.join(_LAYOUTS)}")

    if layout == "lanes" and direction != "TD":
        raise ValueError("lanes are always columns; direction only applies to layout='boxes'")


def Diagram(
        subject: object,
        *,
        live: bool = False,
        limit: int = LIMIT,
        direction: str = "TD",
        format: str = "mermaid",
        layout: str = "boxes",
        ) -> dict[str, str]:
    """Charts of an Agent's Geometry or a Tag's Form, by name: Mermaid
    flowcharts, or Graphviz DOT with ``format="graphviz"``.

    By default a chart is the code's structure: the host's field names,
    one box per Tag with its declarations, layer numbers, box shapes,
    module boxes and the arrows between them. No values, Post verdicts or
    Ripped Tags appear, and no user checks run. ``live=True`` adds one
    object's state: host field values, what each Record layer contributed,
    ``now`` values, Post verdicts with a red border on a broken Tag, and
    Ripped Tags with their ``ripped`` arrows. Contributions and ``now``
    compare the values each layer left: a mutable value changed in place
    rather than replaced shows only its final value.

    One chart, named for the subject; or, with more than ``limit`` Tags,
    one for each module that declares them, named for the module. Inside a
    chart, the Tags of each module sit in a box named for it."""

    if limit < 1:
        raise ValueError("a diagram part holds at least one Tag")

    if format not in _FORMATS:
        raise ValueError(f"format is one of {', '.join(_FORMATS)}")

    _check_layout(layout, direction)
    draw = (_LANES if layout == "lanes" else _FORMATS)[format][0]
    graph = _Graph(subject, live)
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
        live: bool = False,
        limit: int = LIMIT,
        direction: str = "TD",
        format: str = "mermaid",
        image: str | None = None,
        layout: str = "boxes",
        ) -> tuple[Path, ...]:
    """Write ``Diagram(subject)`` as text files: Mermaid ``.mmd``, or
    Graphviz ``.dot`` with ``format="graphviz"``. ``live=True`` draws one
    object's state instead of the general structure; see ``Diagram``.

    One part is written to ``path`` with that suffix; several parts beside
    it, each named ``<stem>-<part name>``, with characters other than
    letters, digits, ``_`` and ``-`` made ``_``. With ``format="graphviz"``,
    ``image="svg"`` or ``image="png"`` also draws each part beside its
    ``.dot`` with Graphviz's ``dot`` command. A ``.mmd`` needs no picture:
    GitHub, VS Code and mermaid.live draw it. Returns the written paths."""

    if format not in _FORMATS:
        raise ValueError(f"format is one of {', '.join(_FORMATS)}")

    _check_layout(layout, direction)

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
            live=live,
            limit=limit,
            direction=direction,
            format=format,
            layout=layout,
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
