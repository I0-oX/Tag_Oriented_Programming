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
from TopKit import Delete
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

    labels = re.findall(r'^\s+(host|t\d+)[({>][^"]*"(.*?)"[^"]*$', text, re.MULTILINE)
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

    return re.findall(r'^  (\w+) (?:-->|-\.->\|"?(.*?)"?\|) (\w+)$', text, re.MULTILINE)


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
                    r'^  (\w+) -> (\w+)(?: \[[^\]]*?label=" (.*?) "\])?;$', dot, re.MULTILINE,
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
                ("Person", "underlay Attack", "Elf"),
                }

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        titles = _titles(dot)

        self.assertEqual(_named(text), expected)
        self.assertEqual({(titles[a], label, titles[b]) for a, label, b in _dot_arrows(dot)}, expected)

    def test_each_row_says_what_the_tag_declares_and_what_it_holds(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari, live=True).values()
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

    def test_the_general_view_names_host_fields_without_values(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        labels = {_title(label): label for label in _boxes(text).values()}

        self.assertEqual(_kinds(labels["Hero"]), ["name"])
        self.assertNotIn("name = 'Ari'", text)
        self.assertNotIn("name = 'Ari'", dot)

    def test_the_general_view_shows_plain_declaration_rows(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        labels = {_title(label): label for label in _boxes(text).values()}

        self.assertEqual(_kinds(labels["Kin"]), ["Record spells", "Action Greet"])
        self.assertEqual(
                _kinds(labels["Mage"]),
                ["Post Has_Spells", "Record spells", "Action Greet"],
                )
        self.assertNotIn("= ['Light']", text)
        self.assertNotIn("+ 'Bolt'", text)
        self.assertNotIn("now", text)
        self.assertNotIn("now", dot)

    def test_the_general_view_keeps_layers_and_layering(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        titles = [label.split("\n")[0] for label in _boxes(text).values()]

        self.assertIn("① Kin", titles)
        self.assertIn("② Mage", titles)
        self.assertIn(">① Kin</TD>", dot)
        self.assertIn('|"underlay spells"|', text)
        self.assertIn('|"replaces Greet"|', text)
        self.assertIn('label=" replaces Greet "', dot)

    def test_the_general_view_checks_no_post_and_marks_nothing_broken(self) -> None:
        ari = Agent()
        ari.strength = 10
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Bruiser(ari)
        ari.strength = 30

        with mock.patch(
                "TopKit.diagram.Contract.Status",
                side_effect=AssertionError("a Post ran in the general view"),
                ) as status:
            (text,) = Diagram(ari).values()
            (dot,) = Diagram(ari, format="graphviz").values()

        status.assert_not_called()
        labels = {_title(label): label for label in _boxes(text).values()}
        boxes = {_title(label): box for box, label in _boxes(text).items()}

        self.assertEqual(_kinds(labels["Bruiser"]), ["Post Strength_Capped"])
        self.assertNotIn("✓ holds", text)
        self.assertNotIn("✗ BROKEN", text)
        self.assertNotIn("BROKEN", dot)
        self.assertNotIn(f"  class {boxes['Bruiser']} broken", text)
        self.assertNotIn('color="#ef4444"', dot)

    def test_the_general_view_draws_no_ripped_tag(self) -> None:
        ari = Agent()
        Elf(ari)
        del Elf[ari]

        with mock.patch(
                "TopKit.diagram.Contract.Status",
                side_effect=AssertionError("a Post ran in the general view"),
                ) as status:
            (text,) = Diagram(ari).values()
            (dot,) = Diagram(ari, format="graphviz").values()

        status.assert_not_called()
        self.assertNotIn("Elf", text)
        self.assertNotIn("ripped", text)
        self.assertNotIn("ripped", dot)
        self.assertNotIn(("Agent", "", "Elf"), _named(text))

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

        (text,) = Diagram(ari, live=True).values()
        (dot,) = Diagram(ari, live=True, format="graphviz").values()

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

        (text,) = Diagram(ari, live=True).values()
        (dot,) = Diagram(ari, live=True, format="graphviz").values()

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

        (text,) = Diagram(ari, live=True).values()
        (dot,) = Diagram(ari, live=True, format="graphviz").values()

        labels = {_title(label): label for label in _boxes(text).values()}
        self.assertIn("Record spells = ['Light']", _kinds(labels["Lights"]))
        self.assertIn("Record</FONT> spells = ['Light']", dot)

    def test_an_in_place_change_shows_only_the_final_value(self) -> None:
        class Spells(Tag):
            @Record
            def spells(agent) -> list[str]:
                return ["Light"]

        class Extended(Spells):
            @Record
            def spells(agent, stored) -> list[str]:
                stored.append("Bolt")
                return stored

        ari = Agent()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Extended(ari)

        (text,) = Diagram(ari, live=True).values()
        labels = {_title(label): label for label in _boxes(text).values()}

        self.assertEqual(_kinds(labels["Extended"]), ["Record spells = ['Light', 'Bolt']"])
        self.assertNotIn("+ 'Bolt'", text)

    def test_a_layering_arrow_names_the_earlier_tag_first(self) -> None:
        ari = _mage()

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        boxes = {_title(label): box for box, label in _boxes(text).items()}
        ids = {title: node for node, title in _titles(dot).items()}
        mermaid_names = {box: title for title, box in boxes.items()}
        graphviz_names = {node: title for title, node in ids.items()}

        underlay = f'  {boxes["Kin"]} -.->|"underlay spells"| {boxes["Mage"]}'
        replaces = f'  {boxes["Kin"]} -.-x|"replaces Greet"| {boxes["Mage"]}'
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
                    (mermaid_names[a], label.strip('"'), mermaid_names[b])
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
        self.assertIn("classDef module fill:none,stroke:#94a3b8,stroke-dasharray:4 4", text)
        self.assertIn("class m0 module", text)
        self.assertIn('style="rounded,dashed", color="#94a3b8"', dot)

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

        (text,) = Diagram(ari, live=True).values()
        (dot,) = Diagram(ari, live=True, format="graphviz").values()
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

        (text,) = Diagram(ari, live=True).values()
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

        (text,) = Diagram(ari, live=True).values()

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

        (text,) = Diagram(lance, live=True).values()
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
                {("Person", "", "Elf"), ("Elf", "", "Hero_Tag"), ("Hero_Tag", "pins", "Rare · Pin"),
                 ("Person", "underlay Attack", "Elf")},
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

    def test_boxes_color_the_kind_word_by_family(self) -> None:
        ari = _mage()
        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()

        self.assertIn("color:rgb(16,185,129)'>Record", text)
        self.assertIn("color:rgb(59,130,246)'>Post", text)
        self.assertIn("color:rgb(139,92,246)'>Action", text)
        self.assertIn('<FONT COLOR="#10b981"', dot)
        self.assertIn('<FONT COLOR="#3b82f6"', dot)
        self.assertIn('<FONT COLOR="#8b5cf6"', dot)

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

        self.assertIn('host(["Odd#quot;#lt;b#gt;&amp;#35;"])', text)
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

        for text in Diagram(ari, live=True, format="graphviz").values():
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

    def test_save_passes_live_to_the_chart(self) -> None:
        ari = _mage()

        with tempfile.TemporaryDirectory() as folder:
            (path,) = Save(ari, pathlib.Path(folder) / "ari", live=True)
            written = path.read_text()

        self.assertEqual(written, Diagram(ari, live=True)["Hero"])
        self.assertIn("name = 'Ari'", written)

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



def _swim_columns(text: str) -> list[tuple[str, str]]:
    """A lanes chart's column ids and titles, in source order."""

    return re.findall(r'^  subgraph (\w+)\["(.*?)"\]$', text, re.MULTILINE)


def _swim_column_nodes(text: str) -> dict[str, dict[str, str]]:
    """Visible Mermaid nodes grouped by the column that declares them."""

    nodes = r'^\s+(\w+)(?:\[\\?"|\("|\{\{")(.*?)(?:"\\?\]|"\)|"\}\})$'
    return {
            column: dict(re.findall(nodes, body, re.MULTILINE))
            for column, body in re.findall(
                    r'^  subgraph (\w+)\[".*?"\]\n(.*?)^  end$',
                    text, re.MULTILINE | re.DOTALL,
                    )
            }


def _swim_links(text: str) -> list[tuple[str, str, str]]:
    """Mermaid layering links: (source, arrow, target), never with a label."""

    return re.findall(r'^  (\w+) (-\.->|-\.-x) (\w+)$', text, re.MULTILINE)


def _lane_tables(dot: str) -> dict[str, list[str | None]]:
    """A DOT node → its HTML-table rows, with the title and rule removed."""

    tables: dict[str, list[str | None]] = {}
    node: str | None = None

    for line in dot.splitlines():
        found = re.match(r"^  (\w+) \[label=<<TABLE", line)

        if found:
            node = found.group(1)
            tables[node] = []
        elif node and line.startswith("<TR>"):
            port = re.search(r'PORT="([^"]+)"', line)
            tables[node].append(port.group(1) if port else None)
        elif node and line.startswith("</TABLE>>"):
            node = None

    return {key: rows[2:] for key, rows in tables.items()}


def _lane_cell(dot: str, node: str, port: str) -> str:
    """The table row that owns a port, including its relation words."""

    table = re.search(rf'^  {node} \[label=<<TABLE.*?</TABLE>>\];$', dot, re.MULTILINE | re.DOTALL)
    assert table is not None
    return next(line for line in table.group(0).splitlines() if f'PORT="{port}"' in line)



def _lane_ids(dot: str) -> list[str]:
    """Graphviz column ids, in the order they share a rank."""

    return re.search(r"\{ rank=same; (.*?); \}", dot).group(1).split("; ")


class LanesTests(unittest.TestCase):
    def test_both_formats_produce_lanes(self) -> None:
        ari = _mage()
        (mmd,) = Diagram(ari, layout="lanes").values()
        (dot,) = Diagram(ari, format="graphviz", layout="lanes").values()

        self.assertEqual(
                [title for _, title in _swim_columns(mmd)],
                ["Hero", "① Kin", "② Mage"],
                )
        self.assertEqual(list(_lane_tables(dot)), _lane_ids(dot))
        self.assertEqual(
                re.findall(r'PORT="title".*?POINT-SIZE="11">(.*?)</FONT>', dot),
                ["Hero", "① Kin", "② Mage"],
                )
        nodes = _swim_column_nodes(mmd)
        mage = _swim_columns(mmd)[2][0]
        self.assertIn("↳ underlay Kin", nodes[mage][f"{mage}_spells"])
        self.assertIn("↳ underlay Kin", _lane_cell(dot, _lane_ids(dot)[2], "spells"))

    def test_mermaid_lanes_start_after_the_front_matter(self) -> None:
        (mmd,) = Diagram(_mage(), layout="lanes").values()
        lines = mmd.splitlines()

        self.assertEqual(lines[0], "---")
        close = lines.index("---", 1)
        self.assertEqual(lines[close + 1], "swimlane-beta TD")
        self.assertNotIn("\nflowchart ", mmd)
        self.assertNotIn("title:", mmd)

    def test_mermaid_lanes_have_one_subgraph_per_column_host_first(self) -> None:
        (mmd,) = Diagram(_mage(), layout="lanes").values()
        columns = _swim_columns(mmd)

        self.assertEqual(columns[0][0], "host")
        self.assertEqual([title for _, title in columns],
                         ["Hero", "① Kin", "② Mage"])
        self.assertEqual(set(_swim_column_nodes(mmd)), {key for key, _ in columns})

    def test_mermaid_lanes_name_kinds_and_use_the_wiki_shapes(self) -> None:
        (mmd,) = Diagram(_mage(), layout="lanes").values()
        self.assertRegex(mmd, r'\["<span style=\'color:rgb\(16,185,129\)\'>Record</span> spells"\]')
        self.assertRegex(mmd, r'\{\{"<span style=\'color:rgb\(59,130,246\)\'>Post</span> Has_Spells"\}\}')
        self.assertRegex(mmd, r'\("<span style=\'color:rgb\(139,92,246\)\'>Action</span> Greet"\)')

    def test_layering_links_name_the_earlier_member_first(self) -> None:
        ari = _mage()
        (mmd,) = Diagram(ari, layout="lanes").values()
        (dot,) = Diagram(ari, format="graphviz", layout="lanes").values()
        by_column = _swim_column_nodes(mmd)
        columns = [key for key, _ in _swim_columns(mmd)]
        nodes = {node: label for group in by_column.values()
                 for node, label in group.items()}

        links = _swim_links(mmd)
        self.assertEqual(len(links), 2)
        for source, arrow, target in links:
            self.assertIn(source, by_column[columns[1]])
            self.assertIn(target, by_column[columns[2]])
        self.assertEqual([arrow for _, arrow, _ in links], ["-.->", "-.-x"])
        self.assertRegex(nodes[links[0][0]], r">Record</span> spells$")
        self.assertRegex(nodes[links[0][2]], r"↳ underlay Kin")
        self.assertIn("↳ replaces Kin", nodes[links[1][2]])
        self.assertNotIn("|underlay", mmd)
        self.assertNotIn("|replaces", mmd)

        styles = dict(re.findall(r'^  linkStyle (\d+) stroke:(#[0-9a-f]{6}),', mmd, re.MULTILINE))
        self.assertEqual(styles["0"], "#8b5cf6")
        self.assertEqual(styles["1"], "#f59e0b")

        ids = _lane_ids(dot)
        underlay = next(line for line in dot.splitlines()
                        if f"{ids[1]}:spells:e -> {ids[2]}:spells:w" in line)
        replaces = next(line for line in dot.splitlines()
                        if f"{ids[1]}:Greet:e -> {ids[2]}:Greet:w" in line)
        self.assertIn('color="#8b5cf6"', underlay)
        self.assertIn("arrowhead=normal", underlay)
        self.assertIn('color="#f59e0b"', replaces)
        self.assertIn("arrowhead=tee", replaces)
        self.assertNotIn("label=", underlay)
        self.assertNotIn("label=", replaces)
        self.assertIn("↳ underlay Kin", _lane_cell(dot, ids[2], "spells"))
        self.assertIn("↳ replaces Kin", _lane_cell(dot, ids[2], "Greet"))

    def test_default_format_stays_mermaid(self) -> None:
        ari = _mage()
        self.assertEqual(
                Diagram(ari, layout="lanes"),
                Diagram(ari, layout="lanes", format="mermaid"),
                )

    def test_lanes_reject_horizontal_direction(self) -> None:
        with self.assertRaisesRegex(ValueError, "direction only applies to layout='boxes'"):
            Diagram(_mage(), layout="lanes", direction="LR")

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                Save(_mage(), pathlib.Path(folder) / "ari", layout="lanes", direction="LR")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])

    def test_an_unknown_direction_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "TD, TB, BT, LR, RL"):
            Diagram(_mage(), direction="ltr")

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                Save(_mage(), pathlib.Path(folder) / "ari", direction="wide")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])

        for good in ("TD", "TB", "BT", "LR", "RL"):
            self.assertTrue(Diagram(_mage(), direction=good))

    def test_a_form_draws_lanes_in_form_order(self) -> None:
        class Rare(Pin):
            @Record
            def rarity(tag) -> str:
                return "rare"

        class Hero_Tag(Elf):
            pass
        Rare(Hero_Tag)
        (mmd,) = Diagram(Hero_Tag, layout="lanes").values()

        columns = _swim_columns(mmd)
        self.assertEqual([title for _, title in columns],
                         ["Person", "Elf · on Person", "Hero_Tag · on Elf", "Rare · Pin"])

        links = _swim_links(mmd)
        self.assertEqual(len(links), 1)
        places = {cid: place for place, (cid, _) in enumerate(columns)}
        column = lambda node: next(cid for cid, _ in columns if node.startswith(cid + "_"))
        self.assertLess(places[column(links[0][0])], places[column(links[0][2])])
                # the layering runs left to right, earlier Tag first

    def test_an_unknown_layout_names_both_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "boxes.*lanes"):
            Diagram(_mage(), layout="cards")

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                Save(_mage(), pathlib.Path(folder) / "ari", layout="cards")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])

    def test_a_mermaid_chart_with_lanes_has_no_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "format='graphviz'"):
                Save(_mage(), pathlib.Path(folder) / "ari", image="png", layout="lanes")

            self.assertEqual(list(pathlib.Path(folder).iterdir()), [])

    def test_same_named_members_share_a_graphviz_row(self) -> None:
        (dot,) = Diagram(_mage(), format="graphviz", layout="lanes").values()
        tables = _lane_tables(dot)
        ids = _lane_ids(dot)
        self.assertIn("splines=line", dot)

        self.assertEqual(list(tables), ids)
        self.assertEqual(len({len(rows) for rows in tables.values()}), 1)
        sharing = [rows for rows in tables.values() if "spells" in rows]
        self.assertEqual(len(sharing), 2)
        self.assertEqual(len({rows.index("spells") for rows in sharing}), 1)
        self.assertIn(f"{ids[1]}:spells:e -> {ids[2]}:spells:w", dot)

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_a_host_field_name_that_is_no_identifier_still_draws(self) -> None:
        ari = Hero()
        setattr(ari, "first name", "Ari")
        setattr(ari, 'q"x <&> \\', 1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Kin(ari)
        (dot,) = Diagram(ari, live=True, format="graphviz", layout="lanes").values()

        picture = subprocess.run(
                ["dot", "-Tsvg"], input=dot, text=True, capture_output=True, check=True,
                )

        self.assertIn("<svg", picture.stdout)
        self.assertIn("first name", picture.stdout)

    def test_live_lanes_add_host_values_and_list_items(self) -> None:
        ari = _mage()
        (general,) = Diagram(ari, layout="lanes").values()
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()
        (dot,) = Diagram(ari, live=True, format="graphviz", layout="lanes").values()

        self.assertNotIn("'Ari'", general)
        self.assertIn("name: 'Ari'", [label for nodes in _swim_column_nodes(mmd).values()
                                      for label in nodes.values()])
        self.assertIn("name = 'Ari'", dot)

        mage = _swim_columns(mmd)[2][0]
        edges = re.findall(r'^\s+(\w+) ---\|\+\| (\w+)$', mmd, re.MULTILINE)
        self.assertEqual(edges, [(f"{mage}_spells", f"{mage}_spells_i0")])
        nodes = {node: label for group in _swim_column_nodes(mmd).values()
                 for node, label in group.items()}
        self.assertEqual(nodes[f"{mage}_spells_i0"], "Bolt")
        self.assertIn("✓ holds", mmd)

    def test_a_layering_is_written_as_words_when_lanes_split_into_charts(self) -> None:
        Low = type("Low", (Tag,), {"__module__": "game.low", "Speak": lambda agent: "a"})
        High = type("High", (Tag,), {"__module__": "game.high", "Speak": lambda agent: "b"})
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Low(ari)
            High(ari)

        parts = Diagram(ari, limit=1, layout="lanes")
        dots = Diagram(ari, limit=1, layout="lanes", format="graphviz")

        self.assertIn("↳ replaces Low", parts["game.high"])
        self.assertNotIn("-.->", parts["game.high"])
        self.assertIn("↳ replaces Low", dots["game.high"])
        self.assertNotIn(":e -> ", dots["game.high"])

    def test_a_record_value_containing_plus_is_not_split_into_items(self) -> None:
        class Calc(Tag):
            @Record
            def expr(agent) -> str:
                return "x + y"
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Calc(ari)
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()

        self.assertIn("expr = 'x + y'", mmd)
        self.assertNotIn("---|+|", mmd)

    def test_a_list_item_containing_a_comma_stays_one_item(self) -> None:
        class Base(Tag):
            @Record
            def xs(agent) -> list:
                return ["a"]
        class More(Tag):
            @Record
            def xs(agent, stored) -> list:
                return stored + ["b, c", "d"]
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Base(ari)
            More(ari)
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()

        nodes = {node: label for group in _swim_column_nodes(mmd).values()
                 for node, label in group.items()}
        items = [label for node, label in nodes.items() if re.fullmatch(r"t\d+_xs_i\d+", node)]
        self.assertEqual(items, ["b, c", "d"])

    def test_a_marked_list_contribution_keeps_its_mark(self) -> None:
        class Base(Tag):
            @Record
            def xs(agent) -> list:
                return ["a"]
        class More(Tag):
            @Constant
            @Record
            def xs(agent, stored) -> list:
                return stored + ["b"]
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Base(ari)
            More(ari)
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()

        more = _swim_columns(mmd)[2][0]
        nodes = _swim_column_nodes(mmd)[more]
        self.assertIn("(constant)", nodes[f"{more}_xs"])
        self.assertEqual(nodes[f"{more}_xs_i0"], "b")

    def test_a_dict_contribution_hangs_readable_items(self) -> None:
        class Base(Tag):
            @Record
            def stats(agent) -> dict:
                return {"hp": 5}
        class More(Tag):
            @Record
            def stats(agent, stored) -> dict:
                return {**stored, "mp": 3}
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Base(ari)
            More(ari)
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()

        more = _swim_columns(mmd)[2][0]
        nodes = _swim_column_nodes(mmd)[more]
        self.assertEqual(nodes[f"{more}_stats_i0"], "mp: 3")

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_a_single_column_graphviz_lanes_chart_still_draws(self) -> None:
        class Solo(Tag):
            @Record
            def x(agent) -> int:
                return 1
        (tag_dot,) = Diagram(Solo, format="graphviz", layout="lanes").values()
        (host_dot,) = Diagram(Hero(), format="graphviz", layout="lanes").values()

        for dot, word in ((tag_dot, "x"), (host_dot, "name")):
            self.assertNotIn("style=invis", dot)
            picture = subprocess.run(
                    ["dot", "-Tsvg"], input=dot, text=True, capture_output=True, check=True,
                    )
            self.assertIn(word, picture.stdout)

    def test_a_tag_form_draws_lanes_without_a_host(self) -> None:
        class Rare(Pin):
            @Record
            def rarity(tag) -> str:
                return "rare"
        class Hero_Tag(Elf):
            pass
        Rare(Hero_Tag)
        (mmd,) = Diagram(Hero_Tag, layout="lanes").values()

        columns = _swim_columns(mmd)
        titles = [title for _, title in columns]
        self.assertNotIn("host", [cid for cid, _ in columns])
        self.assertIn("Hero_Tag · on Elf", titles)
        self.assertIn("Rare · Pin", titles)
        pin = next(cid for cid, title in columns if title == "Rare · Pin")
        nodes = _swim_column_nodes(mmd)[pin]
        self.assertIn("Record</span> rarity", nodes[f"{pin}_rarity"])
        self.assertIn(f"class {pin}_rarity pin", mmd)

    def test_a_deleted_member_draws_a_deletes_layering(self) -> None:
        class Base(Tag):
            @Record
            def x(agent) -> int:
                return 1
        class Gone(Tag):
            @Delete
            def x(agent) -> int:
                return 0
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Base(ari)
            Gone(ari)
        (mmd,) = Diagram(ari, layout="lanes").values()
        (dot,) = Diagram(ari, format="graphviz", layout="lanes").values()

        self.assertIn("-.-x", mmd)
        self.assertIn("↳ deletes Base", mmd)
        self.assertRegex(mmd, r"linkStyle \d+ stroke:#ef4444,")
        self.assertIn("↳ deletes Base", dot)
        self.assertIn('color="#ef4444", arrowhead=tee', dot)

    def test_long_contributions_are_truncated_with_an_ellipsis(self) -> None:
        class Base(Tag):
            @Record
            def xs(agent) -> list:
                return ["a"]
        class More(Tag):
            @Record
            def xs(agent, stored) -> list:
                return stored + ["b", "c", "d", "e", "f"]
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Base(ari)
            More(ari)
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()

        more = _swim_columns(mmd)[2][0]
        nodes = _swim_column_nodes(mmd)[more]
        self.assertEqual(
                [nodes[f"{more}_xs_i{i}"] for i in range(5)],
                ["b", "c", "d", "e", "…"],
                )

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_a_name_with_colon_or_backslash_routes_its_port(self) -> None:
        def rec(stored=False):
            if stored:
                def f(agent, prior):
                    return prior + 1
            else:
                def f(agent):
                    return 1
            return Record(f)
        for name in ("a:b", "a\\b"):
            Base = type("Base", (Tag,), {"__module__": "game.p", name: rec()})
            More = type("More", (Tag,), {"__module__": "game.p", name: rec(True)})
            ari = Hero()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                Base(ari)
                More(ari)
            (dot,) = Diagram(ari, format="graphviz", layout="lanes").values()
            done = subprocess.run(
                    ["dot", "-Tsvg"], input=dot, text=True, capture_output=True, check=True,
                    )
            self.assertNotIn("unrecognized", done.stderr)
            port = "p" + name.encode("utf-8").hex()
            self.assertIn(f't0:{port}:e -> t1:{port}:w', dot)
            self.assertIn(f'PORT="{port}"', dot)

    def test_mermaid_lanes_escape_entity_looking_text(self) -> None:
        class T(Tag):
            @Record
            def x(agent) -> int:
                return 1
        ari = Hero()
        setattr(ari, "q", "&quot;")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            T(ari)
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()
        self.assertIn("q: '&amp;quot;'", mmd)

        Weird = type("Weird", (Tag,), {"__module__": "game.w"})
        Weird.__name__ = "A#35;B"
        other = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Weird(other)
        (titles,) = Diagram(other, layout="lanes").values()
        self.assertIn('subgraph t0["① A#35;35;B"]', titles)

    def test_an_empty_tag_still_gets_a_lane_column(self) -> None:
        @Flag
        class Inspired(Tag):
            pass
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Inspired(ari)
        (mmd,) = Diagram(ari, layout="lanes").values()

        flag = next(cid for cid, title in _swim_columns(mmd) if "Inspired" in title)
        self.assertTrue(_swim_column_nodes(mmd)[flag])    # a placeholder, not an empty subgraph
        self.assertIn(f"class {flag}_empty flag", mmd)

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_empty_and_control_names_still_draw(self) -> None:
        class H:
            pass
        empty_field = H()
        setattr(empty_field, "", 42)
        control = H()
        setattr(control, "\x1b", 1)
        setattr(control, "\x00", 2)
        for subject in (empty_field, type("", (), {})(), type("", (Tag,), {}), control):
            (dot,) = Diagram(subject, layout="lanes", format="graphviz").values()
            done = subprocess.run(
                    ["dot", "-Tsvg"], input=dot, text=True, capture_output=True, check=True,
                    )
            self.assertIn("<svg", done.stdout)
            (mmd,) = Diagram(subject, layout="lanes").values()
            self.assertNotIn('[""]', mmd)                 # no empty Mermaid label

    def test_live_lanes_mark_only_the_broken_owner(self) -> None:
        ari = Agent()
        ari.strength = 10
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Bruiser(ari)
        ari.strength = 30

        (general,) = Diagram(ari, layout="lanes").values()
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()
        (dot,) = Diagram(ari, live=True, format="graphviz", layout="lanes").values()

        self.assertNotIn("BROKEN", general)
        columns = _swim_columns(mmd)
        nodes = _swim_column_nodes(mmd)
        bruiser = next(cid for cid, title in columns if "Bruiser" in title)
        capped = next(cid for cid, title in columns if "Capped" in title and "Bruiser" not in title)
        broken = [node for node, label in nodes[bruiser].items() if "BROKEN" in label]
        self.assertEqual(broken, [f"{bruiser}_Strength_Capped"])
        self.assertIn("Post", nodes[bruiser][broken[0]])
        self.assertFalse(any("BROKEN" in label for label in nodes[capped].values()))
        self.assertIn(f"class {bruiser}_Strength_Capped broken", mmd)
        self.assertIn("✗ BROKEN", dot)

    def test_live_lanes_add_a_ripped_column(self) -> None:
        ari = Agent()
        Elf(ari)
        del Elf[ari]
        (general,) = Diagram(ari, layout="lanes").values()
        (mmd,) = Diagram(ari, live=True, layout="lanes").values()
        (dot,) = Diagram(ari, live=True, format="graphviz", layout="lanes").values()

        self.assertNotIn("ripped", general)
        columns = _swim_columns(mmd)
        self.assertEqual(len(columns), 3)
        self.assertIn("Elf", columns[-1][1])
        self.assertIn("ripped", columns[-1][1])
        self.assertRegex(dot, r'<TABLE[^>]*STYLE="dashed"')
        self.assertNotIn('label=" ripped "', dot)

    def test_save_writes_lanes_and_boxes_stay_unchanged(self) -> None:
        ari = _mage()
        self.assertEqual(Diagram(ari), Diagram(ari, layout="boxes"))
        self.assertEqual(
                Diagram(ari, format="graphviz"),
                Diagram(ari, format="graphviz", layout="boxes"),
                )
        self.assertIn("flowchart TD", next(iter(Diagram(ari).values())))
        self.assertNotIn("swimlane-beta", next(iter(Diagram(ari).values())))

        with tempfile.TemporaryDirectory() as folder:
            (path,) = Save(ari, pathlib.Path(folder) / "ari", layout="lanes")
            name = path.name
            written = path.read_text()
            (dot_path,) = Save(
                    ari, pathlib.Path(folder) / "ari", format="graphviz", layout="lanes",
                    )
            dot_written = dot_path.read_text()

        self.assertEqual(name, "ari.mmd")
        self.assertEqual(written, next(iter(Diagram(ari, layout="lanes").values())))
        self.assertEqual(dot_path.name, "ari.dot")
        self.assertEqual(
                dot_written,
                next(iter(Diagram(ari, format="graphviz", layout="lanes").values())),
                )

    def test_charts_are_deterministic(self) -> None:
        ari = _mage()

        for options in (
                {},
                {"live": True},
                {"format": "graphviz"},
                {"layout": "lanes"},
                {"layout": "lanes", "live": True},
                {"layout": "lanes", "format": "graphviz"},
                ):
            with self.subTest(options=options):
                first = Diagram(ari, **options)
                self.assertEqual(first, Diagram(ari, **options))


if __name__ == "__main__":
    unittest.main()
