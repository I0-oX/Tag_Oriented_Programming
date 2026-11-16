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


def _lanes(text: str) -> dict[str, str]:
    """Mermaid lane id → title, for the host and each Tag (not modules)."""

    return dict(re.findall(r'^\s+subgraph (host|t\d+)\["([^"]*)"\]$', text, re.MULTILINE))


def _rows(text: str, lane: str) -> list[str]:
    """The labels of a Mermaid lane's rows, in order."""

    return re.findall(rf'^\s+{lane}_\d+(?:\{{\{{|\[|\()"([^"]*)"(?:\}}\}}|\]|\))$', text, re.MULTILINE)


def _arrows(text: str) -> list[tuple[str, str, str]]:
    """(source, label, shape) for each Mermaid lane arrow; solid is ""."""

    return re.findall(r"^  (\w+) (?:-->|-\.->\|(\w+)\|) (\w+)$", text, re.MULTILINE)


def _titles(dot: str) -> dict[str, str]:
    """DOT node id → the title of its box, markup removed."""

    return {
            node: re.sub(r"<[^>]*>", "", title)
            for node, title in re.findall(r'^\s+(\w+) \[label=<<TABLE.*?<TD ALIGN="CENTER">(.*?)</TD>', dot, re.MULTILINE)
            }


def _dot_arrows(dot: str) -> list[tuple[str, str, str]]:
    return [
            (a, label, b)
            for a, b, label in re.findall(
                    r'^  (\w+) -> (\w+)(?: \[style=dashed, label=" (\w+) "\])?;$', dot, re.MULTILINE,
                    )
            ]


def _modules(text: str) -> dict[str, list[str]]:
    """Mermaid module box → the titles of the lanes inside it."""

    lanes = _lanes(text)

    return {
            module: [lanes[lane] for lane in re.findall(r"^    subgraph (t\d+)\[", body, re.MULTILINE)]
            for module, body in re.findall(r'^  subgraph m\d+\["([^"]*)"\]\n(.*?)^  end$', text, re.MULTILINE | re.DOTALL)
            }


