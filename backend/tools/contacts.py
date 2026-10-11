"""Contacts: look people up in macOS Contacts (read-only).

There's no claude.ai connector for Google Contacts. The user's phone is Android, so their
contacts live in their Google account; macOS Contacts syncs them once that account is
added under System Settings → Internet Accounts with Contacts on. Ultron reads them with
JavaScript for Automation. The first lookup makes macOS ask to let Ultron use Contacts.

"mom", "my boss", ... are looked up in the related names on the user's own card
("My Card" in Contacts), then searched by that name. Without one, the word is searched as
a name or nickname: English first, then Turkish ("Annem"), then other languages, until
someone matches.
"""

import asyncio
import json
from typing import Any

from claude_agent_sdk import tool

# The query reaches the script as an argument, never pasted into its source.
SCRIPT = r"""
function run(argv) {
  const C = Application('com.apple.AddressBook');  // by id: the name 'Contacts' can resolve to a widget extension
  const [mode, q] = argv;
  const clean = s => (s || '').replace(/^_\$!<|>!\$_$/g, '');
  if (mode === 'related') {
    let me = null;
    try { me = C.myCard(); } catch (e) {}
    if (!me) return 'null';
    const r = me.relatedNames().find(r => clean(r.label()).toLowerCase() === q);
    return JSON.stringify(r ? r.value() : null);
  }
  // q: {terms, exclude}: words tried in order until one finds someone, skipping people whose
  // name or nickname has an exclude word ("Anneannem" contains "annem" but is grandma).
  const {terms, exclude} = JSON.parse(q);
  const list = (items, value) => items.map(i => ({label: clean(i.label()), value: value(i)}));
  const excluded = p => exclude.some(x => `${p.name()} ${p.nickname() || ''}`.toLowerCase().includes(x));
  for (const t of terms) {
    // Contacts has no usable `whose`; read all names in one call and filter here.
    const all = C.people, names = all.name(), nicks = all.nickname();
    const people = names.map((n, i) => i).filter(i => `${names[i]} ${nicks[i] || ''}`.toLowerCase().includes(t))
      .map(i => all[i]).filter(p => !excluded(p));
    if (people.length) return JSON.stringify({term: t, people: people.slice(0, 10).map(p => ({
      name: p.name(),
      nickname: p.nickname() || '',
      organization: p.organization() || '',
      emails: list(p.emails(), i => i.value()),
      phones: list(p.phones(), i => i.value()),
      addresses: list(p.addresses(), i => i.formattedAddress()),
    }))});
  }
  return JSON.stringify({term: null, people: []});
}
"""

# Relation label (as Contacts stores it on "My Card") -> words people save contacts
# under, tried in this order: English, then Turkish, then other languages.
# Longer words first where one contains another ("annem" before "anne").
WORDS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "mother": (["mom", "mum", "mother", "mommy", "mama"], ["annem", "anne", "anneciğim"],
               ["mamá", "maman", "mamma", "mutti", "mutter", "мама", "أمي", "ماما"]),
    "father": (["dad", "father", "daddy", "papa"], ["babam", "baba", "babacığım"],
               ["papá", "papà", "vater", "папа", "أبي", "بابا"]),
    "grandmother": (["grandma", "grandmother", "granny", "nana"], ["anneanne", "babaanne", "ninem", "nenem"],
                    ["abuela", "nonna", "oma", "mamie", "grand-mère", "бабушка", "جدتي", "تيتا"]),
    "grandfather": (["grandpa", "grandfather", "granddad"], ["dedem", "dede", "büyükbaba"],
                    ["abuelo", "nonno", "opa", "papi", "grand-père", "дедушка", "جدي"]),
    "brother": (["brother", "bro"], ["abim", "ağabeyim", "kardeşim"],
                ["hermano", "fratello", "bruder", "frère", "брат", "أخي"]),
    "sister": (["sister", "sis"], ["ablam", "kız kardeşim", "kardeşim"],
               ["hermana", "sorella", "schwester", "sœur", "сестра", "أختي"]),
    "spouse": (["wife", "husband", "spouse"], ["eşim", "karım", "kocam"],
               ["esposa", "esposo", "moglie", "marito", "жена", "муж", "زوجتي", "زوجي"]),
    "child": (["son", "daughter", "child", "kid"], ["oğlum", "kızım", "çocuğum"],
              ["hijo", "hija", "figlio", "figlia", "сын", "дочь", "ابني", "ابنتي"]),
    "partner": (["partner", "boyfriend", "girlfriend"], ["sevgilim"], ["novio", "novia"]),
    "manager": (["boss", "manager"], ["patronum", "müdürüm", "patron", "müdür"], ["jefe", "chef", "capo"]),
    "friend": (["friend"], ["arkadaşım"], ["amigo", "amiga", "amico"]),
    "assistant": (["assistant"], ["asistanım"], []),
    "parent": (["parent"], [], []),
}
RELATIONS = {w: label for label, groups in WORDS.items() for group in groups for w in group}
# Words for a relation that contain another relation's words: skip those people.
GRANDPARENTS = [w for label in ("grandmother", "grandfather") for group in WORDS[label] for w in group]
EXCLUDE = {"mother": GRANDPARENTS, "father": GRANDPARENTS}


