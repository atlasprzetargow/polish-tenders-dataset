"""PII detection and anonymization for Atlas open-data dumps.

Core rule: we cannot publish data that identifies natural persons without consent.
In practice that means anonymizing contractors who are sole proprietors (CEIDG, JDG),
and scrubbing any stray emails/phones in free-text JSON fields.

Buyers are not anonymized: Polish public procurement buyers are, by law,
public bodies or publicly-listed entities — their names and NIPs are public.
If a future data source introduces private-person buyers, add detection here.

Anonymization strategy:
- `contractor_name` → "[Osoba fizyczna]"
- `contractor_national_id` → "anon-" + first 10 hex chars of SHA-256(salt + id)
  (stable across runs given the same salt, so cross-year joins still work; but
  irreversible without the salt)
- `contractor_city` / `contractor_province` kept (geographic aggregates remain useful)
- `contractors` JSON array: per-entry, same rules
- `key_attributes` JSON: regex-mask emails + Polish phone numbers
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

SALT_FILE = Path(__file__).parent / "data" / ".anon_salt"

_DIGIT_RE = re.compile(r"\D+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PL_RE = re.compile(
    r"(?:\+48[\s\-]?)?(?:\d{3}[\s\-]?\d{3}[\s\-]?\d{3})",
)

CORPORATE_MARKER_WORDS = (
    "sp", "spz", "spzoo", "spółka", "sa", "ag", "gmbh", "ltd", "inc", "llc",
    "sc", "spk", "spj",
    "fundacja", "stowarzyszenie", "związek", "spółdzielnia", "wspólnota",
    "gmina", "miasto", "powiat", "urząd", "województwo", "starostwo",
    "szpital", "szkoła", "zespół", "zakład", "instytut", "politechnika",
    "uniwersytet", "akademia", "centrum", "biuro", "ośrodek",
    "przedsiębiorstwo", "komenda", "izba", "parafia", "kościół",
    "nadleśnictwo", "muzeum", "biblioteka", "teatr", "filharmonia",
    "klub", "agencja", "grupa", "group", "holding",
    "medical", "systems", "solutions", "technologies", "consulting",
    "industries", "poland", "polska", "international", "global",
    "services", "trading", "capital", "invest", "finance",
    "logistic", "logistics", "telecom", "energy", "pharma",
    "bank", "laboratorium", "firma",
)

_CORPORATE_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in CORPORATE_MARKER_WORDS) + r")\b",
    re.IGNORECASE,
)

PERSON_EXPLICIT_MARKERS = (
    "osoba fizyczna",
    "jednoosobowa działalność",
    "prowadzący działalność",
    "prowadząca działalność",
    "prowadzacy dzialalnosc",
    "prowadząca dzialalnosc",
    "ceidg",
)

# Two Polish-style words: each starts uppercase, rest lowercase. Allows hyphenated
# double surnames. Anchored to the end of the string — catches the CEIDG pattern
# "FIRMA ABC Krzysztof Nowak" but not corporate suffixes like "Grupa Azoty".
_WORD_TITLE = r"[A-ZŻŹŚĆŁŃÓĄĘ][a-zżźśćłńóąę]+(?:-[A-ZŻŹŚĆŁŃÓĄĘ][a-zżźśćłńóąę]+)?"
_WORD_UPPER = r"[A-ZŻŹŚĆŁŃÓĄĘ]{2,}(?:-[A-ZŻŹŚĆŁŃÓĄĘ]{2,})?"
_PERSON_NAME_TAIL_RE = re.compile(
    r"(?:^|\s)((?:" + _WORD_TITLE + r"|" + _WORD_UPPER + r"))"
    r"\s+((?:" + _WORD_TITLE + r"|" + _WORD_UPPER + r"))"
    r"\s*$"
)

# Top ~400 Polish first names (male + female). Used to disambiguate the
# "FIRMA ... Imię Nazwisko" JDG pattern from a corporate name whose last two
# tokens happen to be Title-cased (e.g. "Roche Diagnostics Polska"). If the
# first captured word matches one of these, we treat the tail as a person.
# Names are stored lower-cased with Polish diacritics preserved.
POLISH_FIRST_NAMES = frozenset(
    # Male
    "adam adrian albert aleksander alan aleksy andrzej antoni apoloniusz arkadiusz "
    "artur bartłomiej bartosz benedykt bernard błażej bogdan bogumił bogusław "
    "bolesław bronisław cezary czesław damian daniel dariusz dawid dionizy dominik "
    "edmund edward emil eryk eugeniusz ernest feliks ferdynand filip franciszek "
    "fryderyk gabriel gerard grzegorz gustaw henryk hieronim hubert ignacy igor "
    "ireneusz jacek jakub jan janusz jarosław jerzy jędrzej józef julian juliusz "
    "kacper kajetan karol kazimierz konrad konstanty kornel krystian krzysztof "
    "leon leszek leopold lucjan ludwik łukasz maciej maksym maksymilian marcin marek "
    "mariusz mateusz maurycy michał miłosz mirosław mścisław nikodem norbert olaf "
    "oskar patryk paweł piotr przemysław rafał radosław remigiusz robert roman "
    "ryszard sebastian seweryn stanisław stefan sylwester szczepan szymon "
    "tadeusz teodor tomasz tymon tymoteusz wacław waldemar walenty wiesław "
    "wiktor wincenty witold władysław włodzimierz wojciech zbigniew zdzisław "
    "zenon zygmunt "
    # Female
    "agata agnieszka aleksandra alicja aldona alina amelia anastazja aneta anna "
    "antonina apolonia aurelia barbara beata berenika bernadeta blanka bogumiła "
    "bogusława bożena cecylia celestyna czesława danuta dominika dorota edyta "
    "elwira elżbieta emilia ewa ewelina filipa franciszka gabriela genowefa grażyna "
    "halina hanna helena henryka honorata iga ilona inga iwona irena izabela jadwiga "
    "janina joanna jolanta judyta julia julianna justyna kaja karolina katarzyna "
    "kinga klara klaudia kornelia krystyna krzysztofa laura lena leokadia liliana "
    "lucyna ludmiła łucja magdalena maja malwina małgorzata maria marianna mariola "
    "marta martyna marzena michalina milena mirosława monika nadzieja natalia "
    "nikola oliwia otylia paulina roksana róża sabina sandra sara sylwia stanisława "
    "stefania stefa stella sylwia teresa urszula wanda weronika wiesława wiktoria "
    "wioletta zofia zuzanna żaneta żanna "
    # Common diminutives that appear in CEIDG business names
    "ania ala asia kasia ola gosia magda beata tosia basia wojtek stachu kuba"
    .split()
)


def _is_null(v) -> bool:
    """True for None, pandas NaN, empty string."""
    if v is None:
        return True
    if isinstance(v, float):
        return v != v  # NaN check
    if isinstance(v, str) and not v:
        return True
    return False


def _digits(s) -> str:
    if _is_null(s):
        return ""
    return _DIGIT_RE.sub("", str(s))


def get_or_create_salt() -> str:
    """Return a stable anonymization salt. Prefers $ANON_SALT env; falls back to
    data/.anon_salt (auto-generated, gitignored)."""
    env_salt = os.environ.get("ANON_SALT")
    if env_salt:
        return env_salt

    SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SALT_FILE.exists():
        return SALT_FILE.read_text().strip()

    salt = uuid.uuid4().hex
    SALT_FILE.write_text(salt)
    return salt


def hash_id(value: str, salt: str) -> str:
    h = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()
    return f"anon-{h[:10]}"


def is_person_contractor(name, national_id) -> bool:
    """Return True if the contractor looks like a natural person (JDG, sole proprietor,
    or bare personal name). Conservative: when in doubt, err toward True."""
    digits = _digits(national_id)
    # PESEL is 11 digits and is always a natural-person identifier.
    if len(digits) == 11:
        return True

    if _is_null(name):
        return False
    name = str(name)
    name_lower = name.lower()

    # Explicit self-declared natural-person markers.
    if any(m in name_lower for m in PERSON_EXPLICIT_MARKERS):
        return True

    # CEIDG-style "Imię Nazwisko" at the end of the name — anchor on the first
    # captured word being a recognized Polish first name. This lets us catch
    # JDG patterns like "Firma Usługowa Krzysztof Dychała" (contains "Firma"
    # which is otherwise a corporate marker) while NOT flagging purely
    # corporate names like "Roche Diagnostics Polska".
    tail_match = _PERSON_NAME_TAIL_RE.search(name.strip())
    if tail_match:
        first_word = tail_match.group(1).lower()
        if first_word in POLISH_FIRST_NAMES:
            return True

    # Corporate marker → company, not a natural person. Word-boundary match so
    # that "Grupa" anywhere in the name counts but "Grupa" as a substring of
    # "Grupaxxx" does not. (Checked AFTER the first-name tail check so that
    # "Firma Usługowa Krzysztof Dychała" is still caught as JDG.)
    if _CORPORATE_MARKER_RE.search(name):
        return False

    # Fallback: tail pattern matched but first word wasn't a known first name.
    # This still catches e.g. all-caps "NEOMED BARBARA STAŃCZYK" when "Barbara"
    # is on the list (it is). Pure 2-word titlecased strings like
    # "Abbott Medical" land here and are NOT flagged (their first word isn't
    # Polish).
    return False


def anonymize_contractor_fields(
    name: str | None,
    national_id: str | None,
    salt: str,
) -> tuple[str | None, str | None]:
    """Return (name, id) tuple anonymized if the contractor is a natural person,
    otherwise the originals."""
    if not is_person_contractor(name, national_id):
        return name, national_id

    anon_name = "[Osoba fizyczna]"
    anon_id = hash_id(_digits(national_id), salt) if national_id else None
    return anon_name, anon_id


def mask_free_text(text) -> str | None:
    """Mask emails and Polish phone numbers in free-text."""
    if _is_null(text):
        return text
    text = str(text)
    out = _EMAIL_RE.sub("[email]", text)
    out = _PHONE_PL_RE.sub(lambda m: "[phone]" if _looks_like_phone(m.group(0)) else m.group(0), out)
    return out


def _looks_like_phone(s: str) -> bool:
    """Filter obvious false positives: year ranges, REGON-like 9-digit runs
    inside a longer number, etc. Require at least one space/dash/plus separator
    OR an explicit '+48'/'tel' marker — bare 9-digit runs often hit REGON."""
    if "+48" in s:
        return True
    if re.search(r"\d{3}[\s\-]\d{3}[\s\-]\d{3}", s):
        return True
    return False


def anonymize_contractors_json(value, salt: str):
    """Anonymize a contractors JSON array (list of dicts with contractorName /
    contractorNationalId keys)."""
    if _is_null(value):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return value
    if not isinstance(value, list):
        return value

    out = []
    for entry in value:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        name = entry.get("contractorName")
        nid = entry.get("contractorNationalId")
        if is_person_contractor(name, nid):
            entry = {**entry}
            entry["contractorName"] = "[Osoba fizyczna]"
            entry["contractorNationalId"] = (
                hash_id(_digits(nid), salt) if nid else None
            )
        out.append(entry)
    return out


def anonymize_key_attributes(value, salt: str):
    """Mask emails/phones within key_attributes JSON (works on dict or JSON string)."""
    if _is_null(value):
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return mask_free_text(value)

    if isinstance(parsed, dict):
        return {k: _walk_and_mask(v) for k, v in parsed.items()}
    if isinstance(parsed, list):
        return [_walk_and_mask(v) for v in parsed]
    return mask_free_text(parsed if isinstance(parsed, str) else value)


def _walk_and_mask(v):
    if isinstance(v, str):
        return mask_free_text(v)
    if isinstance(v, dict):
        return {k: _walk_and_mask(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_walk_and_mask(x) for x in v]
    return v


def anonymize_row_dict(row: dict, salt: str) -> dict:
    """Anonymize a single tender row in-place-style (returns new dict).
    Used by export.py when streaming results."""
    out = dict(row)

    name = out.get("contractor_name")
    nid = out.get("contractor_national_id")
    new_name, new_id = anonymize_contractor_fields(name, nid, salt)
    if new_name != name or new_id != nid:
        out["contractor_name"] = new_name
        out["contractor_national_id"] = new_id

    if "contractors" in out:
        out["contractors"] = anonymize_contractors_json(out["contractors"], salt)

    if "key_attributes" in out:
        out["key_attributes"] = anonymize_key_attributes(out["key_attributes"], salt)

    return out
