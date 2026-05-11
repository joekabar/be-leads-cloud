# kbopub_html golden fixtures

Minimal synthetic HTML pages that exercise the kbopub detail-page parser.
**Do NOT replace with real kbopub pages** — personal data (email, personal addresses) must
not be checked into the repo.

## Fixtures

### `0439401387_bellock_nl.html`
- **Represents**: NL page with a single Bestuurder function holder
- **Expected output**: 1 holder — `Boonen, Jan`, role=`Bestuurder`, role_canonical=`director`,
  since=`2024-03-27`, is_legal_person=`False`, linked_kbo=`None`
- **Edge case**: canonical NL happy path; date parsing via Dutch month name

### `0123456749_no_holders.html`
- **Represents**: Entity with no Functies section at all
- **Expected output**: empty list `[]`
- **Edge case**: absence of the Functies h2 must not raise; returns []

### `0234567890_multiple_roles.html`
- **Represents**: Entity with three function holders of distinct roles
- **Expected output**: 3 holders:
  1. `Janssen, Pieter`, role=`Bestuurder` → role_canonical=`director`, since=2020-01-15
  2. `De Smedt, Lieve`, role=`Gedelegeerd bestuurder` → role_canonical=`managing_director`,
     since=2021-04-01
  3. `Audit Partners BV`, role=`Commissaris` → role_canonical=`auditor`, since=None,
     is_legal_person=True (legal-form suffix)
- **Edge case**: missing "Sinds" date → since=None; legal-form suffix detection

### `0345678901_french.html`
- **Represents**: FR version of the page with `Fonctions` section header
- **Expected output**: 2 holders:
  1. `Dupont, Marie`, role=`Administrateur délégué` → role_canonical=`managing_director`,
     since=2019-02-10
  2. `Martin, Luc`, role=`Gérant` → role_canonical=`manager`, since=None
- **Edge case**: French month name parsing; FR role labels mapped to canonical slugs

### `0456789012_legal_person_holder.html`
- **Represents**: Entity whose bestuurder is a legal person with a linked KBO
- **Expected output**: 2 holders:
  1. `ACME BV met KBO 0502699332` → is_legal_person=True, linked_kbo=`0502699332`,
     role_canonical=`director`
  2. `Vermeersch, Koen` → is_legal_person=False, role_canonical=`permanent_representative`
- **Edge case**: "met KBO" pattern extracts linked_kbo; name contains a legal form abbreviation