def relation_label(query: str) -> str | None:
    """'my mom' -> 'mother', 'Annem' -> 'mother'. None if it isn't a relationship word."""
    return RELATIONS.get(query.lower().strip().removeprefix("my ").strip())


def search_terms(label: str, said: str) -> list[str]:
    """What to search for a relation, in order: the user's own word, English, Turkish, others."""
    english, turkish, others = WORDS[label]
    said = said.lower().strip().removeprefix("my ").strip()
    return list(dict.fromkeys([said, *english, *turkish, *others]))


async def _run(mode: str, query: str) -> Any:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-l", "JavaScript", "-e", SCRIPT, mode, query,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        # Long enough for the user to answer macOS's permission question the first time.
        out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
    except TimeoutError:
        proc.kill()
        raise RuntimeError("Contacts didn't answer in time") from None
    if proc.returncode:
        msg = err.decode().strip()
        if "-1743" in msg or "not allowed" in msg.lower() or "not authorized" in msg.lower():
            msg = ("macOS didn't allow Ultron to use Contacts. Allow it in System Settings → "
                   "Privacy & Security → Automation (and Contacts).")
        raise RuntimeError(msg or "osascript failed")
    return json.loads(out.decode() or "null")


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


@tool(
    "find_contact",
    "Look someone up in the user's contacts (read-only): by name, nickname, or a "
    "relationship like 'mom' or 'my boss'. Returns up to 10 matches with emails, phone "
    "numbers and addresses. Use it before emailing, inviting or messaging someone by name. "
    "Relationships are searched in English, then Turkish ('Annem'), then other languages. "
    "If a name finds nobody, try other spellings (Turkish letters: c/ç, s/ş, g/ğ, i/ı, o/ö, u/ü) "
    "or the name in another language before giving up.",
    {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A name, nickname or relationship."}},
        "required": ["query"],
    },
)
async def find_contact(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return _text("find_contact needs a name.", True)
    try:
        terms, exclude = [query], []
        if label := relation_label(query):
            on_card = await _run("related", label)
            terms = [on_card] if on_card else search_terms(label, query)
            exclude = [] if on_card else EXCLUDE.get(label, [])
        found = await _run("search", json.dumps({"terms": terms, "exclude": exclude}, ensure_ascii=False))
    except (RuntimeError, OSError, ValueError) as e:
        return _text(f"Contacts: {e}", True)
    if not found["people"]:
        return _text(f"No contact matches {query!r} (searched: {', '.join(terms)}).")
    note = f"Found by searching {found['term']!r}. " if found["term"].lower() != query.lower() else ""
    return _text(note + json.dumps(found["people"], ensure_ascii=False))
