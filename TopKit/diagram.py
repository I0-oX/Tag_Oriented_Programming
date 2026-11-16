"""Diagrams: an Agent's Geometry, or a Tag's Form, drawn as Mermaid or
Graphviz.

``Diagram`` returns chart text and ``Save`` writes it to files: Mermaid
``.mmd`` by default, which GitHub, VS Code and mermaid.live draw, or
Graphviz ``.dot`` with ``format="graphviz"``; both need nothing outside the
standard library. With ``format="graphviz"``, ``Save(..., image="svg")`` or
``image="png"`` also draws each file with Graphviz's ``dot`` command.

Each Tag is a box holding one row for each Contribution or condition it
declares itself, kind first: ``Record spells = ['Light']``, ``Action
Attack``, ``Post Has_Book``. On an Agent, a Record shows the value it holds
now, on the Layer that supplied it, and a Post shows whether it holds; the
host's box lists its own fields. An arrow runs from a Base to its Shape;
where two Layers give the same name, a dotted arrow runs from the later to
the earlier one: ``underlay`` when the later extends it, ``replaces`` or
``deletes`` when it covers it. Ripped Tags stay as dashed boxes, a Tag's
Pins hang from it, and when a chart holds Tags of several modules, each
module is a box.

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
        "host": "stroke:#64748b,stroke-width:2px",
        "field": "stroke:#94a3b8",
        "pin": "stroke:#d4a017,stroke-width:2px",
        "flag": "stroke:#0d9488,stroke-width:2px",
        "broken": "stroke:#e5484d,stroke-width:2px,color:#e5484d",
        "ripped": "stroke:#8b8b8b,stroke-dasharray:6 3,color:#8b8b8b",
        "module": "fill:none,stroke:#94a3b8,stroke-dasharray:4 4",
        "check": "stroke:#2563eb",
        "data": "stroke:#059669",
        "act": "stroke:#7c3aed",
        "none": "fill:none,stroke:none",
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
_COLORS = {"check": "#2563eb", "data": "#059669", "act": "#7c3aed"}
# A row's box in Mermaid: checks are hexagons, state is square, behaviour
# is rounded.
_MERMAID_SHAPES = {
        "check": ("{{", "}}"),
        "data": ("[", "]"),
        "act": ("(", ")"),
        }
_LINK_COLORS = {"underlay": "#7c3aed", "replaces": "#d97706", "deletes": "#e5484d"}
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
        "broken": 'color="#e5484d", penwidth=2',
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

        # The value each visible Record holds, and the host's own fields.
        self.values: dict[tuple[type, str], str] = {}
        self.fields: list[tuple[str, str]] = []

        if self.has_host:
            namespace = _namespace(subject)

            for name, (tag, index) in latest.items():
                member = self.members[tag][index]
                value = namespace.get(name, _MISSING)

                if member.kind == "Record" and "secret" not in member.marks and value is not _MISSING:
                    self.values[tag, name] = _shown(value)

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
        tag: type,
        ) -> str:
    """A Tag box's title: its name, and what it is when not a plain Tag."""

    kind = _kind(tag)
    return tag.__name__ if kind == "tag" else f"{tag.__name__} · {kind.title()}"


def _row(
        graph: _Graph,
        tag: type,
        member: _Member,
        ) -> str:
    """A row's text: kind, name, the value it holds and its marks."""

    text = f"{member.kind} {member.name}"
    value = graph.values.get((tag, member.name))

    if value is not None:
        text += f" = {value}"
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
            notes.setdefault((tag, index), []).append(f"{relation} {prior.__name__}")

    return notes


