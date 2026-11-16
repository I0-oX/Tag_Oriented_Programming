"""TopKit tooling: Mermaid and Graphviz diagrams of an Agent's Geometry."""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
import warnings
from unittest import mock

from TopKit import Constant
from TopKit import Flag
from TopKit import Pin
from TopKit import Post
from TopKit import Record
from TopKit import Tag
from TopKit.diagram import Diagram
from TopKit.diagram import Save

from ._fixtures import Agent
from ._fixtures import Bridge
from ._fixtures import Bruiser
from ._fixtures import Elf


LINKS = "game.links"               # a module name that does not depend on how tests run


_NUMBER = re.compile(r"^(?:[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|\d+ ·) ")


def _plain(title: str) -> str:
    """A Tag title without its place in the Overlay."""

    return _NUMBER.sub("", title, count=1)


def _boxes(text: str) -> dict[str, str]:
    """Mermaid box id → the plain text it shows, with lines by newline."""

    labels = re.findall(r'^\s+(host|t\d+)[^"]*"(.*?)"[^"]*$', text, re.MULTILINE)
    return {box: re.sub(r"<[^>]*>", "", label.replace("<br>", "\n")) for box, label in labels}


def _title(label: str) -> str:
    """The first line of a box's label: the Tag or host name, without
    any Overlay layer number."""

    return _plain(label.split("\n")[0])


def _kinds(label: str) -> list[str]:
    """The lines after a box's title and divider: one per declaration or field."""

    return [line for line in label.split("\n")[1:] if line != "─" * 14]


def _modules(text: str) -> dict[str, list[str]]:
    """Mermaid module box → the titles of the Tags inside it."""

    boxes = _boxes(text)

    return {
            module: [_title(boxes[box]) for box in re.findall(r"^    (t\d+)", body, re.MULTILINE)]
            for module, body in re.findall(r'^  subgraph m\d+\["([^"]*)"\]\n(.*?)^  end$', text, re.MULTILINE | re.DOTALL)
            }


def _named(text: str) -> set[tuple[str, str, str]]:
    boxes = _boxes(text)
    return {(_title(boxes[a]), label, _title(boxes[b])) for a, label, b in _arrows(text)}


def _arrows(text: str) -> list[tuple[str, str, str]]:
    """(source, label, shape) for each Mermaid lane arrow; solid is ""."""

    return re.findall(r"^  (\w+) (?:-->|-\.->\|(\w+)\|) (\w+)$", text, re.MULTILINE)


def _titles(dot: str) -> dict[str, str]:
    """DOT node id → the title of its box, markup removed."""

    return {
            node: _plain(re.sub(r"<[^>]*>", "", title))
            for node, title in re.findall(r'^\s+(\w+) \[label=<<TABLE.*?<TD>(.*?)</TD>', dot, re.MULTILINE)
            }


def _dot_arrows(dot: str) -> list[tuple[str, str, str]]:
    return [
            (a, label, b)
            for a, b, label in re.findall(
                    r'^  (\w+) -> (\w+)(?: \[style=dashed, label=" (\w+) "\])?;$', dot, re.MULTILINE,
                    )
            ]




class Hero:
    def __init__(self) -> None:
        self.name = "Ari"


class Kin(Tag):
    @Record
    def spells(agent) -> list[str]:
        return ["Light"]

    def Greet(agent) -> str:
        return "hi"


class Mage(Tag):
    @Post
    def Has_Spells(agent) -> bool:
        return len(agent.spells) > 0

    @Record
    def spells(agent, stored) -> list[str]:
        return stored + ["Bolt"]

    def Greet(agent) -> str:
        return "yo"


def _mage() -> Hero:
    ari = Hero()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        Kin(ari)
        Mage(ari)
    return ari


