# Selector & Regex Catalog — website-analysis

## Phones

```
<a href="tel:...">     → strip 'tel:', pass to validate_phone()
Regex on visible text: (?:\+32|0032|\+31|0)[0-9 \-\.\/]{7,14}
```

Confidence:
- `href="tel:"` link → 0.85
- Regex text scan → 0.60

## Emails

```
<a href="mailto:...">  → strip 'mailto:', drop ?subject= and beyond
Regex fallback: [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}
```

Confidence:
- `href="mailto:"` link → 0.85
- Regex → 0.50

## Persons — microdata

```python
soup.find_all(attrs={"itemtype": re.compile("Person", re.I)})
# within each: .find(attrs={"itemprop": "name"})
# optional:    .find(attrs={"itemprop": "jobTitle"})
```

Confidence: 0.85

## Persons — role-keyword heuristic

Role keywords (test lowercased text):
```
zaakvoerder, ceo, directeur, manager, sales, contact, verantwoordelijke,
gérant, gerant, director, founder, oprichter
```

Within each `<h1-4>`, `<p>`, `<span>`: if role keyword found, extract names matching:
```
\b[A-ZÁÉÍÓÚÀÈÙÂÊÎÔÛÄËÏÖÜ][a-záéíóú]+\s[A-ZÁÉÍÓÚ][a-záéíóú]+\b
```
near it (within the same element or the next sibling).

Confidence: 0.55

## Activity summary

Priority order:
1. `<meta name="description">` content
2. `<meta property="og:description">` content
3. `<meta name="twitter:description">` content
4. `main`/`article`/`section` → first `<p>` with `len(text) > 60`, truncated to 300 chars

## Contact-page links

Scan homepage `<a href>` with case-insensitive match on href containing:
`contact`, `team`, `over-ons`, `about`, `medewerkers`, `wie-zijn-we`, `notre-equipe`

Then probe well-known paths via HEAD (see SKILL.md).

## Opening hours

- JSON-LD `openingHours` / `openingHoursSpecification` → flatten to list of strings
- `itemprop="openingHours"` microdata
- No reliable HTML heuristic — skip if not in JSON-LD

## Contact photos

Optional, not implemented. Skip in this prompt.