def _mermaid(
        graph: _Graph,
        part: list[type],
        name: str | None,
        direction: str,
        ) -> str:
    ids: dict[object, str] = {tag: f"t{i}" for i, tag in enumerate(graph.tags)}
    ids[_HOST] = "host"
    # Compact rows and smooth arrows. Layering stays words on the rows: an
    # arrow between rows would pull Mermaid's layout apart.
    lines = [
            "---",
            "config:",
            "  flowchart:",
            "    curve: basis",
            "    rankSpacing: 28",
            "    nodeSpacing: 18",
            "    padding: 10",
            "---",
            f"flowchart {direction}",
            ]
    classes = []

    def lane(lane: str, title: str, rows: list[tuple[str, str, str]], indent: str) -> None:
        """A box of rows, stacked by invisible links."""

        rows = rows or [(f"{lane}_0", f'{lane}_0[" "]', "none")]
        lines.append(f'{indent}subgraph {lane}["{_text(title)}"]')
        lines.append(f"{indent}  direction TB")

        for node, definition, look in rows:
            lines.append(f"{indent}  {definition}")
            classes.append(f"  class {node} {look}")

        if len(rows) > 1:
            lines.append(f"{indent}  " + " ~~~ ".join(node for node, _, _ in rows))

        lines.append(f"{indent}end")

    if graph.has_host:
        # The part's name in the title: not every renderer draws Mermaid titles.
        lane(
                "host",
                graph.host + (f" · {name}" if name else ""),
                [
                    (f"host_{i}", f'host_{i}["{_text(f"{field} = {value}")}"]', "field")
                    for i, (field, value) in enumerate(graph.fields)
                    ],
                "  ",
                )
        classes.append("  class host host")

    notes = _notes(graph, part, every=True)
    modules = _by_module(part)
    boxed = len(modules) > 1

    for number, (module, tags) in enumerate(modules.items()):
        indent = "    " if boxed else "  "

        if boxed:
            lines.append(f'  subgraph m{number}["{_text(module)}"]')

        for tag in tags:
            rows = []

            for index, member in enumerate(graph.members[tag]):
                node = f"{ids[tag]}_{index}"
                text = _row(graph, tag, member)
                holds = _holds(graph, tag, member)

                if holds is not None:
                    text += " · holds" if holds else " · BROKEN"

                label = "<br>".join([
                        _text(text),
                        *(f"<i>{_text(note)}</i>" for note in notes.get((tag, index), ())),
                        ])
                family = _FAMILY[member.kind]
                opening, closing = _MERMAID_SHAPES[family]
                look = "ripped" if tag in graph.ripped else "broken" if holds is False else family
                rows.append((node, f'{node}{opening}"{label}"{closing}', look))

            lane(ids[tag], _title(tag), rows, indent)
            look = _look(graph, tag)

            if look:
                classes.append(f"  class {ids[tag]} {look}")

        if boxed:
            lines.append("  end")
            classes.append(f"  class m{number} module")

    drawn = set(part)

    for source, shape, label in graph.arrows:
        if shape in drawn:
            arrow = f"-.->|{label}|" if label else "-->"
            lines.append(f"  {ids[source]} {arrow} {ids[shape]}")

    used = {line.rsplit(" ", 1)[1] for line in classes}
    lines.extend(
            f"  classDef {look} {style}"
            for look, style in _MERMAID_STYLES.items()
            if look in used
            )
    lines.extend(classes)

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
    """An HTML label: a title, a rule, then one left-aligned row per port."""

    head = f'<TR><TD ALIGN="CENTER">{title}</TD></TR>'
    body = "".join(f'<TR><TD ALIGN="LEFT" PORT="{port}">{html}</TD></TR>' for port, html in rows)
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
            gone = tag in graph.ripped
            kind = _kind(tag)
            title = _html(tag.__name__)

            if kind != "tag":
                title += small.format(tint.format("#64748b", f" · {kind.title()}"))

            rows = []

            for index, member in enumerate(graph.members[tag]):
                holds = _holds(graph, tag, member)
                rest = _html(_row(graph, tag, member)[len(member.kind):])
                word = _html(member.kind)

                if holds is False:
                    html = tint.format("#e5484d", f"{word}{rest} BROKEN")
                elif gone:
                    html = f"{word}{rest}"
                else:
                    html = tint.format(_COLORS[_FAMILY[member.kind]], word) + rest
                    if holds:
                        html += tint.format("#059669", " holds")

                for note in notes.get((tag, index), ()):
                    html += "<BR/>" + tint.format("#64748b", f"<I>{_html(note)}</I>")

                rows.append((f"m{index}", small.format(html)))

            look = _look(graph, tag)
            extra = f", {_DOT_LOOKS[look]}" if look else ""
            lines.append(f"{indent}{ids[tag]} [label={_table(title, rows)}{extra}];")

        if boxed:
            lines.append("  }")

    drawn = set(part)

    for source, shape, label in graph.arrows:
        if shape in drawn:
            extra = f" [style=dashed, label={_quoted(f' {label} ')}]" if label else ""
            lines.append(f"  {ids[source]} -> {ids[shape]}{extra};")

    for tag, index, prior, row, relation in graph.links:
        if tag in drawn and prior in drawn:
            color = _LINK_COLORS[relation]
            head = "normal" if relation == "underlay" else "tee"
            lines.append(
                    f"  {ids[tag]}:m{index} -> {ids[prior]}:m{row} [style=dotted,"
                    f' constraint=false, color="{color}", fontcolor="{color}",'
                    f" arrowhead={head}, label={_quoted(f' {relation} ')}];"
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