class DiagramTests(unittest.TestCase):
    def test_arrows_run_from_each_base_to_its_shape(self) -> None:
        ari = Agent()
        Bridge(ari)
        Elf(ari)

        expected = {
                ("Agent", "", "Root"),
                ("Root", "", "Left"),
                ("Root", "", "Right"),
                ("Left", "", "Bridge"),
                ("Right", "", "Bridge"),
                ("Agent", "", "Person"),
                ("Person", "", "Elf"),
                }

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        titles = _titles(dot)

        self.assertEqual(_named(text), expected)
        self.assertEqual({(titles[a], label, titles[b]) for a, label, b in _dot_arrows(dot)}, expected)

    def test_each_row_says_what_the_tag_declares_and_what_it_holds(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari).values()
        labels = {_title(label): label for label in _boxes(text).values()}

        self.assertEqual(_kinds(labels["Hero"]), ["name = 'Ari'"])     # host fields only
        self.assertEqual(_kinds(labels["Kin"]), ["Record spells = ['Light']", "Action Greet"])
        self.assertEqual(
                _kinds(labels["Mage"]),
                [
                    "Post Has_Spells ✓ holds",
                    "Record spells + 'Bolt'",
                    "Action Greet",
                    ],
                )

    def test_layer_numbers_follow_application_order(self) -> None:
        ari = Agent()
        Elf(ari)                                           # applies Person first, then Elf

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        titles = [label.split("\n")[0] for label in _boxes(text).values()]

        self.assertIn("① Person", titles)
        self.assertIn("② Elf", titles)
        self.assertLess(titles.index("① Person"), titles.index("② Elf"))
        self.assertIn(">① Person</TD>", dot)
        self.assertIn(">② Elf</TD>", dot)

    def test_an_extending_record_shows_what_it_added(self) -> None:
        class Spells_Base(Tag):
            @Record
            def spells(agent) -> list[str]:
                return ["Light"]

        class Spells_Shape(Spells_Base):
            @Record
            def spells(agent, stored) -> list[str]:
                return stored + ["Bolt", "Shield"]

        class Count_Base(Tag):
            @Record
            def count(agent) -> int:
                return 18

        class Count_Shape(Count_Base):
            @Record
            def count(agent, stored) -> int:
                return stored + 24

        ari = Agent()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Spells_Shape(ari)
            Count_Shape(ari)

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()

        labels = {_title(label): label for label in _boxes(text).values()}
        rows = {name: _kinds(label) for name, label in labels.items()}
        self.assertIn("Record spells + 'Bolt', 'Shield'", rows["Spells_Shape"])
        self.assertIn("Record count +24 → 42", rows["Count_Shape"])
        self.assertIn("Record</FONT> spells + 'Bolt', 'Shield'", dot)
        self.assertIn("Record</FONT> count +24 → 42", dot)

    def test_a_record_changed_after_tagging_shows_now(self) -> None:
        class Counter(Tag):
            @Record
            def count(agent) -> int:
                return 18

        ari = Agent()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Counter(ari)
        ari.count = 42

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()

        self.assertIn("<i>now 42</i>", text)
        self.assertIn("count = 18<BR/><I>now 42</I>", dot)

    def test_a_setting_record_shows_its_value(self) -> None:
        class Lights(Tag):
            @Record
            def spells(agent) -> list[str]:
                return ["Light"]

        ari = Agent()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Lights(ari)

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()

        labels = {_title(label): label for label in _boxes(text).values()}
        self.assertIn("Record spells = ['Light']", _kinds(labels["Lights"]))
        self.assertIn("Record</FONT> spells = ['Light']", dot)

    def test_a_layering_arrow_names_the_earlier_tag_first(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        boxes = {_title(label): box for box, label in _boxes(text).items()}
        ids = {title: node for node, title in _titles(dot).items()}
        mermaid_names = {box: title for title, box in boxes.items()}
        graphviz_names = {node: title for title, node in ids.items()}

        underlay = f"  {boxes['Kin']} -.->|underlay spells| {boxes['Mage']}"
        replaces = f"  {boxes['Kin']} -.-x|replaces Greet| {boxes['Mage']}"
        self.assertIn(underlay, text)
        self.assertIn(replaces, text)
        links = [
                line for line in text.splitlines()
                if re.match(r"^  (?:host|t\d+) (?:-->|-\.->|-\.-x)", line)
                ]
        for label, line, color in (
                (underlay, links.index(underlay), "#8b5cf6"),
                (replaces, links.index(replaces), "#f59e0b"),
                ):
            self.assertIn(
                    f"  linkStyle {line} stroke:{color},"
                    f"stroke-width:2.5px,stroke-dasharray:8 5",
                    text,
                    )

        self.assertIn(
                f"  {ids['Kin']} -> {ids['Mage']} [style=dashed, penwidth=2.2,"
                ' arrowsize=1, color="#8b5cf6", fontcolor="#8b5cf6", fontsize=10,'
                ' arrowhead=normal, label=" underlay spells "];',
                dot,
                )
        self.assertIn(
                f"  {ids['Kin']} -> {ids['Mage']} [style=dashed, penwidth=2.2,"
                ' arrowsize=1, color="#f59e0b", fontcolor="#f59e0b", fontsize=10,'
                ' arrowhead=tee, label=" replaces Greet "];',
                dot,
                )

        # Both formats draw the same arrows: earlier Tag first, same label.
        drawn = {
                ("Kin", "underlay spells", "Mage"),
                ("Kin", "replaces Greet", "Mage"),
                }
        self.assertEqual(
                {
                    (mermaid_names[a], label, mermaid_names[b])
                    for a, label, b in re.findall(
                            r"^  (\w+) (?:-\.->|-\.-x)\|(.*?)\| (\w+)$", text, re.MULTILINE)
                    },
                drawn,
                )
        self.assertEqual(
                {
                    (graphviz_names[a], label, graphviz_names[b])
                    for a, b, label in re.findall(
                            r'^  (\w+) -> (\w+) \[style=dashed, penwidth=2\.2,.*?label=" (.*?) "\];$',
                            dot, re.MULTILINE)
                    },
                drawn,
                )
        self.assertNotIn("↳ underlay", text)
        self.assertNotIn("<I>↳ underlay", dot)

    def test_a_layering_is_written_as_words_when_split_into_charts(self) -> None:
        Low = type("Low", (Tag,), {"__module__": "game.low", "Speak": lambda agent: "a"})
        High = type("High", (Tag,), {"__module__": "game.high", "Speak": lambda agent: "b"})
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Low(ari)
            High(ari)

        parts = Diagram(ari, limit=1)
        dots = Diagram(ari, limit=1, format="graphviz")

        labels = {_title(label): label for label in _boxes(parts["game.high"]).values()}
        self.assertEqual(_kinds(labels["High"]), ["Action Speak", "↳ replaces Low"])
        self.assertIn("<i>↳ replaces Low</i>", parts["game.high"])
        self.assertIn("<I>↳ replaces Low</I>", dots["game.high"])
        self.assertNotIn("|replaces Low|", parts["game.high"])
        self.assertNotIn('label=" replaces Low "', dots["game.high"])

    def test_direction_heads_the_chart(self) -> None:
        ari = Agent()
        Elf(ari)

        (mermaid,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        (wide,) = Diagram(ari, direction="LR").values()
        (wide_dot,) = Diagram(ari, direction="LR", format="graphviz").values()

        head = "---\nconfig:\n  flowchart:\n    wrappingWidth: 360\n---\n"
        self.assertTrue(mermaid.startswith(head + "flowchart TD\n"))       # the default
        self.assertTrue(wide.startswith(head + "flowchart LR\n"))          # the option
        self.assertIn("rankdir=TB", dot)
        self.assertIn("rankdir=LR", wide_dot)

    def test_each_module_of_a_chart_is_a_box(self) -> None:
        Species = type("Species", (Tag,), {"__module__": "game.species"})
        Elf = type("Elf", (Species,), {"__module__": "game.feats"})
        Sage = type("Sage", (Tag,), {"__module__": "game.backgrounds"})
        ari = Agent()
        Elf(ari)
        Sage(ari)

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()

        self.assertEqual(
                _modules(text),
                {"game.species": ["Species"], "game.feats": ["Elf"], "game.backgrounds": ["Sage"]},
                )
        self.assertEqual(dot.count("subgraph cluster_"), 3)

    def test_a_chart_of_one_module_has_no_box(self) -> None:
        ari = Agent()
        Bridge(ari)

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()

        self.assertEqual(_modules(text), {})
        self.assertNotIn("subgraph", dot)

    def test_the_limit_is_soft_a_family_is_never_split(self) -> None:
        chain = []
        base = Tag
        for i in range(7):
            base = type(f"Link_{i}", (base,), {"__module__": LINKS})
            chain.append(base)
        loose = [type(f"Loose_{i}", (Tag,), {"__module__": LINKS}) for i in range(5)]
        ari = Agent()
        chain[-1](ari)
        for tag in loose:
            tag(ari)

        parts = Diagram(ari, limit=4)
        drawn = [
                [_title(label) for box, label in _boxes(part).items() if box != "host"]
                for part in parts.values()
                ]

        self.assertEqual(list(parts), [LINKS, f"{LINKS} (2)", f"{LINKS} (3)"])
        self.assertEqual(
                drawn,
                [
                    [t.__name__ for t in chain],                        # 7, over the limit
                    [t.__name__ for t in loose[:4]],
                    [loose[4].__name__],
                    ],
                )
        self.assertIn(f'host(["Agent<br>{LINKS} (2)<br>', parts[f"{LINKS} (2)"])

    def test_a_family_is_drawn_with_the_module_of_its_top_base(self) -> None:
        Species = type("Species", (Tag,), {"__module__": "game.species"})
        Elf = type("Elf", (Species,), {"__module__": "game.feats"})   # declared elsewhere
        Sage = type("Sage", (Tag,), {"__module__": "game.backgrounds"})
        Tough = type("Tough", (Tag,), {"__module__": "game.feats"})
        ari = Agent()
        for tag in (Elf, Sage, Tough):
            tag(ari)

        parts = Diagram(ari, limit=1)

        self.assertEqual(
                {
                    name: [_title(label) for box, label in _boxes(part).items() if box != "host"]
                    for name, part in parts.items()
                    },
                {
                    "game.species": ["Species", "Elf"],
                    "game.backgrounds": ["Sage"],
                    "game.feats": ["Tough"],
                    },
                )
        self.assertEqual(list(Diagram(ari, limit=4)), ["Agent"])      # under the limit

    def test_a_broken_post_is_marked_on_the_layer_that_declares_it(self) -> None:
        ari = Agent()
        ari.strength = 10
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Bruiser(ari)
        ari.strength = 30

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        labels = {_title(label): label for label in _boxes(text).values()}
        boxes = {_title(label): box for box, label in _boxes(text).items()}

        self.assertEqual(_kinds(labels["Bruiser"]), ["Post Strength_Capped ✗ BROKEN"])
        self.assertEqual(_kinds(labels["Capped"]), ["Post Strength_Capped"])
        self.assertIn(f"  class {boxes['Bruiser']} broken", text)
        self.assertIn('Strength_Capped <FONT COLOR="#ef4444">✗ BROKEN</FONT>', dot)

    def test_a_ripped_tag_stays_dashed(self) -> None:
        ari = Agent()
        Elf(ari)
        del Elf[ari]

        (text,) = Diagram(ari).values()
        boxes = {_title(label): box for box, label in _boxes(text).items()}

        self.assertIn(f"  host -.->|ripped| {boxes['Elf']}", text)
        self.assertIn(f"  class {boxes['Elf']} ripped", text)

    def test_a_base_applied_again_after_its_rip_still_heads_its_family(self) -> None:
        Base_Again = type("Base_Again", (Tag,), {"__module__": "game.bases"})
        Shape_Kept = type("Shape_Kept", (Base_Again,), {"__module__": "game.shapes"})
        Other = type("Other", (Tag,), {"__module__": "game.other"})
        ari = Agent()
        Shape_Kept(ari)
        Other(ari)
        del Base_Again[ari]                                           # the Shape stays
        Base_Again(ari)                                               # now after its Shape

        (text,) = Diagram(ari).values()

        self.assertEqual(
                _named(text),
                {
                    ("Agent", "", "Base_Again"),
                    ("Base_Again", "", "Shape_Kept"),
                    ("Agent", "", "Other"),
                    },
                )
        self.assertEqual(list(Diagram(ari, limit=1)), ["game.bases", "game.other"])

    def test_a_constant_post_broken_after_its_rip_is_still_marked(self) -> None:
        class Intelligence(Tag):
            @Constant
            @Post
            def NDA(agent) -> bool:
                return agent.keeps_secret

        lance = Agent()
        lance.keeps_secret = True
        Intelligence(lance)
        del Intelligence[lance]
        lance.keeps_secret = False                                    # the lifetime term breaks

        (text,) = Diagram(lance).values()
        labels = {_title(label): label for label in _boxes(text).values()}
        boxes = {_title(label): box for box, label in _boxes(text).items()}

        self.assertEqual(_kinds(labels["Intelligence"]), ["Post NDA (constant) ✗ BROKEN"])
        self.assertIn(f"  host -.->|ripped| {boxes['Intelligence']}", text)
        self.assertIn(f"  class {boxes['Intelligence']} broken", text)

    def test_a_tag_draws_its_form_and_its_pins(self) -> None:
        class Rare(Pin):
            @Record
            def rarity(tag) -> str:
                return "rare"

        class Hero_Tag(Elf):
            pass

        Rare(Hero_Tag)
        (text,) = Diagram(Hero_Tag).values()
        boxes = _boxes(text)
        labels = {_title(label): label for label in boxes.values()}
        by_title = {_title(label): box for box, label in boxes.items()}

        self.assertNotIn("host", boxes)
        self.assertEqual(
                _named(text),
                {("Person", "", "Elf"), ("Elf", "", "Hero_Tag"), ("Hero_Tag", "pins", "Rare · Pin")},
                )
        self.assertEqual(_kinds(labels["Rare · Pin"]), ["Record rarity"])
        self.assertIn(f"  class {by_title['Rare · Pin']} pin", text)
        self.assertEqual(_kinds(labels["Elf"]), ["Action Attack"])

    def test_what_a_tag_is_names_and_colors_its_box(self) -> None:
        @Flag
        class Inspired(Tag):
            pass

        ari = Agent()
        Inspired(ari)

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        boxes = {_title(label): box for box, label in _boxes(text).items()}

        self.assertIn(f"  class {boxes['Inspired · Flag']} flag", text)
        self.assertIn(">① Inspired · Flag</TD>", dot)
        self.assertIn('shape=cds, color="#0d9488"', dot)

    def test_a_tag_and_its_pins_are_one_family_never_divided(self) -> None:
        class Rare(Pin):
            pass

        class Rarer(Rare):
            pass

        class Solo(Tag):
            pass

        Rarer(Solo)
        (name, text), = Diagram(Solo, limit=1).items()

        self.assertEqual(name, "Solo")
        self.assertEqual([_title(label) for label in _boxes(text).values()], ["Solo", "Rare · Pin", "Rarer · Pin"])  # not the root
        self.assertEqual(_named(text), {("Rare · Pin", "", "Rarer · Pin"), ("Solo", "pins", "Rare · Pin")})

    def test_labels_cannot_break_out_of_their_box(self) -> None:
        odd = type('Odd"<b>&#', (), {})
        (text,) = Diagram(odd()).values()
        (dot,) = Diagram(odd(), format="graphviz").values()

        self.assertIn('host(["Odd#quot;#lt;b#gt;&#35;"])', text)
        self.assertIn('digraph "Odd\\"<b>&#" {', dot)
        self.assertIn('<TD>Odd&quot;&lt;b&gt;&amp;#</TD>', dot)

    def test_a_box_shape_says_what_a_tag_is(self) -> None:
        class Rare(Pin):
            pass

        @Flag
        class Inspired(Tag):
            pass

        class Plain(Tag):
            pass

        Rare(Plain)
        (form,) = Diagram(Plain).values()
        ari = Agent()
        Inspired(ari)
        (chart,) = Diagram(ari).values()

        self.assertIsNotNone(re.search(r'^\s+t\d+\("Plain"\)$', form, re.MULTILINE))
        self.assertIsNotNone(re.search(r'^\s+t\d+\{\{"Rare · Pin"\}\}$', form, re.MULTILINE))
        self.assertIsNotNone(re.search(r'^\s+t\d+>"① Inspired · Flag"\]$', chart, re.MULTILINE))
        self.assertIn("shape=hexagon", next(iter(Diagram(Plain, format="graphviz").values())))
        self.assertIn("shape=cds", next(iter(Diagram(ari, format="graphviz").values())))

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_graphviz_reads_every_chart(self) -> None:
        odd = type('Odd"<b>&#\\', (Tag,), {"__module__": 'game "odd"'})
        ari = _mage()
        ari.note = '<"&>'
        ari.events = []
        Bridge(ari)
        odd(ari)
        del Bridge[ari]

        for text in Diagram(ari, format="graphviz").values():
            done = subprocess.run(["dot", "-Tsvg"], input=text, capture_output=True, text=True, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_part_holds_at_least_one_tag(self) -> None:
        with self.assertRaises(ValueError):
            Diagram(Agent(), limit=0)

    def test_an_unknown_format_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Diagram(Agent(), format="plantuml")

    def test_save_writes_mermaid_files(self) -> None:
        ari = Agent()
        for module in ("game.feats", "game_feats"):                   # both "game_feats"
            type("Feat", (Tag,), {"__module__": module})(ari)

        with tempfile.TemporaryDirectory() as folder:
            paths = Save(ari, pathlib.Path(folder) / "ari", limit=1)
            written = {p.name: p.read_text() for p in paths}

        parts = Diagram(ari, limit=1)
        self.assertEqual(
                written,
                {
                    "ari-game_feats.mmd": parts["game.feats"],
                    "ari-game_feats-2.mmd": parts["game_feats"],
                    },
                )

    def test_save_writes_dot_files_with_graphviz(self) -> None:
        ari = Agent()
        Elf(ari)

        with tempfile.TemporaryDirectory() as folder:
            paths = Save(ari, pathlib.Path(folder) / "ari", format="graphviz")
            written = {p.name: p.read_text() for p in paths}

        self.assertEqual(written, {"ari.dot": Diagram(ari, format="graphviz")["Agent"]})

    def test_a_mermaid_chart_has_no_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "format='graphviz'"):
                Save(Agent(), pathlib.Path(folder) / "ari", image="svg")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_save_draws_a_graphviz_image_with_dot(self) -> None:
        ari = Agent()
        Elf(ari)

        with tempfile.TemporaryDirectory() as folder:
            paths = Save(ari, pathlib.Path(folder) / "ari", format="graphviz", image="svg")
            names = [p.name for p in paths]
            picture = paths[1].read_text()

        self.assertEqual(names, ["ari.dot", "ari.svg"])
        self.assertIn("<svg", picture)
        self.assertIn(">② Elf</text>", picture)

    def test_an_unknown_image_is_refused_before_anything_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                Save(Agent(), pathlib.Path(folder) / "ari", format="graphviz", image="jpg")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])

    def test_a_graphviz_image_without_dot_names_the_install(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with (
                    mock.patch("TopKit.diagram.shutil.which", return_value=None),
                    self.assertRaisesRegex(FileNotFoundError, "install Graphviz"),
                    ):
                Save(Agent(), pathlib.Path(folder) / "ari", format="graphviz", image="png")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