def _named(text: str) -> set[tuple[str, str, str]]:
    lanes = _lanes(text)
    return {(lanes[a], label, lanes[b]) for a, label, b in _arrows(text)}


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
        lanes = {title: lane for lane, title in _lanes(text).items()}

        self.assertEqual(_rows(text, lanes["Hero"]), ["name = 'Ari'"])     # host fields only
        self.assertEqual(_rows(text, lanes["Kin"]), ["Record spells", "Action Greet"])
        self.assertEqual(
                _rows(text, lanes["Mage"]),
                [
                    "Post Has_Spells · holds",
                    "Record spells = ['Light', 'Bolt']<br><i>underlay Kin</i>",
                    "Action Greet<br><i>replaces Kin</i>",
                    ],
                )

    def test_graphviz_draws_each_layering_as_a_link_between_rows(self) -> None:
        ari = _mage()

        (dot,) = Diagram(ari, format="graphviz").values()
        ids = {title: node for node, title in _titles(dot).items()}

        self.assertIn("Record</FONT> spells = [&#x27;Light&#x27;, &#x27;Bolt&#x27;]".replace("&#x27;", "'"), dot)
        self.assertRegex(
                dot,
                rf'{ids["Mage"]}:m1 -> {ids["Kin"]}:m0 \[style=dotted, constraint=false, .*label=" underlay "\]',
                )
        self.assertRegex(
                dot,
                rf'{ids["Mage"]}:m2 -> {ids["Kin"]}:m1 \[.*arrowhead=tee, label=" replaces "\]',
                )

    def test_a_layering_into_another_chart_stays_as_words(self) -> None:
        Low = type("Low", (Tag,), {"__module__": "game.low", "Speak": lambda agent: "a"})
        High = type("High", (Tag,), {"__module__": "game.high", "Speak": lambda agent: "b"})
        ari = Hero()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            Low(ari)
            High(ari)

        parts = Diagram(ari, limit=1)
        dots = Diagram(ari, limit=1, format="graphviz")

        self.assertIn('"Action Speak<br><i>replaces Low</i>"', parts["game.high"])
        self.assertIn("<I>replaces Low</I>", dots["game.high"])
        self.assertNotIn(":m0 ->", dots["game.high"])

    def test_direction_heads_the_chart(self) -> None:
        ari = Agent()
        Elf(ari)

        (mermaid,) = Diagram(ari, direction="LR").values()
        (dot,) = Diagram(ari, direction="TD", format="graphviz").values()

        self.assertIn("\nflowchart LR\n", mermaid)
        self.assertIn("rankdir=TB", dot)

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
                [title for lane, title in _lanes(part).items() if lane != "host"]
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
        self.assertIn(f'subgraph host["Agent · {LINKS} (2)"]', parts[f"{LINKS} (2)"])

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
                    name: [title for lane, title in _lanes(part).items() if lane != "host"]
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
        lanes = {title: lane for lane, title in _lanes(text).items()}

        self.assertEqual(
                _rows(text, lanes["Bruiser"]),
                ["Post Strength_Capped · BROKEN<br><i>replaces Capped</i>"],
                )
        self.assertEqual(_rows(text, lanes["Capped"]), ["Post Strength_Capped"])
        self.assertIn(f"  class {lanes['Bruiser']} broken", text)
        self.assertIn("Post Strength_Capped BROKEN", dot)

    def test_a_ripped_tag_stays_dashed(self) -> None:
        ari = Agent()
        Elf(ari)
        del Elf[ari]

        (text,) = Diagram(ari).values()
        lanes = {title: lane for lane, title in _lanes(text).items()}

        self.assertIn(f"  host -.->|ripped| {lanes['Elf']}", text)
        self.assertIn(f"  class {lanes['Elf']} ripped", text)

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
        lanes = {title: lane for lane, title in _lanes(text).items()}

        self.assertEqual(_rows(text, lanes["Intelligence"]), ["Post NDA (constant) · BROKEN"])
        self.assertIn(f"  host -.->|ripped| {lanes['Intelligence']}", text)
        self.assertIn(f"  class {lanes['Intelligence']} broken", text)

    def test_a_tag_draws_its_form_and_its_pins(self) -> None:
        class Rare(Pin):
            @Record
            def rarity(tag) -> str:
                return "rare"

        class Hero_Tag(Elf):
            pass

        Rare(Hero_Tag)
        (text,) = Diagram(Hero_Tag).values()
        lanes = {title: lane for lane, title in _lanes(text).items()}

        self.assertNotIn("host", _lanes(text))
        self.assertEqual(
                _named(text),
                {("Person", "", "Elf"), ("Elf", "", "Hero_Tag"), ("Hero_Tag", "pins", "Rare · Pin")},
                )
        self.assertEqual(_rows(text, lanes["Rare · Pin"]), ["Record rarity"])
        self.assertIn(f"  class {lanes['Rare · Pin']} pin", text)
        self.assertEqual(_rows(text, lanes["Elf"]), ["Action Attack<br><i>underlay Person</i>"])

    def test_what_a_tag_is_names_and_colors_its_box(self) -> None:
        @Flag
        class Inspired(Tag):
            pass

        ari = Agent()
        Inspired(ari)

        (text,) = Diagram(ari).values()
        (dot,) = Diagram(ari, format="graphviz").values()
        lanes = {title: lane for lane, title in _lanes(text).items()}

        self.assertIn(f"  class {lanes['Inspired · Flag']} flag", text)
        self.assertIn("Inspired<FONT POINT-SIZE", dot)
        self.assertIn(' · Flag</FONT></FONT></TD></TR></TABLE>>, color="#0d9488"', dot)

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
        self.assertEqual(list(_lanes(text).values()), ["Solo", "Rare · Pin", "Rarer · Pin"])  # not the root
        self.assertEqual(_named(text), {("Rare · Pin", "", "Rarer · Pin"), ("Solo", "pins", "Rare · Pin")})

    def test_labels_cannot_break_out_of_their_box(self) -> None:
        odd = type('Odd"<b>&#', (), {})
        (text,) = Diagram(odd()).values()
        (dot,) = Diagram(odd(), format="graphviz").values()

        self.assertIn('subgraph host["Odd#quot;#lt;b#gt;&#35;"]', text)
        self.assertIn('digraph "Odd\\"<b>&#" {', dot)
        self.assertIn('<TD ALIGN="CENTER">Odd&quot;&lt;b&gt;&amp;#</TD>', dot)

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
        self.assertIn(">Elf</text>", picture)

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
